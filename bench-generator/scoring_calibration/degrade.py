#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Generate four calibration variants of a bench-generator task:

  near_perfect  — verbatim copy of reference HTML. Lower bound for "what a perfect
                  agent would produce." A sane grader should score these >= 0.95.
  mediocre      — wrong colors + Arial/Times fonts + ~30% lorem-substituted paragraphs.
                  Semantic tags and @media queries preserved. Target band 0.40-0.65.
  bad           — all <h*>/<p>/<a>/<li>/<button> text replaced with lorem; @media
                  queries stripped; viewport meta stripped; semantic tags rewritten
                  to <div>; <link rel=stylesheet> removed; the last page (alpha sort)
                  is omitted entirely. Target band ≤ 0.15.
  adversarial   — every DOM primitive a deterministic grader inspects is preserved
                  (text content, headings, paragraphs, links, buttons, nav regions,
                  repeating groups, semantic tags, @media queries, all five pages).
                  ONLY the visual presentation is sabotaged via a forced style block:
                  Comic Sans on everything, 96px headings, 9px body, clashing neon
                  palette (#FF00FF / #00FF00 / #FFFF00), 2deg rotations on alternate
                  headings, drop shadows, center alignment everywhere. A human looks
                  at this and says "garbage"; a deterministic grader sees identical
                  primitives and scores it high. Target band ≤ 0.15 — V2.1 will MISS
                  this band (deterministic graders are architecturally blind to
                  design quality); the MISS is the evidence we need V3's MLLM judge.

Layout produced:

  bench-generator/scoring_calibration/degraded/<task_id>/<variant>/<page>/index.html

The degradations are intentionally aggressive and regex-based. They do not need to
be syntactically perfect — only consistently bad so tier separation is empirically
measurable. Rules are locked to *this file's filename* (degrade.py). If you change
the rules, copy-rename this file to `degrade_v2.py` and start a new results column;
older calibration results become incomparable across rule changes.

Usage:
    uv run python bench-generator/scoring_calibration/degrade.py \
        --task bench-generator/website-bench_v1/synth-t1-burnt-sage-kitchen-9322 \
        --out bench-generator/scoring_calibration/degraded/
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_MEDIOCRE_PALETTE = ["#6B7280", "#3B82F6", "#10B981", "#F59E0B"]  # gray / blue / green / amber
_BAD_PALETTE = ["#FF6B6B", "#00CED1", "#FFD700", "#FF00FF"]  # salmon / turquoise / gold / magenta

_LOREM_SHORT = "Lorem ipsum dolor sit amet consectetur."
_LOREM_MEDIUM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."
)
_LOREM_HEADING = "Lorem Ipsum Dolor"
_NAV_LABELS = ["Link One", "Link Two", "Link Three", "Link Four", "Link Five"]

_SEMANTIC_TAGS = ["nav", "header", "main", "footer", "article", "section", "aside"]


