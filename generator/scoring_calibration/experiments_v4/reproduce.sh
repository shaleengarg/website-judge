#!/usr/bin/env bash
# Run the V4 multi-task grader calibration experiment end-to-end:
#   degrade tasks → grade variants → generate plots → print summary.
#
# Usage:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./reproduce.sh
#
# Tasks come from tasks.txt (one task id per line). Skips degrade for any
# task that already has output under ../degraded/<task>/.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAL_ROOT="$(cd "$HERE/.." && pwd)"
GENERATOR_ROOT="$(cd "$CAL_ROOT/.." && pwd)"
REPO_ROOT="$(cd "$GENERATOR_ROOT/.." && pwd)"

TASKS_FILE="$HERE/tasks.txt"
DEGRADED_DIR="$CAL_ROOT/degraded"
RESULTS_FILE="$CAL_ROOT/results/v4.0.json"
DEGRADE_PY="$CAL_ROOT/degrade.py"
RUN_PY="$CAL_ROOT/run.py"

GRADER_VERSION="v4.0"

if [ ! -f "$TASKS_FILE" ]; then
    echo "ERROR: tasks.txt not found at $TASKS_FILE" >&2
    exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set. The V4 grader requires the Opus judge." >&2
    echo "       export ANTHROPIC_API_KEY=sk-ant-..." >&2
    exit 1
fi

# Read tasks (skip blanks + comments). Portable to bash 3.2 (macOS default).
TASKS=()
while IFS= read -r line; do
    TASKS+=("$line")
done < <(grep -v '^[[:space:]]*\(#\|$\)' "$TASKS_FILE")
if [ ${#TASKS[@]} -eq 0 ]; then
    echo "ERROR: tasks.txt has no tasks" >&2
    exit 1
fi

echo "=== preflight ==="
echo "Tasks (${#TASKS[@]}):"
printf '  - %s\n' "${TASKS[@]}"
echo

# Resolve each task's reference-pages directory. Search both the current
# workloads_v4 dataset and the archived old_bench/* datasets.
find_task_dir() {
    local task_id="$1"
    local candidates=(
        "$REPO_ROOT/workloads_v4/$task_id"
        "$REPO_ROOT/archive/old_bench/website-bench_v2-1/$task_id"
        "$REPO_ROOT/archive/old_bench/website-bench_v2/$task_id"
        "$REPO_ROOT/archive/old_bench/website-bench_v1/$task_id"
        "$REPO_ROOT/archive/old_bench/website-bench_v0/$task_id"
        "$REPO_ROOT/archive/old_bench/website-bench_v3/$task_id"
    )
    for c in "${candidates[@]}"; do
        if [ -d "$c/environment/reference-pages" ]; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

for task in "${TASKS[@]}"; do
    if ! task_dir=$(find_task_dir "$task"); then
        echo "ERROR: cannot find reference-pages for task '$task'" >&2
        echo "       expected under workloads_v4/ or archive/old_bench/website-bench_v*/" >&2
        exit 1
    fi
    page_count=$(find "$task_dir/environment/reference-pages" -maxdepth 2 -name index.html | wc -l | tr -d ' ')
    if [ "$page_count" -lt 4 ]; then
        echo "ERROR: $task has only $page_count pages (need ≥4)" >&2
        exit 1
    fi
    echo "  $task → $task_dir ($page_count pages)"
done
echo

# Run degrade.py only for tasks that don't already have a degraded dir.
echo "=== degrade ==="
for task in "${TASKS[@]}"; do
    if [ -d "$DEGRADED_DIR/$task" ] \
        && [ -d "$DEGRADED_DIR/$task/near_perfect" ] \
        && [ -d "$DEGRADED_DIR/$task/mediocre" ] \
        && [ -d "$DEGRADED_DIR/$task/bad" ] \
        && [ -d "$DEGRADED_DIR/$task/adversarial" ] \
        && [ -d "$DEGRADED_DIR/$task/plain" ]; then
        echo "  $task — already degraded, skipping"
        continue
    fi
    task_dir=$(find_task_dir "$task")
    echo "  $task — running degrade.py"
    (cd "$REPO_ROOT" && uv run python "$DEGRADE_PY" --task "$task_dir" --out "$DEGRADED_DIR")
done
echo

# Back up existing v4.0.json so a partial re-run doesn't lose the previous data.
if [ -f "$RESULTS_FILE" ]; then
    cp "$RESULTS_FILE" "$RESULTS_FILE.bak"
    echo "backed up existing results → $RESULTS_FILE.bak"
fi
echo

# Grade all variants.
echo "=== grade ==="
echo "Calling run.py — this is the long-running step (~30-40 min, ~\$5-15 in Opus calls)"
(cd "$REPO_ROOT" && uv run python "$RUN_PY" --grader-version "$GRADER_VERSION")
echo

# Generate plots.
echo "=== plot ==="
"$HERE/make_plots.sh"
echo

# Print one-line summary.
echo "=== summary ==="
(cd "$REPO_ROOT" && uv run python - <<PY
import json
from pathlib import Path
data = json.loads(Path("$RESULTS_FILE").read_text())
summary = data.get("summary") or {}
print("Per-tier means:")
for tier in ("near_perfect","mediocre","plain","adversarial","bad"):
    if tier in summary:
        s = summary[tier]
        print(f"  {tier:<14} mean={s['mean']:.3f}  stdev={s['stdev']:.3f}  n={s['n']}")
print(f"Inversions: {summary.get('inversions')}")
PY
)
echo

echo "Plots:"
echo "  $REPO_ROOT/docs/img/calibration_ladder.png"
echo "  $REPO_ROOT/docs/img/calibration_per_task.png"
echo "  $REPO_ROOT/docs/img/calibration_dimensions.png"
echo "  $REPO_ROOT/docs/img/calibration_versions.png"
