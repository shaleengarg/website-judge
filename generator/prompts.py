"""
Prompts used by the generator.

Kept separate from generate_dataset.py because:
  1. These get iterated on frequently as the benchmark evolves.
  2. v1 will add a critique/refine loop with two more prompts here.
  3. Some rules (viewport size, forbidden tags) are referenced by other parts
     of the system; centralizing the constants here keeps them in sync.

If you change the viewport list or any of the structural constraints, also update:
  - templates/environment/make.py  (VIEWPORTS)
  - templates/tests/score.py        (VIEWPORTS)
  - generate_dataset.py             (validate_html: banned tags, length floor)
"""
from __future__ import annotations

# ---------- Constants referenced across the project ----------

# Viewports the generated site must look correct at. Keep in sync with
# templates/environment/make.py and templates/tests/score.py.
VIEWPORTS: list[tuple[str, int, int]] = [
    ("desktop", 1440, 900),
    ("tablet",  768,  1024),
    ("phone",   390,  844),
]
# Single-viewport convenience accessors for the bits of the pipeline (sanity,
# relevance) that only render at the dominant size. Reflect the desktop entry.
VIEWPORT_WIDTH = VIEWPORTS[0][1]
VIEWPORT_HEIGHT = VIEWPORTS[0][2]


def _viewports_inline() -> str:
    """Format `desktop 1440×900, tablet 768×1024, phone 390×844`."""
    return ", ".join(f"{label} {w}×{h}" for label, w, h in VIEWPORTS)


# ---------- System prompt ----------

SYSTEM_PROMPT = f"""You generate static HTML/CSS for benchmark websites.

You will be asked to produce ONE self-contained HTML page at a time. The page
belongs to a larger 5-page website that shares visual identity across all
pages. The page will be rendered at THREE viewports — {_viewports_inline()} —
with headless Chromium, each one captured full-page, and used as reference
screenshots for a code-generation benchmark.

Hard rules — violating any of these breaks the benchmark:

1. The page must be a complete, valid HTML document with <!DOCTYPE html>,
   <html>, <head>, and <body> tags.
2. The page MUST reference the site's shared stylesheet as the FIRST element in
   <head>, exactly as:  <link rel="stylesheet" href="../_shared.css">
   You may ALSO add a small inline <style> block in <head> for page-specific
   overrides (page-unique rules only — the shared design system lives in
   _shared.css and you must NOT redefine its tokens or component classes here).
   AT MOST ONE <link rel="stylesheet"> tag per page (the shared one). NO other
   external stylesheets, NO Google Fonts, NO CDN links, NO @import statements
   inside the inline <style> block.
3. NO <script> tags. NO JavaScript. Pure HTML + CSS only.
4. NO network resources: no Google Fonts, no CDN links, no remote images,
   no <link href="https://...">, no <img src="https://...">. The renderer
   has no network access.
5. Use ONLY system fonts (e.g. -apple-system, BlinkMacSystemFont, "Segoe UI",
   Helvetica, Arial, Georgia, Times, monospace, sans-serif, serif).
6. Where images would go, use colored placeholder blocks (a <div> with a
   background color or gradient and optional centered text like "IMG" or a
   short label). NEVER reference image files.
7. The page must share a consistent visual identity (nav bar, footer, palette,
   typography) with the rest of the site. The constraints and palette/type
   hints you receive are the source of truth — anyone reading them should
   produce the same shared elements. Do NOT improvise nav labels or footer
   contents; derive them from the page list and constraints.
8. The page must be RESPONSIVE: it must look correct at every viewport in
   {_viewports_inline()}. Use `@media` queries, flex/grid, and fluid units
   so the layout adapts cleanly from a {VIEWPORTS[0][1]}px desktop down to a
   {VIEWPORTS[-1][1]}px phone. Do NOT pixel-fit to one viewport.

Output format: return the raw HTML document, starting with <!DOCTYPE html>
and ending with </html>. NO markdown fences, NO commentary, NO preamble,
NO JSON wrapper.
"""


# ---------- Shared-CSS system prompt + builder ----------
# This stage runs ONCE per seed, before per-page HTML generation. It produces
# the site's design system as a standalone stylesheet that every page then
# references via <link rel="stylesheet" href="../_shared.css">. Splitting CSS
# out of per-page output cut the per-page token budget enough to fit T7/T8
# infographic pages with 30+ inline SVG primitives under the API streaming
# threshold.

