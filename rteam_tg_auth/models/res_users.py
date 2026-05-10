"""Glue from res.users to its Telegram binding."""

from odoo import api, fields, models


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
