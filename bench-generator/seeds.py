"""
Task seeds for v0 of website-bench.

Each seed is a structured spec the LLM uses to generate a 5-page website.
The seed controls difficulty (tier) and aesthetic (genre/palette/typography),
keeping output variance under control.

The TIERS dict below defines what each tier means; SEEDS references tier
numbers from it. Adding a new tier means adding it to TIERS first, then
adding seeds that reference it.
"""
from __future__ import annotations

from typing import TypedDict


class TierSpec(TypedDict):
    name: str
    description: str
    css_capabilities: list[str]


# ---------- Tier definitions ----------
# Tiers are difficulty levels. Each tier names a set of CSS/HTML capabilities
# the agent needs to replicate websites at that level.

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
    # Future tiers go here. Reference them from SEEDS once added.
    # 4: visual polish (gradients, shadows, decorative pseudo-elements)
    # 5: custom type systems (multiple weights, coherent type scale)
    # 6: forms and data-heavy
    # 7: inline SVG and complex shapes
    # 8: mixed visual systems / magazine layouts
}


# ---------- Genre taxonomy ----------
# Genres available per tier for LLM-driven seed synthesis. concept_gen.py reads
# this to know which (tier, genre) pairs are valid to ask the LLM to flesh out.

GENRES: dict[int, list[str]] = {
    1: ["portfolio", "restaurant", "personal-blog", "event-announcement", "recipe-card"],
    2: ["saas-marketing", "conference", "mobile-app", "editorial", "nonprofit"],
    3: ["documentation", "ecommerce", "dashboard", "news-magazine", "agency"],
}


# ---------- Seed definitions ----------

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


