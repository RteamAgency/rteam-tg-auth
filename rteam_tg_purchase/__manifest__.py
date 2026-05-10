{
    "name": "Rteam Telegram Approvals: Purchase Orders",
    "version": "19.0.1.0.1",
    "category": "Purchases",
    "summary": "One-tap Purchase Order approvals in Telegram. CEO/CFO sign-off from a phone, anywhere.",
    "description": """
Rteam Telegram Approvals: Purchase Orders
=========================================

Stop chasing your CEO with "please confirm PO #1234". When a Purchase
Order over your threshold is confirmed, an inline Telegram message
goes straight to the approver's phone with three buttons: Approve,
Reject, View in Odoo. One tap and the PO confirms in Odoo, the
chatter records who approved and when. No VPN, no Odoo login, no
inbox dig.

How it works
------------
1. Install this module on top of ``rteam_tg_auth``.
2. The approver completes Bind Telegram once in their Odoo
   Preferences (60 seconds via the deep link the bot sends them).
3. Set Settings -> Telegram -> Purchase Approvals: a Threshold (the
   amount above which approval is required) and a Default approver.
4. From now on, when a Purchase Order at or above the threshold is
   confirmed, the order is held in draft state and a Telegram
   message with inline Approve / Reject buttons is delivered to the
   configured approver. Their tap flips the order to confirmed or
   leaves it in draft, and posts a chatter note linking the action
   back to the approver and the time.

Security
--------
Each inline button carries an HMAC-signed callback payload. An
attacker who learns a request id alone cannot forge a tap without
the per-instance webhook secret. Telegram messages and webhook
callbacks share the same path-and-header secret; the bot token
never leaves your database.

Reliability
-----------
* Stale requests (24h default) auto-expire on a 30-minute cron, with
  a chatter note on the source PO.
* Approver opens the same PO in Odoo? The header shows a "View
  Telegram approval" button so they can see exactly which TG message
  is in flight.
* Re-confirming a PO with an open request raises a clear error
  rather than spawning a duplicate.
* Self-approve is blocked: requester == approver = no Telegram
  detour, the order confirms normally.

This is one of a planned family of source-model integrations on top
of the same ``rteam_tg_auth`` ledger -- Vendor Bills, Time Off,
Expenses are next. Building your own is one method on the source
model: ``on_rteam_tg_approval_resolved(request, new_state)``.
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