def replace_hex_colors(html: str, palette: list[str]) -> str:
    """Find every #RRGGBB / #RGB in the source, cycle palette colors over them."""
    seen: dict[str, str] = {}

    def _map(color: str) -> str:
        key = color.lower()
        if key not in seen:
            seen[key] = palette[len(seen) % len(palette)]
        return seen[key]

    def _sub(match: re.Match[str]) -> str:
        return _map(match.group(0))

    return re.sub(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", _sub, html)


def replace_fonts(html: str) -> str:
    """Force Arial on headings, Times New Roman on body — both as font-family values."""
    html = re.sub(
        r"font-family\s*:\s*[^;}]+(;|(?=}))",
        "font-family: Arial, Helvetica, sans-serif;",
        html,
    )
    # Drop any Google Fonts <link>s so the system fonts actually take effect.
    html = re.sub(
        r'<link[^>]*href="https?://fonts\.(google|gstatic)[^"]*"[^>]*>',
        "",
        html,
    )
    html = re.sub(
        r"@import\s+url\([^)]*fonts\.googleapis[^)]*\)\s*;?",
        "",
        html,
    )
    return html


def replace_paragraphs_partial(html: str) -> str:
    """Replace every other <p>'s text content with lorem."""
    count = [0]

    def _replace(match: re.Match[str]) -> str:
        count[0] += 1
        if count[0] % 2 == 0:
            return f"{match.group(1)}{_LOREM_MEDIUM}</p>"
        return match.group(0)

    return re.sub(r"(<p[^>]*>)(.*?)</p>", _replace, html, flags=re.DOTALL)


def replace_all_text(html: str) -> str:
    """Replace text content inside every visible element with lorem placeholders."""
    for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        html = re.sub(
            rf"(<{tag}[^>]*>)(.*?)(</{tag}>)",
            rf"\1{_LOREM_HEADING}\3",
            html,
            flags=re.DOTALL,
        )
    html = re.sub(r"(<p[^>]*>)(.*?)(</p>)", rf"\1{_LOREM_MEDIUM}\3", html, flags=re.DOTALL)
    html = re.sub(r"(<span[^>]*>)(.*?)(</span>)", rf"\1{_LOREM_SHORT}\3", html, flags=re.DOTALL)

    nav_idx = [0]

    def _nav(match: re.Match[str]) -> str:
        label = _NAV_LABELS[nav_idx[0] % len(_NAV_LABELS)]
        nav_idx[0] += 1
        return f"{match.group(1)}{label}</a>"

    html = re.sub(r"(<a[^>]*>)(.*?)</a>", _nav, html, flags=re.DOTALL)
    html = re.sub(r"(<li[^>]*>)([^<]+)(</li>)", rf"\1{_LOREM_SHORT}\3", html, flags=re.DOTALL)
    html = re.sub(
        r"(<button[^>]*>)([^<]+)(</button>)", r"\1Click Here\3", html, flags=re.DOTALL
    )
    return html


def strip_media_queries(html: str) -> str:
    """Remove every @media (...) { ... } block, handling nested braces."""
    result: list[str] = []
    i = 0
    while i < len(html):
        match = re.search(r"@media[^{]*\{", html[i:])
        if not match:
            result.append(html[i:])
            break
        result.append(html[i : i + match.start()])
        depth = 1
        j = i + match.end()
        while j < len(html) and depth > 0:
            if html[j] == "{":
                depth += 1
            elif html[j] == "}":
                depth -= 1
            j += 1
        i = j
    return "".join(result)


def strip_viewport_meta(html: str) -> str:
    return re.sub(r'<meta\s+name=["\']viewport["\'][^>]*>', "", html, flags=re.IGNORECASE)


def strip_semantic_tags(html: str) -> str:
    for tag in _SEMANTIC_TAGS:
        html = re.sub(rf"<{tag}(\s[^>]*)?>", rf'<div class="{tag}"\1>', html, flags=re.IGNORECASE)
        html = re.sub(rf"</{tag}>", "</div>", html, flags=re.IGNORECASE)
    return html


def flatten_layout(html: str) -> str:
    """Replace flex/grid with plain block. Drops alignment + gap properties."""
    html = re.sub(r"display\s*:\s*(flex|grid)\s*;?", "display: block;", html)
    for prop in [
        "flex-direction",
        "flex-wrap",
        "justify-content",
        "align-items",
        "align-content",
        "gap",
        "grid-template-columns",
        "grid-template-rows",
        "grid-column",
        "grid-row",
    ]:
        html = re.sub(rf"{prop}\s*:\s*[^;]+;", "", html)
    return html


def remove_stylesheet_links(html: str) -> str:
    return re.sub(
        r'<link\s+[^>]*rel=["\']stylesheet["\'][^>]*>', "", html, flags=re.IGNORECASE
    )


def make_near_perfect(ref_root: Path, out_root: Path, pages: list[str]) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    for page in pages:
        src = ref_root / page / "index.html"
        dest = out_root / page / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def make_mediocre(ref_root: Path, out_root: Path, pages: list[str]) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    for page in pages:
        src = ref_root / page / "index.html"
        html = src.read_text(encoding="utf-8")
        html = replace_hex_colors(html, _MEDIOCRE_PALETTE)
        html = replace_fonts(html)
        html = replace_paragraphs_partial(html)
        dest = out_root / page / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")


_ADVERSARIAL_STYLE = """
<style>
  * { font-family: "Comic Sans MS", "Papyrus", cursive !important; letter-spacing: 4px !important; }
  body { background: #FF00FF !important; color: #00FF00 !important; }
  h1, h2, h3 { font-size: 96px !important; line-height: 0.85 !important; transform: rotate(2deg) !important; color: #FFFF00 !important; text-shadow: 6px 6px 0 #FF00FF !important; }
  h4, h5, h6 { font-size: 48px !important; color: #00FFFF !important; }
  p, li, span { font-size: 9px !important; line-height: 0.8 !important; text-align: center !important; color: #00FF00 !important; }
  a { color: #FFFF00 !important; text-decoration: underline wavy #FF00FF !important; }
  button { background: #FFFF00 !important; color: #FF00FF !important; box-shadow: 8px 8px 0 #00FF00 !important; }
  nav { background: #00FF00 !important; }
</style>
"""


def make_adversarial(ref_root: Path, out_root: Path, pages: list[str]) -> None:
    """Preserve every DOM primitive; sabotage only the visual presentation."""
    out_root.mkdir(parents=True, exist_ok=True)
    for page in pages:
        src = ref_root / page / "index.html"
        html = src.read_text(encoding="utf-8")
        # Inject the style block as the very last thing inside <head> so it
        # wins the cascade. Use !important to override any source rules.
        if "</head>" in html:
            html = html.replace("</head>", f"{_ADVERSARIAL_STYLE}</head>", 1)
        else:
            html = _ADVERSARIAL_STYLE + html
        dest = out_root / page / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")


def make_bad(ref_root: Path, out_root: Path, pages: list[str]) -> None:
    """Aggressive degradation. The last page (alpha sort) is omitted entirely."""
    out_root.mkdir(parents=True, exist_ok=True)
    if len(pages) <= 1:
        kept = pages
    else:
        kept = pages[:-1]
    for page in kept:
        src = ref_root / page / "index.html"
        html = src.read_text(encoding="utf-8")
        html = replace_hex_colors(html, _BAD_PALETTE)
        html = replace_all_text(html)
        html = strip_media_queries(html)
        html = strip_viewport_meta(html)
        html = strip_semantic_tags(html)
        html = flatten_layout(html)
        html = remove_stylesheet_links(html)
        bad_style = (
            "<style>"
            "body { background: #FF6B6B; color: #2D3436; font-family: monospace; }"
            "div { border: 2px solid #333; padding: 8px; margin: 8px; display: block; }"
            "</style>"
        )
        if "</head>" in html:
            html = html.replace("</head>", f"{bad_style}</head>", 1)
        else:
            html = bad_style + html
        dest = out_root / page / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")


def discover_pages(reference_pages: Path) -> list[str]:
    return sorted(
        p.name for p in reference_pages.iterdir() if p.is_dir() and (p / "index.html").exists()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True, help="Path to a bench-generator task dir")
    parser.add_argument("--out", type=Path, required=True, help="Calibration output root dir")
    args = parser.parse_args()

    task_dir: Path = args.task
    out_root: Path = args.out
    task_id = task_dir.name

    reference_pages = task_dir / "environment" / "reference-pages"
    if not reference_pages.exists():
        print(f"ERROR: no reference-pages at {reference_pages}", file=sys.stderr)
        sys.exit(1)

    pages = discover_pages(reference_pages)
    if not pages:
        print(f"ERROR: no pages under {reference_pages}", file=sys.stderr)
        sys.exit(1)

    print(f"task: {task_id}")
    print(f"pages: {pages}")

    task_out = out_root / task_id
    make_near_perfect(reference_pages, task_out / "near_perfect", pages)
    print(f"  near_perfect/  -> {len(pages)} pages copied verbatim")
    make_mediocre(reference_pages, task_out / "mediocre", pages)
    print(f"  mediocre/      -> {len(pages)} pages (wrong palette, system fonts, partial lorem)")
    make_bad(reference_pages, task_out / "bad", pages)
    bad_pages = len(pages) if len(pages) <= 1 else len(pages) - 1
    print(f"  bad/           -> {bad_pages} pages (full lorem, no @media, no semantic tags, 1 omitted)")
    make_adversarial(reference_pages, task_out / "adversarial", pages)
    print(f"  adversarial/   -> {len(pages)} pages (all DOM preserved; Comic Sans + neon + 96px headings)")


if __name__ == "__main__":
    main()
