# Website-bench generator

Generates a Harbor benchmark dataset of 5-page-website replication tasks at
varying difficulty tiers. An agent under test is shown screenshots of the 5
reference pages and asked to recreate them in HTML/CSS; `score.py` re-renders
the agent's output and scores it against the reference.

Two operating modes:

- **Hand-written seeds** — generate from the 10 curated seeds in `seeds.py`.
  Predictable, reproducible, limited to what's hand-authored.
- **`--synthesize N`** — ask Claude Sonnet to invent N new seeds across the
  tier range, then run the same codegen pipeline. Scalable to any dataset
  size.

For the design rationale and pipeline internals, see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Layout

```
bench-generator/
├── generate_dataset.py            # Orchestrator + codegen (Stage 2 + 3)
├── concept_gen.py                 # LLM-driven seed synthesis (Stage 1)
├── seeds.py                       # TIERS, GENRES, hardcoded SEEDS (10)
├── prompts.py                     # Codegen system + user prompts
├── sanity.py                      # Local Playwright render + DOM checks
├── relevance.py                   # Claude vision judge (per-page scoring)
├── templates/                     # Harness files copied into every task
│   ├── task.toml.tpl              # Templated; placeholders for name/tier/genre
│   ├── instruction.md.tpl         # Templated; placeholders for page list
│   ├── environment/{Dockerfile,make.py}    # Verbatim per task
│   ├── solution/solve.sh          # Verbatim — oracle solver
│   └── tests/{test.sh,score.py}   # Verbatim — scoring harness
├── scripts/test_pipeline.sh       # End-to-end smoke test
├── docs/
│   └── ARCHITECTURE.md            # Design + extension guide
└── README.md                      # This file
```

---

## Quick start

```bash
export ANTHROPIC_API_KEY=...

# Mode A — generate from the 10 hardcoded seeds
uv run generate_dataset.py --count 10 --output ./website-bench

# Mode B — synthesize 50 new tasks via the LLM concept stage
uv run generate_dataset.py --synthesize 50 --concurrency 16 --output ./website-bench-v1
```

Both modes write Harbor task directories under `--output`, plus a
`registry.json` manifest and a `README.md` index.

---

## CLI reference

### Inputs

| Flag | Default | Purpose |
|------|---------|---------|
| `--output <dir>` | required | Where to write task directories |
| `--count N` | 10 | (Mode A) Max number of hardcoded seeds to use |
| `--synthesize N` | 0 | (Mode B) Ask the LLM to invent N new seeds. Mutually exclusive with `--include-id`. |
| `--tier-min N`, `--tier-max N` | full range in `TIERS` | Restrict tier range |
| `--include-id <id>` | — | Mode A only — generate only the named seed(s); repeatable |
| `--synth-seed K` | random | RNG seed for tier/genre pair selection in Mode B; pass an integer for reproducibility |
| `--start-index N` | 0 | (Mode A) skip the first N matching seeds (resuming) |

### Models, concurrency, retries

| Flag | Default | Purpose |
|------|---------|---------|
| `--model <name>` | `claude-opus-4-7` | Model for HTML/CSS codegen (Stage 2). Concept stage always uses `claude-sonnet-4-6`. |
| `--concurrency` / `-j N` | 8 | Parallel workers. **Codegen issues one LLM call per page** (5 per seed), so peak in-flight calls = `5N`. With `-j 16` that's up to 80 concurrent calls — drop it if you hit 429s. |
| `--max-retries N` | 3 | Per-seed codegen retries on HTML validation failure |

### Inspection

| Flag | Purpose |
|------|---------|
| `--dry-run` | Plan the run and exit without calling any LLM |
| `--list-tiers` | Print tier definitions from `seeds.py` and exit |

---

## Examples

```bash
# See what would happen — no API call, no cost
uv run generate_dataset.py --synthesize 5 --dry-run --output /tmp/preview

# Regenerate one hand-written seed (overwrites the existing dir)
uv run generate_dataset.py --include-id 004-saas-marketing --output ./website-bench

# Easy-tier-only batch
uv run generate_dataset.py --synthesize 20 \
  --tier-min 1 --tier-max 1 \
  --output ./bench-easy

# Reproducible synthesis — fixed RNG means the same (tier, genre) pairs each run
uv run generate_dataset.py --synthesize 10 --synth-seed 42 --output ./repro-run

# Larger batch with higher concurrency (needs Tier 3+ Anthropic API limits)
uv run generate_dataset.py --synthesize 100 --concurrency 24 --output ./big-bench
```

