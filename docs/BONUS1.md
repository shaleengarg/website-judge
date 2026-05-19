# Bonus 1 — Animations

How `generator/` was extended to produce, capture, and grade animated
websites (tier 9). This document describes the as-built pipeline, the
design decisions behind it, and the empirical results from the oracle
calibration runs.

For the static-site pipeline this builds on, see
[ARCHITECTURE.md](ARCHITECTURE.md). For the static scoring stack the motion
judge shares plumbing with, see [SCORING.md](SCORING.md).

---

## 1. Problem and scope

The static benchmark grades a single full-page screenshot per viewport. A
benchmark for animated sites has to grade something the agent does *over
time* — a hero stagger, a marquee, an ambient orb drift — using a vision
API that consumes still images, not video.

Three deliberate narrowings make the problem tractable:

1. **CSS-only motion.** `@keyframes` + `animation-*` only. No `<script>`,
   no JS-driven animations. The codegen system prompt's script ban from
   tiers 1–8 carries through to tier 9 unchanged. This sidesteps an entire
   class of "agent wrote interaction-driven behavior" failures that would
   need source-side detection.
2. **Autonomous motion only.** Continuous loops and on-load entrance
   animations. No `:hover`, `:focus`, `:active`, `:checked`, no
   scroll-linked triggers. The grader looks at a passive page; if it has
   to interact to trigger something, it's out of scope.
3. **Hard 5-second cap per animation.** Every animation must complete one
   full cycle (loop) or full settle (entrance) within 5000ms. This bounds
   the capture window so six equidistant frames span visible motion
   instead of leaving 28-second marquees with 27.5 seconds of identical
   frames.

These come from
[seeds.py:TIERS[9]](../generator/seeds.py) and are enforced by the
concept-stage validator at
[concept_gen.py:_validate_motion_fields()](../generator/concept_gen.py).

---

## 2. Approach: clock virtualization + frame-grid PNG

The capture-and-grade strategy in three sentences:

> Use Playwright's `page.clock` API to virtualize the document timeline so
> CSS animations advance deterministically under our control, not the
> wall clock. Sample six equidistant frames across each page's animation
> window. Stitch the frames into a labeled 2×3 grid PNG and send that
> single image to a multimodal judge.

Why a stitched grid and not a video, GIF, or sequence of image blocks:

