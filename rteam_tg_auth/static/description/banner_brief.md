# Banner generation brief — `rteam_tg_auth`

> Use this every time you need to regenerate the listing banner so the
> visual identity stays consistent with Health Check (H+), Prozorro (P+),
> FSM Repair (R+).

## Target

`rteam_tg_auth/static/description/banner.png`, **1120 x 560 (2:1)**.
Apps.odoo.com pulls this from the manifest `"images": [...]` list.

## Pipeline

1. nano banana pro / Gemini 3 Pro Image with the Light Glass prompt below.
2. Crop to 2:1 with `sips -c 560 1120 in.png --out cropped.png` (Apple `sips` is `height width`).
3. Sanity-resize to exactly the target with `sips -Z 1120 cropped.png --out banner.png` (only downscales).
4. Drop into `rteam_tg_auth/static/description/banner.png`. Bump module version. Push. Click Re-scan on apps.odoo.com.

## Prompt for nano banana pro

```
Wide 2:1 landscape banner, 1120x560, light Glass aesthetic.

Background: light surface #F7F8FA with two soft circular blurs ---
violet #7C5CFC at 8% opacity (upper-left, ~500px diameter, 120px blur)
and teal #00D4AA at 5% opacity (lower-right, ~400px diameter, 100px blur).

Centerpiece: a single floating monogram "T+" in a frosted glass card
(thin white-on-light frame, subtle inner shadow, slight depth). The "T+"
fill uses the rteam signature gradient --- linear-gradient(90deg,
#7C5CFC 0%, #00D4AA 100%), violet-to-teal left-to-right. Letter weight
heavy, geometric sans, clean uppercase. Small Telegram paper-plane glyph
sits in the lower-right corner of the glass card in #26A5E4 at 60%
opacity, no larger than the cap-height of the "+".

Right of the monogram, four equal-height tiles arranged 2x2 with the
same frosted-glass treatment, each containing one all-caps label in
#0A1628 weight 700:
   APPROVE     LEDGER
   2FA         AUDIT

Each tile shows a single thin glyph above its label in #7C5CFC at 80%
opacity: a check mark, a list, a phone with shield, a clipboard.

Empty space on left and right edges so the banner reads well even when
apps.odoo.com center-crops slightly. No text other than the monogram
"T+" and the four tile labels. No mockups of Telegram screens, no
phones, no laptops --- just the abstract identity.
```

## Sips cheat sheet

```bash
# 1) crop to 2:1 ratio (height first in sips!)
sips -c 560 1120 source.png --out cropped.png

# 2) downscale-only sanity clamp to exactly 1120 wide
sips -Z 1120 cropped.png --out banner.png

# 3) verify
sips -g pixelWidth -g pixelHeight banner.png
# expect: pixelWidth: 1120, pixelHeight: 560
```

## Icon

Same brand kit, smaller. `static/description/icon.png` 128x128, just the
"T+" monogram in the gradient on light glass background. Used both as
the apps.odoo.com listing icon and the Odoo navbar `web_icon` for the
root menu (declared in `views/rteam_tg_auth_menus.xml`).

## Common pitfalls

- nano banana defaults to 16:9 for "wide" -- explicitly say 2:1 and
  1120x560 in the prompt or you'll need a deeper top/bottom crop.
- Apps.odoo.com listing chrome strips inline `background-color` and
  mis-decodes UTF-8 in description text (per memory). The banner image
  itself is fine; just be careful with HTML in `index.html`.
