"""Per-company Telegram bot configuration."""

from odoo import fields, models


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
