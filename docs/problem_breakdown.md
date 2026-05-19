# Problem Breakdown

The problem statement in this work trial is to make a judge pipeline for
testing agents (Claude) in replicating websites from their screenshots
using HTML + CSS only.

We are to use Modal for compute and Harbor for the testing pipeline.

There are multiple sub-problems in this statement:

1. Creating a scoring function that returns a score between 0 and 1.
2. Creating the testing websites to be used for testing.

Both sub-problems feed each other. A scoring function without realistic
workloads has nothing to be tested against; a corpus of workloads without
a trustworthy scorer just produces noise. So the actual plan is to build a simple
version of each, run the loop end-to-end, and let each side surface gaps
in the other.

## Step 0 — getting Modal + Harbor running end-to-end

Modal and Harbor are both new to me. Before any of the real work can
start I have to understand how a Harbor task is structured (instruction +
references + verifier + Dockerfile), how the verifier is executed
inside Modal, and how reward.txt flows back out. The fastest path is
to copy the [Harbor terminal-bench](https://harborframework.com/)
example layout verbatim and stand up a single hand-written task that
runs end-to-end. That alone takes a meaningful chunk of time: just
getting one green run from `harbor run` against one website, with the
agent receiving screenshots and the verifier emitting a number, is the
checkpoint that unlocks everything after it.

Once one task runs end-to-end, every later iteration is just
"change one knob, re-run."

## Step 1 — a deliberately simple verifier (V1)

The first scorer is the cheapest thing that could possibly work:

- Structural Similarity Index (SSIM) between greyscale screenshots.
- RGB colour-histogram intersection.
- Combine with `0.7·SSIM + 0.3·color_hist`.

It gives me a working reward number for any (reference, agent-output) pair so
the rest of the pipeline can be exercised. See
[running_notes.md](running_notes.md) lines 1–28 for the V1 entry and
its enumerated flaws.

The flaws I'm writing down at this stage (reward hacking via embedded
`<img>`, no text similarity, no fonts, no layout structure, no
responsive testing, fold-only screenshots, single-scalar opacity)
become the checklist that drives every later version.

## Step 2 — workloads, also deliberately simple

In parallel I'm building the workload generator. V0 is 10 hand-written
seeds × an Opus call that emits all 5 pages of each site in a single
JSON response. I want the testing websites to be increasingly difficult so that in 
an RL pipeline, the easier tasks can be done first before turning onto
more difficult tasks.

Three tiers of difficulty (T1 static blocks → T2
multi-page identity → T3 layout complexity), a handful of genres per
tier (marketing / news / agency / dashboard / blog / e-commerce / …).


This works for getting *something* to test the scorer with,
but two scalability gaps surface immediately:

- **How the seed-scaling gap shows up.** Each hand-written seed is
  ~50 lines of design prose (palette hints, typography, per-page
  specs, constraints). At `num_tiers × num_genres` × ~50 lines, I
  blows the time budget before the corpus reaches double digits.
  The trial brief implies thousands of tasks — the static seed list
  isn't going to get there.
- **How the truncation gap shows up.** On tier-3 seeds (sidebar nav +
  KPI grids + tables), the combined 5-pages-in-one-JSON response
  blows past `max_tokens=16000`. The model returns with
  `stop_reason == "max_tokens"` mid-page. Retrying produces the same
  oversized output — the failure isn't transient, it's structural.

V1 of the dataset generator addresses both. I split into two stages
and one call per page:

- **Stage 1 — concept generation** ([generator/concept_gen.py](../generator/concept_gen.py)).
  Sonnet 4.6 at `T=0.95` takes a `(tier, genre)` pair and emits a
  `Seed` JSON (id, palette, typography, page list, per-page specs,
  constraints). The lever for "what does tier 4 look like" lives in
  `TIERS[tier]` in [generator/seeds.py](../generator/seeds.py), not
  in the prompt template — so adding a tier means appending one
  entry, not rewriting prose.
- **Stage 2 — per-page codegen** ([generator/generate_dataset.py](../generator/generate_dataset.py)
  `call_llm_one_page`). One Opus 4.7 call per page, each with its
  own 16k-token budget (80k total per seed), running concurrently
  for similar wall-clock. A single bad page becomes a single-page
  retry instead of a whole-task failure.

I also catch the genre-skew bug here. The naive sampler
(`random.choice` per tier) once produces 8 e-commerce / 3
dashboard / 2 documentation / 2 agency / 1 news-magazine for 16
tier-3 picks — 50% e-commerce. I replace it with a shuffle-bag deck
(deal the genre cards, reshuffle when empty), so within any sliding
window of `len(genres)` picks at a tier, every genre appears at
least once.

The narrative arc here is : ship the simplest
version, run it end-to-end, see what breaks, fix it.

## Step 3 — the iteration loop between verifier and workloads

This is the part the trial brief is really asking about: *how do you
know your grader is good?* The model will learn the grader. If the
grader is wrong, training on it injects pure noise.

The framing I settle on is meta-evaluation by deliberate degradation.
For one reference task, synthesise variants of the agent's output
whose quality I know by construction — then check the grader's
scores fall in the bands those labels predict.

I start with three variants in
[generator/scoring_calibration/degrade.py](../generator/scoring_calibration/degrade.py):

