#!/usr/bin/env bash
# End-to-end pipeline test for website-bench.
#
# Generates 3 synthetic tasks (one per tier 1-3), then runs:
#   1. Schema validation (built into concept_gen + generate_dataset)
#   2. HTML validity (built into generate_dataset retry loop)
#   3. Sanity checks (sanity.py — local Playwright render + DOM/cross-page checks)
#   4. Relevance checks (relevance.py — Claude Sonnet vision judge)
#
# Exit code 0 means every task passed every checkpoint.
#
# Usage:
#     ./scripts/test_pipeline.sh           # full pipeline, ~3-5 min
#     ./scripts/test_pipeline.sh --fast    # skip checkpoint 4 (no API cost)
#     ./scripts/test_pipeline.sh --keep    # don't delete the temp output dir

set -euo pipefail

FAST=0
KEEP=0
for arg in "$@"; do
    case "$arg" in
        --fast) FAST=1 ;;
        --keep) KEEP=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ERROR: ANTHROPIC_API_KEY not set" >&2
    exit 1
fi

OUT_DIR="$(mktemp -d -t website-bench-test-XXXXXX)"
trap 'cleanup' EXIT
cleanup() {
    if [[ "$KEEP" -eq 1 ]]; then
        echo
        echo "(kept output dir: $OUT_DIR)"
    else
        rm -rf "$OUT_DIR"
    fi
}

PY=${PYTHON:-python3}

echo "============================================================"
echo " website-bench pipeline test"
echo "============================================================"
echo " output dir: $OUT_DIR"
echo " fast mode:  $FAST  (1 = skip relevance/VLM step)"
echo

# ----------------------------------------------------------------
# Stage 0: dry-run sanity. Catches CLI/wiring breakage before any LLM cost.
# ----------------------------------------------------------------
echo "[0/4] dry-run check"
$PY generate_dataset.py --synthesize 3 --tier-min 1 --tier-max 3 \
    --output "$OUT_DIR/dryrun" --dry-run

# ----------------------------------------------------------------
# Stage 1+2: synthesize 3 seeds + generate HTML (validation built-in)
# ----------------------------------------------------------------
echo
echo "[1+2/4] synthesize seeds + codegen HTML"
$PY generate_dataset.py \
    --synthesize 3 --tier-min 1 --tier-max 3 \
    --output "$OUT_DIR/tasks" \
    --concurrency 3

n_tasks=$(find "$OUT_DIR/tasks" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
if [[ "$n_tasks" -eq 0 ]]; then
    echo "FAIL: no tasks were generated" >&2
    exit 1
fi
echo "  generated $n_tasks task(s)"

# ----------------------------------------------------------------
# Stage 3: sanity (deterministic, no LLM)
# ----------------------------------------------------------------
echo
echo "[3/4] sanity checks"
mapfile -t task_dirs < <(find "$OUT_DIR/tasks" -mindepth 1 -maxdepth 1 -type d | sort)
if ! $PY sanity.py "${task_dirs[@]}"; then
    echo "FAIL: sanity checks failed" >&2
    exit 1
fi

# ----------------------------------------------------------------
# Stage 4: relevance (VLM judge — only in full mode)
# ----------------------------------------------------------------
if [[ "$FAST" -eq 1 ]]; then
    echo
    echo "[4/4] relevance check  SKIPPED (--fast)"
else
    echo
    echo "[4/4] relevance checks (Claude Sonnet vision judge)"
    if ! $PY relevance.py "${task_dirs[@]}"; then
        echo "FAIL: relevance checks failed" >&2
        exit 1
    fi
fi

echo
echo "============================================================"
echo " PIPELINE OK"
echo "============================================================"