SEEDS: list[Seed] = [
    # ---------- Tier 1 (3 seeds) ----------
    {
        "id": "001-minimal-portfolio",
        "tier": 1,
        "genre": "portfolio",
        "pages": ["home", "work", "writing", "about", "contact"],
        "palette_hint": "off-white background, near-black text, single muted blue accent (#3a5a7a)",
        "type_style": "system serif for headings, system sans for body, generous line-height, no decorations",
        "description": "A minimalist designer's portfolio. Single column, lots of negative space, very restrained.",
        "constraints": [
            "single-column layout, content centered with ~640px max width",
            "no grids, no cards, no boxes — just typography on a clean background",
            "very simple thin horizontal rule (1px) between sections",
            "consistent top nav as plain text links with the active page underlined",
        ],
        "page_specs": {
            "home": "Just a name, one-line tagline, and a short paragraph intro. That's the whole page.",
            "work": "A vertical list of 5 project titles with year and one-line description each.",
            "writing": "A vertical list of 6 article titles with dates. No images, no excerpts.",
            "about": "Two paragraphs of bio text. Email address at the bottom.",
            "contact": "Email, phone, and three social handles as plain text lines.",
        },
    },
    {
        "id": "002-restaurant-simple",
        "tier": 1,
        "genre": "restaurant",
        "pages": ["home", "menu", "about", "hours", "reservations"],
        "palette_hint": "warm cream (#f4ede0) background, deep burgundy text (#5c1f1f), gold accent (#b8941f)",
        "type_style": "serif throughout (Georgia-like), italicized subtitles, traditional restaurant feel",
        "description": "A small neighborhood Italian restaurant. Traditional, warm, no flashy graphics.",
        "constraints": [
            "centered layout with content max-width around 700px",
            "decorative italic subtitles in gold under each section heading",
            "no images at all — text-only, traditional menu styling",
            "consistent top nav, all caps, letter-spaced",
        ],
        "page_specs": {
            "home": "Restaurant name as a large serif headline, italic tagline, two-paragraph welcome.",
            "menu": "Three sections (Antipasti, Primi, Secondi) each listing 4-5 items with name, italic description, and price aligned right.",
            "about": "Story of the restaurant in three paragraphs. Chef's name at the bottom.",
            "hours": "Days of the week with opening hours, two columns aligned. A closure note at the bottom.",
            "reservations": "A short paragraph asking guests to call, with a phone number in large type. No form.",
        },
    },
    {
        "id": "003-personal-blog",
        "tier": 1,
        "genre": "personal-blog",
        "pages": ["home", "posts", "tags", "about", "subscribe"],
        "palette_hint": "white background, dark gray (#222) text, single warm accent (#d4691f) for links and tags",
        "type_style": "Georgia-style serif body, sans-serif metadata, generous spacing",
        "description": "A personal blog by a single writer. Posts-first, no marketing fluff.",
        "constraints": [
            "single column, ~680px max content width, centered",
            "no images, no cards — just typography and rules",
            "post listings show: title (link styling), date (small, muted), one-line excerpt",
            "minimal top nav, blog name on the left, page links on the right",
        ],
        "page_specs": {
            "home": "Blog title and tagline, then a list of the 4 most recent posts with date + title + excerpt.",
            "posts": "Same listing style but 10 posts, grouped under year sub-headings.",
            "tags": "A list of 12 tags shown as inline pill-style links with post counts in parentheses.",
            "about": "Two paragraphs of writer bio. Three small text links at the bottom (Twitter, RSS, email).",
            "subscribe": "A paragraph explaining email + RSS options, a fake email input + button, an RSS link below.",
        },
    },

    # ---------- Tier 2 (4 seeds) ----------
    {
        "id": "004-saas-marketing",
        "tier": 2,
        "genre": "saas-marketing",
        "pages": ["home", "features", "pricing", "customers", "contact"],
        "palette_hint": "white background, charcoal text (#1d2939), vivid indigo primary (#4f46e5), light gray section dividers",
        "type_style": "sans-serif throughout, bold large headlines, regular body weight",
        "description": "A typical SaaS startup marketing site for a productivity tool called Tempo.",
        "constraints": [
            "fixed-width centered container around 1100px",
            "consistent top nav with logo on left, links center, CTA button on right",
            "every page has a footer with 3 columns of links and a copyright line",
            "buttons are rounded (8px radius) with the indigo primary color",
            "use flexbox/grid for multi-column layouts",
        ],
        "page_specs": {
            "home": "Hero with large headline + sub + 2 CTA buttons, then a 3-column feature grid below.",
            "features": "Heading + intro paragraph, then 4 feature blocks each with an emoji icon, title, and 2-line description.",
            "pricing": "Three plan cards in a row (Free, Pro, Team), middle one visually highlighted with a colored border and badge.",
            "customers": "A grid of 6 customer logo placeholders (just text in boxes), and one large pull-quote testimonial.",
            "contact": "Two-column layout: left has a contact form (name, email, message, button); right has email/phone/address.",
        },
    },
    {
        "id": "005-conference-event",
        "tier": 2,
        "genre": "conference",
        "pages": ["home", "schedule", "speakers", "venue", "tickets"],
        "palette_hint": "deep navy background (#0a1929), cream text (#f5efe6), bright coral accent (#ff5e5b)",
        "type_style": "bold sans-serif display for headlines, regular sans for body, all-caps for navigation",
        "description": "A two-day design conference called LAYOUT 2026.",
        "constraints": [
            "dark theme — navy background, cream text, coral for accents and CTAs",
            "consistent top nav with the conference name on left, page links on right (all caps)",
            "all pages have the same footer with date + location reminder",
            "use grid layouts for schedule and speakers",
        ],
        "page_specs": {
            "home": "Huge headline 'LAYOUT 2026' with date + city below, intro paragraph, CTA button.",
            "schedule": "Two-day schedule as a table or grid: time | talk title | speaker name. ~6 sessions per day.",
            "speakers": "Grid of 6 speaker cards. Each card: a colored placeholder square for photo, name, one-line bio.",
            "venue": "Two-column: left has venue name + address + transit info; right has a placeholder map (just a colored box with 'MAP' text).",
            "tickets": "Three ticket tiers (Early Bird, Standard, Student) in a row with price, what's included, button.",
        },
    },
    {
        "id": "006-app-landing",
        "tier": 2,
        "genre": "mobile-app",
        "pages": ["home", "features", "screenshots", "pricing", "support"],
        "palette_hint": "soft mint background (#e8f5ee), deep forest green primary (#1f4d3a), white cards, black text",
        "type_style": "rounded sans-serif (system-ui), medium weight, friendly feel",
        "description": "Landing site for a habit-tracking mobile app called Loop.",
        "constraints": [
            "centered container around 1080px",
            "rounded corners everywhere (12px on cards, 999px on buttons)",
            "consistent footer with app store badges (just text placeholders)",
            "use phone-frame placeholders (tall thin rectangles with rounded corners)",
        ],
        "page_specs": {
            "home": "Hero with headline left, phone mockup right (a tall rounded rectangle with abstract content inside).",
            "features": "Three feature rows alternating image/text (phone on left, text on right; then text on left, phone on right; then alternate again).",
            "screenshots": "A row of 4 phone-frame placeholders side by side with a caption under each.",
            "pricing": "Two cards (Free, Premium) — Premium highlighted. Listed features with checkmarks.",
            "support": "FAQ-style: 5 questions as bold lines with 2-line answers underneath each.",
        },
    },
    {
        "id": "007-news-magazine",
        "tier": 2,
        "genre": "editorial",
        "pages": ["home", "politics", "culture", "tech", "about"],
        "palette_hint": "pure white background, black body text, deep red brand color (#9b1c1c) for masthead and section labels",
        "type_style": "serif throughout (Times-like), small caps for section labels, tight leading",
        "description": "An online newspaper called The Western Tribune.",
        "constraints": [
            "newspaper-style masthead at top (large serif title, thin rule below, date)",
            "two-to-three column layouts where appropriate",
            "small-caps section labels in red above each article block",
            "consistent footer with a copyright line and small text links",
        ],
        "page_specs": {
            "home": "Masthead, then a feature lead story on the left with image placeholder + headline + 2-sentence dek + byline, plus 3 smaller stories stacked on the right.",
            "politics": "Section header, then 4 article blocks in a 2x2 grid. Each: small caps label, headline, dek, byline.",
            "culture": "Section header, then 1 large lead story (full-width) + 3 smaller stories below in a 3-column row.",
            "tech": "Section header, then a vertical list of 6 articles with headline + dek + byline + date, separated by thin rules.",
            "about": "Long-form essay-style page: a single headline, then 4 paragraphs of explanatory copy about the publication.",
        },
    },

    # ---------- Tier 3 (3 seeds) ----------
    {
        "id": "008-docs-site",
        "tier": 3,
        "genre": "documentation",
        "pages": ["home", "getting-started", "guides", "reference", "changelog"],
        "palette_hint": "white main area, very light gray sidebar (#f7f7f8), dark text, blue accent (#2563eb) for links",
        "type_style": "system sans for UI, monospace for code, consistent type scale",
        "description": "Technical documentation site for a fake CLI tool called 'orbit'.",
        "constraints": [
            "fixed left sidebar (~240px) with section navigation, scrollable main content area on the right",
            "code blocks shown as dark backgrounds (~#1e293b) with monospace text inside",
            "consistent top bar with product name, search placeholder, GitHub link",
            "right-side TOC (~200px) on long pages showing sub-headings",
        ],
        "page_specs": {
            "home": "Hero in main area with product name + tagline + install command in a code block. Sidebar nav populated with section links.",
            "getting-started": "Sidebar + main with a numbered list of 5 setup steps. Each step has a code block. No right-side TOC.",
            "guides": "Sidebar + main with cards laid out in a 2-column grid; each card has a title, 2-line description, and a 'Read →' link.",
            "reference": "Three-column layout: sidebar nav, main content, right-side TOC. Main has a heading and 4 sub-sections with code samples.",
            "changelog": "Sidebar + main. Main shows entries grouped by version (v1.2, v1.1, v1.0) each with bullet lists of changes.",
        },
    },
    {
        "id": "009-ecommerce-product",
        "tier": 3,
        "genre": "ecommerce",
        "pages": ["home", "shop", "product", "cart", "account"],
        "palette_hint": "white background, near-black text, single bold accent (#d4380d), light gray for muted areas",
        "type_style": "modern sans-serif, tight tracking on headlines, regular body, prices in bold",
        "description": "An online store selling minimalist home goods.",
        "constraints": [
            "consistent top nav with logo center, account/cart icons on the right (use emoji placeholders)",
            "product grid uses CSS grid with consistent gaps",
            "product cards have a colored placeholder square (no real images), title, price",
            "cart and account pages use sidebar-style layouts",
        ],
        "page_specs": {
            "home": "Hero with full-width colored block + headline overlay, then a 4-up grid of featured products below.",
            "shop": "Two-column: left has a narrow filter sidebar (categories, price range, sort dropdown). Right has a 3x3 product grid.",
            "product": "Two-column: large image placeholder on left (square), product info on right (title, price, description paragraphs, size buttons row, 'Add to cart' button).",
            "cart": "Two-column: left is a vertical list of 3 cart line items (image placeholder, title, qty controls, price). Right is an order summary card sticky at top.",
            "account": "Two-column: left is a sidebar with 5 nav links (Profile, Orders, Addresses, Payment, Sign out). Right shows profile fields in a form layout.",
        },
    },
    {
        "id": "010-dashboard-admin",
        "tier": 3,
        "genre": "dashboard",
        "pages": ["overview", "analytics", "users", "billing", "settings"],
        "palette_hint": "very light gray (#f9fafb) page background, white cards, dark text, blue accent (#2563eb), small status colors (green/yellow/red)",
        "type_style": "system sans, regular weights, tabular numbers feel for stats",
        "description": "An admin dashboard for a fake B2B SaaS analytics tool.",
        "constraints": [
            "fixed left sidebar (~220px) with vertical nav of 5 items + a user info block at the bottom",
            "main area has a top bar (breadcrumb left, profile avatar right) and content below",
            "cards everywhere — rounded white boxes with subtle borders and small shadows",
            "use CSS grid for KPI rows and tables for tabular data",
        ],
        "page_specs": {
            "overview": "Top row of 4 KPI cards (each: small label, big number, tiny up/down indicator). Below: a wide 'chart' placeholder (just a colored gradient box with axis labels), and a recent activity feed card on the right.",
            "analytics": "Top row of 3 KPI cards. Below: two side-by-side chart placeholders. Below those: a wide table with 5 rows of data.",
            "users": "Search bar + 'Add user' button at top. A table with columns: avatar, name, email, role (colored chip), last active, actions.",
            "billing": "Top: current plan card with details + 'Upgrade' button. Below: a table of 5 invoice rows with status chips (paid/pending/failed).",
            "settings": "Sidebar nav has Settings active. Main shows 3 stacked form cards: Profile, Notifications, Security. Each card has 2-3 fields and a Save button at the bottom.",
        },
    },
]


