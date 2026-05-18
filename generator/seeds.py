"""
Tier and genre taxonomy for website-bench.

Seeds themselves are LLM-generated on demand by concept_gen.py — there is no
hand-written SEEDS list. This module defines two things only:

  - TIERS: difficulty levels, the CSS capabilities expected at each level,
    and (for tier 9 onwards) whether the tier needs a harness extension
    beyond static-screenshot grading.
  - GENRES: per-tier lists of website categories the concept LLM is asked
    to flesh out.

Adding a new tier means adding it here, optionally with `requires_motion`
or other capability flags, plus appropriate genres. The rest of the pipeline
picks tiers and genres up automatically.
"""
from __future__ import annotations

from typing import TypedDict


class TierSpec(TypedDict, total=False):
    name: str
    description: str
    css_capabilities: list[str]
    # When True, the tier requires harness changes beyond the static-screenshot
    # path (e.g. clock virtualization, frame-grid capture, motion judge). The
    # generator gates these tiers and the CLI's default tier_max excludes them.
    requires_motion: bool


# ---------- Tier definitions ----------

TIERS: dict[int, TierSpec] = {
    1: {
        "name": "Static blocks",
        "description": (
            "Single-page-feeling layouts. Vertical stacks, basic typography, "
            "solid colors, simple buttons. No multi-column layouts. "
            "DENSITY FLOOR (binding): each page MUST have at least 40 visible "
            "DOM elements AND at least 15 CSS rules. T1 is the simplest tier "
            "but not empty — every page still has a hero, a few sections, "
            "and a footer."
        ),
        "css_capabilities": [
            "system fonts",
            "solid background colors",
            "basic margins/padding",
            "centered single-column content",
            "thin horizontal rules between sections",
            "BINDING density floor: 40+ visible DOM elements and 15+ CSS rules per page",
        ],
    },
    2: {
        "name": "Multi-page identity",
        "description": (
            "Five pages sharing a nav, footer, palette, and typography. "
            "Flexbox basics, simple grid layouts, consistent cross-page "
            "components. DENSITY FLOOR (binding): each page MUST have at "
            "least 100 visible DOM elements AND at least 40 CSS rules. The "
            "shared nav must list ALL 5 pages and appear on every page; the "
            "footer must be identical across pages."
        ),
        "css_capabilities": [
            "flexbox for nav and cards",
            "CSS grid for feature/plan grids",
            "consistent header/footer across pages",
            "buttons with hover-less styling",
            "rounded corners, basic borders",
            "BINDING density floor: 100+ visible DOM elements and 40+ CSS rules per page",
        ],
    },
    3: {
        "name": "Real layout",
        "description": (
            "Multi-column layouts, sidebars, sticky positioning, mixed "
            "content widths. Layout itself becomes a challenge to replicate. "
            "DENSITY FLOOR (binding): each page MUST have at least 180 "
            "visible DOM elements AND at least 60 CSS rules. At least 2 "
            "distinct layout containers per page using flex or grid (e.g. "
            "a sidebar + main + content grid)."
        ),
        "css_capabilities": [
            "fixed sidebars with scrollable main areas",
            "two- and three-column layouts",
            "sticky positioning",
            "filter sidebars",
            "tables and dense data UIs",
            "BINDING density floor: 180+ visible DOM elements and 60+ CSS rules per page",
        ],
    },
    4: {
        "name": "Visual polish",
        "description": (
            "Layouts from tier 2 or 3, treated with intentional decoration. "
            "Gradients, shadow elevation systems, varied border-radius, "
            "decorative pseudo-elements. Layout is not the challenge here — "
            "treatment is. DENSITY FLOOR (binding): each page MUST have at "
            "least 220 visible DOM elements AND at least 80 CSS rules AND "
            "at least 15 distinct CSS colors AND at least 5 gradient or "
            "shadow declarations. A bare hero page with one gradient does "
            "NOT qualify."
        ),
        "css_capabilities": [
            "linear and radial gradients on backgrounds and accents",
            "box-shadow elevation systems with multiple depths",
            "border-radius rhythms (e.g. 4px / 12px / 999px) used consistently",
            "::before and ::after decorative pseudo-elements",
            "CSS filters such as drop-shadow or backdrop-filter (glass)",
            "BINDING density floor: 220+ visible DOM elements, 80+ CSS rules, 15+ distinct colors, 5+ gradients/shadows per page",
        ],
    },
    5: {
        "name": "Custom typography systems",
        "description": (
            "Inherits tier-3 multi-column layout AND tier-4 visual polish, "
            "then layers a deliberate typographic system on top. Pages must be "
            "BOTH text-dense AND visually composed — never a single sparse "
            "column. Each page contains many distinct typographic elements "
            "(sections, callouts, footnotes, marginalia, captions, by-lines, "
            "pull quotes) treated as first-class design objects. A simpler "
            "tier-4 page that merely uses one or two fancy fonts does NOT "
            "qualify as tier 5. DENSITY FLOOR (binding): each page MUST have "
            "at least 280 visible DOM elements AND at least 110 CSS rules "
            "AND at least 6 distinct font-sizes AND at least 3 font-weights. "
            "Must visibly exceed a typical tier-4 page in both content "
            "richness AND visual polish."
        ),
        "css_capabilities": [
            "6+ distinct font-size values forming a clear modular scale (display, h1, h2, h3, body, caption, small)",
            "3+ font-weight values used purposefully across hierarchy",
            "letter-spacing tuned per heading level and per text role",
            "line-height variation between headlines, body, and dense type",
            "drop caps via ::first-letter on lead paragraphs",
            "pull quotes with their own typographic treatment (size, weight, color, position)",
            "marginalia or sidebar annotations alongside main column",
            "captions, by-lines, and section labels as recognizable type elements",
            "preserve tier-3 multi-column layouts (sidebars, sticky positioning)",
            "preserve tier-4 visual polish (gradients, shadows, radii, decorative pseudo-elements)",
            "BINDING density floor: 280+ visible DOM elements, 110+ CSS rules, 6+ font-sizes, 3+ font-weights per page",
        ],
    },
    6: {
        "name": "Forms and data-heavy",
        "description": (
            "Inherits tier-4 visual polish. Each page combines pixel-accurate "
            "forms AND dense data tables — not one or the other. Custom-"
            "styled checkboxes, radios, selects, and toggles — never browser "
            "defaults. Summary stat cards or aggregate-readout strips above "
            "tables. The challenge is precision in many small repeated "
            "elements packed into dense, scannable layouts. DENSITY FLOOR "
            "(binding): each page MUST have at least 380 visible DOM elements "
            "AND at least 140 CSS rules AND at least 15 form inputs spread "
            "across multiple form sections AND at least one data table with "
            "6+ columns × 20+ rows."
        ),
        "css_capabilities": [
            "15+ form inputs per page spread across multiple form sections",
            "styled <input>, <select>, <textarea> with consistent borders and padding",
            "custom checkbox, radio, and toggle appearance (CSS-only, no defaults)",
            "multi-column form layouts with consistent gutter spacing and aligned labels",
            "dense data tables: 6+ columns, 20+ rows, zebra striping, sticky headers",
            "tabular-feeling numeric alignment (right-aligned, monospace digits)",
            "form validation visual states using only CSS pseudo-classes",
            "summary stat cards or aggregate readouts above tables",
            "preserve tier-4 visual polish (gradients, shadows, radii) across all surfaces",
            "BINDING density floor: 380+ visible DOM elements, 140+ CSS rules, 15+ form inputs, 1+ table (6 cols × 20 rows) per page",
        ],
    },
    7: {
        "name": "Inline SVG and complex shapes",
        "description": (
            "Inherits tier-3 multi-column layout AND tier-4 visual polish. "
            "The page's distinguishing signature is non-rectangular geometry "
            "delivered through substantial inline SVG content. Each page must "
            "contain at least 30 inline <path>/<polygon>/<circle>/<rect>/"
            "<ellipse> primitives spread across multiple distinct SVG figures "
            "(illustrations, decorative dividers, custom icons, infographic "
            "diagrams, or chart geometry). A page that uses a single small "
            "SVG logo on top of an otherwise tier-3 layout does NOT qualify "
            "as tier 7 — the SVG must carry meaningful visual weight. "
            "DENSITY FLOOR (binding): each page MUST have at least 460 "
            "visible DOM elements (the SVG primitives count toward this) "
            "AND at least 180 CSS rules in addition to the 30+ SVG primitives."
        ),
        "css_capabilities": [
            "30+ inline SVG primitives (path/polygon/circle/rect/ellipse) per page",
            "multiple distinct SVG figures per page (illustrations, icons, dividers, diagrams)",
            "inline <svg> with custom paths, shapes, and patterns",
            "clip-path for non-rectangular cuts on raster or text content",
            "CSS transforms combining rotate, skew, translate",
            "mask-image or clip-path masking",
            "SVG-defined gradients and patterns as backgrounds",
            "preserve tier-3 multi-column layouts (sidebars, sticky positioning)",
            "preserve tier-4 visual polish (gradients, shadows, varied radii, decorative pseudo-elements)",
            "BINDING density floor: 460+ visible DOM elements, 180+ CSS rules, 30+ SVG primitives per page",
        ],
    },
    8: {
        "name": "Mixed visual systems",
        "description": (
            "The most demanding tier. Each page is a composition of 6+ "
            "distinct visual modules (hero, longform body, sidebar, gallery "
            "grid, data callout, timeline strip, figure with caption, "
            "marginalia, pull quote, footer block — pick 6+), each with its "
            "own internal layout language. Combines tier-3 multi-column "
            "layout, tier-4 visual polish, tier-5 typographic system, tier-6 "
            "data density, and selectively tier-7 SVG accents in a single "
            "coherent page. Held together by disciplined spacing, type, and "
            "color tokens shared across modules. DENSITY FLOOR (binding): "
            "each page MUST have at least 550 visible DOM elements AND at "
            "least 240 CSS rules. A tier-8 page is unmistakably the densest "
            "in the benchmark — no tier-8 page should have fewer visible "
            "elements than a tier-7 infographic page."
        ),
        "css_capabilities": [
            "6+ distinct visual modules per page, each with its own internal layout",
            "intentional mixing of flex, grid, and positioning between modules",
            "module-to-module rhythm breaks held together by global spacing/type discipline",
            "inherit tier-3 multi-column layout (sidebars, sticky positioning)",
            "inherit tier-4 visual polish (gradients, shadows, varied radii, pseudo-elements)",
            "inherit tier-5 typographic system (6+ font sizes, 3+ weights, drop caps, pull quotes)",
            "inherit tier-6 data density where appropriate (tables, stat cards, structured lists)",
            "selective tier-7 inline SVG accents (decorative dividers, icons, illustrative spots)",
            "asymmetric grid systems with deliberate ragged edges",
            "shared color tokens (4+ accent roles) and shared type tokens unifying disparate modules",
            "BINDING density floor: 550+ visible DOM elements and 240+ CSS rules per page",
        ],
    },
    9: {
        "name": "Animations",
        "description": (
            "Autonomous animations only — continuous loops and on-load "
            "entrance effects. No interaction-driven motion (no hover, "
            "click, scroll triggers). JavaScript permitted, but ONLY to "
            "drive animations. Requires the motion harness (Playwright "
            "page.clock virtualization, frame-grid capture, motion judge) "
            "which is not yet wired up in the generator."
        ),
        "css_capabilities": [
            "@keyframes definitions and animation properties",
            "transform-based motion (translate, scale, rotate)",
            "opacity transitions for entrance effects",
            "animation-delay sequencing for staggered reveals",
            "prefers-reduced-motion media query for politeness",
        ],
        "requires_motion": True,
    },
}


