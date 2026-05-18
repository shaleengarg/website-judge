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

- `/app/references/desktop/getting-started.png`
- `/app/references/desktop/api-reference.png`
- `/app/references/desktop/data-models.png`
- `/app/references/desktop/changelog.png`
- `/app/references/desktop/error-codes.png`
- `/app/references/tablet/getting-started.png`
- `/app/references/tablet/api-reference.png`
- `/app/references/tablet/data-models.png`
- `/app/references/tablet/changelog.png`
- `/app/references/tablet/error-codes.png`
- `/app/references/phone/getting-started.png`
- `/app/references/phone/api-reference.png`
- `/app/references/phone/data-models.png`
- `/app/references/phone/changelog.png`
- `/app/references/phone/error-codes.png`

## Output locations

Create exactly these files:

- `/app/output/getting-started/index.html`
- `/app/output/api-reference/index.html`
- `/app/output/data-models/index.html`
- `/app/output/changelog/index.html`
- `/app/output/error-codes/index.html`

You may use additional files (CSS, fonts, etc.) inside each page's directory.
The verifier renders `file://` URLs, so any external assets you reference
(Google Fonts, CDNs, etc.) must be reachable during the agent's run.
