{
    "name": "Rteam Telegram 2FA",
    "version": "19.0.2.0.0",
    "category": "Administration",
    "summary": "Two-factor authentication for Odoo logins via your own Telegram bot",
    "description": """
Rteam Telegram 2FA
==================

Free Odoo module that adds Telegram-based two-factor authentication to Odoo
user logins. Bring your own bot (created via @BotFather), paste the token
into Settings, bind each user once, and Odoo will challenge logins with a
6-digit code delivered to the user's Telegram chat.

Features
--------
* Bring-your-own-bot: no third-party SaaS, no rteam.agency dependency at
  runtime. The bot lives in your Telegram, the secret stays in your Odoo.
* Per-user opt-in: 2FA is off by default; each user enables it after binding
  their Telegram chat.
* Outbound only by default: works on any Odoo deployment that can reach
  api.telegram.org over HTTPS, including on-prem behind NAT.
* Optional webhook for the bind handshake (for public-URL deployments such
  as Odoo.sh) plus a manual chat_id fallback for sites without a public URL.
* 10 single-use recovery codes generated on enrollment to avoid lockouts.
* Audit log: bind, unbind, login challenge sent, code accepted/rejected,
  recovery code used, admin reset; with IP, user agent, and Telegram message
  id.
* Rate limiting on code requests (5 per 15 minutes per user).
* Admin reset flow for lost-phone scenarios, with audit trail.

What this module does NOT do (yet)
----------------------------------
* Approval workflows (Purchase Orders, Vendor Bills, Time Off, Expenses).
  Coming in a separate paid module ``rteam_tg_approvals``.
* SMS or Email fallback channels.
* WhatsApp parity.

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
