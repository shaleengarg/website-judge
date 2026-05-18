# Website-bench generator

Generates a Harbor benchmark dataset of 5-page-website replication tasks at
varying difficulty tiers. An agent under test is shown screenshots of the 5
reference pages and asked to recreate them in HTML/CSS; `score.py` re-renders
the agent's output and scores it against the reference.

**Fully LLM-generated.** Every seed is invented on demand by Claude Sonnet
([concept_gen.py](concept_gen.py)) based on a tier definition and a target
genre. There is no hand-written seed list — only `TIERS` and `GENRES` taxonomies
in [seeds.py](seeds.py).

For the design rationale and pipeline internals, see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Layout

```
bench-generator/
├── generate_dataset.py            # Orchestrator + codegen (Stage 2 + 3)
├── concept_gen.py                 # LLM-driven seed synthesis (Stage 1)
├── seeds.py                       # TIERS, GENRES, schema, tier helpers
├── prompts.py                     # Codegen system + per-page user prompts
├── sanity.py                      # Local Playwright render + DOM checks
├── relevance.py                   # Claude vision judge (per-page scoring)
├── templates/                     # Harness files copied into every task
│   ├── task.toml.tpl              # Templated; placeholders for name/tier/genre
│   ├── instruction.md.tpl         # Templated; placeholders for page list
│   ├── environment/{Dockerfile,make.py}    # Verbatim per task
│   ├── solution/solve.sh          # Verbatim — oracle solver
│   └── tests/{test.sh,score.py}   # Verbatim — scoring harness
├── scripts/test_pipeline.sh       # End-to-end smoke test
├── scripts/check_freshness.py     # Detect tasks stale vs current templates/
├── scripts/upgrade_tasks.py       # Re-apply templates without LLM regen
├── docs/
│   └── ARCHITECTURE.md            # Design + extension guide
└── README.md                      # This file
```

---

## Quick start

```bash
export ANTHROPIC_API_KEY=...

# Generate 10 synthetic tasks across the default tier range (1-8)
uv run generate_dataset.py --count 10 --output ./website-bench

# Larger batch — 50 tasks, higher concurrency
uv run generate_dataset.py --count 50 --concurrency 16 --output ./website-bench-v1

# Constrain to tiers 1-3
uv run generate_dataset.py --count 20 --tier-max 3 --output ./bench-easy

# Print all defined tiers (no API call)
uv run generate_dataset.py --list-tiers
```

Each run writes one Harbor task directory per generated site, plus a
`registry.json` manifest and a `README.md` index.

---

## Tiers

Tiers 1-8 are the static-CSS difficulty ladder. Each is one level harder than
the previous and is tested with deterministic structural checks in
[sanity.py](sanity.py).

| Tier | Name | Defining capability |
|------|------|---------------------|
| 1 | Static blocks | Vertical stacks, basic typography, solid colors |
| 2 | Multi-page identity | Shared nav/footer/palette across 5 pages, flexbox basics |
| 3 | Real layout | Multi-column, sidebars, sticky positioning, tables |
| 4 | Visual polish | Gradients, box-shadow elevation, decorative pseudo-elements |
| 5 | Custom typography systems | Coherent type scale, multiple weights, drop caps |
| 6 | Forms and data-heavy | Styled inputs, dense tables, multi-column form layouts |
| 7 | Inline SVG and shapes | Inline `<svg>`, clip-path, transforms, masking |
| 8 | Mixed visual systems | Magazine-style assemblies of heterogeneous sections |
| 9 | Animations | **Defined but generation-gated** — needs the motion harness |

Tier 9 (animations) has its taxonomy entry and genre list in place for forward
compatibility, but the codegen path requires extensions (Playwright `page.clock`
virtualization, frame-grid capture, motion judge) that are not yet implemented.
Asking for `--tier-max 9` errors with a clear "not yet implemented" message.

