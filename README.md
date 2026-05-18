# website-judge

A benchmark for evaluating LLM agents on **static website replication**. An agent is given screenshots of a 5-page website at three viewports (desktop, tablet, phone) and must produce HTML/CSS that visually matches. A grader (`30%` deterministic + `70%` Claude Opus vision judge) scores the result in `[0, 1]`.

This repo holds:

1. **`workload_v6/`** — the 10-task benchmark itself (Harbor-compatible). Older versions (`workloads_v4/`, `workload_v5/`) are under `archive/`.
2. **`generator/`** — the pipeline that synthesizes those tasks from tier/genre seeds, plus calibration tooling for the grader and the `difficulty_analysis/` scorer that validates the tier ladder empirically.
3. **`docs/`** — architecture and scoring write-ups.

## Directory structure

```text
website-judge/
├── README.md                  # this file
├── problem_breakdown.md       # framing of the problem (what we're solving and why)
├── docs/                      # explanatory docs
│   ├── ARCHITECTURE.md        # generator pipeline, tier/genre system, extension points
│   ├── SCORING.md             # grader design + V4 calibration evidence
│   └── img/                   # calibration plots referenced from SCORING.md
├── workload_v6/               # 10 Harbor tasks (synth-tN-*) — the actual benchmark
├── generator/                 # codegen + calibration tooling
│   ├── README.md              # quick start for generating new datasets
│   ├── generate_dataset.py    # main orchestrator (concept → shared CSS → codegen → package)
│   ├── concept_gen.py         # stage 1: LLM seed synthesis
│   ├── sanity.py              # post-gen DOM checks (no LLM)
│   ├── relevance.py           # post-gen vision judge (Sonnet)
│   ├── seeds.py / prompts.py  # tier/genre taxonomy with binding density floors, system prompts
│   ├── templates/             # files stamped into every task
│   ├── scripts/               # freshness check, upgrade scripts, smoke test
│   ├── scoring_calibration/   # grader version snapshots + experiments_v4/
│   └── difficulty_analysis/   # score_difficulty.py — validates tier ladder is monotonic
├── archive/                   # superseded artifacts (old_bench, rudimentary_test, workloads_v4, workload_v5)
└── docs/running_notes.md      # working scratch pad — design log for V1 → V4 + tier-ladder validation
```

## Install

Requires Python ≥ 3.10 and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
git clone <repo>
cd website-judge
uv sync                        # one-time: install deps
export ANTHROPIC_API_KEY=sk-ant-...
```

Playwright browsers download on first use of `sanity.py` or the grader; no manual install needed.

To run a task end-to-end you also need [Harbor](https://github.com/harboraisafety/harbor) (`pip install harbor-eval` or equivalent — see Harbor's own README).

## Quick start

> **Important — `--ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY` is required on every `harbor run`.** The grader's multimodal-LLM judge (70% of the reward) calls Claude Opus from inside the verifier container, so the key must be forwarded explicitly with `--ve` (or `--env-file`). Without it the verifier raises `RuntimeError: V3 grader requires ANTHROPIC_API_KEY` and `tests/test.sh` writes `0.0` as a fallback — every trial silently reports a zero reward.

**Run a single task with the oracle solver** (verifies the grader returns ≈ 1.0):

```bash
harbor run -p ./workload_v6/synth-t1-copper-kettle-suppers-16cf -a oracle --env modal \
  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
```

**Run the oracle across the whole benchmark** (10 tasks; sanity-checks the grader on every workload):

```bash
harbor run -p ./workload_v6 -a oracle --env modal -n 10 \
  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
```

**Run Claude Code against a single task:**

```bash
harbor run -p ./workload_v6/synth-t1-copper-kettle-suppers-16cf \
  -a claude-code -m anthropic/claude-opus-4-7 --env modal \
  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
```

**Run Claude Code across the whole benchmark** (10 tasks):

```bash
harbor run -p ./workload_v6 -a claude-code -m anthropic/claude-opus-4-7 \
  --env modal -n 10 --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
```

**Generate a fresh dataset:**

```bash
uv run generator/generate_dataset.py --count 10 --tier-min 1 --tier-max 8 \
  --concurrency 2 --output workload_v7
```

**Re-run grader calibration** (~30 min, ~$10 in Opus calls):

```bash
cd generator/scoring_calibration/experiments_v4
./reproduce.sh
```

**Re-plot calibration only** (free, no API):

```bash
cd generator/scoring_calibration/experiments_v4
./make_plots.sh
```

## Where to read next

- [`problem_breakdown.md`](docs/problem_breakdown.md) — why this benchmark exists, what it's testing, what it isn't
- [`docs/observations_and_limitation.md`](docs/observations_and_limitation.md) — end-to-end benchmark run of Claude Code (Opus 4.7) against `workload_v6`: experimental method, per-tier and per-aspect results, where the model breaks, and the limits of the evidence base
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how `generator/` produces tasks (two-stage pipeline, tier/genre taxonomy, parallelism, extension points)
- [`docs/SCORING.md`](docs/SCORING.md) — V4 grader design + calibration evidence
- [`generator/README.md`](generator/README.md) — CLI reference for the codegen tools
- [`workload_v6/README.md`](workload_v6/README.md) — task-by-task index
- [`running_notes.md`](docs/running_notes.md) — design log: how the grader evolved V1 → V4, what was tried and rejected
