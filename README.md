# website-judge

A benchmark for evaluating LLM agents on **static website replication**. An agent is given screenshots of a 5-page website at three viewports (desktop, tablet, phone) and must produce HTML/CSS that visually matches. A grader (`30%` deterministic + `70%` Claude Opus vision judge) scores the result in `[0, 1]`.

This repo holds:

1. **`workloads_v4/`** — the 10-task benchmark itself (Harbor-compatible).
2. **`generator/`** — the pipeline that synthesizes those tasks from tier/genre seeds, plus calibration tooling for the grader.
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
├── workloads_v4/              # 10 Harbor tasks (synth-tN-*) — the actual benchmark
├── generator/                 # codegen + calibration tooling
│   ├── README.md              # quick start for generating new datasets
│   ├── generate_dataset.py    # main orchestrator (concept → codegen → package)
│   ├── concept_gen.py         # stage 1: LLM seed synthesis
│   ├── sanity.py              # post-gen DOM checks (no LLM)
│   ├── relevance.py           # post-gen vision judge (Sonnet)
│   ├── seeds.py / prompts.py  # tier/genre taxonomy, system prompts
│   ├── templates/             # files stamped into every task
│   ├── scripts/               # freshness check, upgrade scripts, smoke test
│   └── scoring_calibration/   # grader version snapshots + experiments_v4/
├── archive/                   # superseded artifacts (old_bench, rudimentary_test, jobs/)
└── running_notes.md           # working scratch pad — design log for V1 → V4
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

**Run a single task with the oracle solver** (verifies the grader returns ≈ 1.0):

```bash
harbor run -p ./workloads_v4/synth-t1-ink-and-insomnia-blog-fea9 -a oracle --env modal
```

**Run Claude Code against a task:**

```bash
harbor run -p ./workloads_v4/synth-t1-ink-and-insomnia-blog-fea9 \
  -a claude-code -m anthropic/claude-opus-4-7 --env modal --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
```

**Run Claude Code across the whole benchmark** (10 tasks):

```bash
harbor run -p ./workloads_v4 -a claude-code -m anthropic/claude-opus-4-7 \
  --env modal --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -n 10
```

**Generate a fresh dataset:**

```bash
cd generator
uv run generate_dataset.py --count 10 --output ../workloads_v5
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
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how `generator/` produces tasks (two-stage pipeline, tier/genre taxonomy, parallelism, extension points)
- [`docs/SCORING.md`](docs/SCORING.md) — V4 grader design + calibration evidence
- [`generator/README.md`](generator/README.md) — CLI reference for the codegen tools
- [`workloads_v4/README.md`](workloads_v4/README.md) — task-by-task index
- [`running_notes.md`](docs/running_notes.md) — design log: how the grader evolved V1 → V4, what was tried and rejected
