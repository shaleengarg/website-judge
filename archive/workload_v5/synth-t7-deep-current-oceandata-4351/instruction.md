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

- `/app/references/desktop/temperature-rise.png`
- `/app/references/desktop/plastic-crisis.png`
- `/app/references/desktop/ocean-health.png`
- `/app/references/desktop/take-action.png`
- `/app/references/desktop/species-atlas.png`
- `/app/references/tablet/temperature-rise.png`
- `/app/references/tablet/plastic-crisis.png`
- `/app/references/tablet/ocean-health.png`
- `/app/references/tablet/take-action.png`
- `/app/references/tablet/species-atlas.png`
- `/app/references/phone/temperature-rise.png`
- `/app/references/phone/plastic-crisis.png`
- `/app/references/phone/ocean-health.png`
- `/app/references/phone/take-action.png`
- `/app/references/phone/species-atlas.png`

## Output locations

Create exactly these files:

- `/app/output/temperature-rise/index.html`
- `/app/output/plastic-crisis/index.html`
- `/app/output/ocean-health/index.html`
- `/app/output/take-action/index.html`
- `/app/output/species-atlas/index.html`

You may use additional files (CSS, fonts, etc.) inside each page's directory.
The verifier renders `file://` URLs, so any external assets you reference
(Google Fonts, CDNs, etc.) must be reachable during the agent's run.