- **The Anthropic Messages API does not document video as a supported
  input.** The
  [vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)
  list the supported formats as: "Claude currently supports JPEG, PNG,
  GIF, and WebP image formats, specifically: `image/jpeg`, `image/png`,
  `image/gif`, `image/webp`." Video MIME types are not on that list. The
  vision page also never mentions "video." A FAQ on the same page states
  "Claude is an image understanding model only. It can interpret and
  analyze images, but it cannot generate, produce, edit, manipulate, or
  create images." The
  [Files API docs](https://platform.claude.com/docs/en/build-with-claude/files)
  list the file-type-to-content-block mapping as PDF → `document`, plain
  text → `document`, images (`image/{jpeg,png,gif,webp}`) → `image`, and
  datasets → `container_upload` (code-execution tool only). Video is not
  in that table either. Strictly speaking, the docs do not explicitly
  forbid video — they list what's supported and video is absent. Either
  way, there is no documented path to send a `video/mp4` content block
  to the model.
- Animated GIFs are not a workaround. The same vision page states:
  "Animations are unsupported, and only the first frame will be used."
- One grid per (page, viewport) keeps the per-page judge token budget
  identical to the existing static path (six image blocks per page) — no
  ensemble cost regression for motion tasks.
- A single image block preserves the existing `JUDGE_IMAGE_MAX_DIM` ceiling
  and the existing judge-prompt structure. The only new bit is a system-
  prompt sentence telling the model "each image is a 2×3 grid; read
  left-to-right, top-to-bottom; timestamps are burned onto each tile."

The static screenshot for a tier-9 page is captured under
`prefers-reduced-motion: reduce` so the existing deterministic V2.1
aspects (palette, layout skeleton, text content) still have a meaningful
settled-state baseline to compare against. Motion grading and static
deterministic grading are then two parallel paths whose results combine
into the page's reward.

---

## 3. End-to-end flow

```text
                        ┌─────────────────────────────────────┐
 concept_gen.py (Sonnet)│ Seed JSON +                         │
 ────────────────────── ▶ motion_style + expected_animations  │
                        │ (per page: 1-3 anims, both kinds)   │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
 prompts.SHARED_CSS     │ Shared CSS with all @keyframes +    │
 + per-page HTML (Opus) │ prefers-reduced-motion block +      │
 ────────────────────── ▶ per-page HTML with data-anim hooks  │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
 generate_dataset.py    │ Task dir + environment/motion.json  │
 ────────────────────── ▶ sidecar with per-page frame windows │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
 Docker build           │ make.py + _motion_capture.py:       │
 (make.py runs at       │   - reduced-motion .png baseline    │
 build time)            │   - 6-frame grid <page>.motion.png  │
                        │     (per page × viewport)           │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
 Agent solves the task  │ Writes /app/output/<page>/index.html│
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
 score.py               │ For each page (motion mode):        │
                        │  1. Capture agent motion grid       │
                        │     (same code path as ref)         │
                        │  2. Pre-flight pixel diff           │
                        │  3. Agent-source primitive scan     │
                        │  4. Motion judge ensemble (Opus)    │
                        │  5. Combine: pre-flight lifts +     │
                        │     source-scan multiplicative      │
                        │     factor + likert mean            │
                        └─────────────────────────────────────┘
```

---

## 4. Concept layer

[concept_gen.py](../generator/concept_gen.py) was extended with a tier-9
branch in the user prompt that asks Sonnet to emit two new top-level seed
fields:

- `motion_style: subtle | playful | dramatic` — overall feel.
- `expected_animations: {page_name: [AnimationSpec, ...]}` keyed by every
  page name, 1-3 animations per page, every page including at least one
  `entrance` and one `loop`.

```python
class AnimationSpec(TypedDict):
    id: str                # kebab-case, becomes data-anim="<id>" + grader id
    target_description: str
    kind: Literal["entrance", "loop"]
    duration_ms: int       # 200..5000 — bounded so the capture window stays tight
    description: str
```

[concept_gen.py:_validate_motion_fields()](../generator/concept_gen.py)
enforces every constraint on the output before the seed is accepted:
keys match `pages`, 1-3 anims per page, both kinds present, ids unique
within a page, duration in [200, 5000].

The motion brief in the prompt is injected only for motion tiers via
`is_motion_tier()`, so static-tier seed generation is byte-identical to
the pre-bonus pipeline.

---

## 5. Codegen layer

[prompts.py](../generator/prompts.py) was extended in two places:

- **Shared-CSS prompt** (`SHARED_CSS_SYSTEM_PROMPT` + the
  `_motion_brief_for_shared_css` helper). When the seed carries
  `expected_animations`, the prompt lists every animation id grouped by
  page and instructs the model to:
  - Define every `@keyframes` rule by name.
  - Use only `transform`, `opacity`, `filter`, `background-position`, and
    similar GPU-friendly animatable properties.
  - Include a `@media (prefers-reduced-motion: reduce)` block that
    disables every animation and forces settled final states.

- **Per-page prompt** (`build_page_prompt` + `_motion_brief_for_page`).
  For each page, the prompt lists the specific animations that page must
  implement (id, target, kind, duration, description) and tells the
  model to pin `data-anim="<id>"` on each animated element. The `<script>`
  ban stays in place.

[generate_dataset.py:validate_html()](../generator/generate_dataset.py)
takes an `expected_anim_ids` argument and rejects pages missing any
expected `data-anim` attribute. The existing `validate_shared_css` got
`require_keyframes` and `require_prefers_reduced_motion` flags that
fire only for motion seeds. Validation failures retry per-page like the
static path, and we did see them fire in practice — the oracle seed had
one page miss `data-anim="star-field-twinkle"` on attempt 1 and got it
right on retry, exactly the failure mode the validator was added to
catch.

---

## 6. Capture: deterministic frames via virtualized clock

[_motion_capture.py](../generator/templates/environment/_motion_capture.py)
is the heart of the bonus. It owns two operations:

### `capture_motion_grid(browser, html_path, viewport, frame_window_ms, out_path)`

1. Create a Playwright context at the requested viewport.
2. `context.clock.install(time=0)` *before* `page.goto()`. The clock is
   installed as paused at t=0; the page never sees the real wall clock.
   This virtualizes `Date.now`, `performance.now`, `setTimeout`,
   `setInterval`, `requestAnimationFrame`, and the CSS animation
   timeline together.
3. Navigate. CSS animations are set up but haven't ticked.
4. For each offset in `_frame_offsets(window_ms)`:
   - `context.clock.fast_forward(delta_ms)` advances the fake clock,
     running pending timers and animation frames.
   - Screenshot the viewport (NOT full-page — grids stay viewport-sized
     to fit under `JUDGE_IMAGE_MAX_DIM`).
5. PIL composites the six frames into a 2×3 grid PNG with a black header
   band on each tile showing `frame N/6 · t = X ms`. Labels matter: the
   judge can't infer temporal order from layout alone.

Offsets are equidistant across `[0, max(window_ms, MIN_FRAME_WINDOW_MS)]`.
Equidistant sampling works because concept-stage validation caps every
animation at 5000ms total cycle, so the window is always tight enough
for visible motion changes to span six tiles.

The window itself is computed seed-side in
[generate_dataset.py:build_motion_sidecar()](../generator/generate_dataset.py):

```python
window = clamp(max(durations) + 300, 1500, 5500)
```

This lands in `environment/motion.json`, baked into the Docker build
context, read by both `make.py` (build-time references) and `score.py`
(verifier-time agent grids).

### `capture_reduced_motion_static(browser, html_path, viewport, out_path)`

Captures one full-page screenshot under `prefers-reduced-motion: reduce`.
This is the per-page `.png` baseline that the existing V2.1 deterministic
aspects can compare against. The reduced-motion media query in the
shared CSS collapses every animation to its settled final state, so this
baseline matches across ref and agent regardless of where the animation
clock happens to be.

### Docker integration

[Dockerfile](../generator/templates/environment/Dockerfile) copies
`motion.json` into `/opt/motion.json` and `_motion_capture.py` into
`/opt/_motion_capture.py` — the helper persists past build time so
`score.py` can re-use the same code path to capture agent grids at
verifier time. Both `make.py` (build) and `score.py` (verify) splice
`/opt` onto `sys.path` to import it.

`make.py` branches on the presence of `expected_animations` in
`motion.json`. For static tasks: unchanged. For motion tasks: each (page,
viewport) gets BOTH the reduced-motion `.png` baseline AND the
`<page>.motion.png` frame grid, side by side under
`/app/references/<viewport>/`.

---

## 7. Scoring: motion judge + pre-flight pixel diff + source scan

[score.py](../generator/templates/tests/score.py) detects motion mode by
reading `/opt/motion.json`. When `expected_animations` is non-empty:

- The static V2.1 deterministic block is *skipped* per page (single-frame
  metrics on animated pages produce noise — SSIM at frame 1 vs settled
  frame 6 is meaningless).
- The judge ensemble is called with `MOTION_JUDGE_CRITERIA` instead of
  the static `JUDGE_CRITERIA`, and `motion=True` adds a sentence to the
  system prompt explaining how to read a 2×3 timestamped grid.

### Motion judge criteria

Six Likert-5 questions sent to Claude Opus 4.7:

| Criterion | What it asks |
|-----------|--------------|
| `motion_presence` | How much visible motion across the six frames? Partial credit fine for subtle/localized motion. |
| `target_element` | Does motion happen on the same elements as the reference? |
| `motion_character` | Is the *kind* of motion (translate / fade / scale / rotate / drift) the same? |
| `timing_fidelity` | Does the pace of motion across frames 1-6 match? |
| `settled_state` | Does the last tile of the agent grid match the last tile of the reference? |
| `overall_motion_fidelity` | Holistic judgment — would a motion designer accept it? |

Ensemble of 3 calls per page, median for Likert (majority vote for binary).
All criteria are Likert — there is no binary in the motion judge, after
calibration showed binary `motion_presence` was the dominant source of
zero-credit cascades on subtle-motion pages.

### Pre-flight pixel diff

Before the judge runs, [score.py:measure_grid_motion()](../generator/templates/tests/score.py)
splits the agent grid back into six tiles and computes the fraction of
pixels in each non-zero tile whose RGB delta vs. tile 0 exceeds 30/255.

This pre-flight result is used in exactly one direction: to *lift* the
judge's `motion_presence` when pixel evidence contradicts a low score.
Specifically, when `judge.motion_presence < 0.5` AND
`pixel_change > MOTION_PIXEL_CHANGE_CREDIT_THRESHOLD (0.5%)`, the
aggregated `motion_presence` is floored at 0.5 (Likert-3 equivalent),
and the page's mean across criteria is recomputed.

The asymmetry is deliberate. An earlier iteration tried to *also* clamp
motion_presence DOWN when pixel change was below a threshold; that
penalized legitimately animated pages like a rotating ring (0.7% pixel
change) where the judge correctly identified perfect motion. Empirically,
pixel-change percentage doesn't predict judge perception — it just
provides a clean positive signal for "motion is definitely present here."
So we trust the judge downward and correct it upward.

### Agent-source motion-primitive scan

[score.py:scan_agent_motion_primitives()](../generator/templates/tests/score.py)
greps the agent's HTML and shared CSS for `@keyframes`, `animation:`,
`animation-name:`, and for `data-anim="<expected_id>"` attributes
matching the per-page expectations.

The result becomes a multiplicative `source_factor`:

- No `@keyframes` AND no `animation:` declarations → factor 0.3
- Some primitives but missing some `data-anim` ids → factor `0.5 + 0.5 * coverage`
- All expected ids wired → factor 1.0

This isolates "agent forgot to animate at all" from VLM judgment.
Cheaper, more diagnostic, and decoupled from the judge's noise floor.

### Per-page reward

```text
preflight    = mean(per-viewport pixel-change %) on agent grids
adjusted     = mean over criteria, with motion_presence lifted to 0.5
                when preflight > threshold and judge was low
source_factor = scan-based multiplicative penalty
final_score   = clamp(adjusted * source_factor, 0, 1)
```

Per-task reward is the mean of per-page final scores.

---

## 8. Empirical calibration

The oracle was run three times on the same generated task
(`synth-t9-solaris-drift-observatory-c75e`, 5 pages, 12 animations
total). Each row is a single oracle trial through Modal — same image,
same input HTML, only the score.py logic differs.

| Run | What changed | Reward |
|-----|--------------|--------|
| v1 — baseline | Likert-only judge, no pre-flight, no source scan | **0.733** |
| v2 — over-clamped pre-flight | Auto-fail to 0 when pixel < 1%, auto-credit to 0.5 when pixel > 1.5% | **0.700** ← worse |
| v3 — credit-only pre-flight + source scan | Drop auto-fail, lower auto-credit threshold to 0.5%, add source-scan multiplier | **0.808** |

The v1 → v3 lift came from three sources:

- Likert-5 `motion_presence` (replacing a binary 0/1) lets subtle motion
  earn 3 (=0.5) instead of being forced to 0.
- Pre-flight auto-credit caught `expeditions`, where the judge said "no
  motion" but pixel diff showed 0.9% change. Floor of 0.5 broke the
  zero cascade across the other criteria.
- Source-scan factor of 1.0 confirmed every oracle page wired all
  expected `data-anim` ids and had `@keyframes` — no penalty, but the
  signal would have surfaced clearly if the agent had skipped animations.

The v1 → v2 regression is instructive. Auto-failing motion_presence to 0
when pixel change < 1% punished `constellations` (0.36% change, judge
correctly saw subtle motion at Likert 3) and `instruments` (0.73%
change, judge correctly saw the rotating ring at Likert 5). Pixel
change does NOT predict judge perception — a tight rotation in a small
area can read as obvious motion even when total pixel delta is sub-1%.
Conclusion: pre-flight is a one-way correction, never a downward clamp.

---

## 9. Methods attempted, what they tried to solve, and why they were rejected

The current design is the third iteration. Earlier attempts and the
specific failure modes that pushed each one out are recorded here so the
trade-offs are explicit.

### 9.1 Capture format

| Method | What was tried | Why it was rejected |
|--------|---------------|---------------------|
| Native MP4 / WebM to the judge | Send a Playwright-recorded video file as a content block | Anthropic docs list supported vision inputs as `image/{jpeg,png,gif,webp}` only; no `video` content block is documented and the Files API doesn't list video MIME types. The docs don't explicitly forbid video — video is just absent from every supported-type list — but there is no documented path to send one. See §2 for the verbatim quotes. |
| Animated GIF as one image block | Single `image/gif` content block carrying the animation | Anthropic docs: "Animations are unsupported, and only the first frame will be used." The model would see a single frame regardless of what we sent. Dead end. |
| N individual image blocks per page | Six labeled `image/png` blocks, one per frame, sent in temporal order | ~6× the token budget per page vs. one stitched grid. The model gets the same information either way — the labeled-grid format gives temporal context cheaper. Rejected for cost, not capability. |
| Frame-grid PNG (chosen) | One 2×3 PNG per (page, viewport) with timestamps burned onto each tile | Matches the existing per-page judge token budget exactly, no protocol change. |

### 9.2 Frame sampling schedule

| Method | What was tried | Why it was rejected |
|--------|---------------|---------------------|
| Linear, tight window | `[0, T/5, 2T/5, …, T]` where T = `max(duration) + 200ms` | The user's first visual review surfaced the problem: when T was small (1500–2000ms), every animation had finished by frame 3 and tiles 4–6 collapsed into near-identical settled-state snapshots. The grid wasted half its tiles. |
| Power-curve, wider window | `t_i = window * (i/(N-1))^p` with `p=2.0` and window in [4000, 8000]ms. Goal: cluster frames around entrance progressions, spread across loop phases | User-rejected. Spec'd the constraint cleanly: "make the animations finish in some seconds and then capture 6 equidistant screenshots." Non-uniform spacing made tile-to-tile reading confusing — the judge had to interpret unequal gaps from timestamps rather than trusting visual position. |
| Equidistant, bounded by generator (chosen) | `[0, T/5, 2T/5, …, T]` with T = `clamp(max(duration) + 300ms, 1500, 5500)`. Generator-side validation caps every animation at 5000ms total cycle. | Pushes the "no tile wastage" problem upstream into the seed, where it belongs. The judge gets a predictable uniform schedule it can rely on. |

### 9.3 Animation duration policy

| Method | What was tried | Why it was rejected |
|--------|---------------|---------------------|
| No cap | Concept LLM was originally asked for "natural" durations — marquees at 28s, ambient drifts at 12s | The first hand-built demo (`generator/examples/tier9-hero/index.html`) used these realistic durations. The frame grid then captured 6 frames across a 28s marquee window, leaving all entrance motion squashed into tile 1. |
| Wide cap (15s) | First draft of the validator allowed `duration_ms ∈ [200, 15000]` | Half-measure. A 15s marquee still produces a grid where most tiles look identical. |
| Hard cap at 5s (chosen) | `duration_ms ∈ [200, 5000]`, validator-enforced. Prose constraint in the user-prompt tells the LLM that slow loops "remain visually slow to the human eye while becoming legible across the grid." | A 5s window puts six frames at ~1s intervals, which is roughly the cadence at which motion is visible at a glance in static frames. |

### 9.4 Motion judge criteria

| Method | What was tried | Why it was rejected |
|--------|---------------|---------------------|
| Binary `motion_presence` (yes/no) | "Does the agent's grid show any visible motion? 1=yes, 0=no" | The v1 oracle hit 0.733 because subtle but legitimate motion (a finished-by-frame-2 entrance, a localized orb breathe) got [0, 0, 0] votes from the ensemble. Binary scoring forced the judge to commit on borderline cases, and "borderline" became "no" too often. Worse, a `motion_presence=0` vote cascaded — once the judge declared no motion, the comparison criteria (target_element, motion_character, timing) collapsed to 1 as well, since they implicitly depend on motion being visible. |
| Likert-5 `motion_presence` (chosen) | "How much visible motion? 5=clear multi-element; 3=subtle/single-area; 1=static" | Gives the judge a "subtle but visible" slot. Ensemble medians on borderline cases now sit at 3 (=0.5) instead of being forced to 0 or 1. |
| Drop motion_presence entirely, rely on comparison criteria | Idea: target_element / motion_character already capture motion presence indirectly | The cascade problem is real: when the judge sees no motion in the agent grid, every comparison criterion bottoms out. We need an explicit "is there motion at all" question to localize the failure mode in the breakdown. Kept. |

### 9.5 Pre-flight pixel diff

| Method | What was tried | Why it was rejected |
|--------|---------------|---------------------|
| Two-way clamps (v2) | Auto-fail `motion_presence` to 0 when `pixel_change < 1%`; auto-credit to 0.5 when `pixel_change > 1.5%`. Reasoning: bound the judge in both directions using objective pixel evidence | Oracle reward dropped from 0.733 → 0.700. Auto-fail punished `constellations` (0.36% pixel change but the judge correctly read subtle motion at Likert 3) and `instruments` (0.73% but the judge saw perfect rotation at Likert 5). Empirically: a tight rotating ring or localized scale animation can be high-information motion at low pixel-ratio. Pixel-change percentage does NOT predict judge perception. |
| Auto-credit only (chosen) | Lift `motion_presence` to 0.5 when `pixel_change > 0.5%` AND the judge gave it < 0.5; never clamp downward | One-way correction. The judge is trusted when it says "I see motion" (because pixel diff can be small for high-info motion) but corrected when it says "I see no motion" and pixels disagree (because the judge sometimes misses real motion in settled-frame grids). Oracle reward recovered to 0.808. |

### 9.6 What the cascade still costs

None of the above fully solves the `expeditions` page failure (final 0.417
in v3). The animation there is a multi-card entrance that finishes by
tile 3, after which tiles 4–6 are settled. To the labeled-grid judge,
this reads as "snapshots of a static page." The auto-credit lifts
`motion_presence` to 0.5, but `target_element`, `motion_character`,
`timing_fidelity`, and `overall_motion_fidelity` all cascade because the
judge cannot identify motion characteristics it doesn't perceive. The
remaining fix is capture-side — non-uniform sampling that puts more
frames inside the entrance window — but that re-introduces the
unequal-spacing UX problem from §9.2. Trade-off pending; see §10.

### 9.7 Side issues that bit

- **`page.clock.pause_at(0)` after `clock.install()` failed with "Cannot
  fast-forward to the past."** The fake clock was installed at t=0 but
  `page.goto()` advanced wall time during navigation. `pause_at(0)`
  treats t=0 as a destination, not a marker, and refused to go backward.
  Fix: `clock.install(time=0)` already creates the clock paused — no
  `pause_at` needed, just `fast_forward` between captures. Found via
  smoke test of the example HTML before the harness ever hit Modal.
- **`apply_templates_to_task` only copied `Dockerfile` and `make.py`,
  not `_motion_capture.py`.** The first end-to-end Modal trial almost
  shipped without the motion helper in the build context. Found by
  inspecting the generated task directory before submitting the trial.
  Fix: one line added to the file list.
- **Markdown-fence linter complained about unlabeled code blocks.**
  Cosmetic, not load-bearing. Fixed by labeling text-diagram fences as
  ` ```text `.

---

## 10. Known limitations and follow-ups

### Judge variance dominates the remaining gap

The oracle should reach 1.0; it lands at 0.808. The remaining ~20% is
not a harness bug — it's ensemble-of-3 variance. Per-page example from
v3:

```text
constellations
  motion_presence raw=[3, 1, 3] agg=0.5
  target_element  raw=[5, 1, 5] agg=1.0
  motion_character raw=[5, 1, 5] agg=1.0
```

One ensemble call out of three returned 1 across every criterion. The
median absorbs it for Likert criteria with three 5's and one 1, but on
motion_presence with [3, 1, 3] the median is 3 = 0.5, not 5 = 1.0.

Two fixes worth considering:

- **Bump ensemble from 3 to 5.** Cost: +66% judge API calls per task.
  Smooths single-outlier calls.
- **Capture-side fix for entrance-heavy pages.** Pages where every
  animation finishes by tile 3 produce grids where tiles 4-6 are
  settled-state. To the judge, this reads as "snapshots of a static
  page." Non-uniform sampling — denser in the entrance window, sparser
  in the loop region — would keep motion visible across more tiles.

### CSS-only is a deliberate ceiling

JavaScript-driven animations (GSAP, anime.js, rAF loops, Lottie, Three.js)
are not currently allowed. The clock virtualization in
`_motion_capture.py` already works for JS animations — Playwright's
`page.clock` API virtualizes `requestAnimationFrame`,
`performance.now`, and timers — so the technical path is open. What
lifting the ban would need:

- A targeted "JS for autonomous animation only" rule in the codegen
  system prompt.
- An interaction-pattern scan in `generate_dataset.py` to reject
  `addEventListener('click'`, `:hover` with transforms,
  scroll-triggered handlers, `<details>`, `<dialog>`, checkbox hacks.
- A relaxed `<script>` validator in `_HTMLValidator` for tier 9 only.

This is bonus 1.5, not bonus 1.

### Three-viewport motion capture has cost implications

Every motion task runs the agent through 6 frames × 3 viewports × 5
pages = 90 extra screenshots at verifier time. On Modal this added
~1m to the v3 trial (3m 23s total vs ~2m for static). The verifier
timeout was bumped from 1200s to 1800s in the tier-9 task.toml. For
heavy batches this would scale linearly.

### Pixel-diff threshold is empirical

`MOTION_PIXEL_CHANGE_CREDIT_THRESHOLD = 0.005` was calibrated on a single
seed. A broader calibration set would tighten it. The threshold is
conservative — it only lifts motion_presence when there's clear pixel
evidence — so the failure mode of a wrong threshold is "we don't lift
when we should," which is at most a single-step Likert miss on one
criterion, never a false positive.

---

## 10. File touch list

| File | Role |
|------|------|
| [seeds.py](../generator/seeds.py) | `AnimationSpec` TypedDict, tier-9 description, `tier_range()` keeps tier-9 opt-in |
| [concept_gen.py](../generator/concept_gen.py) | Motion brief + validator for `motion_style` + `expected_animations` |
| [prompts.py](../generator/prompts.py) | Motion contracts in shared-CSS and per-page prompts |
| [generate_dataset.py](../generator/generate_dataset.py) | `data-anim` validation, `@keyframes`/`prefers-reduced-motion` requirements, `motion.json` sidecar, per-tier verifier timeout, instruction-template motion section |
| [templates/environment/_motion_capture.py](../generator/templates/environment/_motion_capture.py) | New — clock-virtualized 6-frame capture + PIL grid composer |
| [templates/environment/make.py](../generator/templates/environment/make.py) | Branches on `motion.json` to produce reduced-motion baselines + grids |
| [templates/environment/Dockerfile](../generator/templates/environment/Dockerfile) | Copies `motion.json` and persists `_motion_capture.py` at `/opt/` |
| [templates/tests/score.py](../generator/templates/tests/score.py) | `MOTION_JUDGE_CRITERIA`, pre-flight pixel diff, agent-source scan, motion-task reward path |
| [templates/task.toml.tpl](../generator/templates/task.toml.tpl) | `{{VERIFIER_TIMEOUT_SEC}}` placeholder, bumped to 1800s for motion tasks |
| [templates/instruction.md.tpl](../generator/templates/instruction.md.tpl) | `{{MOTION_SECTION}}` placeholder filled with per-animation contract |
| [examples/tier9-hero/index.html](../generator/examples/tier9-hero/index.html) | Hand-written demo of the tier-9 motion contract |

No changes to: `relevance.py`, `sanity.py`, the V2.1 deterministic
aspect implementations in `score.py`, or `solution/solve.sh`. The
static-tier pipeline is byte-identical to the pre-bonus state.