SHARED_CSS_SYSTEM_PROMPT = f"""You generate a single shared CSS stylesheet for a 5-page benchmark website.

The stylesheet is loaded by every page of the site via
<link rel="stylesheet" href="../_shared.css">. Each page then composes its
layout from the classes you define here and adds at most a small inline
<style> for page-unique overrides.

Hard rules — violating any of these breaks the benchmark:

1. Output ONLY CSS. No HTML, no markdown fences, no commentary, no JSON wrapper.
2. NO @import statements at all. The shared stylesheet must be fully self-
   contained — no Google Fonts, no CDN links, no @import of any other file
   (the benchmark allows at most one CSS file per website).
3. Use ONLY system fonts (-apple-system, BlinkMacSystemFont, "Segoe UI",
   Helvetica, Arial, Georgia, Times, monospace, sans-serif, serif).
4. Use CSS custom properties (--ink, --paper, --accent-1, --space-1, etc.) for
   palette, type, and spacing tokens so per-page <style> overrides can reuse them.
5. The stylesheet must encode the FULL shared visual identity: palette tokens,
   type tokens (font-size scale, weights, line-heights, letter-spacing),
   nav and footer styling, layout primitives (containers, grids, sidebars),
   component classes (buttons, cards, callouts, pull quotes, captions, etc.),
   and responsive @media rules for the three viewports {_viewports_inline()}.
6. Be generous: define enough utility/component classes that each page can
   build its layout by composing classes. If a tier needs forms (T6),
   typography (T5), or SVG accents (T7), define their styling here.

Output the complete CSS document. NO markdown fences, NO commentary, NO preamble.
"""


def _motion_brief_for_shared_css(seed: dict) -> str:
    """Tier-9 motion summary for the shared CSS prompt.

    The shared stylesheet is the natural home for `@keyframes` rules and the
    `prefers-reduced-motion` overrides, so the LLM gets the full list of
    animations up-front and is told to define their keyframes here. Per-page
    HTML then references them by name (`animation: word-rise ...`) and pins
    `data-anim` attributes to the right elements.
    """
    anims = seed.get("expected_animations") or {}
    if not anims:
        return ""

    lines: list[str] = []
    for page_name in seed.get("pages", []):
        page_anims = anims.get(page_name, [])
        if not page_anims:
            continue
        lines.append(f"  - **{page_name}**:")
        for a in page_anims:
            lines.append(
                f"      · `data-anim=\"{a['id']}\"` on the {a['target_description']} "
                f"— {a['kind']}, ~{a['duration_ms']}ms — {a['description']}"
            )

    motion_style = seed.get("motion_style", "subtle")
    return f"""

**Tier-9 motion contract (binding — driven by CSS only, NO JavaScript):**

Motion style: **{motion_style}**.

The animations the codegen must implement, page by page:
{chr(10).join(lines)}

In this shared stylesheet you MUST:
  - Define every `@keyframes` rule used by any animation above. Name them
    in kebab-case (e.g. `@keyframes word-rise`, `@keyframes orb-float`).
    Per-page HTML will reference these names via the `animation` property.
  - Use only `transform`, `opacity`, `filter`, `background-position`, `color`,
    `background-color`, `border-radius`, `box-shadow`, and `clip-path` as
    animated properties (these are GPU-friendly and judge-grade-able).
  - Include a `@media (prefers-reduced-motion: reduce)` block that disables
    every animation (`animation: none !important`) and forces animated
    elements to their settled final state (`opacity: 1; transform: none`).
    The motion harness uses this state to capture a static baseline.

Do NOT add any `<script>` directives, JS hooks, or interactive triggers
(`:hover`, `:focus`, `:active`, `:checked`, `@scroll-timeline`). All motion
must be autonomous, driven by `animation` shorthand with `animation-delay`,
`animation-iteration-count`, `animation-fill-mode`, etc."""


def build_shared_css_prompt(seed: dict) -> str:
    """Format the prompt for generating the site's shared stylesheet."""
    constraints = "\n".join(f"  - {c}" for c in seed["constraints"])
    page_spec_lines = "\n".join(
        f"  - **{p}**: {seed['page_specs'][p]}" for p in seed["pages"]
    )
    return f"""Generate the shared stylesheet for a 5-page website.

**Site ID:** {seed["id"]}
**Tier:** {seed["tier"]}  **Genre:** {seed["genre"]}
**Description:** {seed["description"]}

**Palette:** {seed["palette_hint"]}
**Typography:** {seed["type_style"]}

**Hard constraints — must hold identically on every page:**
{constraints}

**The site's 5 pages (each will <link rel="stylesheet" href="../_shared.css">):**
{page_spec_lines}
{_motion_brief_for_shared_css(seed)}

The pages share nav, footer, palette, and typography — encode those here.
Define enough component/utility classes that each page can build its layout
by composing classes you define. Per-page HTML will reference your tokens
and classes; do NOT expect pages to redefine them inline.

Output the complete CSS document. NO markdown fences, NO commentary.
"""


