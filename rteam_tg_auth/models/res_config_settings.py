"""Per-company Telegram bot configuration."""

from odoo import _, fields, models
from odoo.exceptions import UserError

from .telegram_api import TelegramApiError, get_me


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    rteam_tg_bot_token = fields.Char(
        string="Bot Token",
        config_parameter="rteam_tg_auth.bot_token",
    )
    rteam_tg_bot_username = fields.Char(
        string="Bot Username",
        config_parameter="rteam_tg_auth.bot_username",
        help="Resolved from getMe; do not edit manually.",
    )
    rteam_tg_webhook_secret = fields.Char(
        string="Webhook Secret",
        config_parameter="rteam_tg_auth.webhook_secret",
        help="Random secret embedded in the webhook URL path. Rotate to invalidate the current webhook.",
    )
    rteam_tg_webhook_base_url = fields.Char(
        string="Public Base URL",
        config_parameter="rteam_tg_auth.webhook_base_url",
        help="Public HTTPS URL of this Odoo instance. Required for webhook bind path. Leave empty for manual chat_id fallback.",
    )
    rteam_tg_enforce_2fa = fields.Boolean(
        string="Enforce 2FA on Login",
        config_parameter="rteam_tg_auth.enforce_2fa",
        default=False,
        help="When enabled, every user with an active binding is challenged on login. Off by default for safe rollout.",
    )

    def action_rteam_tg_validate_token(self):
        """Call Telegram getMe to validate the configured bot token.

        On success: writes back the bot username so it appears in the URL hint
        on user binding pages, and returns a green sticky notification with
        the bot identity. On failure: surfaces the API error verbatim so the
        admin can act on it (bad token, no egress, Telegram down, etc.).
        """
        self.ensure_one()
        # Persist current edits before talking to Telegram so the token used
        # for the call matches what the admin sees in the form.
        self.execute()
        token = self.env["ir.config_parameter"].sudo().get_param("rteam_tg_auth.bot_token")
        if not token:
            raise UserError(_("Set the bot token first, then click Validate."))
        try:
            bot = get_me(token)
        except TelegramApiError as e:
            raise UserError(_("Telegram rejected the token:\n\n%(err)s", err=str(e))) from e
        username = bot.get("username") or ""
        self.env["ir.config_parameter"].sudo().set_param("rteam_tg_auth.bot_username", username)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "sticky": False,
                "title": _("Bot connected"),
                "message": _(
                    "Telegram accepted the token. Bot: @%(username)s (id %(id)s).",
                    username=username,
                    id=bot.get("id"),
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
