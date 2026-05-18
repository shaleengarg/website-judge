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

Fully synthetic. Every seed is invented by the concept LLM on demand — there
is no hand-written seed list.

```
                  (tier, genre) pairs
                  picked by shuffle-bag
                  sampler (per tier)
                       │
                       ▼
            ┌──────────────────────┐
            │ concept_gen.py       │  Stage 1: Sonnet
            │  Seed JSON           │  T=0.95, 1 call/seed
            │  (parallel)          │
            └──────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │ generate_dataset.py  │  Stage 2: Opus
            │  call_llm_one_page() │  per-page parallel codegen
            │  5 HTML pages        │  per-page retry loop
            │  (5 calls per seed)  │  (up to --max-retries)
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
portfolios with the same nav layout. We observed this directly and split the
stages for two reasons:

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
- An explicit anti-laziness instruction ("NEVER use Lorem ipsum or generic
  filler", "Brand name should be evocative, not descriptive").

Note: there is no hand-written seed library to draw few-shot examples from.
The prompt relies on the schema + tier description + `css_capabilities` list
+ the genre name to constrain output. If concept quality at a new tier is
poor, the lever is the tier description and capabilities list (in
`seeds.py:TIERS`) — make them more prescriptive before reaching for
prompt-engineering elsewhere.

### 3.3 Validation and retry

`_validate_seed_shape()` checks the parsed JSON against the schema:
- All required keys present, all of correct type.
- `tier` matches the requested tier, `genre` matches the requested genre.
- Exactly 5 page names, all non-empty strings.
- `page_specs.keys()` exactly matches `pages` (same order, same names) —
  this invariant is load-bearing downstream: codegen iterates page_specs to
  spawn per-page calls, and `score.py` iterates `reference-pages/*`.
- `constraints` has at least 3 items.
- Free-text fields (`palette_hint`, `type_style`, `description`) non-empty.

Up to 3 retries. On retry, prior errors are appended to the user prompt so the
model gets a concrete fix-list rather than generic "try again" feedback.

### 3.4 ID assignment

The ID returned by Sonnet is sanitized and **always** prefixed with
`synth-t{tier}-` plus a 4-hex-char UUID suffix. Example:
`synth-t2-saas-marketing-3b9f`. Two properties matter:

- The `synth-` prefix tags every task as LLM-generated (every task is, today —
  the prefix is reserved for future hand-curated or imported tasks should we
  ever add them).
- The UUID suffix prevents collisions when the model reuses a brand name across
  runs (it does this more than you'd think).

---

## 4. Stage 2 — HTML/CSS codegen (`generate_dataset.py` + `prompts.py`)

**Input:** a `Seed` dict (from Stage 1 or from the hardcoded `SEEDS` list).
**Output:** five HTML documents, one per page name in `seed["pages"]`.
**Model:** `claude-opus-4-7` by default at default temperature.
**Call shape:** one LLM call per page (5 per seed), running in parallel.

### 4.1 Why one call per page

An earlier design asked for all 5 pages in a single JSON response keyed by
page name. On tier-3 seeds (sidebar nav + tables + KPI grids), the combined
output blew past `max_tokens=16000` and the run failed with truncation
errors that no amount of retry could fix — every retry produced the same
oversized output.

Splitting into 5 per-page calls gives each page its own 16k-token budget
(80k total per seed), runs them concurrently for similar wall-clock, and
turns "1 of 5 pages broke" from a whole-task failure into a single-page
retry. The tradeoff is that the model no longer sees the other 4 pages
while generating each one, so cross-page consistency (nav labels, footer
text, palette adherence) has to come from the seed's `constraints` and
`palette_hint` being prescriptive enough. `sanity.py` catches drift after
the fact.

The next step up — generating a shared layout (nav + footer + CSS) in a
single call up front and injecting it verbatim into each per-page prompt —
is the right answer for production but a larger refactor; see §9 for the
extension path.

### 4.2 Prompt structure

`prompts.SYSTEM_PROMPT` declares the hard rules every generated page must obey:

1. Complete, valid HTML5 document with `<!DOCTYPE html>` through `</html>`.
2. CSS inline in `<style>` only — no external stylesheets.
3. No `<script>`, no JavaScript.
4. No network resources — no Google Fonts, no CDN, no remote images.
5. System fonts only (`-apple-system`, `Helvetica`, `Georgia`, ...).
6. Image placeholders are colored `<div>`s, never `<img src=...>`.
7. The page shares nav/footer/palette/typography with the rest of the site;
   the constraints + hints are the source of truth (do not improvise).
8. Designed for 1280×800 viewport.

`prompts.build_page_prompt(seed, page_name, prior_errors=...)` formats the
prompt for one specific page. It includes:
- The full site identity (description, palette, typography, all constraints).
- The full list of page names in nav order (so the model knows the nav scope).
- Brief specs for the OTHER pages as context (so the model can keep nav and
  footer consistent with what the other calls will produce).
- The current page's spec as the explicit generation target.
- On retry, the validator errors for *this page* appended verbatim.

### 4.3 Output format

Raw HTML — no JSON wrapper, no fences, no preamble. `call_llm_one_page()`
strips any markdown fences the model snuck in and checks the response starts
with `<`. Truncation is caught explicitly via `stop_reason == "max_tokens"`
so the failure mode reports as "output truncated" rather than a downstream
HTML parser error.

### 4.4 Validation and retry

Every page passes through `validate_html()`:
- HTML parser doesn't raise.
- Has `<body>`.
- No `<script>` tag.
- No `http(s)://` URLs in any attribute value.
- Length ≥ 200 bytes (catches "the model returned an empty string" failures).

Each page has its own retry loop (up to `--max-retries`). On retry the
errors for that specific page are appended to its next prompt. A page that
exhausts retries kills the whole task — the orchestrator cancels the
remaining in-flight page calls and propagates the failure, since a missing
page makes the task unusable.

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
`querySelectorAll('nav')`, computed-style probing for gradients/shadows/
font-sizes/font-weights, `<form>`/`<input>`/`<table>`/`<svg>` counts) and
asserts a small set of thresholds (see constants at the top of `sanity.py`).

Render-level checks: screenshot not blank, visible text length, page height
in `[400, 20000]` px.

Tier-conditional structural checks (each tier inherits the lower-tier ones):
- Tier 1+: ≥1 heading, ≥1 paragraph
- Tier 2+: `<nav>` and `<footer>` landmarks present
- Tier 3+: ≥2 flex/grid layout containers
- Tier 4+: at least one gradient or non-trivial box-shadow
- Tier 5+: ≥3 distinct font-sizes OR ≥2 distinct font-weights
- Tier 6+: a `<form>`, a `<table>`, or ≥4 inputs
- Tier 7+: ≥1 inline `<svg>` with drawable content
- Tier 8+: ≥3 distinct flex/grid layout containers

Cross-page checks (tier 2+): nav labels identical across all 5 pages,
footer text overlap ≥ 80% in jaccard, background color within ΔE 12 in LAB
space.

Tier 1 is exempt from nav/footer and cross-page checks because tier-1
sites are explicitly single-page-feeling.

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

Tiers are difficulty levels, defined in `TIERS: dict[int, TierSpec]`. Each
tier has a name, a description, and a `css_capabilities` list naming the
CSS features the agent is expected to use. Tier 9 additionally carries
`requires_motion: True` to mark that it needs harness extensions beyond
the static-screenshot path.

| Tier | Name | Defining capability |
|------|------|---------------------|
| 1 | Static blocks | Vertical stacks, solid colors, basic typography |
| 2 | Multi-page identity | Shared nav/footer/palette, flexbox basics, simple grids |
| 3 | Real layout | Multi-column, sidebars, sticky positioning, tables |
| 4 | Visual polish | Gradients, box-shadow elevation, decorative pseudo-elements |
| 5 | Custom typography | Coherent type scale, multiple weights, drop caps |
| 6 | Forms and data-heavy | Styled inputs, dense tables, multi-column forms |
| 7 | Inline SVG and shapes | Inline `<svg>`, clip-path, transforms, masking |
| 8 | Mixed visual systems | Magazine-style assemblies of heterogeneous sections |
| 9 | Animations | **Gated** — taxonomy in place, codegen needs the motion harness |

Tier definitions are read by the Stage-1 concept LLM (it sees the description
and `css_capabilities` and chooses constraints accordingly) and by
`sanity.py` (which applies tier-conditional structural checks).

Genres live in `GENRES: dict[int, list[str]]` — 5 genres per tier. The synth
pair-picker (`concept_gen.pick_tier_genre_pairs`) uses two patterns:

- **Tier selection: round-robin.** `tiers[i % len(tiers)]`. For N picks across
  K tiers you get `N/K` (rounded) per tier; the lower tiers get the extras
  when N is not divisible by K.
- **Genre selection within a tier: shuffle-bag (deck).** A shuffled deck of
  the tier's genres is dealt one at a time; when empty, it reshuffles. Over
  K picks at a tier with G genres you get `floor(K/G)` complete cycles plus
  a partial — no genre repeats until every other genre at that tier has been
  used at least as many times.

Both are deterministic given `--synth-seed`.

### 7.1 Tier gating

`tier_range()` excludes tiers with `requires_motion=True`. The CLI default
`--tier-max` therefore stops at the highest static tier. Asking for
`--tier-max 9` explicitly hits a `sys.exit` with a clear "motion harness not
yet implemented" message — the gate is at the orchestrator entry point.

### 7.2 Adding a new tier

1. Add an entry to `TIERS` with name, description, and `css_capabilities`.
   If the tier needs harness changes (motion, video, build step), add
   `requires_motion=True` (or invent a new flag).
2. Add 5 genres to `GENRES[<new tier>]`.
3. Add a tier-conditional check to `sanity.py:_check_page_structure` that
   tests for the new tier's signature feature (e.g. tier 7 requires an
   inline `<svg>`).
4. If the new tier is gated (like 9), the existing `is_motion_tier` check
   in `generate_dataset.py` will pick it up automatically and refuse to
   generate it. Otherwise no further wiring is needed.

`concept_gen.py` and `prompts.py` read tier info via `TIERS[tier]`, so they
pick up new tiers without change.

---

## 8. Parallelism model

The generator runs three `ThreadPoolExecutor` pools at two levels:

- **Synth pool**: outer pool sized to `--concurrency`, one Sonnet call per
  worker, each producing one seed.
- **Codegen outer pool**: sized to `--concurrency`, one worker per seed.
  A worker's job is to produce all 5 pages of its seed, write the task dir,
  and return the manifest entry.
- **Codegen inner pool** (one per outer worker): sized to 5, one worker per
  page. Each runs an independent retry loop and returns the HTML for that
  page.

All pools share a single `Anthropic` client instance. The Python SDK is
thread-safe (it uses `httpx` underneath with connection pooling), so sharing
one client is correct and gives better connection reuse than one client per
worker.

The synth stage and the codegen stage are sequential — all seeds are
synthesized first, then codegen begins. Not pipelined because:
- Synth is fast (~10 s/seed); codegen is slow (~30-60 s/seed). Pipelining
  would save only the first synth round-trip.
- Sequential makes failures easier to diagnose: if synth fails, we never spend
  codegen money.

Result order is stable: synth seeds are sorted by `id` after collection so
downstream task numbering is deterministic for a given `--synth-seed`.

### 8.1 Concurrency math and rate-limit guidance

With `--concurrency N`, the worst-case in-flight call count is **5N** during
codegen (N seeds × 5 pages each). With the default `N=8` that's up to 40
concurrent Anthropic calls; with `N=16` it's 80. The previous (whole-site)
design held at exactly N in-flight, so per-page codegen is 5× more
concurrency-hungry for the same `--concurrency` setting.

| `--concurrency` | Peak in-flight | Use when |
|-----------------|----------------|----------|
| 4               | 20             | First-time setup, debugging, org tier-1 API limits |
| 8 (default)     | 40             | Routine generation, single dev account |
| 16              | 80             | Tier-3/4 API limits, batch dataset builds |
| 32              | 160            | Only with tier-4 API limits and a high concurrent-request quota |

If you hit HTTP 429, drop `--concurrency` and retry — there's no built-in
backoff yet.

---

## 9. Extension points

The framework is designed so that adding new generation modes touches the
codegen and harness layers, not the concept layer.

### 9.1 New static tiers (beyond 8)

Append to `TIERS` with name + description + `css_capabilities`. Add 5 genres
to `GENRES[<new tier>]`. Add a tier-conditional check to
`sanity.py:_check_page_structure` testing for the new tier's signature
feature. No other changes — concept_gen reads from `TIERS[tier]`, codegen
doesn't care about tier numbers, and the relevance judge gets the constraints
from the seed regardless.

### 9.2 Tier 9 — Animations

Taxonomy is in place: `TIERS[9]` has `requires_motion=True`, `GENRES[9]`
lists 5 motion-oriented categories, and the orchestrator refuses to generate
tier 9 with a clear "not yet implemented" message. To enable generation, the
following changes are needed:

**Concept layer:**
- Add `expected_animations: list[AnimationSpec]` to the Seed schema, where
  `AnimationSpec` has `id`, `target_description`, `kind` (`loop|entrance`),
  `duration_ms`, `description`. Add `motion_style` to the seed
  (`none|subtle|playful|dramatic`).
- Update `concept_gen.py` to emit these fields for tier 9.

**Codegen layer:**
- Carve `prompts.py:SYSTEM_PROMPT` rule 3 into a constant; tier 9 overrides
  it to allow `<script>` *only* for driving autonomous animations (no click,
  hover, or scroll handlers).
- Add per-`AnimationSpec` hook instructions (`data-anim="{id}"`) so the
  capture step can find each animated element.

**Harness extensions:**
- `templates/environment/make.py` and `templates/tests/score.py` gain a
  `capture_motion()` path that uses Playwright's `page.clock.install()` to
  virtualize JS time, then samples the page at controlled `fast_forward`
  offsets to produce a 3×2 stitched frame-grid PNG per animation.
- New `relevance` dimension (or a separate `motion_judge.py`) feeds the
  ground-truth + agent frame grids to Opus with Likert criteria for motion
  presence, target element, visual character, and overall fidelity.

The static path is unchanged because tier 9 lives in its own gated branch.
Static tiers (1-8) keep using the existing screenshot harness verbatim.

### 9.3 React + Tailwind

The agent produces a buildable project, not a single HTML file. Three
pieces need updating:

- A new codegen prompt that emits JSX + Tailwind classes instead of inline-CSS HTML.
- A new template set (`templates/react-tailwind/`) with a Dockerfile that
  installs Node + Vite + Tailwind, a `make.py` that runs `npm install && npm
  run build` before rendering, and an `instruction.md` template describing
  the project structure the agent should produce.
- `generate_dataset.py` learns a `--track` flag selecting which codegen +
  template pair to use.

The concept layer (`concept_gen.py`, `seeds.py`) is reusable as-is — palette,
typography, page specs, and constraints describe a site, not its
implementation.

---

## 10. File reference

| File | Role |
|------|------|
| `generate_dataset.py` | Orchestrator; CLI; per-page codegen with retries; packaging |
| `concept_gen.py`      | Stage-1 LLM seed synthesis; shuffle-bag tier/genre pair-picker; standalone CLI for debugging |
| `seeds.py`            | `TIERS`, `GENRES`, `Seed` TypedDict (schema), `tier_range()`, `is_motion_tier()` |
| `prompts.py`          | Codegen system prompt + per-page user prompt builder; viewport constant |
| `sanity.py`           | Deterministic post-generation render + DOM checks |
| `relevance.py`        | VLM judge scoring each page against its seed |
| `scripts/test_pipeline.sh` | End-to-end smoke test runner |
| `templates/`          | Files copied verbatim into each generated task |
| `templates/task.toml.tpl`, `templates/instruction.md.tpl` | Rendered with placeholder substitution |
