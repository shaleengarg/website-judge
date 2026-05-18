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
            "solid colors, simple buttons. No multi-column layouts."
        ),
        "css_capabilities": [
            "system fonts",
            "solid background colors",
            "basic margins/padding",
            "centered single-column content",
            "thin horizontal rules between sections",
        ],
    },
    2: {
        "name": "Multi-page identity",
        "description": (
            "Five pages sharing a nav, footer, palette, and typography. "
            "Flexbox basics, simple grid layouts, consistent cross-page "
            "components."
        ),
        "css_capabilities": [
            "flexbox for nav and cards",
            "CSS grid for feature/plan grids",
            "consistent header/footer across pages",
            "buttons with hover-less styling",
            "rounded corners, basic borders",
        ],
    },
    3: {
        "name": "Real layout",
        "description": (
            "Multi-column layouts, sidebars, sticky positioning, mixed "
            "content widths. Layout itself becomes a challenge to replicate."
        ),
        "css_capabilities": [
            "fixed sidebars with scrollable main areas",
            "two- and three-column layouts",
            "sticky positioning",
            "filter sidebars",
            "tables and dense data UIs",
        ],
    },
    4: {
        "name": "Visual polish",
        "description": (
            "Layouts from tier 2 or 3, treated with intentional decoration. "
            "Gradients, shadow elevation systems, varied border-radius, "
            "decorative pseudo-elements. Layout is not the challenge here — "
            "treatment is."
        ),
        "css_capabilities": [
            "linear and radial gradients on backgrounds and accents",
            "box-shadow elevation systems with multiple depths",
            "border-radius rhythms (e.g. 4px / 12px / 999px) used consistently",
            "::before and ::after decorative pseudo-elements",
            "CSS filters such as drop-shadow or backdrop-filter (glass)",
        ],
    },
    5: {
        "name": "Custom typography systems",
        "description": (
            "Typography is the visual identity. A coherent type scale across "
            "multiple sizes and weights, deliberate letter-spacing and "
            "line-height tuning, drop caps, pull quotes."
        ),
        "css_capabilities": [
            "4+ distinct font-size values forming a clear modular scale",
            "2-3 font-weight values used purposefully (not just bold/regular)",
            "letter-spacing tuned per heading level",
            "line-height variation between headlines and body",
            "drop caps via ::first-letter",
            "pull quotes with their own typographic treatment",
        ],
    },
    6: {
        "name": "Forms and data-heavy",
        "description": (
            "Pixel-accurate forms with custom-styled inputs, checkboxes, and "
            "radios. Or dense tables with zebra striping, sticky headers, "
            "and aligned numeric columns. The challenge is precision in "
            "many small repeated elements."
        ),
        "css_capabilities": [
            "styled <input>, <select>, <textarea> with consistent borders, padding",
            "custom checkbox and radio appearance (CSS-only)",
            "multi-column form layouts with consistent gutter spacing",
            "dense data tables with zebra striping and sticky headers",
            "tabular-feeling numeric alignment (right-aligned, monospace digits)",
            "form validation visual states using only CSS pseudo-classes",
        ],
    },
    7: {
        "name": "Inline SVG and complex shapes",
        "description": (
            "Inline <svg> illustrations, custom icons drawn from paths, "
            "clipped images, masked elements, transformed shapes. The page's "
            "visual signature comes from non-rectangular geometry."
        ),
        "css_capabilities": [
            "inline <svg> with custom paths, shapes, and patterns",
            "clip-path for non-rectangular cuts",
            "CSS transforms combining rotate, skew, translate",
            "mask-image or clip-path masking",
            "SVG-defined gradients and patterns as backgrounds",
        ],
    },
    8: {
        "name": "Mixed visual systems",
        "description": (
            "Multiple distinct sections per page, each with its own internal "
            "layout language. Magazine-style assemblies or dashboard-style "
            "compositions of disparate components. Cohesion comes from "
            "spacing, type, and color discipline holding heterogeneous "
            "sections together."
        ),
        "css_capabilities": [
            "3+ distinct layout regions per page with different grid systems",
            "intentional mixing of flex, grid, and positioning in one page",
            "intentional rhythm breaks between sections",
            "typography variation aligned with section purpose",
            "a discernible spacing system across heterogeneous sections",
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
