"""Webhook receiver for the Telegram bot.

In v0.1 the only update kind we care about is ``message`` with text
``/start <bind_token>`` -- the second leg of the bind handshake started
by the Bind Telegram wizard. Other update kinds are accepted with 200 OK
and ignored so Telegram does not retry them.

Auth: the per-instance secret is in the URL path AND in the
``X-Telegram-Bot-Api-Secret-Token`` header (Telegram echoes whatever we
passed via setWebhook). Both are validated.
"""

import json
import logging

from odoo import _, fields, http
from odoo.http import request

from ..models.telegram_api import TelegramApiError, send_message

_logger = logging.getLogger(__name__)


class RteamTgAuthController(http.Controller):
    @http.route(
        "/rteam_tg_auth/webhook/<string:secret>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def webhook(self, secret, **_kw):
        params = request.env["ir.config_parameter"].sudo()
        configured = params.get_param("rteam_tg_auth.webhook_secret")
        if not configured or secret != configured:
            _logger.warning("rteam_tg_auth: webhook called with bad path secret")
            return request.make_response("forbidden", status=403)

        header_secret = request.httprequest.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header_secret and header_secret != configured:
            _logger.warning("rteam_tg_auth: webhook header secret mismatch")
            return request.make_response("forbidden", status=403)

        try:
            update = json.loads(request.httprequest.get_data() or b"{}")
        except json.JSONDecodeError:
            return request.make_response("bad json", status=400)

        try:
            self._handle_update(update)
        except Exception:  # noqa: BLE001 -- never 5xx back to Telegram
            _logger.exception("rteam_tg_auth: webhook handler crashed")
        # Telegram retries on non-2xx, so always ack.
        return request.make_response("ok", status=200)

    # ------------------------------------------------------------------ helpers

    def _handle_update(self, update):
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        chat_id = chat.get("id")
        if not chat_id or not text.startswith("/start"):
            return

        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) == 2 else ""
        if not token:
            self._reply(
                chat_id,
                _(
                    "Hi! Open Odoo, go to Preferences and click Bind Telegram. "
                    "I will receive a one-time start command and link your account."
                ),
            )
            return

        env = request.env(su=True)
        Binding = env["rteam.tg.binding"]
        Audit = env["rteam.tg.audit"]

        binding = Binding.search(
            [("bind_token", "=", token), ("state", "=", "pending")],
            limit=1,
        )
        if not binding:
            Audit.create(
                {
                    "event": "bind_failed",
                    "tg_message_id": str(message.get("message_id") or ""),
                    "note": f"Unknown or already-consumed token (chat_id {chat_id})",
                }
            )
            self._reply(
                chat_id,
                _(
                    "This bind link is unknown or already used. Open Odoo and "
                    "click Bind Telegram again to get a fresh one."
                ),
            )
            return

        if binding.bind_token_expires_at and binding.bind_token_expires_at < fields.Datetime.now():
            Audit.create(
                {
                    "user_id": binding.user_id.id,
                    "binding_id": binding.id,
                    "event": "bind_failed",
                    "tg_message_id": str(message.get("message_id") or ""),
                    "note": "Token expired",
                }
            )
            self._reply(
                chat_id,
                _("This bind link has expired. Click Bind Telegram in Odoo to generate a new one."),
            )
            return

        # One TG chat = one Odoo user. Refuse if this chat is already wired
        # to a different active user.
        clash = Binding.search(
            [
                ("chat_id", "=", str(chat_id)),
                ("state", "=", "active"),
                ("id", "!=", binding.id),
            ],
            limit=1,
        )
        if clash:
            Audit.create(
                {
                    "user_id": binding.user_id.id,
                    "binding_id": binding.id,
                    "event": "bind_failed",
                    "tg_message_id": str(message.get("message_id") or ""),
                    "note": f"Chat {chat_id} already bound to user {clash.user_id.id}",
                }
            )
            self._reply(
                chat_id,
                _(
                    "This Telegram chat is already linked to another Odoo user. "
                    "Unbind it there first, or use a different Telegram account."
                ),
            )
            return

        binding.write(
            {
                "state": "active",
                "chat_id": str(chat_id),
                "tg_username": from_user.get("username") or "",
                "bound_at": fields.Datetime.now(),
                "bind_token": False,
                "bind_token_expires_at": False,
            }
        )
        Audit.create(
            {
                "user_id": binding.user_id.id,
                "binding_id": binding.id,
                "event": "bind_completed",
                "tg_message_id": str(message.get("message_id") or ""),
                "note": f"Chat {chat_id} (@{from_user.get('username') or '-'})",
            }
        )
        self._reply(
            chat_id,
            _(
                "Bound to %(login)s. You will receive Odoo 2FA codes here when "
                "you log in. To remove this binding, open Odoo Preferences and "
                "click Unbind Telegram."
            )
            % {"login": binding.user_id.login},
        )

    def _reply(self, chat_id, text):
        token = request.env["ir.config_parameter"].sudo().get_param("rteam_tg_auth.bot_token")
        if not token:
            return
        try:
            send_message(token, chat_id, text)
        except TelegramApiError:
            _logger.exception("rteam_tg_auth: reply to %s failed", chat_id)
