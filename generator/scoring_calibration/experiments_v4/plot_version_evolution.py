#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.7",
# ]
# ///
"""Plot F — V1 → V4 grader evolution.

X-axis: grader versions in order (V1, V2, V2.1, V3, V3.1, V3.2, V3.3, V4.0).
Y-axis: mean reward (0–1).
One line per tier, plus a shaded target band per tier behind the lines.

The argument it supports: each grader version closed a specific gap.
V1 had a `bad > mediocre` inversion (visible as the bad line above the
mediocre line at x=V1). V2 fixed monotonicity but ran high on bad. V3
introduced the multimodal judge to address the adversarial blind spot
that deterministic graders are architecturally unable to catch.

Reads every results/v*.json the calibration directory has produced and
plots whichever tiers each version contained (early versions only had
near_perfect / mediocre / bad).

Run:
    uv run python plot_version_evolution.py
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _common import (
    TIER_ORDER,
    TIER_TARGETS,
    discover_version_results,
    save_fig,
)

# Per-tier line styling. Order matches TIER_ORDER (best→worst replication).
TIER_COLORS: dict[str, str] = {
    "near_perfect": "#2ca02c",  # green
    "mediocre": "#ff7f0e",  # orange
    "plain": "#9467bd",  # purple
    "adversarial": "#d62728",  # red
    "bad": "#7f7f7f",  # gray
}


def main() -> None:
    versions = discover_version_results()
    if not versions:
        raise RuntimeError("no results/v*.json files found")

    fig, ax = plt.subplots(figsize=(11, 6.5))

    x_positions = list(range(len(versions)))
    x_labels = [v.label for v, _ in versions]

    # Target bands as horizontal shaded strips behind the lines
    for tier in TIER_ORDER:
        lo, hi = TIER_TARGETS[tier]
        color = TIER_COLORS[tier]
        ax.axhspan(lo, hi, alpha=0.08, color=color, zorder=1)

    # One line per tier
    for tier in TIER_ORDER:
        xs: list[int] = []
        ys: list[float] = []
        for x, (_version, data) in zip(x_positions, versions):
            summary = data.get("summary") or {}
            tier_data = summary.get(tier)
            if tier_data is None or tier_data.get("n", 0) == 0:
                continue
            xs.append(x)
            ys.append(float(tier_data["mean"]))
        if not xs:
            continue
        ax.plot(
            xs,
            ys,
            marker="o",
            linewidth=2.0,
            color=TIER_COLORS[tier],
            label=tier,
            zorder=3,
            markersize=6,
            markeredgecolor="white",
            markeredgewidth=1.0,
        )
        # Value annotations on each marker
        for x, y in zip(xs, ys):
            ax.annotate(
                f"{y:.2f}",
                (x, y),
                fontsize=7,
                color="#222222",
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
            )

    # Annotate the V1 inversion (bad > mediocre at x=0)
    v1_summary = versions[0][1].get("summary", {})
    bad_at_v1 = v1_summary.get("bad", {}).get("mean")
    med_at_v1 = v1_summary.get("mediocre", {}).get("mean")
    if bad_at_v1 is not None and med_at_v1 is not None and bad_at_v1 > med_at_v1:
        ax.annotate(
            "V1: bad > mediocre\n(inversion)",
            xy=(0, bad_at_v1),
            xytext=(0.6, 0.78),
            fontsize=9,
            color="#a00000",
            arrowprops=dict(arrowstyle="->", color="#a00000", lw=1.2),
        )

    # Annotate the adversarial introduction
    for idx, (version, data) in enumerate(versions):
        summary = data.get("summary") or {}
        if (summary.get("adversarial") or {}).get("n", 0) > 0:
            ax.annotate(
                f"adversarial tier\nfirst measured (V{version.label[1:]})",
                xy=(idx, summary["adversarial"]["mean"]),
                xytext=(idx + 0.4, 0.58),
                fontsize=8,
                color="#a00000",
                arrowprops=dict(arrowstyle="->", color="#a00000", lw=1.0),
            )
            break

    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels, fontsize=10)
    ax.set_xlim(-0.5, len(versions) - 0.5)
    ax.set_ylim(-0.04, 1.04)
    ax.set_xlabel("Grader version", fontsize=11)
    ax.set_ylabel("Mean reward (0–1)", fontsize=11)
    ax.set_title(
        "Grader evolution V1 → V4: each tier's mean reward across versions\n"
        "shaded strips = current (V4) target bands per tier",
        fontsize=12,
    )
    ax.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    # Tier legend — also include a band patch so readers know what the strips mean
    handles = [
        mpatches.Patch(color=TIER_COLORS[t], label=t) for t in TIER_ORDER
    ]
    ax.legend(
        handles=handles,
        loc="lower left",
        fontsize=9,
        framealpha=0.95,
        title="Tier",
        title_fontsize=9,
    )

    fig.tight_layout()
    save_fig(fig, "calibration_versions.png")


if __name__ == "__main__":
    main()
