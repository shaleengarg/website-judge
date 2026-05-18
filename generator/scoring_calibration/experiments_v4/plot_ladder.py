#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.7",
# ]
# ///
"""Plot A+B — range-and-dots ladder across the 5 quality tiers.

For each tier (left = best replication, right = worst), draws:
  - the target band as a shaded horizontal region in the background
  - a thin vertical line from min to max across the 5 calibration tasks
  - one colored dot per task at its actual reward
  - a short horizontal tick at the mean

This combines the "average ladder" view (Plot A) with the "every variant
landed" view (Plot B) in a single figure. The argument it supports:
the grader produces a clean staircase from near_perfect down to bad, and
no individual variant escapes its target band.

Run:
    uv run python plot_ladder.py
"""
from __future__ import annotations

import statistics

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _common import (
    TASK_COLORS,
    TIER_ORDER,
    TIER_TARGETS,
    load_results,
    save_fig,
    task_rewards,
)


def main() -> None:
    data = load_results()
    fig, ax = plt.subplots(figsize=(11, 6))

    x_positions = list(range(len(TIER_ORDER)))

    # Target bands behind the data
    for x, tier in zip(x_positions, TIER_ORDER):
        lo, hi = TIER_TARGETS[tier]
        ax.add_patch(
            mpatches.Rectangle(
                (x - 0.38, lo),
                0.76,
                hi - lo,
                facecolor="#d4e6d4",
                edgecolor="#8fbc8f",
                linewidth=0.5,
                alpha=0.6,
                zorder=1,
            )
        )

    # Per-tier range bar + dots + mean tick
    for x, tier in zip(x_positions, TIER_ORDER):
        rewards = task_rewards(data, tier)
        if not rewards:
            continue
        values = [r for _, r in rewards]
        mn, mx = min(values), max(values)
        mean = statistics.mean(values)

        # Thin vertical range bar min→max
        ax.plot([x, x], [mn, mx], color="#444444", linewidth=1.4, zorder=2)

        # Mean tick
        ax.plot(
            [x - 0.18, x + 0.18],
            [mean, mean],
            color="#222222",
            linewidth=2.4,
            zorder=3,
            solid_capstyle="butt",
        )

        # Each task as a colored dot
        for task_id, reward in rewards:
            color = TASK_COLORS.get(task_id, "#888888")
            ax.scatter(
                x,
                reward,
                s=120,
                color=color,
                edgecolor="white",
                linewidth=1.4,
                zorder=4,
            )

        # Annotate mean to the right of the column
        ax.annotate(
            f"μ={mean:.2f}",
            (x + 0.22, mean),
            fontsize=9,
            color="#222222",
            verticalalignment="center",
        )

    # Tier label decoration: name + target band
    tick_labels = [
        f"{tier}\n[{lo:.2f}, {hi:.2f}]"
        for tier in TIER_ORDER
        for (lo, hi) in [TIER_TARGETS[tier]]
    ]
    ax.set_xticks(x_positions)
    ax.set_xticklabels(tick_labels, fontsize=10)
    ax.set_xlim(-0.6, len(TIER_ORDER) - 0.4)
    ax.set_ylim(-0.04, 1.04)
    ax.set_ylabel("Reward (0–1)", fontsize=11)
    ax.set_title(
        "V4 grader: 5-tier separation across 5 tasks\n"
        "shaded band = target · dot = task reward · tick = mean · line = min–max",
        fontsize=12,
    )
    ax.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    # Legend mapping color → task short-name
    handles = [
        mpatches.Patch(color=color, label=task_id)
        for task_id, color in TASK_COLORS.items()
        if task_id in data["results"]
    ]
    ax.legend(
        handles=handles,
        loc="upper right",
        fontsize=8,
        framealpha=0.95,
        title="Tasks",
        title_fontsize=9,
    )

    save_fig(fig, "calibration_ladder.png")


if __name__ == "__main__":
    main()
