"""Outbound Telegram Bot API helper.

Stdlib-only (urllib) so the module has no external Python deps and installs
cleanly on Odoo.sh, on-prem, and air-gapped enterprise builds. Same precedent
as rteam_prozorro.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from odoo import _

_logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 10  # seconds


class TelegramApiError(Exception):
    """Raised when the Telegram Bot API returns a non-ok response."""


def _request(token, method, payload=None, timeout=DEFAULT_TIMEOUT):
    """POST JSON to https://api.telegram.org/bot<token>/<method>.

    Returns the parsed ``result`` field on success.
    Raises ``TelegramApiError`` on transport or API-level failure.
    """
    if not token:
        raise TelegramApiError(_("Telegram bot token is not configured."))
    url = f"{API_BASE}/bot{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Telegram returns JSON even on 4xx; surface description if present.
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            desc = err_body.get("description") or str(e)
        except Exception:
            desc = str(e)
        raise TelegramApiError(
            _("Telegram API error %(code)s: %(desc)s", code=e.code, desc=desc)
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TelegramApiError(_("Telegram API unreachable: %(err)s", err=e)) from e
    if not body.get("ok"):
        raise TelegramApiError(
            _(
                "Telegram API returned not-ok: %(desc)s",
                desc=body.get("description", "(no description)"),
            )
        )
    return body.get("result")


def get_me(token, timeout=DEFAULT_TIMEOUT):
    """Validate token and return bot identity (id, username, first_name)."""
    return _request(token, "getMe", timeout=timeout)


def send_message(token, chat_id, text, parse_mode=None, timeout=DEFAULT_TIMEOUT):
    """Send a plain text message to a chat. Returns Telegram message dict."""
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _request(token, "sendMessage", payload=payload, timeout=timeout)


def send_message_with_buttons(
    token, chat_id, text, reply_markup, parse_mode=None, timeout=DEFAULT_TIMEOUT
):
    """Send a message with an inline keyboard. ``reply_markup`` is a dict like
    ``{"inline_keyboard": [[{"text": ..., "callback_data": ...}]]}``."""
    payload = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _request(token, "sendMessage", payload=payload, timeout=timeout)


def edit_message_reply_markup(token, chat_id, message_id, reply_markup, timeout=DEFAULT_TIMEOUT):
    """Replace the inline keyboard of an existing message (e.g. to flip
    Approve/Reject buttons into a "Approved by X" status)."""
    payload = {
        "chat_id": chat_id,
        "message_id": int(message_id),
        "reply_markup": reply_markup,
    }
    return _request(token, "editMessageReplyMarkup", payload=payload, timeout=timeout)


def answer_callback_query(token, callback_query_id, text=None, timeout=DEFAULT_TIMEOUT):
    """Acknowledge an inline-button tap. Without this Telegram shows a
    spinner on the button forever."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]  # Telegram caps text at 200 chars
    return _request(token, "answerCallbackQuery", payload=payload, timeout=timeout)


def set_webhook(token, url, secret_token=None, timeout=DEFAULT_TIMEOUT):
    """Register webhook URL with Telegram. Pass empty url to delete."""
    payload = {"url": url}
    if secret_token:
        payload["secret_token"] = secret_token
    return _request(token, "setWebhook", payload=payload, timeout=timeout)


def get_updates(token, offset=None, timeout=DEFAULT_TIMEOUT):
    """Long-poll fallback for the bind handshake when no public URL exists."""
    payload = {}
    if offset is not None:
        payload["offset"] = offset
    return _request(token, "getUpdates", payload=payload, timeout=timeout) or []
