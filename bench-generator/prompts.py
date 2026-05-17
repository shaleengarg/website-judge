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

Your job: produce 5 self-contained HTML pages for a single website at a given
difficulty tier, genre, and aesthetic. The pages will be rendered at viewport
{VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT} with headless Chromium and used as reference
screenshots for a code-generation benchmark.

Hard rules — violating any of these breaks the benchmark:

1. Each page must be a complete, valid HTML document with <!DOCTYPE html>,
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
7. All 5 pages must share a consistent visual identity: same nav bar, same
   footer (if any), same palette, same typography. Style code can be
   duplicated across pages — each page is standalone.
8. Design for a {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT} viewport. Content should
   look intentional in that space; the "fold" at {VIEWPORT_HEIGHT}px should
   feel like a deliberate breakpoint.

Output format: return STRICT JSON, no markdown, no commentary. Top-level keys
are the page names (e.g. "home", "about"). Each value is a complete HTML
document as a single string. No other keys, no extra fields, no preamble.
"""


# ---------- User prompt builder ----------

def build_user_prompt(seed: dict, prior_errors: list[str] | None = None) -> str:
    """Format a seed (and optional prior validation errors) into a user prompt."""
    page_lines = "\n".join(
        f"  - **{name}**: {desc}" for name, desc in seed["page_specs"].items()
    )
    constraints = "\n".join(f"  - {c}" for c in seed["constraints"])

    prompt = f"""Generate a website with the following spec.

**Task ID:** {seed["id"]}
**Tier:** {seed["tier"]}
**Genre:** {seed["genre"]}
**Description:** {seed["description"]}

**Palette:** {seed["palette_hint"]}
**Typography:** {seed["type_style"]}

**Hard constraints (must all hold):**
{constraints}

**Pages to generate** (each is a single HTML file at /app/output/<name>/index.html):
{page_lines}

Return JSON with these exact keys: {list(seed["page_specs"].keys())}.

Each value is a complete HTML document. The pages must share a consistent
header/footer/palette/typography. They are different pages of the same site.
"""

    if prior_errors:
        prompt += (
            "\n\n**Previous attempt failed validation with these errors:**\n"
            + "\n".join(f"  - {e}" for e in prior_errors)
            + "\n\nFix the issues and regenerate."
        )

    return prompt
