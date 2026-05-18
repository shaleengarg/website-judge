#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "playwright>=1.40",
#     "Pillow>=10",
#     "numpy>=1.24",
# ]
# ///
"""
Deterministic sanity checks for a generated website task.

This runs locally (no Docker) and validates that the generated pages render
to *something coherent* — not blank, not collapsed, with the structural
elements a tier-N page should have, and with cross-page consistency.

This does NOT check that the page matches its seed spec (that's relevance.py).
This DOES catch the failure modes:
  - HTML parses but renders blank (CSS hides body, missing close tag, etc.)
  - Pages individually fine but nav/footer drift across pages
  - Layout collapsed to a few pixels or runaway to tens of thousands

Usage:
    python sanity.py <task_dir>                      # check one task
    python sanity.py <dataset_dir>/*/                # check every task in a dir

Exit code: 0 if all tasks pass, 1 if any fail. Prints per-page detail on failure.

Task layout assumed (matches templates/):
    <task_dir>/
        task.toml
        environment/
            reference-pages/
                <page>/index.html
                ...
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

# Thresholds. All tunable here so a failing run can be diagnosed by reading
# the constants alongside the printed measurements.
# Single-viewport gate at the V4 desktop default. This script's job is "is the
# site renderable and coherent at all", not "is it responsive" — responsive
# correctness is the grader's responsibility. Keep cheap, deterministic.
VIEWPORT = {"width": 1440, "height": 900}
MIN_SCREENSHOT_BYTES = 5_000          # < 5 KB is almost certainly blank
MIN_PIXEL_STDDEV = 8.0                # uniform-color pages have stddev ~0
MIN_VISIBLE_TEXT_CHARS = 200          # body.innerText threshold
MIN_PAGE_HEIGHT_PX = 400              # below: layout collapsed
MAX_PAGE_HEIGHT_PX = 20_000           # above: probably runaway
MAX_FOOTER_TEXT_DELTA = 0.20          # 1 - jaccard on footer word sets
MAX_BG_COLOR_LAB_DE = 12.0            # any cross-page pair above this fails


# ---------- Tier inference ----------

def _read_tier(task_dir: Path) -> int:
    """Pull the tier number out of task.toml without a TOML parser dep."""
    toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    for line in toml.splitlines():
        line = line.strip()
        if line.startswith("tier"):
            # forms: tier = 2  |  tier="2"  |  tier = "2"
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            try:
                return int(val)
            except ValueError:
                pass
    # Fallback: scan for difficulty line containing "Tier N"
    import re
    m = re.search(r"Tier\s+(\d+)", toml)
    if m:
        return int(m.group(1))
    raise ValueError(f"could not read tier from {task_dir / 'task.toml'}")


# ---------- Per-page measurement ----------

@dataclass
class PageMeasurement:
    name: str
    screenshot_path: Path
    screenshot_bytes: int = 0
    pixel_stddev: float = 0.0
    visible_text_chars: int = 0
    visible_text: str = ""
    page_height_px: int = 0
    bg_color: tuple[int, int, int] = (255, 255, 255)
    nav_labels: list[str] = field(default_factory=list)
    footer_text: str = ""
    n_headings: int = 0
    n_paragraphs: int = 0
    has_nav_landmark: bool = False
    has_footer_landmark: bool = False
    n_layout_containers: int = 0
    # Tier 4+ — visual polish
    has_gradient: bool = False
    has_box_shadow: bool = False
    # Tier 5+ — typography system
    distinct_font_sizes: int = 0
    distinct_font_weights: int = 0
    # Tier 6+ — forms / data
    n_form_elements: int = 0
    n_inputs: int = 0
    n_tables: int = 0
    # Tier 7+ — inline SVG
    n_svg_elements: int = 0
    # Source CSS introspection (read from the source HTML, not the DOM)
    source_html_size: int = 0
    render_error: str | None = None


_INSTRUMENT_JS = """
() => {
  const txt = (document.body && document.body.innerText) || "";
  const navEl = document.querySelector('nav') || document.querySelector('[role="navigation"]') || document.querySelector('header');
  const navLinks = navEl ? Array.from(navEl.querySelectorAll('a')).map(a => a.innerText.trim()).filter(t => t.length > 0) : [];
  const footerEl = document.querySelector('footer') || document.querySelector('[role="contentinfo"]');
  const footerText = footerEl ? footerEl.innerText : "";
  const headings = document.querySelectorAll('h1,h2,h3').length;
  const paragraphs = document.querySelectorAll('p').length;

  // Layout-bearing containers: any descendant of <body> whose computed display
  // is 'flex' or 'grid'. Catches both modern layout systems.
  let layoutContainers = 0;
  const fontSizes = new Set();
  const fontWeights = new Set();
  let hasGradient = false;
  let hasBoxShadow = false;

  document.querySelectorAll('body *').forEach(el => {
    const cs = window.getComputedStyle(el);
    const d = cs.display;
    if (d === 'flex' || d === 'grid') layoutContainers += 1;

    // Tier-5: distinct typography values across non-trivial elements.
    // Limit to elements with visible text so empty wrappers don't count.
    if (el.innerText && el.innerText.trim().length > 0) {
      fontSizes.add(cs.fontSize);
      fontWeights.add(cs.fontWeight);
    }

    // Tier-4: gradient or shadow presence. Computed bg-image carries gradients;
    // computed box-shadow is "none" when unset.
    const bgImg = cs.backgroundImage || "";
    if (bgImg.includes("gradient(")) hasGradient = true;
    const shadow = cs.boxShadow || "";
    if (shadow && shadow !== "none") hasBoxShadow = true;
  });

  // Tier-6: forms and tables (DOM count, not CSS).
  const nForms = document.querySelectorAll('form').length;
  const nInputs = document.querySelectorAll('input, select, textarea').length;
  const nTables = document.querySelectorAll('table').length;

  // Tier-7: inline <svg> with at least one drawable child.
  const svgs = document.querySelectorAll('svg');
  let nSvgWithContent = 0;
  svgs.forEach(s => {
    if (s.querySelector('path, rect, circle, ellipse, polygon, polyline, line, g, use, image')) {
      nSvgWithContent += 1;
    }
  });

  const bgRaw = window.getComputedStyle(document.body).backgroundColor;
  return {
    visibleText: txt,
    navLabels: navLinks,
    footerText: footerText,
    nHeadings: headings,
    nParagraphs: paragraphs,
    hasNavLandmark: !!document.querySelector('nav, [role="navigation"], header'),
    hasFooterLandmark: !!footerEl,
    nLayoutContainers: layoutContainers,
    bgColor: bgRaw,
    docHeight: document.documentElement.scrollHeight,
    hasGradient: hasGradient,
    hasBoxShadow: hasBoxShadow,
    distinctFontSizes: fontSizes.size,
    distinctFontWeights: fontWeights.size,
    nForms: nForms,
    nInputs: nInputs,
    nTables: nTables,
    nSvgElements: nSvgWithContent,
  };
}
"""


def _parse_bg_rgb(raw: str) -> tuple[int, int, int]:
    """Parse 'rgb(r, g, b)' or 'rgba(r, g, b, a)' into (r, g, b)."""
    import re
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", raw or "")
    if not m:
        return (255, 255, 255)  # default to white if browser returned 'transparent'
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _measure_page(browser, html_path: Path, screenshot_path: Path) -> PageMeasurement:
    pm = PageMeasurement(name=html_path.parent.name, screenshot_path=screenshot_path)
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    try:
        page.goto(f"file://{html_path.resolve()}", wait_until="load", timeout=15_000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(screenshot_path), full_page=True)

        instr = page.evaluate(_INSTRUMENT_JS)
        pm.visible_text = instr["visibleText"]
        pm.visible_text_chars = len(pm.visible_text)
        pm.nav_labels = list(instr["navLabels"])
        pm.footer_text = instr["footerText"]
        pm.n_headings = int(instr["nHeadings"])
        pm.n_paragraphs = int(instr["nParagraphs"])
        pm.has_nav_landmark = bool(instr["hasNavLandmark"])
        pm.has_footer_landmark = bool(instr["hasFooterLandmark"])
        pm.n_layout_containers = int(instr["nLayoutContainers"])
        pm.page_height_px = int(instr["docHeight"])
        pm.bg_color = _parse_bg_rgb(instr["bgColor"])
        pm.has_gradient = bool(instr["hasGradient"])
        pm.has_box_shadow = bool(instr["hasBoxShadow"])
        pm.distinct_font_sizes = int(instr["distinctFontSizes"])
        pm.distinct_font_weights = int(instr["distinctFontWeights"])
        pm.n_form_elements = int(instr["nForms"])
        pm.n_inputs = int(instr["nInputs"])
        pm.n_tables = int(instr["nTables"])
        pm.n_svg_elements = int(instr["nSvgElements"])

    except Exception as e:
        pm.render_error = f"{type(e).__name__}: {e}"
    finally:
        context.close()

    # Record source size — sometimes useful when diagnosing render errors.
    try:
        pm.source_html_size = html_path.stat().st_size
    except OSError:
        pass

    if screenshot_path.exists():
        pm.screenshot_bytes = screenshot_path.stat().st_size
        try:
            arr = np.asarray(Image.open(screenshot_path).convert("RGB"))
            pm.pixel_stddev = float(arr.std())
        except Exception:
            pass

    return pm


# ---------- Color distance (LAB ΔE) ----------

def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB 0-255 → CIE Lab. Standard D65 illuminant."""
    def _lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(v) for v in rgb)
    # sRGB -> XYZ (D65)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def _f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else (t / (3 * (6 / 29) ** 2) + 4 / 29)

    fx, fy, fz = _f(x), _f(y), _f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b_ = 200 * (fy - fz)
    return L, a, b_


