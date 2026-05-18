"""
Prompts used by the generator.

Kept separate from generate_dataset.py because:
  1. These get iterated on frequently as the benchmark evolves.
  2. v1 will add a critique/refine loop with two more prompts here.
  3. Some rules (viewport size, forbidden tags) are referenced by other parts
     of the system; centralizing the constants here keeps them in sync.

If you change the viewport or any of the structural constraints, also update:
  - templates/environment/make.py  (VIEWPORT)
  - templates/tests/score.py        (VIEWPORT)
  - generate_dataset.py             (validate_html: banned tags, length floor)
"""
from __future__ import annotations

# ---------- Constants referenced across the project ----------

# Viewport everything renders at. Keep in sync with make.py and score.py.
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800


# ---------- System prompt ----------

SYSTEM_PROMPT = f"""You generate static HTML/CSS for benchmark websites.

You will be asked to produce ONE self-contained HTML page at a time. The page
belongs to a larger 5-page website that shares visual identity across all
pages. The page will be rendered at viewport {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT}
with headless Chromium and used as a reference screenshot for a
code-generation benchmark.

Hard rules — violating any of these breaks the benchmark:

1. The page must be a complete, valid HTML document with <!DOCTYPE html>,
   <html>, <head>, and <body> tags.
2. All CSS must be inline in <style> tags inside <head>. NO external stylesheets.
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
8. Design for a {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT} viewport. Content should
   look intentional in that space; the "fold" at {VIEWPORT_HEIGHT}px should
   feel like a deliberate breakpoint.

Output format: return the raw HTML document, starting with <!DOCTYPE html>
and ending with </html>. NO markdown fences, NO commentary, NO preamble,
NO JSON wrapper.
"""


# ---------- User prompt builder ----------

def build_page_prompt(
    seed: dict,
    page_name: str,
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

**THE PAGE YOU ARE GENERATING NOW:**
- **{page_name}**: {seed["page_specs"][page_name]}

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
