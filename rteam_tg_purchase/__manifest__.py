{
    "name": "Rteam Telegram Approvals -- Purchase",
    "version": "19.0.1.0.0",
    "category": "Purchases",
    "summary": "Approve Purchase Orders from Telegram with one tap",
    "description": """
Rteam Telegram Approvals -- Purchase
====================================

Glue between ``rteam_tg_auth`` and the Odoo Purchase module. When a
purchase order is confirmed and the order amount exceeds a configurable
threshold, the order is held in a pending state and a Telegram message
with Approve / Reject inline buttons is delivered to the configured
approver. The approver's tap (validated by HMAC-signed callback_data,
not just by request id) flips the order to confirmed or back to draft,
and writes a chatter note + audit row.

Approver, threshold, and the per-source kill switch are all configured
under Settings -> Telegram 2FA -> Purchase Approvals. The approver must
already have an active Telegram binding from rteam_tg_auth.

This is the first source-model integration; the underlying ledger
(``rteam.tg.approval.request``) is source-agnostic, so future sibling
modules ``rteam_tg_invoice``, ``rteam_tg_timeoff``, etc. can plug in
without duplicating the Telegram side.
""",
    "author": "Rteam",
    "maintainer": "Rteam",
    "website": "https://rteam.agency",
    "support": "alex@rteam.top",
    "license": "LGPL-3",
    "depends": ["rteam_tg_auth", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter_data.xml",
        "views/purchase_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
