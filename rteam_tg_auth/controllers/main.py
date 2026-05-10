"""Webhook receiver for the Telegram bind handshake.

Path includes a per-instance secret so untrusted callers cannot replay updates.
Telegram also sends an ``X-Telegram-Bot-Api-Secret-Token`` header that we
validate when configured.

This is a skeleton in v0.1: the request is logged and acknowledged; bind logic
lands in the next iteration.
"""

import json
import logging

from odoo import http
from odoo.http import request

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
        configured = (
            request.env["ir.config_parameter"].sudo().get_param("rteam_tg_auth.webhook_secret")
        )
        if not configured or secret != configured:
            _logger.warning("rteam_tg_auth: webhook called with bad secret")
            return request.make_response("forbidden", status=403)

        header_secret = request.httprequest.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if configured and header_secret and header_secret != configured:
            _logger.warning("rteam_tg_auth: webhook header secret mismatch")
            return request.make_response("forbidden", status=403)

        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except json.JSONDecodeError:
            return request.make_response("bad json", status=400)

        _logger.info("rteam_tg_auth: webhook update received: %s", payload)
        # Bind handler will land in the next iteration.
        return request.make_response("ok", status=200)
