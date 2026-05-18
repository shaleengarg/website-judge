# Recreate a 5-page website from screenshots

The directory `/app/references/` contains screenshots of each page across
**three viewports** — desktop, tablet, and phone. The pages share a visual
identity (logo, navigation, color palette, typography). Every screenshot is a
**full-page** capture (entire scrollable content, not just the fold).

Reference screenshots are grouped by viewport:

- Desktop (1440 × 900): `/app/references/desktop/<page>.png`
- Tablet (768 × 1024): `/app/references/tablet/<page>.png`
- Phone (390 × 844): `/app/references/phone/<page>.png`

Recreate each page as static, **responsive** HTML/CSS so that when rendered at
each of the three viewports with headless Chromium, it visually matches the
matching-viewport reference as closely as possible.

## Visual fidelity only — functionality does not matter

You are scored **purely on visual appearance**, not behavior. Specifically:

- Navigation links do not need to work. `href="#"` is fine.
- Forms do not need to submit. No `action` or JS required.
- Buttons do not need to do anything. No event handlers.
- No JavaScript is required at all. Plain HTML and CSS are enough.
- No accessibility, no SEO, no semantics beyond what's needed to render.

Concentrate on making each page **look like** the references at every viewport.
Use responsive CSS (`@media` queries, `flex`/`grid`, fluid units) so the layout
adapts cleanly across the three sizes.

## Inputs

- `/app/references/desktop/account.png`
- `/app/references/desktop/cart.png`
- `/app/references/desktop/product-detail.png`
- `/app/references/desktop/about.png`
- `/app/references/desktop/shop.png`
- `/app/references/tablet/account.png`
- `/app/references/tablet/cart.png`
- `/app/references/tablet/product-detail.png`
- `/app/references/tablet/about.png`
- `/app/references/tablet/shop.png`
- `/app/references/phone/account.png`
- `/app/references/phone/cart.png`
- `/app/references/phone/product-detail.png`
- `/app/references/phone/about.png`
- `/app/references/phone/shop.png`

## Output locations

Create exactly these files:

- `/app/output/account/index.html`
- `/app/output/cart/index.html`
- `/app/output/product-detail/index.html`
- `/app/output/about/index.html`
- `/app/output/shop/index.html`

You may use additional files (CSS, fonts, etc.) inside each page's directory.
The verifier renders `file://` URLs, so any external assets you reference
(Google Fonts, CDNs, etc.) must be reachable during the agent's run.
