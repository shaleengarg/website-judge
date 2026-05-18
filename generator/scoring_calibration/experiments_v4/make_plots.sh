#!/usr/bin/env bash
# Generate the 4 calibration PNGs from the existing results JSON.
# Cheap to run (no API calls). Use this after editing _common.py styling
# or any plot_*.py script.
#
# Usage:
#   ./make_plots.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

(cd "$HERE" && uv run plot_ladder.py)
(cd "$HERE" && uv run plot_per_task.py)
(cd "$HERE" && uv run plot_dimension_heatmap.py)
(cd "$HERE" && uv run plot_version_evolution.py)
