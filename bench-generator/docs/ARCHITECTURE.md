# Architecture — website-bench generator

This document explains how `bench-generator/` produces benchmark websites: the
two-stage pipeline, the quality-gate stack, the tier/genre system, the
parallelism model, and where the seams are for future extensions (animations,
React+Tailwind, new tiers).

For a quick start guide and CLI reference, see [README.md](README.md). This
document is for engineers who need to add tiers, tune prompts, debug failures,
or extend the framework.

---

## 1. What it produces

Each run of `generate_dataset.py` writes a directory of Harbor tasks. One task =
one website = five HTML pages sharing nav/footer/palette/typography. Each task
directory is a self-contained Harbor evaluation: a Dockerfile that renders the
reference pages to PNG at build time, an agent instruction, a scoring harness,
and an oracle solver.

```
<output-dir>/
├── synth-t1-portfolio-a3b2/        # one task = one website
│   ├── task.toml                   # Harbor metadata
│   ├── instruction.md              # what the agent is told to do
│   ├── seed.json                   # originating Seed (read by relevance.py)
│   ├── environment/
│   │   ├── Dockerfile              # playwright-python base
│   │   ├── make.py                 # renders ref-pages → PNG at build time
│   │   └── reference-pages/
│   │       ├── home/index.html
│   │       ├── work/index.html
│   │       ├── writing/index.html
│   │       ├── about/index.html
│   │       └── contact/index.html
│   ├── solution/solve.sh           # oracle: copy ref → output, reward ≈ 1.0
│   └── tests/
│       ├── test.sh
│       └── score.py                # 0.7·SSIM + 0.3·color-histogram, per page
├── synth-t2-conference-9f1e/
├── ...
├── registry.json                   # manifest of all tasks
└── README.md                       # generated index of tasks
```

The agent under test sees only `instruction.md` + the rendered reference PNGs
(via `/app/references/<page>.png`). It does not see the source HTML.

---

## 2. The pipeline

```
   (--synthesize N)        OR        (hardcoded SEEDS list)
        │                                     │
        ▼                                     │
┌──────────────────────┐                      │
│ concept_gen.py       │  Stage 1: Sonnet     │
│  Seed JSON           │  T=0.95, 1 call/seed │
│  (parallel)          │                      │
└──────────────────────┘                      │
        │                                     │
        └──────────────┬──────────────────────┘
                       ▼
            ┌──────────────────────┐
            │ generate_dataset.py  │  Stage 2: Opus
            │  call_llm()          │  validate_html() retry loop
            │  5 HTML pages        │  (up to --max-retries)
            │  (parallel)          │
            └──────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │ write_task()         │  Stage 3: copy templates
            │  Harbor task dir     │  render task.toml + instruction.md
            │                      │  drop seed.json sidecar
            └──────────────────────┘
                       │
                       ▼  (optional, run separately)
            ┌──────────────────────┐
            │ sanity.py            │  Playwright local render
            │ relevance.py         │  Sonnet vision judge
            └──────────────────────┘
```

Two LLM stages plus a local-only packaging stage, followed by an optional QA
pass (`sanity.py` + `relevance.py`) that doesn't run inside the generator but
exists in the same codebase and is called by `scripts/test_pipeline.sh`.

---

## 3. Stage 1 — concept generation (`concept_gen.py`)

**Input:** a `(tier: int, genre: str)` pair.
**Output:** a `Seed` dict matching the schema defined in [seeds.py](seeds.py).
**Model:** `claude-sonnet-4-6` at `temperature=0.95`.

### 3.1 Why a separate concept stage exists

Generating both the *concept* (what site, what palette, what pages, what tone)
and the *code* (the actual HTML/CSS) in one LLM call biases the model toward
the same handful of safe patterns: SaaS landing pages, generic dashboards,
portfolios with the same nav layout. The team that built the `small_checks/`
reference pipeline observed this directly and split the stages for two reasons:

1. **Diversity.** A small high-temperature Sonnet call is cheap and explicitly
   tasked with being surprising in brand, palette, and content. The downstream
   Opus codegen call is told *not* to be creative — only to faithfully render
   the spec.
2. **Cheap rejection.** A bad concept can be retried for ~$0.001. A bad
   codegen run costs ~50× more. If we ever add a concept-level filter (e.g.
   "reject if too similar to a previous concept"), it runs before the expensive
   stage.

