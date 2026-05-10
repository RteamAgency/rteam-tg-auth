{
    "name": "Rteam Telegram 2FA & Approvals",
    "version": "19.0.2.1.2",
    "category": "Productivity",
    "summary": "Approve POs, invoices and more from Telegram with one tap. Login 2FA included.",
    "description": """
Rteam Telegram 2FA & Approvals
==============================

Approve Purchase Orders, Vendor Bills, Time Off and other Odoo records
from Telegram with one tap. Bring your own bot (created via @BotFather)
in 60 seconds, bind each approver to their Telegram chat, and the bot
delivers Approve / Reject / View-in-Odoo buttons straight to their phone.

Two-factor authentication for Odoo logins is bundled in: the same bot
that delivers approvals also delivers a 6-digit login code, no extra
setup once the bot is configured.

Why Telegram, not email or SMS
------------------------------
* One tap, no link to follow, no inbox to dig through. The Approve
  button is the action.
* Free outbound (Telegram Bot API costs nothing). Email approvals
  bury the request in noise; SMS via Twilio costs ~$0.05 per message
  and lacks inline buttons.
* Push delivery your CEO/CFO already lives in. Telegram has 800M+
  users in EU, MENA, UA, SEA -- the same regions where your Odoo
  install is most likely deployed.

Architecture in one paragraph
-----------------------------
Bring-your-own-bot. The token lives in your database, never in ours.
The module talks outbound to ``api.telegram.org`` over HTTPS for
notifications and 2FA codes. Telegram delivers user taps back to one
webhook endpoint guarded by both a path secret and the
``X-Telegram-Bot-Api-Secret-Token`` header. Each inline button carries
HMAC-signed callback data so an attacker who learns a request id alone
cannot forge a tap.

What's in the box
-----------------
* Approval ledger (source-agnostic). State machine: pending -> approved
  / rejected / expired / cancelled. Audit trail per request: who, when,
  from which chat, with which Telegram message id.
* Inline-button approval messages with three actions: Approve, Reject,
  View in Odoo (deep-link).
* 24-hour TTL on requests, configurable. Stale requests auto-expire on
  a 30-minute cron.
* Admin Approvals dashboard under Settings -> Telegram.
* Two-factor login with 6-digit codes, 5-minute TTL, rate-limited
  (5 requests per 15 min per user). Per-user opt-in, off by default,
  global enforce switch when you are ready.
* Bind wizard with one-tap deep link ``https://t.me/<bot>?start=<token>``.
* Audit log for every Telegram-side event. CSV export ready.
* No external Python dependencies (stdlib urllib only).
* No third-party SaaS, no rteam.agency dependency at runtime.

Source-model integrations
-------------------------
This module is the foundation. Source-side glue ships as separate
modules so the core stays light:

* ``rteam_tg_purchase`` -- Purchase Order approvals (free, this repo)
* ``rteam_tg_invoice`` -- Vendor Bill approvals (planned)
* ``rteam_tg_timeoff`` -- Time Off approvals (planned)
* ``rteam_tg_expenses`` -- Expense Report approvals (planned)

Building your own integration is one method on the source model:
``on_rteam_tg_approval_resolved(request, new_state)``. The Telegram
side is fully reusable.

Targeted at Odoo 19 (Community and Enterprise). Backports to 17 and 18
follow on the ``17.0`` and ``18.0`` branches.
""",
    "author": "Rteam",
    "maintainer": "Rteam",
    "website": "https://rteam.agency",
    "support": "alex@rteam.top",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
    ],
    "external_dependencies": {
        "python": [],
    },
    "data": [
        "security/rteam_tg_auth_security.xml",
        "security/ir.model.access.csv",
        "data/ir_config_parameter_data.xml",
        "wizard/rteam_tg_bind_wizard_views.xml",
        "wizard/rteam_tg_recovery_codes_wizard_views.xml",
        "views/rteam_tg_binding_views.xml",
        "views/rteam_tg_audit_views.xml",
        "views/rteam_tg_approval_views.xml",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "views/rteam_tg_login_template.xml",
        "views/rteam_tg_auth_menus.xml",
    ],
    "images": [
        "static/description/banner.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "post_init_hook": "post_init",
}