Run `--list-tiers` to print full definitions including CSS capabilities and
genre lists.

---

## CLI reference

| Flag | Default | Purpose |
|------|---------|---------|
| `--count N` | 10 | Number of synthetic tasks to generate. |
| `--output <dir>` | required (unless `--list-tiers`) | Output directory. |
| `--tier-min N`, `--tier-max N` | static range (1-8) | Tier range to sample from. Motion tiers (9) are excluded unless `--tier-max 9` is set explicitly, in which case generation errors with a clear message. |
| `--synth-seed K` | random | RNG seed for tier/genre pair selection. Pass an integer for reproducibility. |
| `--model <name>` | `claude-opus-4-7` | Codegen model. Concept stage always uses `claude-sonnet-4-6`. |
| `--concurrency` / `-j N` | 8 | Outer parallel workers. **Codegen issues one LLM call per page** (5 per seed), so peak in-flight calls = `5N`. With `-j 16` that's up to 80 concurrent calls — drop it if you hit 429s. |
| `--max-retries N` | 3 | Per-page retries on HTML validation failure. |
| `--dry-run` | — | Plan the run and exit without calling any LLM. |
| `--list-tiers` | — | Print tier and genre definitions and exit. |

---

## Examples

```bash
# Plan a run with no API cost
uv run generate_dataset.py --count 5 --output /tmp/preview --dry-run

# Reproducible: fixed RNG gives the same (tier, genre) pair sequence
uv run generate_dataset.py --count 16 --synth-seed 42 --output ./repro-run

# Tier 4-5 only — visual polish + typography systems
uv run generate_dataset.py --count 10 --tier-min 4 --tier-max 5 \
  --output ./bench-polish

# Big batch (needs Anthropic tier-3+ rate limits)
uv run generate_dataset.py --count 100 --concurrency 24 --output ./big-bench
```

---

## Inspecting a single concept before a full run

`concept_gen.py` runs standalone and prints one generated `Seed` JSON to stdout:

```bash
uv run concept_gen.py --tier 6 --genre signup-flow
uv run concept_gen.py --tier 8 --genre design-magazine
```

Useful when iterating on prompts in [prompts.py](prompts.py) or sanity-checking
a new tier definition.

---

## Validating generated tasks

Two checks run **after** generation. They take a directory of generated tasks
and report which ones look good.

### `sanity.py` — deterministic, no LLM

Renders each page locally with Playwright and asserts:

- Render succeeds; screenshot not blank; page height in `[400, 20000]` px
- Visible text length ≥ 200 chars
- Tier 2+: page has `<nav>` and `<footer>` landmarks
- Tier 3+: ≥ 2 flex/grid layout containers
- Tier 4+: page CSS uses a gradient or box-shadow
- Tier 5+: typography has ≥ 3 distinct sizes OR ≥ 2 distinct weights
- Tier 6+: page has a `<form>`, a `<table>`, or ≥ 4 input elements
- Tier 7+: ≥ 1 inline `<svg>` with drawable content
- Tier 8+: ≥ 3 distinct flex/grid layout containers
- **Cross-page (tier 2+):** nav labels identical across all 5 pages; footer
  text overlap ≥ 80 %; background-color drift < ΔE 12 in LAB space

```bash
uv run sanity.py ./website-bench-v1/synth-t1-portfolio-a3b2
uv run sanity.py ./website-bench-v1/*/               # whole dataset
uv run sanity.py ./website-bench-v1/*/ --json        # machine-readable summary
```

Exit code 0 if every task passes; 1 otherwise. Failed tasks print exactly
which threshold tripped and the measured value.

### `relevance.py` — Claude Sonnet vision judge

For each page, sends the rendered screenshot + the seed spec to Claude Sonnet
(vision-enabled) and collects five 1-5 Likert scores: `matches_page_spec`,
`matches_palette`, `matches_typography`, `respects_constraints`,
`overall_coherence`. A page passes if every rubric is ≥ 3 and
`overall_coherence` ≥ 4. A task passes if every page passes.

