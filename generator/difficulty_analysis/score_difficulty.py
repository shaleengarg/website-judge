# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#     "playwright==1.49.0",
#     "numpy>=2.0",
#     "scikit-image>=0.24",
#     "pillow>=11.0",
#     "scipy>=1.13",
# ]
# ///
"""
Empirical difficulty scorer for workloads_v4.

Combines:
- Yellow Lab Tools (https://github.com/YellowLabTools/YellowLabTools) — HTML+CSS
  structural metrics extracted via headless Chromium. We use raw `phantomas`
  metrics; the YLT `globalScore` is a quality grade, not a difficulty score.
- Five custom signals YLT does not emit: SVG path count, CSS gradient count,
  JPEG-filesize visual-clutter proxy (Forsythe 2011), Canny edge density
  (Miniukovich CHI 2015), and cross-page nav Jaccard (T2 identity signal).
- Composite difficulty score using the DesignBench (arXiv:2506.06251) formula
  S = 0.25*z(I) + 0.25*z(U) + 0.25*z(C) + 0.25*z(L).

See /Users/shaleen/.claude/plans/what-makes-a-website-playful-candy.md for
the literature grounding behind each metric.

Run: uv run python generator/difficulty_analysis/score_difficulty.py [--report]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright
from skimage import feature
from skimage.color import rgb2gray

REPO = Path(__file__).resolve().parents[2]
DEFAULT_WORKLOADS = REPO / "workloads_v4"
GRADER = REPO / "generator" / "scoring_calibration" / "grader_versions" / "v4.0" / "score.py"
OUT_DIR = Path(__file__).resolve().parent / "out"

YLT_CLI = Path("/opt/homebrew/lib/node_modules/yellowlabtools/bin/cli.js")
NODE = Path("/opt/homebrew/opt/node@20/bin/node")
CHROMIUM_OVERRIDE = (
    Path.home()
    / "Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64"
    / "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
)

# Single viewport for difficulty scoring — desktop is canonical.
# (The grader uses 3 viewports for fidelity; for intrinsic complexity, one
#  rendering is enough and triples runtime if we add the other two.)
VIEWPORT = {"width": 1440, "height": 900}

YLT_METRIC_KEYS = [
    "DOMelementsCount",
    "DOMelementMaxDepth",
    "iframesCount",
    "cssRules",
    "cssSelectors",
    "cssDeclarations",
    "cssComplexSelectors",
    "cssSpecificityIdAvg",
    "cssDuplicatedSelectors",
    "cssImportants",
    "cssEmptyRules",
    "cssColors",
    "nodesWithInlineCSS",
]

# Extract EXTRACTION_JS from the grader without importing it (the grader has
# heavy module-level imports we don't need). The constant is a triple-quoted
# raw string and we slice between EXTRACTION_JS = r""" ... """ markers.
def _load_extraction_js() -> str:
    src = GRADER.read_text()
    start = src.index('EXTRACTION_JS = r"""') + len('EXTRACTION_JS = r"""')
    end = src.index('"""', start)
    return src[start:end]


EXTRACTION_JS = _load_extraction_js()


@dataclass
class PageMetrics:
    task_id: str
    tier: int
    genre: str
    page: str
    # YLT raw metrics (some workloads have no `imagesCount`; we drop it).
    ylt: dict[str, float] = field(default_factory=dict)
    # Custom add-ons
    svg_path_count: int = 0
    gradient_count: int = 0
    html_bytes: int = 0
    css_bytes: int = 0
    jpeg_proxy_bytes_per_kpixel: float = 0.0
    edge_density: float = 0.0
    # Nav signature (used at task level for cross_page_nav_jaccard)
    nav_link_texts: list[str] = field(default_factory=list)


@dataclass
class TaskDifficulty:
    id: str
    tier: int
    genre: str
    per_page: list[PageMetrics]
    aggregates: dict[str, float] = field(default_factory=dict)
    cross_page_nav_jaccard: float = 0.0
    composite_designbench_S: float = 0.0
    composite_axis_mean: float = 0.0