# ---------- Genre taxonomy ----------
# Genres available per tier for LLM-driven seed synthesis. concept_gen.py reads
# this to know which (tier, genre) pairs are valid to ask the LLM to flesh out.

GENRES: dict[int, list[str]] = {
    1: ["portfolio", "restaurant", "personal-blog", "event-announcement", "recipe-card"],
    2: ["saas-marketing", "conference", "mobile-app", "editorial", "nonprofit"],
    3: ["documentation", "ecommerce", "dashboard", "news-magazine", "agency"],
    4: ["marketing-landing", "photographer-portfolio", "hotel-resort", "fashion-lookbook", "music-album-page"],
    5: ["poetry-collection", "magazine-feature", "gallery-exhibition", "book-publisher", "restaurant-elegant"],
    6: ["signup-flow", "application-form", "comparison-table", "account-settings", "survey"],
    7: ["data-viz-report", "infographic", "brand-identity", "illustration-showcase", "icon-library"],
    8: ["longform-article", "news-feature", "design-magazine", "special-report", "multimedia-essay"],
    9: ["hero-animation", "loading-experience", "ambient-background", "brand-reveal", "motion-portfolio"],
}


# ---------- Seed schema (documentation only) ----------
# concept_gen.py produces dicts matching this shape. No hand-written instances
# of Seed live in this module — the LLM generates every one. The TypedDict
# is kept so downstream code has a single place to look up the schema.

class Seed(TypedDict):
    id: str
    tier: int
    genre: str
    pages: list[str]
    palette_hint: str
    type_style: str
    description: str
    constraints: list[str]
    page_specs: dict[str, str]  # short description per page


# ---------- Tier helpers ----------

def tier_range() -> tuple[int, int]:
    """Inclusive (min, max) of currently generatable tiers.

    Excludes tiers that require harness extensions (e.g. tier 9 motion) so the
    CLI defaults pick up only tiers the pipeline can actually emit today. To
    target a gated tier, pass --tier-max explicitly.
    """
    static_tiers = [
        t for t, spec in TIERS.items()
        if not spec.get("requires_motion", False)
    ]
    if not static_tiers:
        raise RuntimeError("no static tiers defined in TIERS")
    return min(static_tiers), max(static_tiers)


def is_motion_tier(tier: int) -> bool:
    """True if this tier requires the motion harness (not yet implemented)."""
    spec = TIERS.get(tier)
    return bool(spec and spec.get("requires_motion", False))