```bash
uv run relevance.py ./website-bench-v1/synth-t1-portfolio-a3b2
uv run relevance.py ./website-bench-v1/*/
```

Cost: ~$0.01/page, ~$0.05/task.

### Freshness — keeping generated tasks in sync with `templates/`

Generated tasks copy `templates/` verbatim at generation time. So when you
edit any template file (Dockerfile, make.py, score.py, task.toml.tpl,
instruction.md.tpl, ...), existing on-disk tasks are silently out of sync
until you regenerate or upgrade them. To detect and fix this without burning
LLM tokens:

```bash
# Detect: is every task in this dataset using the current templates/?
uv run scripts/check_freshness.py ./website-bench_v3

# Fix: re-apply templates to stale tasks. Does NOT touch reference-pages/
# (the LLM HTML) or seed.json — only the harness wrapper.
uv run scripts/upgrade_tasks.py ./website-bench_v3
uv run scripts/upgrade_tasks.py ./website-bench_v3 --only-stale   # skip fresh

# Confirm:
uv run scripts/check_freshness.py ./website-bench_v3
```

Each task carries a `template_version.txt` stamp (SHA256 of the templates/
tree, written by `generate_dataset.py`). `check_freshness.py` compares each
stamp against the current `templates/` hash. `upgrade_tasks.py` re-applies
templates: wipes and re-copies `solution/` and `tests/`, overwrites
`environment/Dockerfile` and `environment/make.py`, re-renders `task.toml`
and `instruction.md` from the current `.tpl` files using each task's
`seed.json` sidecar, and re-stamps `template_version.txt`. Use this before
any `harbor run` after a template change.

### `scripts/test_pipeline.sh` — full end-to-end smoke

Generates 3 fresh tasks (tier-min 1, tier-max 3 by default), then runs both
checks above:

```bash
./scripts/test_pipeline.sh           # full pipeline (~3-5 min, costs API)
./scripts/test_pipeline.sh --fast    # skip relevance/VLM step
./scripts/test_pipeline.sh --keep    # don't delete the temp output dir
```

Use as a CI gate — exits non-zero on any checkpoint failure.

---

## Iterating on the dataset

Two LLM-facing knobs live in separate files:

- **Tier definitions** ([seeds.py:TIERS](seeds.py)) — what each difficulty level
  encompasses, and the CSS capabilities the agent is expected to demonstrate.
  Concept-gen reads these directly into its prompt.
- **Codegen rules** ([prompts.py:SYSTEM_PROMPT](prompts.py)) — the hard rules
  every generated page must obey (no JS, no external URLs, system fonts, etc.).

When you change either, regenerate the affected tasks. Re-running
`generate_dataset.py` overwrites any task directories that already exist at the
target output paths.

Genre coverage lives in [seeds.py:GENRES](seeds.py). Adding a genre is one
line; the synth pair-picker picks it up automatically and the shuffle-bag
sampler keeps the distribution even.

---

## Roadmap

In place today:

- Tiers 1-8, 5 genres per tier, fully LLM-generated seeds
- Two-stage parallel pipeline (Sonnet for concepts, Opus for codegen, one call
  per page, all parallelized)
- Sanity (deterministic) + relevance (VLM judge) post-generation QA
- End-to-end smoke test in `scripts/test_pipeline.sh`

Defined but not yet generation-enabled:

- **Tier 9 — Animations.** Taxonomy in place; needs harness work
  (Playwright `page.clock` virtualization, frame-grid capture, motion judge).
  Pattern documented in [docs/ARCHITECTURE.md §9](docs/ARCHITECTURE.md).

Future:

- React + Tailwind track — separate codegen prompt + template set, agent
  produces a buildable project. See [docs/ARCHITECTURE.md §9](docs/ARCHITECTURE.md)
  for the seams.
