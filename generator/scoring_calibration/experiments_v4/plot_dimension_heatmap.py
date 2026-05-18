#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.7",
#     "numpy>=1.24",
# ]
# ///
"""Plot D — per-dimension behavior heatmap.

Rows: 5 judge criteria + 11 deterministic aspects (16 total).
Cols: the 5 quality tiers, left = best replication, right = worst.
Cell value: mean score for that (dimension, tier) across all calibration
tasks and all pages in each task.

The argument it supports: each dimension fires on the failure modes it
was designed to catch. For example:
  - text_content stays ~1.0 on near_perfect/adversarial (text preserved)
    but collapses on bad (lorem ipsum everywhere)
  - judge.typography stays high on near_perfect/plain (correct or absent
    fonts) but collapses on adversarial (Comic Sans + 96px headings)
  - palette stays ~1.0 on near_perfect but collapses across all
    degradations that touch colors

If the diagonal pattern of "each dimension reacts to its target failure"
is visible, the dimensions are doing their jobs.

Run:
    uv run python plot_dimension_heatmap.py
"""
from __future__ import annotations

import statistics

import matplotlib.pyplot as plt
import numpy as np

from _common import (
    DETERMINISTIC_ASPECTS,
    JUDGE_CRITERIA,
    TIER_ORDER,
    load_results,
    save_fig,
)


def _collect_aspect(data: dict, tier: str, aspect: str) -> list[float]:
    """Pull every (task, page) score for one deterministic aspect under one tier."""
    out: list[float] = []
    for variants in data["results"].values():
        per_page = variants.get(tier, {}).get("details", {}).get("per_page", {})
        for page_data in per_page.values():
            aspect_data = page_data.get("aspects", {}).get(aspect)
            if aspect_data is None:
                continue
            applied = float(aspect_data.get("applied_weight", 0.0))
            if applied <= 0.0:
                # Aspect did not apply for this page; skip rather than count as 0.
                continue
            out.append(float(aspect_data["score"]))
    return out


def _collect_judge(data: dict, tier: str, criterion: str) -> list[float]:
    """Pull every (task, page) normalized judge score for one criterion under one tier."""
    out: list[float] = []
    for variants in data["results"].values():
        per_page = variants.get(tier, {}).get("details", {}).get("per_page", {})
        for page_data in per_page.values():
            breakdown = page_data.get("judge_breakdown", {})
            criteria = breakdown.get("per_criterion", {})
            crit_data = criteria.get(criterion)
            if crit_data is None:
                continue
            out.append(float(crit_data["aggregated"]))
    return out


def main() -> None:
    data = load_results()

    judge_rows = [f"judge · {c}" for c in JUDGE_CRITERIA]
    det_rows = [f"det · {a}" for a in DETERMINISTIC_ASPECTS]
    row_labels = judge_rows + det_rows

    matrix = np.full((len(row_labels), len(TIER_ORDER)), np.nan, dtype=float)

    # Judge criteria rows (top)
    for i, criterion in enumerate(JUDGE_CRITERIA):
        for j, tier in enumerate(TIER_ORDER):
            values = _collect_judge(data, tier, criterion)
            if values:
                matrix[i, j] = statistics.mean(values)

    # Deterministic aspect rows (bottom)
    offset = len(JUDGE_CRITERIA)
    for i, aspect in enumerate(DETERMINISTIC_ASPECTS):
        for j, tier in enumerate(TIER_ORDER):
            values = _collect_aspect(data, tier, aspect)
            if values:
                matrix[offset + i, j] = statistics.mean(values)

    fig, ax = plt.subplots(figsize=(8.5, 8))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0.0, vmax=1.0, aspect="auto")

    ax.set_xticks(range(len(TIER_ORDER)))
    ax.set_xticklabels(TIER_ORDER, fontsize=10, rotation=20, ha="right")
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=9)

    # Cell annotations
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            val = matrix[i, j]
            if np.isnan(val):
                text = "—"
                color = "#888888"
            else:
                text = f"{val:.2f}"
                # Pick text color based on cell darkness
                color = "white" if (val < 0.35 or val > 0.85) else "black"
            ax.text(
                j,
                i,
                text,
                ha="center",
                va="center",
                fontsize=9,
                color=color,
            )

    # Divider line between judge and deterministic blocks
    ax.axhline(len(JUDGE_CRITERIA) - 0.5, color="black", linewidth=1.5)

    # Block labels on the right
    ax.text(
        len(TIER_ORDER) - 0.4,
        (len(JUDGE_CRITERIA) - 1) / 2,
        "Judge\n(0.70 weight)",
        fontsize=9,
        ha="left",
        va="center",
        rotation=0,
    )
    ax.text(
        len(TIER_ORDER) - 0.4,
        len(JUDGE_CRITERIA) + (len(DETERMINISTIC_ASPECTS) - 1) / 2,
        "Deterministic\n(0.30 weight)",
        fontsize=9,
        ha="left",
        va="center",
        rotation=0,
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.16)
    cbar.set_label("Mean score across tasks × pages", fontsize=9)

    ax.set_title(
        "V4 per-dimension behavior across quality tiers\n"
        "(rows = grader components, cells = mean score on N tasks × ~5 pages)",
        fontsize=11,
    )
    fig.tight_layout()
    save_fig(fig, "calibration_dimensions.png")


if __name__ == "__main__":
    main()
