"""Append-only audit log for security-relevant events.

Keep one row per event. Never update or delete from code. Retention via cron
in a future revision.
"""

from odoo import fields, models


class RteamTgAudit(models.Model):
    _name = "rteam.tg.audit"
    _description = "Rteam Telegram 2FA Audit Log"
    _order = "create_date desc"

    user_id = fields.Many2one("res.users", index=True, ondelete="set null")
    binding_id = fields.Many2one(
        "rteam.tg.binding",
        index=True,
        ondelete="set null",
    )

    event = fields.Selection(
        [
            ("bind_started", "Bind started"),
            ("bind_completed", "Bind completed"),
            ("bind_failed", "Bind failed"),
            ("unbind", "Unbind"),
            ("admin_reset", "Admin reset"),
            ("challenge_sent", "Challenge sent"),
            ("challenge_accepted", "Challenge accepted"),
            ("challenge_rejected", "Challenge rejected"),
            ("recovery_used", "Recovery code used"),
            ("rate_limited", "Rate limited"),
        ],
        required=True,
        index=True,
    )

    ip = fields.Char(string="Client IP")
    user_agent = fields.Char()
    tg_message_id = fields.Char(string="Telegram Message ID")

    note = fields.Text()
