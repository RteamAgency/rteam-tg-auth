"""User-to-Telegram binding.

One active binding per Odoo user. Holds the chat_id that outbound 2FA codes
are delivered to, plus the short-lived ``bind_token`` consumed during the
handshake and the recovery codes generated at enrollment.
"""

from odoo import fields, models


class RteamTgBinding(models.Model):
    _name = "rteam.tg.binding"
    _description = "Rteam Telegram 2FA Binding"
    _rec_name = "user_id"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="user_id.company_id",
        store=True,
        index=True,
    )

    state = fields.Selection(
        [
            ("pending", "Awaiting bind"),
            ("active", "Active"),
            ("revoked", "Revoked"),
        ],
        default="pending",
        required=True,
        index=True,
    )

    chat_id = fields.Char(
        string="Telegram Chat ID",
        help="Numeric Telegram chat identifier where 2FA codes are delivered.",
    )
    tg_username = fields.Char(string="Telegram Username")

    bind_token = fields.Char(
        string="Bind Token",
        help="Short-lived token the user sends to the bot to complete the handshake.",
    )
    bind_token_expires_at = fields.Datetime()

    bound_at = fields.Datetime()
    last_used_at = fields.Datetime()

    recovery_codes = fields.Text(
        string="Recovery Codes",
        help="Newline-separated single-use codes. Stored hashed on enrollment.",
    )

    pending_code_hash = fields.Char(string="Pending Code Hash")
    pending_code_expires_at = fields.Datetime()
    pending_code_attempts = fields.Integer(default=0)

    _sql_constraints = [
        (
            "user_unique_active",
            "unique(user_id)",
            "A user can only have one Telegram binding.",
        ),
    ]
