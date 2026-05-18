"""Shared utilities for the experiments_v4 plot scripts.

Tier ordering, target bands, task colors, and JSON loading live here so the
4 plot scripts stay visually consistent and a single edit propagates
everywhere.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
CALIBRATION_ROOT = HERE.parent
RESULTS_DIR = CALIBRATION_ROOT / "results"
DEFAULT_RESULTS_PATH = RESULTS_DIR / "v4.0.json"
DEFAULT_IMG_OUT_DIR = CALIBRATION_ROOT.parent.parent / "docs" / "img"

# Tier order used everywhere — left = best replication, right = worst.
TIER_ORDER: list[str] = ["near_perfect", "mediocre", "plain", "adversarial", "bad"]

# Target bands (inclusive lower, inclusive upper). Mirrors run.py TIER_TARGETS
# kept in sync manually — if these drift, the version-evolution plot would
# shade the wrong region.
TIER_TARGETS: dict[str, tuple[float, float]] = {
    "near_perfect": (0.85, 1.00),
    "mediocre": (0.25, 0.50),
    "plain": (0.00, 0.40),
    "adversarial": (0.00, 0.35),
    "bad": (0.00, 0.15),
}

# Five-task palette. Picked for readability against a white background and
# clear separation on grayscale prints. Kept consistent across plots so the
# same task is the same color in Plot A+B and Plot C.
TASK_COLORS: dict[str, str] = {
    "synth-t6-vaultline-private-banking-52b7": "#1f77b4",  # blue
    "synth-t1-ink-and-insomnia-blog-fea9": "#ff7f0e",  # orange
    "synth-t3-ferroflux-systems-docs-712d": "#2ca02c",  # green
    "synth-t5-ashen-meridian-verses-2521": "#9467bd",  # purple
    "synth-t7-deep-ocean-pressure-atlas-3d66": "#d62728",  # red
}

# One-word style descriptors for panel titles in the per-task plot.
TASK_STYLES: dict[str, str] = {
    "synth-t6-vaultline-private-banking-52b7": "banking",
    "synth-t1-ink-and-insomnia-blog-fea9": "blog",
    "synth-t3-ferroflux-systems-docs-712d": "docs",
    "synth-t5-ashen-meridian-verses-2521": "editorial",
    "synth-t7-deep-ocean-pressure-atlas-3d66": "atlas",
}

# Deterministic aspect order (V4 weights, descending). Drives heatmap row order.
DETERMINISTIC_ASPECTS: list[str] = [
    "text_content",
    "region_color",
    "headings",
    "palette",
    "navigation",
    "repeating_groups",
    "layout_skeleton",
    "pixel_ssim",
    "paragraphs",
    "color_histogram",
    "interactive",
]

# Judge criteria order (matches grader's JUDGE_CRITERIA list).
JUDGE_CRITERIA: list[str] = [
    "visual_hierarchy",
    "color_palette",
    "typography",
    "layout_fidelity",
    "overall_fidelity",
]


def results_path() -> Path:
    """Return the calibration JSON path, honoring CAL_RESULTS_PATH env override."""
    override = os.environ.get("CAL_RESULTS_PATH")
    return Path(override).resolve() if override else DEFAULT_RESULTS_PATH


def img_out_dir() -> Path:
    """Return the PNG output directory, honoring CAL_IMG_OUT_DIR env override."""
    override = os.environ.get("CAL_IMG_OUT_DIR")
    out = Path(override).resolve() if override else DEFAULT_IMG_OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def load_results(path: Path | None = None) -> dict:
    """Load the calibration JSON and validate top-level shape."""
    p = path or results_path()
    if not p.exists():
        raise FileNotFoundError(
            f"Calibration results not found at {p}. "
            "Run ./reproduce.sh first (or set CAL_RESULTS_PATH)."
        )
    data = json.loads(p.read_text())
    if "results" not in data:
        raise ValueError(f"{p} missing top-level 'results' key")
    return data


def task_rewards(data: dict, tier: str) -> list[tuple[str, float]]:
    """Return [(task_id, reward), ...] for one tier across all tasks."""
    out: list[tuple[str, float]] = []
    for task_id, variants in data["results"].items():
        if tier in variants and "reward" in variants[tier]:
            out.append((task_id, float(variants[tier]["reward"])))
    return out


@dataclass(frozen=True)
class Version:
    label: str  # e.g. "v2.1"
    major: int
    minor: int


_VERSION_RE = re.compile(r"^v(\d+)(?:\.(\d+))?$")


def parse_version(stem: str) -> Version | None:
    """Parse 'v1', 'v2', 'v2.1', 'v4.0' into a sortable Version. None if no match."""
    m = _VERSION_RE.match(stem)
    if not m:
        return None
    return Version(label=stem, major=int(m.group(1)), minor=int(m.group(2) or 0))


def discover_version_results() -> list[tuple[Version, dict]]:
    """Load every results/v*.json, sorted in true version order."""
    out: list[tuple[Version, dict]] = []
    for path in RESULTS_DIR.glob("v*.json"):
        version = parse_version(path.stem)
        if version is None:
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        out.append((version, data))
    out.sort(key=lambda x: (x[0].major, x[0].minor))
    return out


def save_fig(fig, name: str) -> Path:
    """Write `fig` to `<IMG_OUT_DIR>/<name>` at 150 DPI and print the path."""
    out_dir = img_out_dir()
    path = out_dir / name
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {path}")
    return path