# ---------- User prompt builder ----------

def _motion_brief_for_page(seed: dict, page_name: str) -> str:
    """Tier-9 motion contract for a single page's codegen call.

    Lists the animations this page MUST implement (matching what the shared
    CSS prompt told the model to define `@keyframes` for) plus rules on how
    to pin `data-anim` attributes and what NOT to do.
    """
    all_anims = seed.get("expected_animations") or {}
    page_anims = all_anims.get(page_name) or []
    if not page_anims:
        return ""

    lines: list[str] = []
    for a in page_anims:
        lines.append(
            f"  - **`data-anim=\"{a['id']}\"`** on the {a['target_description']} "
            f"({a['kind']}, ~{a['duration_ms']}ms) — {a['description']}"
        )
    motion_style = seed.get("motion_style", "subtle")

    return f"""

**Tier-9 motion contract for this page (binding):**

Motion style: **{motion_style}**. The shared stylesheet already defines the
`@keyframes` rules; in THIS page you must:

  - Pin a `data-anim="<id>"` attribute on the exact element each animation
    targets. The harness uses these attributes to locate animated elements.
  - Apply the `animation` shorthand on each animated element via inline
    `style="..."` or a small inline `<style>` block. Use kebab-case keyframe
    names that match what you defined in the shared stylesheet.

Animations this page MUST implement (one element per id, no duplicates):
{chr(10).join(lines)}

Hard rules — violating these breaks the grader:
  - NO `<script>` tag. NO JavaScript. All motion is CSS-driven.
  - NO `:hover`, `:focus`, `:active`, `:checked`, or scroll-linked triggers.
    Animations must start on load and run autonomously (loops continue
    indefinitely; entrances settle to a final state with `animation-fill-mode:
    forwards`).
  - The page must still render usefully under `@media
    (prefers-reduced-motion: reduce)` — collapse motion to the settled final
    state. The shared stylesheet should handle this; do not override it."""


def build_page_prompt(
    seed: dict,
    page_name: str,
    shared_css: str = "",
    prior_errors: list[str] | None = None,
) -> str:
    """Format a prompt for generating ONE page of a multi-page site.

    The prompt includes the full site identity (palette, typography,
    constraints) plus brief specs of the OTHER pages so the model knows the
    nav scope and the site's surface area. Only the target page is asked for
    in the output.
    """
    if page_name not in seed["page_specs"]:
        raise KeyError(f"page {page_name!r} not in seed page_specs")

    constraints = "\n".join(f"  - {c}" for c in seed["constraints"])
    other_pages = [p for p in seed["pages"] if p != page_name]
    other_page_lines = "\n".join(
        f"  - **{p}**: {seed['page_specs'][p]}" for p in other_pages
    )
    pages_list = ", ".join(seed["pages"])

    shared_css_block = ""
    if shared_css:
        shared_css_block = (
            "\n**Shared stylesheet (already generated — REUSE its tokens and "
            "classes; do NOT redefine them inline):**\n"
            "```css\n"
            f"{shared_css}\n"
            "```\n"
        )

    prompt = f"""Generate ONE page of a 5-page website.

**Site ID:** {seed["id"]}
**Tier:** {seed["tier"]}  **Genre:** {seed["genre"]}
**Description:** {seed["description"]}

**Palette:** {seed["palette_hint"]}
**Typography:** {seed["type_style"]}

**Hard constraints — must hold identically on every page of this site:**
{constraints}

**The site's 5 pages, in nav order:** {pages_list}
The nav must list all 5 page names. Plain anchor links (href="#" or
href="../<other>/index.html") are fine — the renderer does not follow them.

**Other pages of this site** (DO NOT generate these — listed so you know the
site's full surface area and can keep the nav/footer consistent):
{other_page_lines}
{shared_css_block}
**THE PAGE YOU ARE GENERATING NOW:**
- **{page_name}**: {seed["page_specs"][page_name]}
{_motion_brief_for_page(seed, page_name)}

Reference the shared stylesheet as the FIRST element in <head>:
<link rel="stylesheet" href="../_shared.css">
Then add a small inline <style> only for page-unique overrides (do NOT
redefine the shared tokens or component classes).

Output the complete HTML document for the **{page_name}** page only. No JSON,
no fences, no commentary.
"""

    if prior_errors:
        prompt += (
            "\n\n**Previous attempt for this page failed validation:**\n"
            + "\n".join(f"  - {e}" for e in prior_errors)
            + "\n\nFix the issues and regenerate the full HTML for this page."
        )

    return prompt
