#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.7",
# ]
# ///
"""Plot C — per-task small multiples.

One panel per task. Inside each panel, the 5-tier mini-ladder for that
task as a bar chart. Shared 0–1 Y-axis so panels are visually
comparable. Target bands shaded behind the bars.

The argument it supports: the staircase shape isn't an artifact of one
task — it repeats across very different sites (blog, dashboard,
editorial, banking, atlas), so the grader isn't tuned to one design
language.

Run:
    uv run python plot_per_task.py
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _common import (
    TASK_COLORS,
    TASK_STYLES,
    TIER_ORDER,
    TIER_TARGETS,
    load_results,
    save_fig,
)


def _short_tier_label(tier: str) -> str:
    """Compact tier label for crowded panel x-axes."""
    return {
        "near_perfect": "near\nperfect",
        "mediocre": "medio-\ncre",
        "plain": "plain",
        "adversarial": "adver-\nsarial",
        "bad": "bad",
    }[tier]


def _task_tier_prefix(task_id: str) -> str:
    """Extract 't1', 't6', etc. from synth-t1-... task names."""
    parts = task_id.split("-")
    if len(parts) >= 2 and parts[1].startswith("t"):
        return parts[1]
    return "?"


def main() -> None:
    data = load_results()
    task_ids = [t for t in TASK_COLORS if t in data["results"]]
    n = len(task_ids)
    if n == 0:
        raise ValueError("no tasks in calibration JSON")

    # 1 row × n cols. For 5 tasks this is 1×5 (wide); switch to 2×3 if we
    # ever scale past 5.
    if n <= 5:
        rows, cols = 1, n
    else:
        rows = (n + 2) // 3
        cols = 3
    fig, axes = plt.subplots(
        rows, cols, figsize=(3.2 * cols, 3.6 * rows), sharey=True
    )
    axes_flat = [axes] if n == 1 else list(axes.ravel()) if rows > 1 else list(axes)

    x_positions = list(range(len(TIER_ORDER)))

    for idx, task_id in enumerate(task_ids):
        ax = axes_flat[idx]
        variants = data["results"][task_id]

        # Target band rectangles
        for x, tier in zip(x_positions, TIER_ORDER):
            lo, hi = TIER_TARGETS[tier]
            ax.add_patch(
                mpatches.Rectangle(
                    (x - 0.42, lo),
                    0.84,
                    hi - lo,
                    facecolor="#d4e6d4",
                    edgecolor="none",
                    alpha=0.55,
                    zorder=1,
                )
            )

        # Bars per tier
        rewards = []
        for tier in TIER_ORDER:
            v = variants.get(tier, {})
            rewards.append(float(v.get("reward", 0.0)))

        color = TASK_COLORS[task_id]
        bars = ax.bar(
            x_positions,
            rewards,
            width=0.7,
            color=color,
            edgecolor="white",
            linewidth=1.0,
            zorder=2,
        )
        for bar, val in zip(bars, rewards):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                val + 0.018,
                f"{val:.2f}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#222222",
            )

        ax.set_xticks(x_positions)
        ax.set_xticklabels([_short_tier_label(t) for t in TIER_ORDER], fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", linestyle="--", alpha=0.25, zorder=0)
        ax.set_axisbelow(True)

        tier_prefix = _task_tier_prefix(task_id)
        style = TASK_STYLES.get(task_id, "")
        short_name = task_id.split("-")[2] if len(task_id.split("-")) >= 3 else task_id
        ax.set_title(
            f"{tier_prefix} · {short_name} · {style}",
            fontsize=10,
        )

    # Hide any unused panels (when 2×3 grid has leftover cells)
    for j in range(n, rows * cols):
        axes_flat[j].axis("off")

    if rows == 1:
        axes_flat[0].set_ylabel("Reward (0–1)", fontsize=10)
    else:
        for row_first in range(0, rows * cols, cols):
            axes_flat[row_first].set_ylabel("Reward (0–1)", fontsize=10)

    fig.suptitle(
        "V4 grader: 5-tier ladder per task — staircase shape is consistent across design languages",
        fontsize=12,
        y=1.02,
    )
    fig.tight_layout()
    save_fig(fig, "calibration_per_task.png")


if __name__ == "__main__":
    main()
