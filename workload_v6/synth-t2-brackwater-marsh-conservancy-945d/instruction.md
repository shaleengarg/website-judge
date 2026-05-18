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

- `/app/references/desktop/volunteer.png`
- `/app/references/desktop/mission.png`
- `/app/references/desktop/contact.png`
- `/app/references/desktop/grants.png`
- `/app/references/desktop/wetlands.png`
- `/app/references/tablet/volunteer.png`
- `/app/references/tablet/mission.png`
- `/app/references/tablet/contact.png`
- `/app/references/tablet/grants.png`
- `/app/references/tablet/wetlands.png`
- `/app/references/phone/volunteer.png`
- `/app/references/phone/mission.png`
- `/app/references/phone/contact.png`
- `/app/references/phone/grants.png`
- `/app/references/phone/wetlands.png`

## Output locations

You MUST create exactly these page files:

- `/app/output/volunteer/index.html`
- `/app/output/mission/index.html`
- `/app/output/contact/index.html`
- `/app/output/grants/index.html`
- `/app/output/wetlands/index.html`

You MAY additionally create **exactly ONE** shared stylesheet at
`/app/output/_shared.css` and reference it from each page via
`<link rel="stylesheet" href="../_shared.css">`. Each page may also contain a
small inline `<style>` block in `<head>` for page-specific overrides.

### Hard constraints on file structure

- **At most ONE CSS file** anywhere under `/app/output/`. No per-page CSS files
  (e.g. `/app/output/about/about.css` is NOT allowed). No additional shared
  stylesheets.
- **No `@import` statements** in any CSS — the one shared stylesheet must be
  self-contained.
- **No external network resources**: no Google Fonts, no CDN links, no remote
  images. The renderer has NO network access; external URLs will silently
  fail to load.
- **No JavaScript.** Pure HTML + CSS only.
- **No image files.** Where images would go, use colored placeholder blocks
  (e.g. a `<div>` with a background color or gradient).