# ---------------------------------------------------------------------------
# HTTP server + YLT runner
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve_directory(directory: Path):
    port = _free_port()
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "http.server", str(port), "--directory", str(directory)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait until the port answers; cap at ~5 s.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    try:
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_ylt(url: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["PUPPETEER_EXECUTABLE_PATH"] = str(CHROMIUM_OVERRIDE)
    result = subprocess.run(
        [str(NODE), str(YLT_CLI), url, "--device", "desktop", "--reporter", "json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    if not result.stdout.strip():
        raise RuntimeError(f"YLT empty output for {url}; stderr tail:\n{result.stderr[-500:]}")
    return json.loads(result.stdout)


def ylt_metrics_subset(ylt_json: dict[str, Any]) -> dict[str, float]:
    metrics = ylt_json.get("toolsResults", {}).get("phantomas", {}).get("metrics", {})
    return {k: float(metrics.get(k, 0)) for k in YLT_METRIC_KEYS}


# ---------------------------------------------------------------------------
# Custom metrics
# ---------------------------------------------------------------------------


SVG_PRIMITIVE_RE = re.compile(
    r"<(path|polygon|circle|rect|ellipse|polyline|line)\b", re.IGNORECASE
)
GRADIENT_RE = re.compile(r"(linear|radial|conic)-gradient\s*\(", re.IGNORECASE)
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def extract_css_from_html(html: str) -> str:
    """Concatenate all inline <style> blocks plus inline style="" attribute
    values. The workloads ship single-file HTML with embedded CSS, so this
    captures everything."""
    blocks = STYLE_BLOCK_RE.findall(html)
    inline = re.findall(r'style="([^"]*)"', html)
    return "\n".join(blocks + inline)


def count_svg_primitives(html: str) -> int:
    # Count svg primitive tags *within* <svg>…</svg> regions only, so an
    # incidental <rect> elsewhere (very unlikely in plain HTML) doesn't count.
    total = 0
    for m in re.finditer(r"<svg\b[^>]*>(.*?)</svg>", html, re.DOTALL | re.IGNORECASE):
        total += len(SVG_PRIMITIVE_RE.findall(m.group(1)))
    return total


def count_gradients(css_text: str) -> int:
    return len(GRADIENT_RE.findall(css_text))


def jpeg_proxy_per_kpixel(png_path: Path) -> float:
    """Forsythe 2011 visual-complexity proxy: re-encode the rendered
    screenshot as JPEG q=75 and take byte size. Normalize by pixel count so
    larger screenshots don't dominate."""
    img = Image.open(png_path).convert("RGB")
    # Cap dimension for stable comparison — different pages have different
    # full-page heights, but the *density* of visual content is what we want.
    img.thumbnail((1440, 4000))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    n_kpix = (img.width * img.height) / 1000.0
    return len(buf.getvalue()) / n_kpix if n_kpix > 0 else 0.0


def canny_edge_density(png_path: Path) -> float:
    """Mean of Canny edge map — Miniukovich CHI 2015 contour-congestion proxy."""
    img = np.asarray(Image.open(png_path).convert("RGB"))
    # Downsample for speed; full-page screenshots can be 1440x10000+.
    max_h = 2000
    if img.shape[0] > max_h:
        ratio = max_h / img.shape[0]
        new_size = (int(img.shape[1] * ratio), max_h)
        img = np.asarray(Image.fromarray(img).resize(new_size, Image.LANCZOS))
    gray = rgb2gray(img)
    edges = feature.canny(gray, sigma=1.0)
    return float(edges.mean())


def nav_link_texts(dom: dict[str, Any]) -> list[str]:
    """Collect link texts from the first nav region (largest by area) as the
    cross-page identity signature."""
    nav_regions = dom.get("navRegions", [])
    if not nav_regions:
        return []
    # Pick the region with the most links — that's the primary nav.
    nav = max(nav_regions, key=lambda r: r.get("linkCount", 0))
    return [link["text"].strip().lower() for link in nav.get("links", []) if link.get("text", "").strip()]


def pairwise_jaccard(sets: list[set[str]]) -> float:
    if len(sets) < 2:
        return 0.0
    sims = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if not a and not b:
                continue
            inter = len(a & b)
            union = len(a | b)
            if union == 0:
                continue
            sims.append(inter / union)
    return float(np.mean(sims)) if sims else 0.0


# ---------------------------------------------------------------------------
# Per-page measurement
# ---------------------------------------------------------------------------


def measure_page(
    browser,
    task_id: str,
    tier: int,
    genre: str,
    page: str,
    html_path: Path,
    server_url_base: str,
    cache_dir: Path,
    shared_css_text: str = "",
    shared_css_bytes: int = 0,
    n_pages: int = 1,
) -> PageMetrics:
    png_path = cache_dir / f"{task_id}.{page}.png"
    dom_path = cache_dir / f"{task_id}.{page}.dom.json"
    ylt_path = cache_dir / f"{task_id}.{page}.ylt.json"

    html_text = html_path.read_text()
    inline_css = extract_css_from_html(html_text)
    # All CSS contributing to this page = inline + shared (apportioned per-page
    # for the bytes total, but counted in full for content-based metrics like
    # gradient_count where any single occurrence is enough to count).
    css_text = inline_css + ("\n" + shared_css_text if shared_css_text else "")

    # Playwright render — skip if cached.
    if not (png_path.exists() and dom_path.exists()):
        ctx = browser.new_context(viewport=VIEWPORT)
        pg = ctx.new_page()
        try:
            pg.goto(f"file://{html_path.resolve()}", wait_until="load")
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(png_path), full_page=True)
            dom = pg.evaluate(EXTRACTION_JS)
            dom_path.write_text(json.dumps(dom))
        finally:
            ctx.close()
    else:
        dom = json.loads(dom_path.read_text())

    # YLT — skip if cached.
    if ylt_path.exists():
        ylt_json = json.loads(ylt_path.read_text())
    else:
        url = f"{server_url_base}/{page}/"
        ylt_json = run_ylt(url)
        ylt_path.write_text(json.dumps(ylt_json))

    # html_bytes is the per-page HTML weight + an apportioned share of the
    # shared CSS so workloads using shared CSS aren't penalized in the
    # DesignBench S composite's I (image-size) axis.
    apportioned_shared_bytes = shared_css_bytes // max(n_pages, 1)
    return PageMetrics(
        task_id=task_id,
        tier=tier,
        genre=genre,
        page=page,
        ylt=ylt_metrics_subset(ylt_json),
        svg_path_count=count_svg_primitives(html_text),
        gradient_count=count_gradients(css_text),
        html_bytes=len(html_text.encode()) + apportioned_shared_bytes,
        css_bytes=len(inline_css.encode()) + apportioned_shared_bytes,
        jpeg_proxy_bytes_per_kpixel=jpeg_proxy_per_kpixel(png_path),
        edge_density=canny_edge_density(png_path),
        nav_link_texts=nav_link_texts(dom),
    )


# ---------------------------------------------------------------------------
# Per-task aggregation + composites
# ---------------------------------------------------------------------------


METRIC_FIELDS_NUMERIC = [
    # YLT (prefixed with "ylt." in aggregates dict)
    *(f"ylt.{k}" for k in YLT_METRIC_KEYS),
    # Custom per-page
    "svg_path_count",
    "gradient_count",
    "html_bytes",
    "css_bytes",
    "jpeg_proxy_bytes_per_kpixel",
    "edge_density",
]


def _get_metric(p: PageMetrics, key: str) -> float:
    if key.startswith("ylt."):
        return p.ylt.get(key[4:], 0.0)
    return float(getattr(p, key))


def aggregate_task(per_page: list[PageMetrics]) -> dict[str, float]:
    """Mean across pages for every numeric metric. We use mean (not sum or
    max) because the composite is computed on a per-page mean basis to keep
    workloads with the same per-page complexity but more pages from looking
    artificially harder."""
    agg = {}
    for key in METRIC_FIELDS_NUMERIC:
        values = [_get_metric(p, key) for p in per_page]
        agg[key] = float(np.mean(values)) if values else 0.0
    return agg


def compute_composites(tasks: list[TaskDifficulty]) -> None:
    """Fill in composite_designbench_S and composite_axis_mean for each task,
    using z-scores across the 10 tasks."""

    def zscores(values: list[float]) -> list[float]:
        mu = float(np.mean(values))
        sd = float(np.std(values))
        if sd == 0:
            return [0.0 for _ in values]
        return [(v - mu) / sd for v in values]

    # DesignBench S = 0.25*z(I) + 0.25*z(U) + 0.25*z(C) + 0.25*z(L)
    I = [t.aggregates["html_bytes"] for t in tasks]
    U = [t.aggregates["ylt.DOMelementsCount"] for t in tasks]
    C = [t.aggregates["ylt.cssColors"] for t in tasks]
    L = [
        t.aggregates["ylt.cssDeclarations"]
        + t.aggregates["ylt.DOMelementMaxDepth"]
        + t.aggregates["ylt.cssComplexSelectors"]
        for t in tasks
    ]
    zI, zU, zC, zL = zscores(I), zscores(U), zscores(C), zscores(L)
    for t, zi, zu, zc, zl in zip(tasks, zI, zU, zC, zL):
        t.composite_designbench_S = 0.25 * (zi + zu + zc + zl)

    # Axis-balanced composite: z-score every metric, group into 5 axes, mean
    # within each axis, then mean across axes.
    AXES: dict[str, list[str]] = {
        "structural": [
            "ylt.DOMelementsCount",
            "ylt.DOMelementMaxDepth",
            "ylt.iframesCount",
            "html_bytes",
        ],
        "layout": [
            "ylt.cssRules",
            "ylt.cssSelectors",
            "ylt.cssComplexSelectors",
            "ylt.cssSpecificityIdAvg",
        ],
        "style": [
            "ylt.cssColors",
            "ylt.cssDeclarations",
            "ylt.cssImportants",
            "gradient_count",
        ],
        "clutter": [
            "jpeg_proxy_bytes_per_kpixel",
            "edge_density",
            "svg_path_count",
        ],
        "compress_neg": [
            # signed *negative* — high cross-page consistency lowers difficulty.
            # Handled below by flipping sign.
            "cross_page_nav_jaccard",
        ],
    }

    # Pre-compute z-scores per metric across tasks.
    per_metric_z: dict[str, list[float]] = {}
    for metric in METRIC_FIELDS_NUMERIC + ["cross_page_nav_jaccard"]:
        if metric == "cross_page_nav_jaccard":
            vals = [t.cross_page_nav_jaccard for t in tasks]
        else:
            vals = [t.aggregates[metric] for t in tasks]
        per_metric_z[metric] = zscores(vals)

    for idx, t in enumerate(tasks):
        axis_means = []
        for axis_name, metrics in AXES.items():
            vals = [per_metric_z[m][idx] for m in metrics if m in per_metric_z]
            if not vals:
                continue
            mean = float(np.mean(vals))
            if axis_name == "compress_neg":
                mean = -mean
            axis_means.append(mean)
        t.composite_axis_mean = float(np.mean(axis_means)) if axis_means else 0.0


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def measure_workload(
    browser,
    task_meta: dict[str, Any],
    cache_dir: Path,
    workloads_dir: Path,
) -> TaskDifficulty:
    task_id = task_meta["id"]
    tier = int(task_meta["tier"])
    genre = task_meta["genre"]
    refdir = workloads_dir / task_id / "environment" / "reference-pages"
    pages = sorted(p.name for p in refdir.iterdir() if p.is_dir())

    # New (post-v5) workloads ship a single shared stylesheet at the ref root.
    # Older workloads (v4 inline-CSS) won't have it — fall through to empty.
    shared_css_path = refdir / "_shared.css"
    shared_css_text = shared_css_path.read_text() if shared_css_path.exists() else ""
    shared_css_bytes = len(shared_css_text.encode())

    print(f"  [{task_id}] tier={tier} genre={genre} pages={pages} "
          f"shared_css={shared_css_bytes}B", flush=True)

    per_page: list[PageMetrics] = []
    with serve_directory(refdir) as port:
        base_url = f"http://127.0.0.1:{port}"
        for page in pages:
            html_path = refdir / page / "index.html"
            pm = measure_page(
                browser, task_id, tier, genre, page, html_path, base_url, cache_dir,
                shared_css_text=shared_css_text,
                shared_css_bytes=shared_css_bytes,
                n_pages=len(pages),
            )
            per_page.append(pm)
            print(
                f"    {page}: DOM={int(pm.ylt['DOMelementsCount'])} "
                f"depth={int(pm.ylt['DOMelementMaxDepth'])} "
                f"cssRules={int(pm.ylt['cssRules'])} "
                f"cssColors={int(pm.ylt['cssColors'])} "
                f"gradients={pm.gradient_count} svg={pm.svg_path_count} "
                f"jpeg/kpx={pm.jpeg_proxy_bytes_per_kpixel:.1f} "
                f"edge={pm.edge_density:.3f}",
                flush=True,
            )

    nav_sets = [set(pm.nav_link_texts) for pm in per_page]
    return TaskDifficulty(
        id=task_id,
        tier=tier,
        genre=genre,
        per_page=per_page,
        aggregates=aggregate_task(per_page),
        cross_page_nav_jaccard=pairwise_jaccard(nav_sets),
    )


def serialize_task(t: TaskDifficulty) -> dict[str, Any]:
    return {
        "id": t.id,
        "tier": t.tier,
        "genre": t.genre,
        "aggregates": t.aggregates,
        "cross_page_nav_jaccard": t.cross_page_nav_jaccard,
        "composite_designbench_S": t.composite_designbench_S,
        "composite_axis_mean": t.composite_axis_mean,
        "per_page": [asdict(p) for p in t.per_page],
    }


def write_per_page_csv(tasks: list[TaskDifficulty], path: Path) -> None:
    fields = (
        ["task_id", "tier", "genre", "page"]
        + METRIC_FIELDS_NUMERIC
    )
    lines = [",".join(fields)]
    for t in tasks:
        for p in t.per_page:
            row = [t.id, str(t.tier), t.genre, p.page]
            for m in METRIC_FIELDS_NUMERIC:
                v = _get_metric(p, m)
                row.append(f"{v:.4f}" if isinstance(v, float) else str(v))
            lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


def spearman(x: list[float], y: list[float]) -> tuple[float, float]:
    """Spearman rank correlation + 2-sided p-value (asymptotic). N small; use
    advisorily. Implemented with scipy.stats which ships transitively via
    scikit-image, so no new dep."""
    from scipy.stats import spearmanr

    rho, p = spearmanr(x, y)
    return float(rho), float(p)


def kendalltau_(x: list[float], y: list[float]) -> tuple[float, float]:
    from scipy.stats import kendalltau

    tau, p = kendalltau(x, y)
    return float(tau), float(p)


def bootstrap_spearman_ci(
    x: list[float], y: list[float], n_resamples: int = 1000, seed: int = 0
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(x)
    rhos = []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, n)
        xr = [x[i] for i in idx]
        yr = [y[i] for i in idx]
        if len(set(xr)) < 2 or len(set(yr)) < 2:
            continue
        rho, _ = spearman(xr, yr)
        if not np.isnan(rho):
            rhos.append(rho)
    if not rhos:
        return (float("nan"), float("nan"))
    return (float(np.percentile(rhos, 2.5)), float(np.percentile(rhos, 97.5)))


def designbench_bin(S: float) -> str:
    # DesignBench bins are on the raw 0–100ish weighted sum, not on z-space.
    # Our z-based composite is centered at 0; map to bins by quantile:
    if S < -0.3:
        return "easy"
    if S < 0.3:
        return "medium"
    return "hard"


def generate_report(tasks: list[TaskDifficulty], path: Path) -> None:
    tiers = [t.tier for t in tasks]
    sorted_by_S = sorted(tasks, key=lambda t: t.composite_designbench_S, reverse=True)
    sorted_by_axis = sorted(tasks, key=lambda t: t.composite_axis_mean, reverse=True)

    lines: list[str] = []
    lines.append("# Workloads_v4 Difficulty Validation Report\n")
    lines.append(f"_N = {len(tasks)} tasks, tier ladder T1–T7 per docs/running_notes.md_\n")

    # 1. Composite correlations
    lines.append("## Composite scores vs. tier\n")
    for name, getter in (
        ("composite_designbench_S", lambda t: t.composite_designbench_S),
        ("composite_axis_mean", lambda t: t.composite_axis_mean),
    ):
        vals = [getter(t) for t in tasks]
        rho, p_rho = spearman(tiers, vals)
        tau, p_tau = kendalltau_(tiers, vals)
        lo, hi = bootstrap_spearman_ci(tiers, vals)
        lines.append(
            f"- **{name}** — Spearman ρ={rho:+.3f} (p={p_rho:.3g}, 95% CI "
            f"[{lo:+.2f}, {hi:+.2f}]); Kendall τ={tau:+.3f} (p={p_tau:.3g})"
        )
    lines.append("")
    lines.append("Headline target: ρ ≥ 0.85, τ ≥ 0.7. Below either → tier ladder needs revision.\n")

    # 2. Ranked tables (composite vs. tier)
    lines.append("## Ranking by composite_designbench_S vs. tier\n")
    lines.append("| Rank | Task | Tier | Genre | S | axis_mean |")
    lines.append("|---|---|---|---|---|---|")
    for i, t in enumerate(sorted_by_S, start=1):
        lines.append(
            f"| {i} | {t.id} | T{t.tier} | {t.genre} | "
            f"{t.composite_designbench_S:+.2f} | {t.composite_axis_mean:+.2f} |"
        )
    lines.append("")

    # 3. Per-tier descriptives for composite + key per-axis metrics
    lines.append("## Per-tier descriptives\n")
    headers = [
        "tier",
        "n",
        "designbench_S(mean)",
        "axis_mean(mean)",
        "DOM(mean)",
        "cssRules(mean)",
        "cssColors(mean)",
        "gradients(mean)",
        "svg_paths(mean)",
        "edge_density(mean)",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for tier in sorted(set(tiers)):
        bucket = [t for t in tasks if t.tier == tier]
        row = [
            f"T{tier}",
            str(len(bucket)),
            f"{statistics.mean(t.composite_designbench_S for t in bucket):+.2f}",
            f"{statistics.mean(t.composite_axis_mean for t in bucket):+.2f}",
            f"{statistics.mean(t.aggregates['ylt.DOMelementsCount'] for t in bucket):.0f}",
            f"{statistics.mean(t.aggregates['ylt.cssRules'] for t in bucket):.0f}",
            f"{statistics.mean(t.aggregates['ylt.cssColors'] for t in bucket):.1f}",
            f"{statistics.mean(t.aggregates['gradient_count'] for t in bucket):.1f}",
            f"{statistics.mean(t.aggregates['svg_path_count'] for t in bucket):.1f}",
            f"{statistics.mean(t.aggregates['edge_density'] for t in bucket):.3f}",
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 4. Inversions
    lines.append("## Adjacent-tier inversions (composite_designbench_S)\n")
    tier_groups: dict[int, list[TaskDifficulty]] = {}
    for t in tasks:
        tier_groups.setdefault(t.tier, []).append(t)
    inversions = []
    seen = sorted(tier_groups.keys())
    for k1, k2 in zip(seen, seen[1:]):
        a = [t for t in tier_groups[k1]]
        b = [t for t in tier_groups[k2]]
        med_a = statistics.median(t.composite_designbench_S for t in a)
        med_b = statistics.median(t.composite_designbench_S for t in b)
        marker = "✗ inversion" if med_a > med_b else "✓"
        inversions.append(
            f"- T{k1} → T{k2}: median S = {med_a:+.2f} vs {med_b:+.2f} ({marker})"
        )
    lines.extend(inversions)
    lines.append("")

    # 5. Per-metric correlation table
    lines.append("## Per-metric Spearman ρ vs. tier (10 tasks)\n")
    lines.append("Each metric is expected to *jump at a specific tier boundary*, not rise monotonically T1→T7. Treat correlations as exploratory.\n")
    lines.append("| Metric | ρ | p | Expected boundary |")
    lines.append("|---|---|---|---|")
    boundary_map = {
        "ylt.DOMelementsCount": "T5→T6 (dense forms/tables)",
        "ylt.DOMelementMaxDepth": "T2→T3 (layout nesting)",
        "ylt.cssRules": "T3→T4 (visual polish)",
        "ylt.cssDeclarations": "T3→T4",
        "ylt.cssComplexSelectors": "T3→T4",
        "ylt.cssColors": "T3→T4 (palette grows)",
        "ylt.cssImportants": "(noise)",
        "ylt.cssSpecificityIdAvg": "(noise)",
        "ylt.cssDuplicatedSelectors": "(noise)",
        "ylt.cssEmptyRules": "(noise)",
        "ylt.cssSelectors": "T3→T4",
        "ylt.iframesCount": "(noise — workloads use no iframes)",
        "ylt.nodesWithInlineCSS": "(noise)",
        "svg_path_count": "T6→T7 (inline SVG)",
        "gradient_count": "T3→T4 (visual polish)",
        "html_bytes": "monotone (size grows with all of the above)",
        "css_bytes": "monotone",
        "jpeg_proxy_bytes_per_kpixel": "Forsythe clutter (T4, T7)",
        "edge_density": "T6→T7 (SVG/forms)",
        "cross_page_nav_jaccard": "T1→T2 (multi-page identity)",
    }
    for metric in METRIC_FIELDS_NUMERIC + ["cross_page_nav_jaccard"]:
        if metric == "cross_page_nav_jaccard":
            vals = [t.cross_page_nav_jaccard for t in tasks]
        else:
            vals = [t.aggregates[metric] for t in tasks]
        if len(set(vals)) < 2:
            lines.append(f"| {metric} | (constant) | — | {boundary_map.get(metric, '?')} |")
            continue
        rho, p = spearman(tiers, vals)
        lines.append(f"| {metric} | {rho:+.2f} | {p:.2g} | {boundary_map.get(metric, '?')} |")
    lines.append("")

    # 6. Web Almanac context
    lines.append("## Web Almanac context (where our workloads sit on the public web)\n")
    web_almanac = {
        "ylt.DOMelementsCount": ("p10=180, p50=594, p90=1716", "Markup 2024"),
        "ylt.cssRules": ("p50=613, p90=2023", "CSS 2022"),
        "ylt.DOMelementMaxDepth": ("Lighthouse fails >32", "Markup 2024"),
    }
    for metric, (band, source) in web_almanac.items():
        vals = [t.aggregates[metric] for t in tasks]
        lines.append(
            f"- **{metric}** — workloads_v4 range {min(vals):.0f}–{max(vals):.0f}, "
            f"mean {np.mean(vals):.0f}. Public ({source}): {band}."
        )
    lines.append("")

    # 7. Caveats
    lines.append("## Caveats\n")
    lines.append("- N=10 workloads. Wide bootstrap CIs are honest; treat composite as headline, per-metric as exploratory.")
    lines.append("- Per-tier N unbalanced: T1=T2=T5=T6=1; T3=T4=T7=2; T8=0. Several adjacent-tier checks reduce to a single comparison.")
    lines.append("- Genre confound: T6 only `comparison-table`, T5 only `poetry`. Tier-correlated metrics may really measure genre.")
    lines.append("- Visual ≠ total task difficulty. Agents also see the prompt; harder visual content may be offset by clearer text.")
    lines.append("- DesignBench S formula validated on real pages; our LLM-generated workloads may have different distributions. Cross-check with Web Almanac context above.")
    lines.append("")

    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--workloads-dir",
        type=Path,
        default=DEFAULT_WORKLOADS,
        help=f"workloads root containing registry.json (default: {DEFAULT_WORKLOADS})",
    )
    ap.add_argument("--workload", help="single workload id (skip composite)")
    ap.add_argument("--cache", type=Path, default=OUT_DIR / "cache")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help=f"directory for per_task.json / per_page.csv / report (default: {OUT_DIR})",
    )
    ap.add_argument("--report", action="store_true", help="emit tier_validation_report.md")
    args = ap.parse_args()

    workloads_dir = args.workloads_dir.resolve()
    if not workloads_dir.exists():
        sys.exit(f"workloads dir not found: {workloads_dir}")
    if not (workloads_dir / "registry.json").exists():
        sys.exit(f"no registry.json in {workloads_dir}")

    args.cache.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if not NODE.exists():
        sys.exit(f"Node 20 not found at {NODE}")
    if not YLT_CLI.exists():
        sys.exit(f"YLT not found at {YLT_CLI}; install: npm install -g yellowlabtools")
    if not CHROMIUM_OVERRIDE.exists():
        sys.exit(f"Playwright Chromium not found at {CHROMIUM_OVERRIDE}")

    registry = json.loads((workloads_dir / "registry.json").read_text())
    tasks_meta = registry["tasks"]
    if args.workload:
        tasks_meta = [t for t in tasks_meta if t["id"] == args.workload]
        if not tasks_meta:
            sys.exit(f"Unknown workload: {args.workload}")

    tasks: list[TaskDifficulty] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for task_meta in tasks_meta:
                tasks.append(measure_workload(browser, task_meta, args.cache, workloads_dir))
        finally:
            browser.close()

    if len(tasks) >= 3:
        compute_composites(tasks)

    # Write outputs
    per_task_path = args.out_dir / "per_task.json"
    per_task_path.write_text(json.dumps([serialize_task(t) for t in tasks], indent=2))
    print(f"wrote {per_task_path}")

    per_page_path = args.out_dir / "per_page.csv"
    write_per_page_csv(tasks, per_page_path)
    print(f"wrote {per_page_path}")

    if args.report and len(tasks) >= 3:
        report_path = args.out_dir / "tier_validation_report.md"
        generate_report(tasks, report_path)
        print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