def _lab_delta_e(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    L1, a1, b1 = _srgb_to_lab(c1)
    L2, a2, b2 = _srgb_to_lab(c2)
    return float(((L1 - L2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2) ** 0.5)


# ---------- Per-task check ----------

@dataclass
class TaskResult:
    task_dir: Path
    tier: int
    page_failures: dict[str, list[str]] = field(default_factory=dict)
    cross_page_failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.page_failures and not self.cross_page_failures


def _check_page_render(pm: PageMeasurement) -> list[str]:
    """Render-level checks: did anything actually render to the canvas?"""
    fails: list[str] = []
    if pm.render_error:
        fails.append(f"render_error: {pm.render_error}")
        return fails
    if pm.screenshot_bytes < MIN_SCREENSHOT_BYTES:
        fails.append(
            f"screenshot too small: {pm.screenshot_bytes} bytes "
            f"(< {MIN_SCREENSHOT_BYTES})"
        )
    if pm.pixel_stddev < MIN_PIXEL_STDDEV:
        fails.append(
            f"pixel stddev too low: {pm.pixel_stddev:.2f} (< {MIN_PIXEL_STDDEV}) "
            f"— page appears uniform color"
        )
    if pm.visible_text_chars < MIN_VISIBLE_TEXT_CHARS:
        fails.append(
            f"visible text too short: {pm.visible_text_chars} chars "
            f"(< {MIN_VISIBLE_TEXT_CHARS})"
        )
    if pm.page_height_px < MIN_PAGE_HEIGHT_PX:
        fails.append(
            f"page height collapsed: {pm.page_height_px}px (< {MIN_PAGE_HEIGHT_PX})"
        )
    if pm.page_height_px > MAX_PAGE_HEIGHT_PX:
        fails.append(
            f"page height runaway: {pm.page_height_px}px (> {MAX_PAGE_HEIGHT_PX})"
        )
    return fails


def _check_page_structure(pm: PageMeasurement, tier: int) -> list[str]:
    """DOM-level checks: does the page have the structure its tier requires?

    Each tier inherits the lower-tier expectations. The checks below test
    for the *signature feature* of each new tier — they don't try to verify
    full tier-N fidelity (that's the relevance judge's job).
    """
    fails: list[str] = []
    # Tier 1+: at least one heading and one paragraph
    if pm.n_headings < 1:
        fails.append("no <h1>/<h2>/<h3> headings found")
    if pm.n_paragraphs < 1:
        fails.append("no <p> paragraphs found")
    # Tier 2+: nav + footer landmarks
    if tier >= 2:
        if not pm.has_nav_landmark:
            fails.append("no <nav>/<header>/[role=navigation] landmark (required for tier>=2)")
        if not pm.has_footer_landmark:
            fails.append("no <footer>/[role=contentinfo] landmark (required for tier>=2)")
    # Tier 3+: real layout — at least 2 flex/grid containers
    if tier >= 3 and pm.n_layout_containers < 2:
        fails.append(
            f"only {pm.n_layout_containers} flex/grid container(s); "
            f"tier>=3 should have multi-region layouts (>=2)"
        )
    # Tier 4+: visual polish — gradient or non-trivial box-shadow somewhere
    if tier >= 4 and not (pm.has_gradient or pm.has_box_shadow):
        fails.append(
            "no gradient or box-shadow anywhere on the page; "
            "tier>=4 expects visual polish (decoration)"
        )
    # Tier 5+: custom typography system — multiple sizes OR multiple weights
    if tier >= 5 and pm.distinct_font_sizes < 3 and pm.distinct_font_weights < 2:
        fails.append(
            f"typography too flat: {pm.distinct_font_sizes} distinct sizes and "
            f"{pm.distinct_font_weights} distinct weights; tier>=5 expects "
            f">=3 sizes OR >=2 weights"
        )
    # Tier 6+: forms or dense data signature
    if tier >= 6 and pm.n_form_elements == 0 and pm.n_tables == 0 and pm.n_inputs < 4:
        fails.append(
            f"no <form>, no <table>, and only {pm.n_inputs} input(s); "
            f"tier>=6 expects either a form, a data table, or >=4 inputs"
        )
    # Tier 7+: inline SVG presence
    if tier >= 7 and pm.n_svg_elements < 1:
        fails.append("no inline <svg> element with drawable content (tier>=7)")
    # Tier 8: magazine — 3+ distinct layout containers (was 2 at tier 3)
    if tier >= 8 and pm.n_layout_containers < 3:
        fails.append(
            f"only {pm.n_layout_containers} flex/grid container(s); "
            f"tier 8 magazine assemblies expect >=3 distinct layout regions"
        )
    return fails


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _check_cross_page(measurements: list[PageMeasurement], tier: int) -> list[str]:
    """Cross-page consistency: nav labels, footer text, background color."""
    fails: list[str] = []
    if tier < 2:
        return fails  # tier-1 sites are single-page-feeling; consistency optional

    # Only consider pages that rendered cleanly.
    ok_pages = [pm for pm in measurements if pm.render_error is None]
    if len(ok_pages) < 2:
        return fails

    # Nav labels: every page should report the SAME set of labels.
    ref_nav = set(ok_pages[0].nav_labels)
    for pm in ok_pages[1:]:
        cur = set(pm.nav_labels)
        if cur != ref_nav:
            only_ref = ref_nav - cur
            only_cur = cur - ref_nav
            fails.append(
                f"nav labels differ on {pm.name!r} vs {ok_pages[0].name!r}: "
                f"missing={sorted(only_ref)}, extra={sorted(only_cur)}"
            )

    # Footer: jaccard on word set; large differences are drift.
    def _words(s: str) -> set[str]:
        return {w.lower() for w in s.split() if len(w) > 2}

    ref_footer = _words(ok_pages[0].footer_text)
    for pm in ok_pages[1:]:
        cur = _words(pm.footer_text)
        j = _jaccard(ref_footer, cur)
        if (1 - j) > MAX_FOOTER_TEXT_DELTA:
            fails.append(
                f"footer text drift on {pm.name!r} vs {ok_pages[0].name!r}: "
                f"jaccard={j:.2f} (allowed >= {1 - MAX_FOOTER_TEXT_DELTA:.2f})"
            )

    # Background color consistency (LAB ΔE).
    for i, pm_a in enumerate(ok_pages):
        for pm_b in ok_pages[i + 1:]:
            de = _lab_delta_e(pm_a.bg_color, pm_b.bg_color)
            if de > MAX_BG_COLOR_LAB_DE:
                fails.append(
                    f"background color drift {pm_a.name!r} vs {pm_b.name!r}: "
                    f"ΔE={de:.1f} (allowed <= {MAX_BG_COLOR_LAB_DE})"
                )

    return fails


def check_task(task_dir: Path, *, screenshots_dir: Path | None = None) -> TaskResult:
    """Run all sanity checks on one task. Returns a TaskResult with failures, if any."""
    tier = _read_tier(task_dir)
    ref_root = task_dir / "environment" / "reference-pages"
    if not ref_root.is_dir():
        raise FileNotFoundError(f"missing reference-pages under {task_dir}")

    pages = sorted(p.name for p in ref_root.iterdir()
                   if p.is_dir() and (p / "index.html").exists())
    if not pages:
        raise FileNotFoundError(f"no pages under {ref_root}")

    shots_dir = screenshots_dir or (task_dir / ".sanity-shots")
    shots_dir.mkdir(parents=True, exist_ok=True)

    result = TaskResult(task_dir=task_dir, tier=tier)
    measurements: list[PageMeasurement] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for name in pages:
                html_path = ref_root / name / "index.html"
                shot_path = shots_dir / f"{name}.png"
                pm = _measure_page(browser, html_path, shot_path)
                measurements.append(pm)

                fails = _check_page_render(pm) + _check_page_structure(pm, tier)
                if fails:
                    result.page_failures[name] = fails
        finally:
            browser.close()

    result.cross_page_failures = _check_cross_page(measurements, tier)
    return result


# ---------- Reporting ----------

def _print_result(result: TaskResult) -> None:
    name = result.task_dir.name
    if result.ok:
        print(f"  PASS  {name} (tier {result.tier})")
        return
    print(f"  FAIL  {name} (tier {result.tier})")
    for page, errs in result.page_failures.items():
        print(f"    [{page}]")
        for e in errs:
            print(f"      - {e}")
    for e in result.cross_page_failures:
        print(f"    [cross-page] {e}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dirs", type=Path, nargs="+",
                        help="One or more task directories to check.")
    parser.add_argument("--json", action="store_true",
                        help="Print a machine-readable JSON summary at the end.")
    args = parser.parse_args()

    results: list[TaskResult] = []
    for task_dir in args.task_dirs:
        if not task_dir.is_dir():
            print(f"  SKIP  {task_dir} (not a directory)", file=sys.stderr)
            continue
        if not (task_dir / "task.toml").exists():
            print(f"  SKIP  {task_dir} (no task.toml)", file=sys.stderr)
            continue
        try:
            result = check_task(task_dir)
        except Exception as e:
            print(f"  ERROR {task_dir.name}: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(2)
        results.append(result)
        _print_result(result)

    n_pass = sum(1 for r in results if r.ok)
    n_fail = len(results) - n_pass
    print(f"\nsanity: {n_pass}/{len(results)} tasks passed, {n_fail} failed")

    if args.json:
        summary = {
            "total": len(results),
            "passed": n_pass,
            "failed": n_fail,
            "tasks": [
                {
                    "task": r.task_dir.name,
                    "tier": r.tier,
                    "ok": r.ok,
                    "page_failures": r.page_failures,
                    "cross_page_failures": r.cross_page_failures,
                }
                for r in results
            ],
        }
        print(json.dumps(summary, indent=2))

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
