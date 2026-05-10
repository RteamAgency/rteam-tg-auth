"""Source-agnostic approval ledger.

One row per requested signoff on an arbitrary source record (a Purchase
Order, an Invoice, a Time Off entry, etc.). The source-side glue
(rteam_tg_purchase, rteam_tg_invoice, ...) decides WHEN to create the
request and WHAT to do on approve / reject; this model owns the
Telegram side and the state machine.

Callback signature: each inline button carries a callback_data of the
form ``a:{request_id}:{action}:{sig8}``. ``sig8`` is the first 8 hex
chars of HMAC-SHA256(webhook_secret, "{request_id}:{action}"). An
attacker who learns the request id alone cannot forge a button tap
without knowing the per-instance webhook secret.
"""

import hashlib
import hmac
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .telegram_api import (
    TelegramApiError,
    answer_callback_query,
    edit_message_reply_markup,
    send_message_with_buttons,
)

_logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_TTL_SECONDS = 86400  # 24h
CALLBACK_PREFIX = "a"
ACTION_APPROVE = "y"
ACTION_REJECT = "n"


class RteamTgApprovalRequest(models.Model):
    _name = "rteam.tg.approval.request"
    _description = "Rteam Telegram Approval Request"
    _order = "create_date desc"

    name = fields.Char(compute="_compute_name", store=True, string="Reference")

    source_model = fields.Char(required=True, index=True)
    source_id = fields.Integer(required=True, index=True)
    source_ref = fields.Char(string="Source")

    requester_user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    approver_user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)

    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        index=True,
    )

    summary = fields.Text(string="Summary shown in Telegram")
    deep_link_url = fields.Char(help="Direct link to the source record in Odoo.")
    expires_at = fields.Datetime(required=True, index=True)

    tg_chat_id = fields.Char()
    tg_message_id = fields.Char()

    responded_at = fields.Datetime()
    response_note = fields.Char()

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)

    @api.depends("source_model", "source_id", "source_ref")
    def _compute_name(self):
        for rec in self:
            ref = rec.source_ref or f"{rec.source_model}#{rec.source_id}"
            rec.name = ref

    # ---------------------------------------------------------------- helpers

    def _params(self):
        return self.env["ir.config_parameter"].sudo()

    @api.model
    def _approval_ttl_seconds(self):
        try:
            return int(
                self._params().get_param(
                    "rteam_tg_auth.approval_ttl_seconds", DEFAULT_APPROVAL_TTL_SECONDS
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_APPROVAL_TTL_SECONDS

    def _bot_token(self):
        return self._params().get_param("rteam_tg_auth.bot_token") or ""

    def _webhook_secret(self):
        return self._params().get_param("rteam_tg_auth.webhook_secret") or ""

    def _deep_link_for(self, source_model, source_id):
        base_url = (self._params().get_param("rteam_tg_auth.webhook_base_url") or "").rstrip("/")
        if not base_url:
            base_url = (self._params().get_param("web.base.url") or "").rstrip("/")
        if not base_url:
            return ""
        return f"{base_url}/odoo/action-base.action_ui?model={source_model}&id={source_id}&view_type=form"

    @api.model
    def _sign(self, request_id, action):
        secret = self._webhook_secret()
        if not secret:
            return ""
        msg = f"{request_id}:{action}".encode()
        digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return digest[:8]

    @api.model
    def _verify_signed_callback(self, callback_data):
        """Parse ``a:{id}:{action}:{sig}`` and verify the signature.

        Returns (request, action) on success, (None, None) on failure.
        """
        if not callback_data or not isinstance(callback_data, str):
            return None, None
        parts = callback_data.split(":")
        if len(parts) != 4 or parts[0] != CALLBACK_PREFIX:
            return None, None
        try:
            request_id = int(parts[1])
        except (TypeError, ValueError):
            return None, None
        action = parts[2]
        if action not in (ACTION_APPROVE, ACTION_REJECT):
            return None, None
        provided_sig = parts[3]
        expected_sig = self._sign(request_id, action)
        if not expected_sig or not hmac.compare_digest(provided_sig, expected_sig):
            return None, None
        request = self.sudo().browse(request_id)
        if not request.exists():
            return None, None
        return request, action

    # ----------------------------------------------------------------- create

    @api.model
    def request_approval(
        self,
        source_record,
        approver_user,
        summary,
        requester_user=None,
    ):
        """Create a pending approval request and deliver it to Telegram.

        ``source_record`` is the record needing approval (e.g. a
        purchase.order). The caller decides what to do once the state
        transitions to approved / rejected by listening to the
        ``approval_resolved`` event hook on the source model.
        """
        source_record.ensure_one()
        if not approver_user:
            raise UserError(_("Cannot request approval: no approver was specified."))
        binding = approver_user.tg_binding_id[:1]
        if not binding or binding.state != "active":
            raise UserError(
                _(
                    "%(login)s has no active Telegram binding. They need to "
                    "complete Bind Telegram in their Preferences first."
                )
                % {"login": approver_user.login}
            )
        token = self._bot_token()
        if not token:
            raise UserError(_("The Telegram bot is not configured. Contact your administrator."))

        ttl = self._approval_ttl_seconds()
        expires_at = fields.Datetime.now() + timedelta(seconds=ttl)
        requester = requester_user or self.env.user

        request = self.sudo().create(
            {
                "source_model": source_record._name,
                "source_id": source_record.id,
                "source_ref": source_record.display_name,
                "requester_user_id": requester.id,
                "approver_user_id": approver_user.id,
                "summary": summary,
                "deep_link_url": self._deep_link_for(source_record._name, source_record.id),
                "expires_at": expires_at,
                "tg_chat_id": binding.chat_id,
            }
        )
        request._dispatch_tg_message()
        self.env["rteam.tg.audit"].sudo().create(
            {
                "user_id": approver_user.id,
                "binding_id": binding.id,
                "event": "approval_requested",
                "note": f"{source_record._name}#{source_record.id} '{source_record.display_name}'",
            }
        )
        return request

    def _dispatch_tg_message(self):
        self.ensure_one()
        token = self._bot_token()
        if not token:
            return

        text = self._render_tg_text()
        keyboard = self._build_keyboard()
        try:
            msg = send_message_with_buttons(
                token,
                self.tg_chat_id,
                text,
                keyboard,
                parse_mode="HTML",
            )
        except TelegramApiError as e:
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.approver_user_id.id,
                    "binding_id": self.approver_user_id.tg_binding_id[:1].id,
                    "event": "challenge_sent",
                    "note": f"APPROVAL DELIVERY FAILED: {e}",
                }
            )
            raise UserError(
                _("Could not deliver the approval request to Telegram:\n\n%(err)s")
                % {"err": str(e)}
            ) from e
        self.sudo().write({"tg_message_id": str(msg.get("message_id") or "")})

    def _render_tg_text(self):
        self.ensure_one()
        # Plain text + small HTML; Telegram parse_mode=HTML allows <b>, <i>, <a>.
        title = self.source_ref or self.name
        body = self.summary or ""
        requester = self.requester_user_id.name or self.requester_user_id.login
        ttl_minutes = max(1, (self._approval_ttl_seconds() // 60))
        return (
            f"<b>Approval requested</b>\n"
            f"<b>From:</b> {requester}\n"
            f"<b>What:</b> {title}\n\n"
            f"{body}\n\n"
            f"<i>Expires in {ttl_minutes} min if not actioned.</i>"
        )

    def _build_keyboard(self):
        self.ensure_one()
        sig_y = self._sign(self.id, ACTION_APPROVE)
        sig_n = self._sign(self.id, ACTION_REJECT)
        rows = [
            [
                {"text": "Approve", "callback_data": f"a:{self.id}:y:{sig_y}"},
                {"text": "Reject", "callback_data": f"a:{self.id}:n:{sig_n}"},
            ],
        ]
        if self.deep_link_url:
            rows.append([{"text": "View in Odoo", "url": self.deep_link_url}])
        return {"inline_keyboard": rows}

    def _build_resolved_keyboard(self, label):
        # Single disabled-looking row with no callback_data, just a status.
        # Telegram does not support "disabled" buttons so we use a
        # callback_data that nobody listens to.
        return {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}

    # ----------------------------------------------------------------- resolve

    def _ack_button_tap(self, callback_query_id, text):
        token = self._bot_token()
        if not token or not callback_query_id:
            return
        try:
            answer_callback_query(token, callback_query_id, text=text)
        except TelegramApiError:
            _logger.exception("rteam_tg_auth: answerCallbackQuery failed")

    def _replace_buttons_with_status(self, label):
        self.ensure_one()
        token = self._bot_token()
        if not token or not self.tg_chat_id or not self.tg_message_id:
            return
        try:
            edit_message_reply_markup(
                token,
                self.tg_chat_id,
                self.tg_message_id,
                self._build_resolved_keyboard(label),
            )
        except TelegramApiError:
            _logger.exception("rteam_tg_auth: editMessageReplyMarkup failed")

    def _resolve(self, action, callback_query_id=None, actor_chat_id=None):
        """Common path for approve/reject. Updates state + audit + TG."""
        self.ensure_one()
        if self.state != "pending":
            self._ack_button_tap(
                callback_query_id,
                _("This request is no longer pending (state: %s).") % self.state,
            )
            return False
        if self.expires_at and self.expires_at < fields.Datetime.now():
            self.write({"state": "expired", "responded_at": fields.Datetime.now()})
            self._ack_button_tap(callback_query_id, _("This request has already expired."))
            self._replace_buttons_with_status(_("Expired"))
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.approver_user_id.id,
                    "event": "approval_expired",
                    "note": f"{self.source_model}#{self.source_id}",
                }
            )
            return False

        # Prevent someone else's chat from acting on someone's request.
        if actor_chat_id and self.tg_chat_id and str(actor_chat_id) != str(self.tg_chat_id):
            self._ack_button_tap(callback_query_id, _("This approval is for a different user."))
            return False

        new_state = "approved" if action == ACTION_APPROVE else "rejected"
        self.write({"state": new_state, "responded_at": fields.Datetime.now()})
        actor_label = _("Approved") if action == ACTION_APPROVE else _("Rejected")
        self._ack_button_tap(callback_query_id, actor_label)
        self._replace_buttons_with_status(
            _("%(label)s by %(user)s")
            % {"label": actor_label, "user": self.approver_user_id.display_name}
        )
        self.env["rteam.tg.audit"].sudo().create(
            {
                "user_id": self.approver_user_id.id,
                "binding_id": self.approver_user_id.tg_binding_id[:1].id,
                "event": "approval_approved" if action == ACTION_APPROVE else "approval_rejected",
                "note": f"{self.source_model}#{self.source_id}",
            }
        )
        # Hand control to the source-model glue. The source model decides
        # what "approved" actually means (e.g. call button_confirm on
        # purchase.order, or just post to chatter).
        self._notify_source_model(new_state)
        return True

    def _notify_source_model(self, new_state):
        """Look up the source record and call its on_approval_resolved hook.

        Source-model glue modules (rteam_tg_purchase, ...) implement
        ``on_rteam_tg_approval_resolved(self, request, new_state)`` on
        the source model.
        """
        self.ensure_one()
        Source = self.env.get(self.source_model)
        if Source is None:
            _logger.warning(
                "rteam_tg_auth: no model %s in registry; cannot notify", self.source_model
            )
            return
        source = Source.sudo().browse(self.source_id).exists()
        if not source:
            _logger.warning(
                "rteam_tg_auth: source record %s#%s gone; nothing to notify",
                self.source_model,
                self.source_id,
            )
            return
        hook = getattr(source, "on_rteam_tg_approval_resolved", None)
        if not callable(hook):
            _logger.info(
                "rteam_tg_auth: %s has no on_rteam_tg_approval_resolved hook; skipping",
                self.source_model,
            )
            return
        try:
            hook(self, new_state)
        except Exception:  # noqa: BLE001 -- never crash the webhook
            _logger.exception(
                "rteam_tg_auth: on_rteam_tg_approval_resolved on %s#%s raised",
                self.source_model,
                self.source_id,
            )

    # ----------------------------------------------------------------- cron

    @api.model
    def _cron_expire_stale(self):
        stale = self.sudo().search(
            [("state", "=", "pending"), ("expires_at", "<", fields.Datetime.now())]
        )
        for req in stale:
            req.write({"state": "expired", "responded_at": fields.Datetime.now()})
            req._replace_buttons_with_status(_("Expired"))
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": req.approver_user_id.id,
                    "event": "approval_expired",
                    "note": f"{req.source_model}#{req.source_id}",
                }
            )
        return len(stale)