def get_seeds(count: int | None = None, tier_range: tuple[int, int] | None = None) -> list[Seed]:
    """Return seeds, optionally filtered by tier range and capped at count."""
    seeds = SEEDS
    if tier_range:
        lo, hi = tier_range
        seeds = [s for s in seeds if lo <= s["tier"] <= hi]
    if count is not None:
        seeds = seeds[:count]
    return seeds


def tier_range() -> tuple[int, int]:
    """Inclusive (min, max) of all defined tiers. Use as CLI defaults."""
    tiers = list(TIERS.keys())
    return min(tiers), max(tiers)


def validate_seeds() -> list[str]:
    """Return a list of validation problems; empty means seeds are well-formed.

    Catches the common authoring mistakes: a seed referencing a tier that
    isn't in TIERS, page_specs out of sync with pages list, duplicate ids.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()
    valid_tiers = set(TIERS.keys())
    for s in SEEDS:
        if s["id"] in seen_ids:
            errors.append(f"duplicate seed id: {s['id']}")
        seen_ids.add(s["id"])
        if s["tier"] not in valid_tiers:
            errors.append(
                f"{s['id']}: tier {s['tier']} not defined in TIERS "
                f"(known: {sorted(valid_tiers)})"
            )
        if s["pages"] != list(s["page_specs"].keys()):
            errors.append(
                f"{s['id']}: pages list out of sync with page_specs keys"
            )
    return errors