---

## Inspecting one seed before kicking off a full run

`concept_gen.py` can be run standalone to see what a single seed looks like
without going through codegen:

```bash
uv run concept_gen.py --tier 1 --genre portfolio
uv run concept_gen.py --tier 3 --genre dashboard
```

It prints the generated `Seed` JSON to stdout. Useful when iterating on
prompts in [prompts.py](prompts.py) or adding a new genre.

---

## Validating generated tasks

Two checks run **after** generation. They take a directory of generated tasks
and report which ones look good.

### `sanity.py` — deterministic, no LLM

Renders each page locally with Playwright and asserts:

- Render succeeds, screenshot is not blank, page height in `[400, 20000]` px
- Visible text length ≥ 200 chars
- Tier 2+: page has `<nav>` and `<footer>` landmarks
- Tier 3+: page has ≥ 2 flex/grid layout containers
- **Cross-page (tier 2+):** nav labels identical across all 5 pages, footer
  text overlap ≥ 80 %, background-color drift < ΔE 12 in LAB space

```bash
uv run sanity.py ./website-bench-v1/synth-t1-portfolio-a3b2
uv run sanity.py ./website-bench-v1/*/               # whole dataset
uv run sanity.py ./website-bench-v1/*/ --json        # machine-readable summary
```

Exit code 0 if every task passes; 1 otherwise. Failed tasks print exactly
which threshold tripped and the measured value.

### `relevance.py` — Claude Sonnet vision judge

For each page in a task, sends the rendered screenshot + the seed spec to
Claude Sonnet (vision-enabled) and collects five 1-5 Likert scores:
`matches_page_spec`, `matches_palette`, `matches_typography`,
`respects_constraints`, `overall_coherence`.

A page passes if every rubric is ≥ 3 and `overall_coherence` ≥ 4. A task
passes if every page passes.

```bash
uv run relevance.py ./website-bench-v1/synth-t1-portfolio-a3b2
uv run relevance.py ./website-bench-v1/*/
```

Cost: ~$0.01/page, ~$0.05/task. Failures print the judge's `notes` field so
you can see why a page didn't pass.

### `scripts/test_pipeline.sh` — full end-to-end smoke

Generates 3 fresh tasks (one per tier), then runs both checks above:

```bash
./scripts/test_pipeline.sh           # full pipeline (~3-5 min, costs API)
./scripts/test_pipeline.sh --fast    # skip relevance/VLM step
./scripts/test_pipeline.sh --keep    # don't delete the temp output dir
```

Use this as a CI gate — it exits non-zero on any checkpoint failure.

---

## Iterating on the dataset

The two LLM-facing knobs live in separate files:

- **Tier definitions** (`seeds.py:TIERS`) — what each difficulty level
  encompasses, and the CSS capabilities the agent is expected to demonstrate.
- **Codegen rules** (`prompts.py:SYSTEM_PROMPT`) — the hard rules every
  generated page must obey (no JS, no external URLs, system fonts, etc.).

When you change either, regenerate the affected tasks. Re-running
`generate_dataset.py` overwrites task directories that already exist at the
target paths.

Genre coverage lives in `seeds.py:GENRES`. Adding a genre is one line; the
synth pair-picker picks it up automatically.

---

## Roadmap

What's in Phase A (the current release):

- Tiers 1-3 with 5 genres each
- LLM-driven concept stage (`concept_gen.py`)
- Two-stage parallel pipeline (synth + codegen, both threaded)
- Three layers of post-generation QA (schema, HTML validity, sanity, relevance)
- End-to-end smoke test (`scripts/test_pipeline.sh`)

Planned for Phase B and beyond:

- Tiers 4-8 (visual polish, custom typography systems, forms/data, inline SVG,
  magazine layouts)
- Bonus tier: animations — requires relaxing the no-JS rule and recording
  video for scoring
- Bonus tier: React + Tailwind track — separate codegen prompt + template
  set, agent produces a buildable project

See [docs/ARCHITECTURE.md §9](docs/ARCHITECTURE.md) for what each extension
touches and where the seams are.