This split also lets us swap genre taxonomies, add a tier, or change the
concept-level diversity policy without touching codegen prompts.

### 3.2 Prompt shape

The user prompt to Sonnet contains:
- The tier definition (name, description, `css_capabilities` list) — pulled
  from `TIERS[tier]` in `seeds.py`.
- The target genre.
- The required output schema, declared inline so the model produces exactly the
  `Seed` shape.
- Two hand-written seeds at the same tier as **few-shot examples** — the model
  sees what level of detail and what kind of constraints look like.
- An explicit anti-laziness instruction ("NEVER use Lorem ipsum or generic
  filler", "Brand name should be evocative, not descriptive").

### 3.3 Validation and retry

`_validate_seed_shape()` checks the parsed JSON against the schema:
- All required keys present, all of correct type.
- `tier` matches the requested tier, `genre` matches the requested genre.
- Exactly 5 page names, all non-empty strings.
- `page_specs.keys()` exactly matches `pages` (same order, same names) —
  this invariant is load-bearing downstream: `call_llm()` checks the same
  thing on the codegen output, and `score.py` iterates `reference-pages/*`.
- `constraints` has at least 3 items.
- Free-text fields (`palette_hint`, `type_style`, `description`) non-empty.

Up to 3 retries. On retry, prior errors are appended to the user prompt so the
model gets a concrete fix-list rather than generic "try again" feedback.

### 3.4 ID assignment

The ID returned by Sonnet is sanitized and **always** prefixed with
`synth-t{tier}-` plus a 4-hex-char UUID suffix. Example:
`synth-t2-saas-marketing-3b9f`. Two properties matter:

- The `synth-` prefix makes synthetic tasks visually distinguishable from
  hand-written ones in the output directory.
- The UUID suffix prevents collisions when the model reuses a brand name across
  runs (it does this more than you'd think).

---

## 4. Stage 2 — HTML/CSS codegen (`generate_dataset.py` + `prompts.py`)

**Input:** a `Seed` dict (from Stage 1 or from the hardcoded `SEEDS` list).
**Output:** five HTML documents, one per page name in `seed["pages"]`.
**Model:** `claude-opus-4-7` by default at default temperature.

### 4.1 Prompt structure

`prompts.SYSTEM_PROMPT` declares the hard rules every generated page must obey:

1. Complete, valid HTML5 document with `<!DOCTYPE html>` through `</html>`.
2. CSS inline in `<style>` only — no external stylesheets.
3. No `<script>`, no JavaScript.
4. No network resources — no Google Fonts, no CDN, no remote images.
5. System fonts only (`-apple-system`, `Helvetica`, `Georgia`, ...).
6. Image placeholders are colored `<div>`s, never `<img src=...>`.
7. All 5 pages share the same nav, footer, palette, typography.
8. Designed for 1280×800 viewport.

`prompts.build_user_prompt(seed, prior_errors=...)` formats the seed into the
per-task user message, including palette/type hints, constraints, and per-page
specs. On retry, the validator errors are appended verbatim.

### 4.2 Output format

Strict JSON, top-level keys = page names, values = full HTML documents as
strings. `call_llm()` strips any markdown fences the model may have added,
parses as JSON, and checks that the returned keys exactly match
`seed["page_specs"].keys()`.

`max_tokens=16000` is sized for the most content-dense tier-3 seeds (docs sites
with sidebars + tables + KPI cards). If a future tier blows this, bump it; the
SDK signals truncation via `stop_reason == "max_tokens"`, which we detect
explicitly so the failure mode reports as "output truncated" rather than the
misleading "Unterminated string in JSON" you'd get from parsing the truncated
buffer.

### 4.3 Validation and retry

Every page passes through `validate_html()`:
- HTML parser doesn't raise.
- Has `<body>`.
- No `<script>` tag.
- No `http(s)://` URLs in any attribute value.
- Length ≥ 200 bytes (catches "the model returned an empty string" failures).

Failures are batched per page and fed back as `prior_errors` on the next
attempt, with a per-page tag so the model knows which page broke. Up to 3
retries (controlled by `--max-retries`).

---

## 5. Stage 3 — packaging (`write_task()` in `generate_dataset.py`)

Once codegen succeeds, packaging is purely local file operations:

1. Create `<output-dir>/<seed.id>/`, removing any prior dir at that path.
2. Copy `templates/solution/` and `templates/tests/` verbatim.
3. Copy `templates/environment/{Dockerfile,make.py}` verbatim.
4. Write each generated page to `environment/reference-pages/<name>/index.html`.
5. Render `task.toml` from `templates/task.toml.tpl` with placeholders.
6. Render `instruction.md` from `templates/instruction.md.tpl`.
7. `chmod +x` the two shell scripts (`solve.sh`, `test.sh`).
8. Drop a `seed.json` sidecar so `relevance.py` can read the full seed later.

The `seed.json` sidecar is important: `task.toml` only retains tier/genre/
description, but the relevance judge needs palette, typography, and the per-
page specs to grade faithfully. The sidecar is the canonical record of
"what was this task supposed to be."

After all tasks finish, the orchestrator writes `registry.json` (a manifest)
and a `README.md` index summarizing the dataset.

---

## 6. Quality-gate stack

Four checkpoints, layered cheap-to-expensive. The first two run *inside* the
generator on every run; the last two are separate scripts you can run on a
generated dataset to filter or audit it.

| # | Checkpoint   | Where         | Cost  | Catches                                            |
|---|--------------|---------------|-------|----------------------------------------------------|
| 1 | Seed schema  | `concept_gen` | free  | Bad JSON, missing keys, tier/genre mismatch, page-name desync |
| 2 | HTML validity| `generate_dataset` | free  | Unparseable HTML, missing `<body>`, `<script>`, external URLs |
| 3 | Sanity       | `sanity.py`   | local Playwright | Blank renders, collapsed layouts, nav/footer drift across pages, background-color drift, tier-required structural elements (`<nav>`/`<footer>`/flex/grid) |
| 4 | Relevance    | `relevance.py`| 1 Sonnet vision call/page | Page doesn't match its spec, wrong palette/typography, hard constraints ignored |

Checkpoint 3 — sanity — is deterministic. It renders each page locally with
Playwright, screenshots it, runs JS instrumentation (`document.body.innerText`,
`querySelectorAll('nav')`, computed style probing) and asserts a small set of
thresholds (see constants at the top of `sanity.py`). It also runs cross-page
checks: nav labels must be identical across all 5 pages, footer text must
overlap in jaccard ≥ 0.8, background color must be within ΔE 12 in LAB space.
Tier 1 is exempt from nav/footer checks because tier-1 sites are explicitly
single-page-feeling.

Checkpoint 4 — relevance — is LLM-based. Each page screenshot + its seed spec
go to `claude-sonnet-4-6` with vision. The model returns five 1-5 Likert
scores: `matches_page_spec`, `matches_palette`, `matches_typography`,
`respects_constraints`, `overall_coherence`, plus a freeform `notes` field.
A page passes if every rubric is ≥ 3 and `overall_coherence` ≥ 4. A task
passes if every page passes. Cost: ~$0.01/page, ~$0.05/task.

`scripts/test_pipeline.sh` runs the whole stack against 3 freshly generated
tasks (one per tier) as a smoke test.

---

## 7. Tier and genre taxonomy (`seeds.py`)

Tiers are difficulty levels, defined in `TIERS: dict[int, TierSpec]`. Each tier
has a name, a description, and a `css_capabilities` list naming the CSS
features the agent is expected to use at that tier. Tiers 1-3 ship today:

- **Tier 1** — Static blocks: vertical stacks, basic typography, solid colors,
  single-column. Examples: minimal portfolio, simple restaurant menu, personal
  blog.
- **Tier 2** — Multi-page identity: 5 pages sharing nav/footer/palette,
  flexbox basics, simple grids. Examples: SaaS marketing, conference, mobile
  app landing.
- **Tier 3** — Real layout: multi-column, sidebars, sticky positioning,
  tables, dense data. Examples: docs site, ecommerce, admin dashboard.

The tier definitions are visible to the Stage-1 concept LLM (so it knows what
to constrain itself to) and the Stage-2 codegen LLM (indirectly, via the
constraints field in the seed).

Genres are an orthogonal axis defined in `GENRES: dict[int, list[str]]`. Each
tier has 5 genres. The synth pair-picker (`concept_gen.pick_tier_genre_pairs`)
cycles through tiers in the requested range; within a tier it samples genres
with replacement so `--synthesize 50` can generate multiple sites per
(tier, genre) cell.

### 7.1 Adding a new tier

1. Add an entry to `TIERS` with name, description, and `css_capabilities`.
2. Add 3-5 genres to `GENRES[<new tier>]`.
3. (Optional but recommended) Add 2-3 hand-written seeds to `SEEDS` at the new
   tier so `concept_gen` has same-tier few-shot examples.
4. Update tier-conditional logic in `sanity.py` if the new tier requires
   structural elements the current checks don't enforce.

The generator picks up the new tier automatically — no other changes.

---

## 8. Parallelism model

The generator runs two `ThreadPoolExecutor` pools sized to `--concurrency`:

- **Synth pool** (only with `--synthesize`): one Sonnet call per worker, each
  producing one seed.
- **Codegen pool**: one Opus call per worker, each producing 5 HTML pages.

Both pools share a single `Anthropic` client instance. The Python SDK is
thread-safe (it uses `httpx` underneath with connection pooling), so sharing
one client is correct and gives better connection reuse than one client per
worker.

The two pools are sequential — all seeds are synthesized first, then codegen
begins. They are not pipelined because:
- Synth is fast (~10 s/seed); codegen is slow (~30-60 s/seed). Pipelining
  would save only the first synth round-trip.
- Sequential makes failures easier to diagnose: if synth fails, we never spend
  codegen money.

Result order is stable: synth seeds are sorted by `id` after collection so
downstream task numbering is deterministic for a given `--synth-seed`.

### 8.1 Rate-limit guidance

| `--concurrency` | Use when |
|-----------------|----------|
| 4               | First-time setup, debugging, or org tier-1 API limits |
| 8 (default)     | Routine generation, single dev account |
| 16-32           | Tier-3/4 API limits, batch dataset builds |

If you hit HTTP 429, drop concurrency and retry; the generator doesn't have a
built-in backoff yet.

---

## 9. Extension points

The framework is designed so that adding new generation modes touches the
codegen layer, not the concept layer.

### 9.1 New tiers (4-8)
Append to `TIERS` and `GENRES`. No other change.

### 9.2 Animations
Three pieces need updating:
- `prompts.py SYSTEM_PROMPT` — relax the no-`<script>` and no-CSS-animation rule.
- `generate_dataset.py validate_html()` — allow `<script>` (or only allow CSS
  `@keyframes`, depending on scope).
- `templates/environment/make.py` and `templates/tests/score.py` — capture
  video instead of (or in addition to) a screenshot. The scoring rubric needs
  a motion-aware dimension; the simplest path is to hand the recorded video
  to a VLM judge (mirroring `relevance.py`).

The seed schema gains an `animation_spec` field describing the intended
motion in plain text; the codegen prompt is told to honor it.

### 9.3 React + Tailwind
The agent now produces a buildable project, not a single HTML file. Three
pieces need updating:
- A new codegen prompt that emits JSX + Tailwind classes.
- A new template set (`templates/react-tailwind/`) with a Dockerfile that
  installs Node + Vite + Tailwind, a `make.py` that runs `npm install &&
  npm run build` before rendering, and an `instruction.md` template that
  describes the project structure the agent should produce.
- `generate_dataset.py` learns a `--track` flag selecting which codegen +
  template pair to use.

The concept layer (`concept_gen.py`, `seeds.py`) is reusable as-is — palette,
typography, page specs, and constraints describe a site, not its
implementation.

---

## 10. File reference

| File | Role |
|------|------|
| `generate_dataset.py` | Orchestrator; CLI; codegen prompts + retries; packaging |
| `concept_gen.py`      | Stage-1 LLM seed synthesis; pair-picker; standalone CLI for debugging |
| `seeds.py`            | `TIERS`, `GENRES`, hardcoded `SEEDS`, schema validators |
| `prompts.py`          | Codegen system prompt + user prompt builder; viewport constant |
| `sanity.py`           | Deterministic post-generation render + DOM checks |
| `relevance.py`        | VLM judge scoring each page against its seed |
| `scripts/test_pipeline.sh` | End-to-end smoke test runner |
| `templates/`          | Files copied verbatim into each generated task |
| `templates/task.toml.tpl`, `templates/instruction.md.tpl` | Rendered with placeholder substitution |
