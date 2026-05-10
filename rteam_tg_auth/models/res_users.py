"""Glue from res.users to its Telegram binding."""

import logging
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

DEFAULT_BIND_TTL_SECONDS = 600
MFA_TYPE = "rteam_tg"
MFA_URL = "/web/login/rteam_tg"

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    tg_binding_id = fields.One2many(
        "rteam.tg.binding",
        "user_id",
        string="Telegram Binding",
    )
    tg_2fa_state = fields.Selection(
        [
            ("none", "Not bound"),
            ("pending", "Awaiting bind"),
            ("active", "Active"),
            ("revoked", "Revoked"),
        ],
        compute="_compute_tg_2fa_state",
        store=False,
    )

    @api.depends("tg_binding_id.state")
    def _compute_tg_2fa_state(self):
        for user in self:
            binding = user.tg_binding_id[:1]
            user.tg_2fa_state = binding.state if binding else "none"

    # ---------------------------------------------------------------- MFA

    def _rteam_tg_2fa_required(self):
        """True when this user must complete a Telegram 2FA challenge to log in."""
        self.ensure_one()
        if self.tg_2fa_state != "active":
            return False
        enforce = (
            self.env["ir.config_parameter"].sudo().get_param("rteam_tg_auth.enforce_2fa", "False")
        )
        return str(enforce).lower() in ("1", "true", "yes")

    def _mfa_type(self):
        r = super()._mfa_type()
        if r is not None:
            return r
        if self._rteam_tg_2fa_required():
            return MFA_TYPE
        return r

    def _mfa_url(self):
        r = super()._mfa_url()
        if r is not None:
            return r
        if self._mfa_type() == MFA_TYPE:
            return MFA_URL
        return r

    def _check_credentials(self, credentials, env):
        if credentials.get("type") != MFA_TYPE:
            return super()._check_credentials(credentials, env)

        sudo = self.sudo()
        binding = sudo.tg_binding_id[:1]
        if not binding or binding.state != "active":
            _logger.info("rteam_tg 2FA: no active binding for %r", sudo.login)
            raise AccessDenied(_("Telegram 2FA is not configured for this user."))

        ip = None
        user_agent = None
        if request:
            ip = request.httprequest.environ.get("REMOTE_ADDR")
            user_agent = request.httprequest.headers.get("User-Agent")

        if binding.verify_challenge(
            str(credentials.get("token") or ""),
            ip=ip,
            user_agent=user_agent,
        ):
            _logger.info("rteam_tg 2FA: SUCCESS for %r", sudo.login)
            return {
                "uid": self.env.user.id,
                "auth_method": MFA_TYPE,
                "mfa": "default",
            }
        _logger.info("rteam_tg 2FA: FAIL for %r", sudo.login)
        raise AccessDenied(
            _("Wrong code. Check your Telegram and try again, or request a new code.")
        )

    def _get_session_token_fields(self):
        # Invalidate live sessions when the binding row changes (revoke / rotate).
        return super()._get_session_token_fields() | {"tg_binding_id"}

    # ---------------------------------------------------------------- bind

    def _rteam_tg_bot_username(self):
        """Resolved bot username from Settings; raises if Settings is unconfigured."""
        params = self.env["ir.config_parameter"].sudo()
        username = params.get_param("rteam_tg_auth.bot_username")
        if not username:
            raise UserError(
                _(
                    "The Telegram bot is not configured yet. Ask an administrator "
                    "to fill in the bot token in Settings -> Telegram 2FA."
                )
            )
        return username

    def _rteam_tg_bind_ttl_seconds(self):
        params = self.env["ir.config_parameter"].sudo()
        try:
            return int(
                params.get_param("rteam_tg_auth.bind_token_ttl_seconds", DEFAULT_BIND_TTL_SECONDS)
            )
        except (TypeError, ValueError):
            return DEFAULT_BIND_TTL_SECONDS

    def action_rteam_tg_bind(self):
        """Open the Bind Telegram wizard for this user.

        Creates or refreshes the user's pending binding row with a fresh
        single-use token. Refuses if the user is already actively bound
        (must Unbind first to re-bind a different chat).
        """
        self.ensure_one()
        bot_username = self._rteam_tg_bot_username()
        Binding = self.env["rteam.tg.binding"].sudo()
        binding = Binding.search([("user_id", "=", self.id)], limit=1)
        if binding and binding.state == "active":
            raise UserError(
                _(
                    "This user is already bound to a Telegram chat. Click "
                    "Unbind first to start over with a different chat."
                )
            )
        token = secrets.token_urlsafe(8)
        expires_at = fields.Datetime.now() + timedelta(seconds=self._rteam_tg_bind_ttl_seconds())
        if binding:
            binding.write(
                {
                    "state": "pending",
                    "bind_token": token,
                    "bind_token_expires_at": expires_at,
                    "chat_id": False,
                    "tg_username": False,
                }
            )
        else:
            binding = Binding.create(
                {
                    "user_id": self.id,
                    "state": "pending",
                    "bind_token": token,
                    "bind_token_expires_at": expires_at,
                }
            )
        self.env["rteam.tg.audit"].sudo().create(
            {
                "user_id": self.id,
                "binding_id": binding.id,
                "event": "bind_started",
                "note": "Bind token issued",
            }
        )
        wizard = self.env["rteam.tg.bind.wizard"].create(
            {
                "user_id": self.id,
                "binding_id": binding.id,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Bind Telegram"),
            "res_model": "rteam.tg.bind.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context, default_bot_username=bot_username),
        }

    def action_rteam_tg_unbind(self):
        """Revoke the user's binding. Hard-deletes the row; audit log keeps the trail."""
        self.ensure_one()
        Binding = self.env["rteam.tg.binding"].sudo()
        binding = Binding.search([("user_id", "=", self.id)], limit=1)
        if not binding:
            raise UserError(_("Nothing to unbind for this user."))
        self.env["rteam.tg.audit"].sudo().create(
            {
                "user_id": self.id,
                "binding_id": binding.id,
                "event": "unbind",
                "note": f"Unbind from chat_id {binding.chat_id or '(none)'}",
            }
        )
        binding.unlink()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "sticky": False,
                "title": _("Unbound"),
                "message": _("Telegram binding removed."),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
