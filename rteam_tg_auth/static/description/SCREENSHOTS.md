# Screenshots needed for the apps.odoo.com listing

Capture from `https://alex-odoo-test-19.odoo.com` (current dogfood
environment) in 1440x900 viewport, light theme. Save as PNG into
`rteam_tg_auth/static/description/screenshots/` with the exact filenames
below; `index.html` already references them.

## 01_telegram_approval.png

Hero shot. **The Telegram chat with @odoo_app_bot** showing one of the
approval messages (pick the unresolved P00002 one or trigger a fresh PO
to get clean buttons). Crop tightly so the inline buttons (Approve /
Reject / View in Odoo) are the visual center.

Tip: zoom Telegram to 110-120% so text is readable in thumbnail.

## 02_settings.png

Odoo Settings page, scrolled to the **Telegram** app block. Frame so all
four sub-blocks are visible: Bot, Webhook, 2FA on Login, Purchase
Approvals. Show real values (token masked, username `odoo_app_bot`,
threshold filled, approver = Administrator).

## 03_approvals_list.png

**Telegram -> Approvals** list view with the search default `Pending`
filter, then turn it off so both approved P00001 + P00002 + still-pending
ones appear. State badge column is the eye-catcher.

## 04_2fa_login.png

The **6-digit Telegram code form** on the login flow. Capture after a
fresh logout + password POST so you land on `/web/login/rteam_tg`. Crop
to just the form card (headline "Telegram 2FA", helper text, code input,
"Log in" / "Resend code" / "Cancel" buttons).

## Optional extras (worth adding when time allows)

- `05_bind_wizard.png` -- the Bind Telegram modal showing the "Open in
  Telegram" deep-link button.
- `06_audit_log.png` -- Telegram -> Audit Log filtered to recent
  approval events, group-by Event.
- `07_po_chatter.png` -- a confirmed PO with the chatter trail
  ("Telegram approval request sent..." -> "Approved via Telegram by ...").

## Capture method

macOS: `Shift+Cmd+4` -> spacebar to grab a window cleanly. Or use
`Shift+Cmd+5` for a region capture with dimension preview.

For Telegram, capture from the web client at `https://web.telegram.org/`
so the styling matches what apps.odoo.com browsers see (mobile screenshots
look out of place on a desktop listing).

After each capture, sanity check the file is < 500 KB. If larger, run
`sips -s formatOptions 80 image.png --out image.png` to compress without
visible quality loss.
