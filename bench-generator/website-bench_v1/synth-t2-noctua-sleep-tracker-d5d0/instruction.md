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

- `/app/references/how-it-works.png`
- `/app/references/download.png`
- `/app/references/features.png`
- `/app/references/pricing.png`
- `/app/references/home.png`

## Output locations

Create exactly these files:

- `/app/output/how-it-works/index.html`
- `/app/output/download/index.html`
- `/app/output/features/index.html`
- `/app/output/pricing/index.html`
- `/app/output/home/index.html`

You may use additional files (CSS, fonts, etc.) inside each page's directory.
Everything must be self-contained — **no external CDNs, no Google Fonts, no
network requests**. The verifier renders `file://` URLs.

## Evaluation

Each page is rendered with Chromium at 1280 × 800 and compared to a re-render
of the reference HTML. The per-page score is:

    score = 0.7 * SSIM + 0.3 * color_histogram_intersection

The final reward is the mean across all 5 pages, clipped to [0, 1].
