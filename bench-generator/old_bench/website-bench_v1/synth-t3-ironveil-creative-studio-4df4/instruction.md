# Recreate a 5-page website from screenshots

The directory `/app/references/` contains 5 PNG screenshots of pages
from the **same website**. The pages share a visual identity (logo, navigation,
color palette, typography). Each screenshot was captured at a viewport of
**1280 × 800** using headless Chromium.

Recreate each page as static HTML/CSS so that, when rendered at the same
viewport with headless Chromium, it visually matches the reference as closely
as possible.

## Visual fidelity only — functionality does not matter

You are scored **purely on visual appearance**, not behavior. Specifically:

- Navigation links do not need to work. `href="#"` is fine.
- Forms do not need to submit. No `action` or JS required.
- Buttons do not need to do anything. No event handlers.
- No JavaScript is required at all. Plain HTML and CSS are enough.
- No accessibility, no SEO, no semantics beyond what's needed to render.

Concentrate everything on making each page **look like** the screenshot at
1280 × 800.

## Inputs

- `/app/references/work.png`
- `/app/references/contact.png`
- `/app/references/studio.png`
- `/app/references/services.png`
- `/app/references/process.png`

## Output locations

Create exactly these files:

- `/app/output/work/index.html`
- `/app/output/contact/index.html`
- `/app/output/studio/index.html`
- `/app/output/services/index.html`
- `/app/output/process/index.html`

You may use additional files (CSS, fonts, etc.) inside each page's directory.
The verifier renders `file://` URLs, so any external assets you reference
(Google Fonts, CDNs, etc.) must be reachable during the agent's run.