- `near_perfect` — verbatim copy of the reference. Establishes the
  ceiling: if the grader doesn't rank a byte-identical copy near
  1.0, the grader is broken at the simplest possible test.
- `mediocre` — colours swapped to a generic palette (gray/blue/
  green/amber cycling via `_MEDIOCRE_PALETTE`), every `font-family`
  forced to `Arial, Helvetica, sans-serif`, every other `<p>`
  replaced with lorem ipsum. Semantic tags + `@media` queries
  intact. Models a "low-effort agent — structure right, brand wrong."
- `bad` — wrong-palette + lorem on every visible string + semantic
  tags rewritten to `<div>` + flex/grid flattened + `@media` blocks
  stripped + viewport meta stripped + last page deleted entirely.
  Models an agent that has given up.

The runner at
[generator/scoring_calibration/run.py](../generator/scoring_calibration/run.py)
loads a **snapshotted grader version** (one of
[generator/scoring_calibration/grader_versions/v1/](../generator/scoring_calibration/grader_versions/v1/)
through `v4.0/`) and runs it against every (task, variant) pair.
Frozen snapshots mean the `vN.json` filename and the bytes that
produced it can never disagree — calibration runs are reproducible
even after the live template moves on.

The grader passes calibration only when every tier lands inside its
target band **and** `near_perfect > mediocre > bad` holds with zero
inversions. Hitting two of three bands by luck while inverting the
third is failure, not partial credit. The rest of the work is a
tight loop: run the calibration, read the per-aspect breakdown for
whichever tier missed its band, decide whether the right fix is
sharpening an aspect, retuning weights, adding a new aspect, or
adding a new calibration tier, snapshot the new grader version,
re-run.

What follows is what that loop produced, version by version, with
the actual *detect → diagnose → fix → verify* I went through each
time.

### V1 — pixel SSIM + RGB histogram only

- **Symptom.** First calibration on `synth-t1-burnt-sage-kitchen-9322`:
  `near_perfect 1.000 HIT, mediocre 0.465 HIT, bad 0.482 MISS,
  inversions=1 MISS`. Two HITs are misleading — the four surviving
  `bad` pages (0.58–0.65) all score **higher** than every `mediocre`
  page (0.46–0.50); the fifth bad page is the intentionally-deleted
  one so it scores 0.000. The grader is literally rewarding the
  structurally-broken output over the structurally-intact one.
