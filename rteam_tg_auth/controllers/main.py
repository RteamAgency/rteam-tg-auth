"""HTTP entry points for rteam_tg_auth.

Two routes:

1. ``/rteam_tg_auth/webhook/<secret>`` -- receives Telegram bot updates.
   Used for the bind handshake (``/start <bind_token>``).
2. ``/web/login/rteam_tg`` -- the second-step login form for users with
   Telegram 2FA enabled. Mirrors the auth_totp ``/web/login/totp``
   pattern: reads ``request.session['pre_uid']`` set by the framework
   after password verification, sends a 6-digit code to the user's bound
   chat, accepts the code on POST, finalizes the session.

Webhook auth: the per-instance secret is in the URL path AND in the
``X-Telegram-Bot-Api-Secret-Token`` header (Telegram echoes whatever we
passed via setWebhook). Both are validated.
"""

import json
import logging
import re

from odoo import _, fields, http
from odoo.addons.web.controllers import home as web_home
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from ..models.telegram_api import TelegramApiError, send_message

_logger = logging.getLogger(__name__)


class RteamTgLoginHome(web_home.Home):
    @http.route(
        "/web/login/rteam_tg",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        sitemap=False,
        website=True,
        multilang=False,
    )
    def web_login_rteam_tg(self, redirect=None, **kwargs):
        # Already authenticated -> bounce to wherever the redirect points.
        if request.session.uid:
            return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))

        # No pre-auth in session means the user landed here directly without
        # going through /web/login first. Send them back to the password page.
        if not request.session.get("pre_uid"):
            return request.redirect("/web/login")

        user = request.env["res.users"].sudo().browse(request.session["pre_uid"])
        binding = user.tg_binding_id[:1]
        ip = request.httprequest.environ.get("REMOTE_ADDR")
        user_agent = request.httprequest.headers.get("User-Agent")

        info = None
        error = None

        if request.httprequest.method == "GET":
            # First GET (or refresh): if we don't already have a fresh code
            # in flight, send one.
            if binding and binding.state == "active":
                try:
                    sent = binding.issue_challenge(ip=ip, user_agent=user_agent)
                    info = (
                        _("A 6-digit code was just sent to your Telegram chat.")
                        if sent
                        else _("Use the most recent code sent to your Telegram chat.")
                    )
                except UserError as e:
                    error = str(e)
            else:
                error = _(
                    "This account is no longer bound to Telegram. Contact your administrator."
                )
            request.session.touch()
            return request.render(
                "rteam_tg_auth.tg_login_form",
                {
                    "user": user,
                    "info": info,
                    "error": error,
                    "redirect": redirect,
                    "bot_username": request.env["ir.config_parameter"]
                    .sudo()
                    .get_param("rteam_tg_auth.bot_username")
                    or "",
                },
            )

        # POST: action is either "verify" (default) or "resend".
        action = (kwargs.get("action") or "verify").lower()

        if action == "resend":
            if binding and binding.state == "active":
                try:
                    binding.write({"pending_code_hash": False, "pending_code_expires_at": False})
                    binding.issue_challenge(ip=ip, user_agent=user_agent)
                    info = _("A new 6-digit code was just sent to your Telegram chat.")
                except UserError as e:
                    error = str(e)
            request.session.touch()
            return request.render(
                "rteam_tg_auth.tg_login_form",
                {
                    "user": user,
                    "info": info,
                    "error": error,
                    "redirect": redirect,
                    "bot_username": request.env["ir.config_parameter"]
                    .sudo()
                    .get_param("rteam_tg_auth.bot_username")
                    or "",
                },
            )

        # action == "verify"
        token = re.sub(r"\s", "", kwargs.get("rteam_tg_token") or "")
        if not token:
            error = _("Enter the 6-digit code from Telegram.")
        else:
            try:
                with user._assert_can_auth(user=user.id):
                    user._check_credentials(
                        {"type": "rteam_tg", "token": token},
                        {"interactive": True},
                    )
            except AccessDenied as e:
                error = str(e)
            else:
                request.session.finalize(request.env)
                request.update_env(user=request.session.uid)
                request.update_context(**request.session.context)
                response = request.redirect(
                    self._login_redirect(request.session.uid, redirect=redirect)
                )
                request.session.touch()
                return response

        request.session.touch()
        return request.render(
            "rteam_tg_auth.tg_login_form",
            {
                "user": user,
                "info": info,
                "error": error,
                "redirect": redirect,
                "bot_username": request.env["ir.config_parameter"]
                .sudo()
                .get_param("rteam_tg_auth.bot_username")
                or "",
            },
        )


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
