# Grader calibration harness

Calibration evaluates `bench-generator/templates/tests/score.py` — the grader
template stamped into every Harbor task. For each grader version (V1, V2, V3, ...)
we run the grader against a fixed set of degraded outputs and check tier separation.

## Tier targets

(Copied from `small_checks/docs/GRADING.md` §3.)

| Tier | Target band | Description |
| --- | --- | --- |
| `near_perfect` | ≥ 0.85 | Verbatim copy of reference HTML. Lower bound for "what a perfect agent produces." |
| `mediocre` | 0.40–0.65 | Wrong palette + system fonts + ~30% lorem text. Semantic tags + `@media` preserved. |
| `bad` | ≤ 0.15 | Full lorem text, no `@media`, no semantic elements, wrong palette, last page omitted. |

Plus: **zero per-task inversions** (`near_perfect > mediocre > bad` must hold for every task).

## Setup

All commands must be run via `uv run` from the repo root
(`/Users/shaleen/proximal/website-judge`). Bare `python` / `python3` will not see
the project's deps. If `uv` isn't installed yet, `brew install uv` then
`uv sync` once.

## How grader versions work

Each calibration run uses a **frozen snapshot** of the grader, not the live
`bench-generator/templates/tests/score.py`. Snapshots live at:

```text
bench-generator/scoring_calibration/grader_versions/<version>/score.py
```

`run.py --grader-version v1` loads `grader_versions/v1/score.py` and refuses to
run if it isn't there. This way the `vN.json` results filename and the bytes
that produced it can never disagree — even if you keep editing the live
template after snapshotting.

The snapshot workflow:

```bash
# Snapshot the current templates/tests/score.py as v1 (one-time, per version)
uv run bench-generator/scoring_calibration/snapshot.py v1
```

`v1` is already snapshotted in this repo. Snapshot `v2` after editing the
template for V2, `v3` after V3, etc.

## How to run

```bash
# 1. Generate degraded variants for one task
uv run bench-generator/scoring_calibration/degrade.py \
    --task bench-generator/website-bench_v1/synth-t1-burnt-sage-kitchen-9322 \
    --out bench-generator/scoring_calibration/degraded/

# 2. Run a snapshotted grader against those variants
uv run bench-generator/scoring_calibration/run.py --grader-version v1

# Restrict to a subset of tasks (after multiple have been degraded)
uv run bench-generator/scoring_calibration/run.py --grader-version v2 \
    --tasks synth-t1-burnt-sage-kitchen-9322

# Oracle ceiling only (near_perfect tier — cheap)
uv run bench-generator/scoring_calibration/run.py --grader-version v3 --oracle-only
```

The runner shells out to `uv run _score_wrapper.py` under the hood —
no manual venv activation required.

Results land in `results/<grader_version>.json`. The runner reuses the exact
`templates/tests/score.py` code — it loads the module via importlib and overrides
the hard-coded container paths (`/opt/reference-pages`, `/app/output`, etc.) via
env vars consumed by `_score_wrapper.py`. The template itself stays byte-identical
to what ships in every generated benchmark.

## Design notes

- **Degradation rules are locked to `degrade.py`'s filename.** If the rules change,
  copy-rename to `degrade_v2.py` and start a new results column — earlier
  calibration numbers become incomparable across rule changes.
- **Calibration lives in `bench-generator/`, not in the templated Docker image.**
  Including 3-tier degraded variants in every benchmark image would inflate each
  task by ~10 MB. Calibration is a developer-side meta-eval, not a runtime artifact.
- **No screenshots needed.** `score.py` renders both reference and agent HTML
  itself via Playwright. The runner only supplies HTML.
- **API key forwarding.** When `ANTHROPIC_API_KEY` is set in the host env, the
  runner forwards it into the subprocess — V3's MLLM judge will pick it up.

## Cost (V3 only, planned)

V3 ensemble = 3 Opus 4.7 calls × ~5 pages × 3 variants × N tasks. At Opus pricing
this is roughly $5 per task per calibration run. Use `--tasks <id>` to limit cost
during iteration.
