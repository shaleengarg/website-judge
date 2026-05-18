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

- `/app/references/desktop/archive-index.png`
- `/app/references/desktop/type-lab.png`
- `/app/references/desktop/cover-story.png`
- `/app/references/desktop/grid-dispatch.png`
- `/app/references/desktop/object-study.png`
- `/app/references/tablet/archive-index.png`
- `/app/references/tablet/type-lab.png`
- `/app/references/tablet/cover-story.png`
- `/app/references/tablet/grid-dispatch.png`
- `/app/references/tablet/object-study.png`
- `/app/references/phone/archive-index.png`
- `/app/references/phone/type-lab.png`
- `/app/references/phone/cover-story.png`
- `/app/references/phone/grid-dispatch.png`
- `/app/references/phone/object-study.png`

## Output locations

Create exactly these files:

- `/app/output/archive-index/index.html`
- `/app/output/type-lab/index.html`
- `/app/output/cover-story/index.html`
- `/app/output/grid-dispatch/index.html`
- `/app/output/object-study/index.html`

You may use additional files (CSS, fonts, etc.) inside each page's directory.
The verifier renders `file://` URLs, so any external assets you reference
(Google Fonts, CDNs, etc.) must be reachable during the agent's run.
