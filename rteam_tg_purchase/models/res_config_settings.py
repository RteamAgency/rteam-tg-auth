"""Per-company settings for Telegram-gated purchase approvals."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    rteam_tg_purchase_threshold = fields.Float(
        string="Approval threshold",
        config_parameter="rteam_tg_purchase.threshold",
        default=0.0,
        help=(
            "Purchase orders with an Untaxed/Total amount equal to or above "
            "this number trigger a Telegram approval request when confirmed. "
            "Below this threshold, the order is confirmed normally. Set to 0 "
            "to gate every order (not recommended; high noise)."
        ),
    )
    rteam_tg_purchase_approver_id = fields.Many2one(
        "res.users",
        string="Default approver",
        config_parameter="rteam_tg_purchase.approver_user_id",
        help=(
            "Whoever is named here will receive the Telegram approval request. "
            "They must already have completed Bind Telegram in their Preferences."
        ),
    )
