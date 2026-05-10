"""Glue from res.users to its Telegram binding."""

import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DEFAULT_BIND_TTL_SECONDS = 600


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