- **Diagnose.** Open the saved `score_details.json` for both runs.
  The bad tier's RGB histogram intersection is 0.33; the mediocre
  tier's is 0.01. Reason: the bad palette
  (salmon/turquoise/gold/magenta) coincidentally has *more red
  coverage* than the muted gray/blue mediocre palette, and the
  reference (burnt-sage kitchen) is warm (cream + terracotta), so
  RGB histogram intersection gives `bad` a free 0.33. The mediocre
  tier *destroys* the histogram match by going gray; the bad tier
  *preserves* it by also going red. Pure RGB histogram isn't a
  brand-fidelity signal — it's "is there any red on the page."
  Grayscale SSIM gives bad the edge too: monolithic blocks of one
  colour (the bad variant's stripped-flex layout) produce smoother
  gradients than the mediocre variant's mixed-wrong-colours-over-
  intact-structure does.
- **Fix.** Two metrics that are both pixel-statistical can't be
  re-weighted into a structural signal. Re-design as multi-aspect
  with DOM extraction. → V2.
- **Verify.** Deferred to V2's calibration.

### V2 — schema-free, 11 weighted aspects

- **Symptom.** Re-run the same calibration: `near_perfect 0.999 HIT,
  mediocre 0.661 MISS (too high), bad 0.393 MISS (too high),
  inversions=0 HIT`. Ranking is finally correct; magnitudes are
  too generous.
- **Diagnose.** Open
  [generator/scoring_calibration/results/v2.json](../generator/scoring_calibration/results/v2.json)
  per-aspect breakdown for the bad tier. Three aspects leak credit:
  - `navigation = 0.804` despite the bad variant stripping `<nav>`
    to `<div class="nav">` and replacing link text with "Link
    One"/"Link Two". The extractor's "4+ child links" heuristic
    still detects the nav region; link count matches; position
    matches; only link-text similarity is low. Averaged equally,
    it lands at 0.80.
  - `repeating_groups = 0.74` because the JS extractor only requires
    `tag + size_bucket` similarity to call something a group. After
    flattening flex to block, children still share tags, so groups
    are detected and matched by IoU.
  - `pixel_ssim = 0.68–0.79` because grayscale SSIM is forgiving of
    colour changes when layout is mostly intact.
- **Fix.** Sub-aspect sharpening + top-level weight retune + a new
  calibration tier:
  - Inside `score_navigation`, link-text similarity now carries 70%
    of the weight (was 25%); structure signals share 30%.
  - Inside `score_repeating_groups`, per-item text similarity now
    carries 55% of the within-group weight (was 30%); count /
    direction / position share 35%.
  - Top-level weights: `pixel_ssim` 0.18 → 0.08, `text_content` 0.10
    → 0.32, `region_color` 0.08 → 0.10, `palette` 0.05 → 0.07. The
    aspects that survived structural rewrites are demoted; the
    aspects that actually discriminate are promoted.
  - A multiplicative text gate: `final_per_page = raw × (0.30 +
    0.70 × text_content_score)`. A lorem page can never exceed 30%
    of its raw weighted average no matter how perfect its DOM.
- **Verify.** → V2.1 calibration.

### V2.1 — sub-aspect sharpening, text gate, plus the adversarial tier

- **Symptom.** Calibration with V2.1: `near_perfect 0.999 HIT,
  mediocre 0.538 HIT, bad 0.112 HIT, inversions=0 HIT`. Three of
  three monotonic tiers HIT cleanly. But this version also
  introduced a new fourth tier — `adversarial` — and it MISSes
  badly at 0.441 (target ≤ 0.15).
- **Why I added the `adversarial` tier in the first place.** The
  three structural tiers all test what happens when the agent gets
  the *structure* wrong (lorem text, flattened semantics, missing
  page). None of them test what happens when the agent gets the
  structure right but the *visual design* wrong — exactly the
  failure mode a deterministic grader is architecturally blind to.
  Without a tier that exercises it, every numeric improvement I
  make to the structural side looks like progress on a complete
  problem. The adversarial rule (in `degrade.py`) preserves every
  DOM primitive — all 5 pages, all semantic tags, all `@media`
  queries, every heading/paragraph/link with original text — and
  injects a `<style>` block with `!important` rules: Comic Sans on
  everything, 96px headings with `transform: rotate(2deg)`, 9px
  centre-aligned body, clashing neon palette
  (`#FF00FF`/`#00FF00`/`#FFFF00`), drop shadows, wavy underlines.
- **Diagnose.** Open
  [generator/scoring_calibration/results/v2.1.json](../generator/scoring_calibration/results/v2.1.json)
  for adversarial. `text_content = 0.92`, `navigation = 0.99`,
  `headings = 0.57`, `paragraphs = 0.71`, `layout_skeleton = 0.34`
  — mostly high. The text-gate factor is 0.97 (text is preserved
  → no penalty). Only `region_color` (0.06), `palette` (0.0), and
  `pixel_ssim` (0.58, dragged down only by giant headings shifting
  edges) tank. Every aspect that depends on DOM primitives passes.
- **Fix decision.** There is no deterministic weighting that solves
  this. Push pixel/colour weights to 100% and structural aspects to
  0% — and any agent output with the right text but slightly
  different rendering (font hinting, antialiasing) scores bad. The
  signal the grader needs — "this looks visually broken" — requires
  actually looking at the rendered image at the level of semantic
  design, and no combination of pixel histograms, IoU overlaps, and
  string-similarity metrics can produce it. Time to add a
  multimodal LLM judge. → V3.
- **Verify.** Deferred to V3.

### V3 — Claude Opus 4.7 vision joins the grader

- **Implementation choices that matter.**
  - **Combine linearly:** `final = 0.70 × judge + 0.30 × V2.1_deterministic`.
    The deterministic side is kept as-is, demoted to one of two
    halves rather than thrown away.
  - **Generic, page-agnostic criteria:** six 1-5 Likert questions —
    `visual_hierarchy`, `color_palette`, `typography`,
    `layout_fidelity`, `content_present`, `overall_fidelity`. The
    same six work for every task without per-task authoring.
    (Per-task criteria from `seed.json` are more precise but a
    larger infrastructure piece — deferred until generic stops
    working.)
  - **Anthropic `tools` for structured output:** a hard-coded
    `submit_scores` tool whose `input_schema` is
    `{scores: [{id, score}, ...]}`, with `tool_choice` forcing the
    call. The model can't return freeform JSON or markdown.
  - **Async ensemble per page, concurrent across pages:** each page
    fires `JUDGE_ENSEMBLE_SIZE` calls via `asyncio.gather`, then all
    pages' ensembles fire concurrently inside a single
    `AsyncAnthropic` client. Wall-clock is one call's latency for
    the whole task regardless of ensemble size; cost scales linearly.
  - **Aggregation:** majority vote on binary criteria, median on
    Likert. Likert 1–5 normalised as `(median - 1) / 4`.
- **Symptom.** Calibration with ensemble=1: `near_perfect 1.000 HIT,
  mediocre 0.336 MISS (now too low — dropped under its old band),
  bad 0.092 HIT, adversarial 0.301 MISS, inversions=0 HIT`.
- **Diagnose adversarial.** The judge correctly floors `typography`,
  `color_palette`, `layout_fidelity`, `overall_fidelity` (all 1/5
  on Likert), but `content_present = 1` because the adversarial
  variant *does* preserve all the reference text. One binary at
  1.0 against five Likerts near 0 gives the judge a 1/6 ≈ 0.17
  floor. Combined with V2.1's 0.30 × 0.55 = 0.165 contribution,
  the total lands at 0.30 instead of closer to 0.10.
- **Diagnose mediocre.** The judge is *honest* about mediocre. Gray
  palette + Arial + half lorem reads as `overall_fidelity = 1`
  and `content_present = 0` to a vision model — closer to bad than
  to "half decent." Arguably correct, but it dropped out of the
  band the deterministic-era calibration set up. This is a
  framework-level issue, not a grader bug: the bands assumed a
  deterministic grader that gives partial credit for
  structure-still-there. A vision judge doesn't credit invisible
  structural correctness.
- **Fix.** Two pieces, in two minor versions:
  - V3.1 drops `content_present` from the criteria (double-counts
    with V2.1's `text_content` aspect plus the text gate). Five
    criteria remain.
  - V3.2 adds a fifth calibration tier `plain` (all CSS stripped:
    no `<style>` blocks, no `<link rel=stylesheet>`, no inline
    `style="..."`, no Google Fonts — page renders with browser
    defaults). This models "agent submitted valid HTML but ignored
    the visual reference entirely" — a failure mode none of the
    other tiers were exercising. V3.2 also re-bands `mediocre`
    (0.40–0.65 → 0.25–0.50) and `adversarial` (≤ 0.15 → ≤ 0.20)
    to match what a vision-based judge actually scores, and bumps
    `JUDGE_ENSEMBLE_SIZE` from 1 to 3 as production insurance.
- **Verify.** V3.1 alone: adversarial 0.30 → 0.20 (closing 0.10 of
  the gap), confirming the double-counting hypothesis. V3.2 with
  the new tier and new bands and ensemble=3:

  | tier | mean | target | verdict |
  |---|---|---|---|
  | near_perfect | 1.000 | ≥ 0.85 | HIT |
  | plain | 0.236 | 0.00–0.40 | HIT |
  | mediocre | 0.350 | 0.25–0.50 | HIT |
  | bad | 0.104 | 0.00–0.15 | HIT |
  | adversarial | 0.195 | 0.00–0.20 | HIT |
  | inversions | 0 | 0 | HIT |

  Monotonic ladder `near_perfect 1.000 > mediocre 0.350 > plain
  0.236 > adversarial 0.195 > bad 0.104` across five
  qualitatively distinct failure modes.
- **Side-finding from the ensemble.** With every individual
  ensemble call's raw score saved in
  `per_page[*].judge_breakdown.per_criterion[*].raw`, I can
  measure whether ensemble=3 was worth it. Across 120
  criterion-judgements: 112/120 (93%) returned the same score, 8
  disagreed by 1 Likert step, 0 disagreed by ≥ 2 steps. Max noise
  impact ≈ ±0.01–0.03 per tier — matching the observed
  ensemble=1-vs-3 delta of ≤ 0.007. Ensemble=1 would have been
  fine *for these extreme tiers*. Whether mid-quality agent output
  is noisier to judge is not measurable from calibration; the
  ensemble=3 default is held as production insurance.

### V3.3 — fail loudly when the key is missing

- **Symptom.** Not a calibration miss — a contract problem I notice
  while reading the V3.2 code. The grader has a "graceful fallback":
  if `ANTHROPIC_API_KEY` is missing or any judge call errors, it
  silently drops the judge dimension, renormalises the
  deterministic side to weight 1.0, and continues producing a
  reward number.
- **Diagnose.** Three issues with that path:
  1. Silent degradation hides infra failures. "reward = 0.42"
     doesn't tell the operator whether the judge ran. Anyone
     reading the leaderboard a week later has no way to know half
     the rows were graded with the full V3 stack and the other half
     with V2.1-only because the key expired on Tuesday.
  2. Scores stop being comparable across runs. Falling back is
     silently changing the rules.
  3. The fallback was never calibrated. V2.1 scored adversarial at
     0.44 — the failure mode V3 was specifically added to catch. A
     run that fell back to V2.1 would emit a 0.44 for an output
     that V3 should score 0.20.
- **Fix.** Raise loudly on missing key, raise loudly on judge call
  errors, exit non-zero. Snapshot at
  [generator/scoring_calibration/grader_versions/v3.3/score.py](../generator/scoring_calibration/grader_versions/v3.3/score.py).
- **Verify.** Re-running V3.2's calibration tasks against V3.3 with
  the key present produces numerically identical results (max
  delta 0.007 — ensemble noise). Behavioural change only.

### V4 — three viewports, full-page capture

- **Symptom.** Two latent flaws that have been on the
  what-we-don't-cover list since V2:
  - **No responsive testing.** Every `page.screenshot(...)` across
    the codebase uses a single 1280×800 viewport. A page that
    looks fine at 1440 and completely broken at 390 scores the
    same as one that's correct everywhere.
  - **Below-the-fold content invisible.** `full_page=False` cuts
    pages longer than 800px at the fold. The DOM extractor's JS
    reinforces this by treating elements with `top >= 800` as
    invisible. An agent could write garbage below 800px and score
    perfectly.
- **Diagnose.** The plumbing was always multi-viewport-ready (the
  judge call accepts a `list[(label, base64_png)]` per side); the
  orchestration just only ever fed one viewport in. Same with
  `full_page=True` — a one-flag flip per `page.screenshot` call.
- **Fix.** Three viewports — desktop 1440×900, tablet 768×1024,
  phone 390×844 (industry-standard responsive bracket). Every
  page produces six PNGs per trial (3 reference + 3 agent). Both
  the deterministic V2.1 pipeline and the judge see all three;
  per-viewport aspect scores are averaged. `full_page=True`
  everywhere. DOM extractor's `top >= 800` cull removed.
- **Verify.** Run calibration on two qualitatively different
  tasks this time, not just one — burnt-sage-kitchen (tier-1
  recipe site, ~200 lines/page) and vaultline-private-banking
  (tier-6 five-page form-heavy onboarding, ~450 lines/page).

  | tier | burnt-sage (t1) | vaultline (t6) | target |
  |---|---:|---:|---|
  | near_perfect | 1.000 | 1.000 | ≥ 0.85 |
  | plain | 0.275 | 0.287 | 0.00–0.40 |
  | mediocre | 0.431 | 0.398 | 0.25–0.50 |
  | bad | 0.100 | 0.078 | 0.00–0.15 |
  | adversarial | 0.265 | 0.315 | 0.00–0.35¹ |
  | inversions | 0 | 0 | 0 |

  ¹ Re-banded from V3.2's ≤ 0.20 because multi-viewport averaging
  systematically lifts adversarial 0.07–0.12 — the structural
  primitives the adversarial variant preserves now accumulate
  credit at three viewports each.

  All five tiers HIT on both tasks; zero inversions. More
  importantly, every tier landed within 0.05 of the other task's
  score across two very different sites. That cross-task
  reproducibility number is more important than the absolute
  scores — earlier V3.x calibration was on burnt-sage alone, so
  we'd never measured this. V4 measured it by accident (re-running
  to stress-test multi-viewport) and the answer was "the grader is
  task-stable."

Nothing in V2 or V3 is a *new idea*
that arrives fully formed. Each version is the previous version
plus the smallest fix that addresses whichever tier missed its band
in the last calibration run. The adversarial tier in V2.1 exists
specifically because I need an empirical reason to add the judge —
without it the V2.1 numbers all look fine and V3 reads as ornament.
Building the calibration set as a forcing function for the grader
is the part I'd repeat next time.

## Step 4 — the verifier surfacing gaps in the workloads, and vice versa

The loop goes both ways. The verifier improvements keep revealing
weaknesses in the workloads, and the workloads keep revealing
weaknesses in the verifier and its surrounding plumbing.

### 4a — verifier reveals workload gaps

**V4 surfaces non-responsiveness in the existing corpus.**

- **Detect.** The 16 V1 workload tasks were generated under a "design
  for 1280×800 viewport" prompt. V4 now renders them at three
  viewports. Tablet (768) and phone (390) screenshots show layouts
  that overflow, text that wraps poorly, and nav bars that fall
  off-screen. The grader is now measuring something the dataset
  wasn't designed to satisfy.
- **Diagnose.** Look at the per-viewport `judge_breakdown` in
  `score_details.json` for a real-agent run. Desktop scores are
  consistently 0.10–0.15 above tablet and phone. That's the
  grader doing what it should — surfacing a real failure mode the
  earlier single-viewport grader was blind to.
- **Fix.** Update [generator/prompts.py](../generator/prompts.py)
  system prompt to tell the model the site will be rendered at
  three viewports — so future-generated sites are designed
  responsive from the start instead of pixel-fitted to 1280×800.
  The existing 16 sites' HTML is not regenerated; their drop in
  mean reward under V4 is the empirical baseline future runs
  measure against.
- **Verify.** Deferred to the next batch generation under the
  updated prompts.

**T1–T3 alone don't stress the judge dimension enough.**

- **Detect.** With only static blocks (T1), multi-page identity
  (T2), and layout complexity (T3), the corpus doesn't have any
  workloads exercising gradients, custom type scales, dense
  forms, inline SVG, or magazine-style layouts. Those are
  exactly the design idioms a vision judge is in the best
  position to evaluate.
- **Fix.** Extend the tier ladder to 4–8 in
  [generator/seeds.py](../generator/seeds.py) and add tier-
  conditional structural checks to
  [generator/sanity.py](../generator/sanity.py)
  (e.g. T7 requires ≥ 1 inline `<svg>` with drawable content).
  Each new tier needs only: a `TierSpec` entry, 5 genres in
  `GENRES`, and a structural check. Concept-gen and codegen
  prompts pick them up automatically by reading `TIERS[tier]`.

**Tier numbers themselves are unverified claims.**

- **Detect.** After running the V4 grader against `workloads_v4`,
  I have fidelity scores but no answer to: "if I claim T6 is
  harder than T4, is that empirically true on the websites we
  actually generated?" The tier ladder I wrote in `seeds.py` is a
  *conceptual* taxonomy — nothing in the codebase enforces or
  measures whether a generated workload actually meets its tier's
  difficulty.
- **Fix.** Build
  [generator/difficulty_analysis/score_difficulty.py](../generator/difficulty_analysis/score_difficulty.py)
  — a reusable scorer that takes a `workloads/` directory and
  emits per-task difficulty metrics + a composite + a tier-
  validation report. Three commitments up front:
  - Structural metrics from Yellow Lab Tools (GPL-2.0), driven by
    `phantomas` under headless Chromium — ~13 HTML+CSS metrics
    for free (DOMelementsCount, DOMelementMaxDepth, cssRules,
    cssSelectors, cssDeclarations, cssColors, etc.).
  - Custom add-ons (~80 LOC Python) for what YLT doesn't emit:
    `svg_path_count` (T7 driver), `gradient_count`, JPEG-filesize-
    per-kpixel (Forsythe 2011 visual-clutter proxy, r=0.74 with
    human ratings), Canny edge density (Miniukovich CHI 2015
    contour-congestion), cross-page nav Jaccard (T2 multi-page
    identity signal).
  - Composite via the DesignBench (arXiv:2506.06251) formula
    `S = 0.25·z(I) + 0.25·z(U) + 0.25·z(C) + 0.25·z(L)`. A 
    multi-axis difficulty composite for screenshot-to-code;
    DesignBench validated monotonic MLLM
    degradation across its bins on real pages.
- **Verify (run 1).** Composite Spearman ρ vs tier = +0.36 (CI
  [-0.39, +0.90]), Kendall τ = +0.28 on `workloads_v4`. Below
  ρ ≥ 0.85 target; CI includes zero. Two adjacent-tier inversions
  in median composite: **T4 → T5** (+0.56 → -0.87 — T5 poetry-
  collection came out *simpler* than T4 on every measured axis:
  DOM 131→107, cssRules 86→42, cssColors 27→10, gradients
  10.3→0.8) and **T6 → T7** (+0.49 → +0.33).
- **Diagnose.** The root cause was the tier specs themselves in
  `generator/seeds.py`. T1–T4 worked because T4 says "Layouts
  from tier 2 or 3, treated with intentional decoration" —
  explicit inheritance. T5–T8 didn't inherit. T5 was framed as
  "typography is the visual identity," which the LLM read as a
  *substitute* for layout/polish, not an *addition on top*. T6
  said "forms *or* tables" (the LLM picked the easier side). T8
  was the vaguest: "multiple distinct sections per page" with no
  count.
- **Fix.** Tighten T5/T6/T7/T8 in two ways: (a) explicit
  inheritance — T5 inherits T3+T4, T6 inherits T4, T7 inherits
  T3+T4, T8 inherits T3+T4+T5+T6 plus selective T7; (b) concrete
  minimums replacing vague "multiple/many" — T5 = 6+ distinct
  font-sizes, 3+ font-weights, marginalia + drop caps + pull
  quotes required; T6 = 15+ inputs per page AND tables with 6+
  columns × 20+ rows (not "or"); T7 = 30+ inline SVG primitives
  across multiple distinct figures; T8 = 6+ distinct visual
  modules per page from an enumerated module catalog.
- **Verify (run 2).** T1–T4 copied verbatim from v4, T5–T8
  regenerated under the new specs in `workload_v5/`. Composite ρ
  = +0.57 (CI [-0.20, +0.96], p=0.083). Real improvement from
  +0.36, still below 0.85. Six per-metric correlations now
  significant at p<0.05 (vs 2 in v4): html_bytes +0.77,
  cssDeclarations +0.72, cssRules +0.70, cssSelectors +0.67,
  DOMelementsCount +0.65, svg_path_count +0.69. T5 fixed
  (composite -0.87 → +0.11); T6 fixed (now densest workload).
  T7 (the brand-identity workload at the time of this run, since
  re-rolled) regressed — DOM 216, cssRules 63, below v4's T7
  average. T8 (the news-feature workload at the time of this
  run, also since re-rolled) landed but didn't surpass T6.
  Plausibly those genres pulled toward minimalism and the spec
  text isn't strong enough on raw density. Plan for the next
  retry — re-roll T7 toward `data-viz-report`/`infographic` and
  T8 toward `longform-article`/`multimedia-essay`, plus add
  numeric density floors to the T7/T8 spec text — is documented
  in [running_notes.md](running_notes.md) lines 1342–1349. The
  current `workload_v5/` and `workload_v6/` directories on disk
  reflect that retry having been partially executed.

### 4b — workloads reveal verifier-side gaps

**The instruction.md template was the silent third leg of the benchmark.**

- **Detect.** First end-to-end Harbor run against the 16 V1 tasks
  with V3.3 deployed: `Trials: 16, Exceptions: 9 (AgentTimeoutError),
  Mean: 0.841`. Some tier-1 sites — supposedly the easiest tier —
  time out at 900s and score 0.38; tier-3 dashboards finish cleanly
  at 0.999. The tier ordering isn't tracking what we think it is.
- **Diagnose.** Open `trial.log` for one of the timed-out tier-1
  trials. The instruction.md template was still telling the agent:
  1. The V1 scoring formula (`score = 0.7 * SSIM + 0.3 * color_hist`)
     — bake-in date V1, never updated. The agent reads this and
     spends its 15-minute budget on pixel-level reproduction
     (chasing antialiasing, subpixel font positioning) instead of
     focusing on holistic design fidelity that V3.3 actually grades.
     Telling the agent the metric makes the metric a target
     (Goodhart). Also bait for reward hacking — an agent told
     "you're scored on SSIM" learns it can embed the reference PNG
     as `<img>` and ace the metric.
  2. A blanket "no external CDNs, no Google Fonts" rule. The
     agent's container has internet access during the agent-execution
     phase — the restriction was self-imposed, not infra-required.
     Effect: agents had to either inline base64 font files (slow,
     error-prone) or fall back to system fonts, which then fails
     on the typography dimension the V3.3 judge actually grades.
     We were handicapping the agent on the exact dimension we
     then graded.
- **Fix.** Drop both. The instruction template ends with a brief
  description of what visual fidelity *means* (colours / fonts /
  spacing / layout) and stops there. Notably: the brand palette and
  fonts are still not handed to the agent — colour-picking and
  font-identification are part of what we're testing, and
  pre-resolving them would change the nature of the benchmark.
  Recorded as a deliberate design choice rather than a deficiency.
- **Verify.** Re-run: `Trials: 16, Exceptions: 1 (AgentTimeoutError),
  Mean: 0.908`.

  | metric | before fix | after fix |
  |---|---:|---:|
  | mean reward | 0.841 | **0.908** |
  | median reward | 0.870 | 0.882 |
  | min reward | 0.382 | **0.828** |
  | max reward | 1.000 | 1.000 |
  | timeouts | 9 / 16 | **1 / 16** |
  | trials < 0.50 | 2 | 0 |

  The min-reward jump (0.38 → 0.83) is the SSIM-formula removal.
  The timeout collapse (9 → 1) is the Google-Fonts ban removal:
  before, the agent looped trying to embed fonts; after, it
  adds `<link href="https://fonts.googleapis.com/...">` and moves
  on. The remaining 1 timeout was on a tier-3 fleet-ops dashboard
  doing a "draft then polish" strategy that occasionally exceeds
  900s on dense layouts — fix is a bigger `agent.timeout_sec`,
  deferred until it fires reproducibly.
- **Lesson worth recording.** The instruction template was the
  silent half of the benchmark we'd been ignoring all the way
  through V1 → V3.3 of the grader evolution. The grader can be
  perfectly calibrated and the agent can be capable, but if the
  instruction tells the agent the wrong objective or imposes a
  self-defeating constraint, every benchmark number is shaped
  by those bugs. The instruction.md is now part of the grader
  contract. Future grader evolutions must check the instruction
  template too: when scoring rules change, the instruction either
  doesn't mention them or is updated in lockstep.

**Tier-7 SVG content tripped the HTML validator.**

- **Detect.** While generating T7 workloads, multiple pages
  burned through their retry budget. Validator error:
  `external network URLs present: ['http://www.w3.org/2000/svg']`.
- **Diagnose.** `validate_html` flags any `http(s)://` URL in any
  attribute value. T7 pages contain inline SVG, and SVG roots
  carry `xmlns="http://www.w3.org/2000/svg"` — an XML namespace
  identifier that *looks* like a URL but isn't fetched.
- **Fix.** One-line skip in the URL check when the attribute name
  is `xmlns` or `xmlns:*`.
- **Verify.** T7 generation now completes without false-positive
  rejections.

**A full benchmark run reported `reward=0.0` across the board with zero exceptions.**

- **Detect.** A run that should have produced a reward distribution
  produced all zeros — and no exceptions to investigate.
- **Diagnose.** The V3.3 scorer raises if it can't import
  `anthropic`. The Dockerfile in
  [generator/templates/environment/Dockerfile](../generator/templates/environment/Dockerfile)
  predated the judge dimension and didn't install the package. The
  scorer raised inside the container, `test.sh` caught the error
  and wrote `0.0` to `reward.txt` for every trial — that's how
  Harbor sees "no signal, no exception."
- **Fix.** Add `anthropic>=0.40` to the Dockerfile's pip install
  line. Re-deploy to all 16 v1 task directories. Cost of
  discovery: $83 of Opus tokens producing zero signal.
- **Structural lesson.** Generated tasks copy `templates/`
  verbatim at generation time, with no version pin tying a task
  back to its template revision. Any later change to
  `templates/environment/Dockerfile` is silently non-applied to
  existing tasks. Candidate for a future generator pass: stamp
  a `template_version.txt` into each task and have the verifier
  refuse to run on stamp mismatch.

The point: both sides of the pipeline teach the other side what it
is missing. Either side in isolation would be wrong in ways the
other side makes visible.

## Step 5 — what's left

- Concept-level uniqueness in the workload generator is not yet
  enforced — at `--count 1000+` Sonnet converges on a small lexical
  neighbourhood (three "Summit" conferences, two "Iron-" brands).
  Fix is straightforward (an `AVOID these brands` block in the prompt
  plus a post-hoc SequenceMatcher reject), deferred until the next
  big batch.
- Per-task judge criteria. The five generic criteria catch the
  full failure spectrum on the calibration tiers, but a Sonnet pass
  at task-creation time emitting a per-page checklist from seed.json
  would be more precise. Deferred until the generic criteria
  measurably fail on a real task.
- T7 / T8 tier validation. Progression across regenerations: v4 ρ
  +0.36 → v5 +0.85 (hit target) → v6 +0.75 (regressed). v5's win
  came from tightened T5/T6/T7/T8 specs with explicit numeric
  density floors plus the shared-CSS refactor (every seed authors
  one `_shared.css` and pages link it, instead of inlining the
  design system per page — this kept dense T7 pages under the API
  streaming token cap). v6 extended the floors to all tiers T1-T8
  and rebuilt the whole set with the new generator. T1–T6 + T7 now
  hit their floors cleanly and T1→T6→T7 is perfectly monotonic for
  the first time; T7 infographic landed at DOM = 732 (above its 460
  floor) with composite S = +1.34, top of the ladder where it
  should be. T8 missed its 550 DOM floor (came out 298 across two
  attempts) — the floor is advisory prose, not an enforced minimum,
  and the LLM treats it as a hint. Result: T7→T8 is the persistent
  remaining inversion. Web Almanac comparison improved
  dramatically: v6 mean DOM = 280 (v4: 177) and cssRules = 208 (v4:
  66); top of v6 range exceeds the public web median page for the
  first time.
- Per-page DOM-count enforcement. The next iteration on tier
  validation is a post-codegen Playwright pass that renders each
  generated page, counts visible DOM elements via the existing
  `EXTRACTION_JS`, and rejects pages under the tier's floor with a
  retry loop. ~30 LOC change in `generate_dataset.py`. Deferred
  because v6's overall ρ = +0.75 is already statistically
  significant (p = 0.0125, CI [+0.13, +0.99]) and the structural
  improvements (shared CSS, single-CSS-file rule, monotonic floors
  T1-T8) shipped with v6.
- Single-CSS-file rule and shared-CSS workflow. Every generated
  website now ships at most one CSS file: a shared
  `environment/reference-pages/_shared.css` authored by a dedicated
  pre-codegen LLM call. Each page `<link rel="stylesheet"
  href="../_shared.css">` it as the FIRST head element plus an
  optional small inline `<style>` for page-unique overrides.
  Rationale: any future judge MLLM that grades agent output by
  reading source + screenshots must fit everything into one prompt,
  so per-page CSS files would multiply attachments unnecessarily.
  The HTML validator now rejects multiple `<link rel="stylesheet">`,
  wrong hrefs, and `@import` inside inline `<style>`;
  `validate_shared_css()` rejects any `@import` or external URL in
  the stylesheet itself (with a W3C XML namespace allow-list for
  `http://www.w3.org/2000/svg` and friends, which look like URLs to a
  regex but are static identifiers Chromium never fetches).
- Per-task template version stamping so that future verifier changes
  don't silently fail to propagate to already-generated tasks.
- websites with different languages.
- all the websites are of the same form, ie. multiple visible links,
  each page with one link. but typically, websites layouts are very
  diverse. There should be a way to generate and test for those.

## Step 6 — the end-to-end benchmark run

With the V4 grader pinned and v6 of the workloads released, I run
the actual benchmark the trial brief asks for: Claude Code with
Opus 4.7 against the full v6 dataset, 10 attempts per task.

```bash
harbor run -p ./workload_v6 -a claude-code -m anthropic/claude-opus-4-7 \
  --env modal --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -k 10 -n 100
```

100 trials total, 60 minutes wall-clock on Modal, $380 of Opus
calls, 4 errored trials (3 agent timeouts, 1 verifier timeout —
T7 absorbed 2 of those 4, the others scattered across T1 and
T8). Mean reward across the 99 trials that have a reward:
**0.725** (Harbor's reported metric is **0.7176** — same numbers
divided by 100 instead of 99, treating the one unrewarded trial
as 0). Three of the four errored trials still produced rewards
from the partial output the agent had written before timeout.

The numbers do what calibration predicted they would:

- **Tier monotonicity holds on real agent output.** Mean reward
  declines across tiers — T1 (0.831), T2 (0.747), T3 (0.782),
  T4 (0.727), T5 (0.668), T6 (0.655), T7 (0.684), T8 (0.573).
  Two small inversions (T3 above T2, T7 above T6), both inside
  per-tier stdev. The tier ladder is at least partially
  predictive of real difficulty, not just structural-metric
  difficulty.
- **The grader uses its dynamic range.** Trials span 0.452 to
  0.962. No piling-up at 1.0, no collapse at 0.5.
- **The judge dominates layout failures, the deterministic side
  dominates text failures.** Both halves carry the weight they
  were designed to. The 30/70 split holds.

And the failure patterns are concrete and reproducible across
all 99 trials:

- **Layout fidelity is the universal bottleneck.** Across ~7,400
  individual Likert votes, `layout_fidelity` Likert 5 happens only
  5% of the time vs. 63% for `color_palette`. The deterministic
  side agrees: `repeating_groups` (mean 0.32) and
  `layout_skeleton` (mean 0.42) sit below 0.5 on roughly 90% of
  page-trials. The agent puts the right elements on the page but
  not in the right grid.
- **T8 (magazine layouts) is in its own difficulty bucket** —
  mean 0.573, a 0.08 gap to the nearest tier. The 6-distinct-
  visual-modules-per-page target collapses to a generic
  "blog-with-hero."
- **Text-as-design tiers fail on text-content axes.** T5
  (editorial) and T6 (forms) drop `text_content` and `paragraphs`
  by 30–40 points vs. T1 because the agent ad-libs body copy and
  form labels instead of transcribing them.
- **Domain-specific microcopy breaks navigation extraction.** T7
  (scientific infographic) has `det.navigation = 0.181` because
  V2.1 weighted navigation 70% on link-text similarity and Opus
  paraphrases the reference's domain terms.

Full method, per-tier and per-aspect tables, Likert
distributions, and the limitations of this evidence base are in
[`observations_and_limitation.md`](observations_and_limitation.md).

## Why this shape

I spent most of my time in iterating over the grader and the generator.
This is because I havent made websites earlier so I dont know whats difficult about them.
Also, an unvalidated grader produces meaningless numbers. Once the calibration loop 
was made, every grader and generator was just an increment over the last and I had clear
answer to the question "did this change actually help ?"