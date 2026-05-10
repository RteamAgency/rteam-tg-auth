# Rteam Telegram 2FA

Free Odoo module that adds Telegram-based two-factor authentication to Odoo
user logins. Bring your own bot, paste the token into Settings, bind each
user once, and Odoo will challenge logins with a 6-digit code delivered to
the user's Telegram chat.

- License: LGPL-3
- Maintainer: [Rteam](https://rteam.agency) (alex@rteam.top)
- Targeted Odoo versions: 19 (main / `19.0`), backports on `17.0` and `18.0`
- Status: v0.1 in development

## Why

Odoo Enterprise ships a TOTP authenticator. It works, but it adds yet another
authenticator app for users who already live in Telegram. This module offers
Telegram as a parallel 2FA channel, plus a clean substrate for the upcoming
`rteam_tg_approvals` paid extension (one-tap inline approvals for Purchase
Orders, Vendor Bills, Time Off, Expenses).

## Architecture in one paragraph

Bring-your-own-bot. Admin creates a bot via [@BotFather](https://t.me/BotFather)
and pastes the token into Odoo Settings. The module talks **outbound only**
to `api.telegram.org` for the 2FA challenge: code is pushed to the user's
chat, user copies it back into the Odoo login form. The optional webhook
endpoint is only used for the one-time bind handshake; deployments without
a public URL fall back to entering the chat id manually.

## Install

```bash
git clone git@github.com:RteamAgency/rteam-tg-auth.git
ln -s $(pwd)/rteam-tg-auth/rteam_tg_auth /path/to/odoo/addons/rteam_tg_auth
# then in Odoo: Apps -> Update Apps List -> install "Rteam Telegram 2FA"
```

## Configuration

1. Create a bot via [@BotFather](https://t.me/BotFather), copy the token.
2. Settings -> Telegram 2FA -> paste the bot token, save.
3. Optionally fill in the public HTTPS base URL of your Odoo instance to
   enable the webhook-based bind path. Otherwise the module uses the
   manual chat-id fallback.
4. Each user enables 2FA on their own profile and completes the bind handshake.

## Status of v0.1

This release lays the skeleton: models, security groups, settings UI, audit
log view, webhook stub. The actual bind handshake, login challenge flow and
recovery-code wizard land in the next iterations of v0.1.

## License

LGPL-3. See [LICENSE](LICENSE).
