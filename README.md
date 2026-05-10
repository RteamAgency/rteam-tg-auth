# Rteam Telegram Approvals & 2FA

> Approve POs and 2FA-log-in to Odoo from Telegram with one tap.
> Bring your own bot, no SaaS dependency, no third-party data exposure.

[![ci](https://github.com/RteamAgency/rteam-tg-auth/actions/workflows/ci.yml/badge.svg)](https://github.com/RteamAgency/rteam-tg-auth/actions/workflows/ci.yml)
&nbsp;
License: LGPL-3
&nbsp;
Maintainer: [Rteam](https://rteam.agency) (alex@rteam.top)

## What this gives you

Telegram inline-button approvals on top of any Odoo workflow that has a
"please confirm this thing" moment. The first integration shipped is
Purchase Orders; Vendor Bills, Time Off and Expenses are next.

Two-factor authentication for Odoo logins is bundled in: the same bot
delivers approval messages and login codes, so once it's wired in there
is nothing else for you to configure.

```
+---------------+        +-----------------+        +-----------------+
|  PO confirmed |  --->  |  Telegram bot   |  --->  |  Approver phone |
|   in Odoo     |        |   (your bot)    |        |   one tap UI    |
+---------------+        +-----------------+        +-----------------+
                                                            |
                                                            v
                                              +----------------------+
                                              |  PO confirms in Odoo |
                                              |  + chatter audit row |
                                              +----------------------+
```

## Why Telegram, not email or SMS

| Channel | Cost | Inline action | Push delivery | Audit |
|---------|------|---------------|---------------|-------|
| **Telegram** | Free | One-tap Approve / Reject buttons | Native | Yes (HMAC-signed callbacks) |
| Email | Free | Click a link, wait for browser | Inbox noise | Sender-reported only |
| SMS (Twilio) | ~$0.05 / msg | None (no buttons) | Native | Carrier-reported, no payload |
| WhatsApp Business | ~$0.005-$0.05 / msg | Buttons in template, slow approvals | Native | Yes |

For Odoo install bases concentrated in EU, MENA, UA and SEA -- where
Telegram has 800M+ active users -- the channel match is closest to
where your CEO already lives.

## Modules in this repo

| Module | What it is | Depends on |
|--------|------------|------------|
| [`rteam_tg_auth`](rteam_tg_auth) | Core: bot config, bind wizard, approval ledger, login challenge | `base`, `web`, `mail` |
| [`rteam_tg_purchase`](rteam_tg_purchase) | Purchase Order approval glue | `rteam_tg_auth`, `purchase` |

The split is intentional: the core has zero source-side dependencies,
so it works as a 2FA-only install for shops that do not use Odoo
Purchase. New source-model integrations
(`rteam_tg_invoice`, `rteam_tg_timeoff`, ...) reuse the core ledger
without duplicating the Telegram side.

## Install

```bash
git clone git@github.com:RteamAgency/rteam-tg-auth.git
ln -s $(pwd)/rteam-tg-auth/rteam_tg_auth /path/to/odoo/addons/rteam_tg_auth
ln -s $(pwd)/rteam-tg-auth/rteam_tg_purchase /path/to/odoo/addons/rteam_tg_purchase
# in Odoo: Apps -> Update Apps List -> install
#   "Rteam Telegram Approvals & 2FA" (always)
#   "Rteam Telegram Approvals: Purchase Orders" (if you want PO approvals)
```

On Odoo.sh, add the repo as a submodule of your project.

## Configuration in 5 minutes

1. Create a bot via [@BotFather](https://t.me/BotFather) (`/newbot`,
   give it a name and username, copy the token).
2. **Settings -> Telegram -> Bot**: paste the token, click **Validate**.
   You should see "Bot connected: @your_bot_name".
3. **Settings -> Telegram -> Webhook**: enter your Public Base URL
   (`https://mycompany.odoo.com`), click **Register Webhook**. The
   secret is generated for you and stored in `ir.config_parameter`.
4. Each approver: open **My Preferences -> Telegram**, click
   **Bind Telegram**, follow the deep link, press **Send** in
   Telegram. The bot replies "Bound to <login>".
5. **Settings -> Telegram -> Purchase Approvals**: set Threshold and
   Default approver. From now on, POs at or above the threshold are
   gated through Telegram.

Optional: flip on **Enforce 2FA on Login** in the same Settings page
to require a 6-digit Telegram code at login for every bound user.

## Architecture in one paragraph

Bring-your-own-bot. The bot token lives in your `ir.config_parameter`,
never in any Rteam-hosted system. The module talks outbound to
`api.telegram.org` over HTTPS for notifications. Telegram delivers
button taps back to one webhook endpoint guarded by both a path secret
and the `X-Telegram-Bot-Api-Secret-Token` header. Each inline button
carries `callback_data` of the form `a:{request_id}:{action}:{sig8}`
where `sig8` is the first 8 hex characters of HMAC-SHA256(secret,
`{request_id}:{action}`); an attacker who learns a request id alone
cannot forge a tap. No external Python dependencies (stdlib `urllib`
only).

## Building your own source-model integration

Implement one method on the source model:

```python
class MyModel(models.Model):
    _inherit = "my.model"

    def _request_approval(self, approver):
        return self.env["rteam.tg.approval.request"].request_approval(
            source_record=self,
            approver_user=approver,
            summary="Approval needed for ...",
        )

    def on_rteam_tg_approval_resolved(self, request, new_state):
        if new_state == "approved":
            self.confirm()
        elif new_state == "rejected":
            self.message_post(body="Rejected via Telegram")
```

The Telegram side -- inline buttons, signed callbacks, expiry, audit,
"Approved by X" status replacement -- is fully handled by the core.
Look at [`rteam_tg_purchase/models/purchase_order.py`](rteam_tg_purchase/models/purchase_order.py)
for the working pattern.

## Status

* `rteam_tg_auth` 19.0.2.0.0
* `rteam_tg_purchase` 19.0.1.0.0
* Targeted Odoo versions: 19 (main / `19.0`); backports to 17 and 18
  follow on the `17.0` and `18.0` branches.
* Tests: smoke only at the moment; coverage target 70% before
  apps.odoo.com submission. See `tests/`.

## License

LGPL-3. See [LICENSE](LICENSE).
