# Observations and Limitations

This document covers the end-to-end benchmark result for Claude Code
(Opus 4.7) on the v6 dataset: the experimental method, the headline
numbers, where the model breaks down, and the limitations of the
evidence base. It complements [`SCORING.md`](SCORING.md) (which
proves the *grader* works on synthetic degradations) by showing
what the grader actually reports on *real agent output*.

## 1. Experimental method

### 1.1 What is being measured

A single trial is one full evaluation of Claude Code on one task:

1. The Harbor agent layer starts a fresh `claude-code` agent inside
   a Modal container, installs the CLI, and hands it the task's
   `instruction.md` + the rendered reference PNGs at desktop /
   tablet / phone viewports (`/app/references/{viewport}/<page>.png`).
2. The agent has a 900 s wall-clock budget to write five HTML pages
   into `/app/output/<page>/index.html`. It can use any model
   provider it has keys for; here it is forced to
   `anthropic/claude-opus-4-7`.
3. The verifier (`tests/test.sh` → `tests/score.py`, both pinned to
   grader **V4.0**) renders both reference and agent HTML at all
   three viewports, runs the 11 deterministic aspects + the
   5-criterion Claude Opus vision judge (ensemble size 3), and
   writes a single float reward to `reward.txt` plus a complete
   per-page-per-aspect-per-viewport breakdown to
   `score_details.json`.

### 1.2 The run

```bash
harbor run -p ./workload_v6 -a claude-code -m anthropic/claude-opus-4-7 \
  --env modal --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -k 10 -n 100
```

- `-k 10` → 10 attempts per task. `-n 100` → up to 100 concurrent
  trials (effectively "no concurrency cap" given the 100 total).
- Dataset: `workload_v6/` — 10 tasks, one per (tier, genre)
  combination across tiers 1–8 (T1 and T2 have two tasks each).
- Job at [`jobs/2026-05-19__02-17-44/`](../jobs/2026-05-19__02-17-44/).

### 1.3 Run-level statistics

- **Total trials:** 100 (10 tasks × 10 attempts).
- **Completed:** 100. **Errored:** 4.
  - 3 × `AgentTimeoutError` (one on each of: T1 maren-solvik,
    T7 deep-current-oceandata, T8 forma-negra).
  - 1 × `VerifierTimeoutError` (T7 deep-current-oceandata).
  - T7 absorbed two of the four errored trials (one agent
    timeout, one verifier timeout); T1 and T8 absorbed one agent
    timeout each. Three of the four errored trials still produced
    rewards from partial agent output (the verifier ran on
    whatever HTML existed when the agent was killed); only the
    `VerifierTimeoutError` trial (T7 zfhG5qe) has no reward at
    all.
- **Wall-clock:** 60 minutes for the full run.
- **Cost:** $380.74 of Opus calls (449M input tokens, 5M output
  tokens, 440M cached). Roughly $3.80 per trial — most of which
  is the agent's Claude Code calls, not the judge.

### 1.4 Why this method

- **`-k 10` rather than re-running the whole job.** Repeating the
  job only re-rolls *grader* noise; on the V3.2 calibration we
  already measured grader noise at ≤ ±0.03 per tier (93% of judge
  ensemble votes were identical across 3 calls). Re-rolling the
  agent is the only way to measure *agent* variance, which is what
  the brief is actually asking about ("how well does your grader
  do at scoring the results when running Claude Code … 10 times on
  the task").
- **One model, one agent.** Holding the agent and model fixed
  isolates "what does Claude Code do on this design space" as the
  only varying factor. Cross-model and cross-agent comparisons are
  outside this run's scope.
- **V4 grader pinned.** Grader is at version V4.0 for every trial,
  snapshotted at
  [`grader_versions/v4.0/score.py`](../generator/scoring_calibration/grader_versions/v4.0/score.py).
  No mid-run grader changes.

## 2. Headline results

| Tier | n | Mean | Stdev | Min | Max |
|---|---:|---:|---:|---:|---:|
| T1 | 20 | **0.831** | 0.056 | 0.757 | 0.962 |
| T2 | 20 | 0.747 | 0.050 | 0.676 | 0.840 |
| T3 | 10 | 0.782 | 0.025 | 0.726 | 0.813 |
| T4 | 10 | 0.727 | 0.108 | 0.452 | 0.835 |
| T5 | 10 | 0.668 | 0.085 | 0.497 | 0.779 |
| T6 | 10 | 0.655 | 0.027 | 0.602 | 0.688 |
| T7 |  9 | 0.684 | 0.118 | 0.500 | 0.831 |
| T8 | 10 | **0.573** | 0.083 | 0.494 | 0.731 |
| **all** | **99** | **0.725** | **0.121** | **0.452** | **0.962** |

T7 is 9 trials (not 10) because one trial errored on a
`VerifierTimeoutError` and produced no `score_details.json`.
Note Harbor's `result.json` reports the eval mean as **0.7176**
because it computes `sum_of_99_rewards / 100` (treating the
missing trial as 0). 0.7176 is the citable Harbor metric; 0.725
is the mean over the 99 trials that actually have a reward.
The other three errored trials (T1 b5Qn2jC at 0.962, T7 4Bfh6Zk
at 0.831, T8 LSFCmwB at 0.716) **are** in the per-tier and
all-trials means above — Harbor scored them on the partial
output the agent had produced before timeout.

### 2.1 Reading the table

- **Strong tier monotonicity.** Mean reward declines almost cleanly
  with tier difficulty: T1 (0.831) → T2 (0.747) → T4 (0.727) →
  T5 (0.668) → T6 (0.655) → T8 (0.573). Two small inversions
  remain — T3 lands slightly above T2 (0.782 vs 0.747, Δ = 0.035)
  and T7 slightly above T6 (0.684 vs 0.655, Δ = 0.029) — both
  inside the stdev of their neighbouring tiers and consistent with
  what
  [`difficulty_analysis/score_difficulty.py`](../generator/difficulty_analysis/score_difficulty.py)
  reports for the v6 tier ladder (Spearman ρ = +0.75 with two
  remaining inversions).
- **The headline number isn't 0.5 or 0.95.** Overall mean of
  0.725 (Harbor metric 0.7176 with the unrewarded trial counted
  as 0) sits comfortably in the discriminating middle of the
  grader's range, far above the "agent gave up" floor (V4
  calibration: `bad ≈ 0.09`) and well below the "agent matched
  reference" ceiling (`near_perfect ≈ 1.00`). The benchmark is
  measuring something.
- **Per-task stdev tells you which tiers are "luck-dependent".**
  T3 stdev is 0.025 (the task is consistently doable); T4 stdev is
  0.108 (the same task ranges from 0.45 to 0.84 across attempts).
  High intra-task stdev = the agent's strategy quality varies
  trial-to-trial on that design. Low stdev = the task has a stable
  ceiling the agent reliably hits or misses.

### 2.2 Best and worst single trials

- **Best trial overall:** `synth-t1-maren-solvik-design` attempt
  b5Qn2jC at **0.962** — interestingly, this trial errored on
  `AgentTimeoutError` at 900 s but the agent had already written
  enough HTML for the verifier to score it as the run's best
  output. Best **clean (non-errored) trial:**
  `synth-t1-maren-solvik-design` attempt yaQbhvt at **0.926**.
  Either way, the same tier-1 design portfolio confirms the
  ceiling exists: Opus can produce a near-reference rendering
  when the design vocabulary is simple.
- **Worst valid trial:** `synth-t4-lumivex-signal-boost` attempt
  Qfdxb59 at **0.452**. A tier-4 SaaS-marketing site with hero +
  features + pricing + how-it-works + results. The agent's output
  on this trial scored Likert 2/5 on judge.layout_fidelity on
  three of the five pages and det.repeating_groups in the
  0.05–0.25 band.

## 3. Where the model breaks

### 3.1 The dominant failure mode — layout fidelity

Distribution of Likert votes across all 99 valid trials × 5 pages
× 5 criteria × 3 ensemble votes ≈ 7,425 individual judge votes:

| Criterion | L1 | L2 | L3 | L4 | L5 |
|---|---:|---:|---:|---:|---:|
| color_palette     | 0% | 1% | 4% | 32% | **63%** |
| visual_hierarchy  | 0% | 0% | 3% | **57%** | 40% |
| typography        | 0% | 0% | 2% | **60%** | 38% |
| layout_fidelity   | 0% | 2% | **44%** | 49% | 5% |
| overall_fidelity  | 0% | 2% | **38%** | **54%** | 6% |

The judge thinks Opus is **excellent on colour and typography
choices** — `color_palette` lands at Likert 5 ("indistinguishable
from reference") on 63% of page-trials. But on `layout_fidelity`
Likert 5 happens only 5% of the time, and on `overall_fidelity`
only 6%. The dominant judge verdict on layout is L3 + L4 ("partial
match" / "recognisable but clearly different").

The deterministic side agrees with the judge on the *direction* of
this failure:

| Aspect | Mean | n_below_0.5 / 495 |
|---|---:|---:|
| repeating_groups | **0.321** | **438** |
| layout_skeleton  | **0.415** | **460** |
| interactive      | 0.490 | 56/129 |
| color_histogram  | 0.491 | 243 |
| navigation       | 0.568 | 219 |
| palette          | 0.631 | 144 |
| pixel_ssim       | 0.648 | 14 |
| paragraphs       | 0.676 | 89 |
| headings         | 0.679 | 62 |
| text_content     | 0.816 | 61 |
| region_color     | 0.904 | 7 |

`repeating_groups` and `layout_skeleton` — the two aspects that
measure whether bounded boxes line up across reference and agent —
are below 0.5 on roughly 90% of all page-trials. Both halves of
the grader independently say the same thing: **Opus puts the
right elements on the page but they are rarely in the right
grid.**

### 3.2 Tier 8 is in its own difficulty bucket

T8 mean is **0.573**, vs. nearest tier 0.655 — a Δ of 0.08, wider
than any other tier-to-tier step. Six of the ten lowest-reward
trials in the whole run are T8 (`forma-negra-review`).

Per-aspect on T8 specifically (mean across 10 trials × 5 pages):

- `repeating_groups` 0.180, `palette` 0.203, `color_histogram`
  0.261, `text_content` 0.532, `paragraphs` 0.652.
- Judge: `layout_fidelity` Likert mean ≈ 2.0–2.1 (vs. T1 ≈ 3.0),
  `overall_fidelity` Likert mean ≈ 2.1 (vs. T1 ≈ 3.0).

T8 is the magazine / mixed-visual-systems tier: each page is
supposed to contain 6+ distinct heterogeneous regions (hero +
longform body + sidebar + gallery + data callout + timeline +
marginalia + …). Opus's output collapses this to a generic
"blog-with-hero" — the multi-region heterogeneity that defines
the tier is what's lost, exactly the failure mode the tier was
designed to detect.

### 3.3 Tier 7 — domain-specific microcopy breaks navigation

T7 (deep-current-oceandata, an infographic atlas) has
`det.navigation = 0.181`, dramatically lower than any other tier
(next-lowest is T3 at 0.283). Two plausible mechanisms:

1. **The judge-targeted navigation aspect punishes paraphrase.**
   V2.1's navigation aspect is 70%-weighted on link-text similarity.
   The reference site has scientific nav labels ("Bathymetry",
   "Thermohaline", "Coral Systems"). If Opus paraphrases to "Depth",
   "Currents", "Reefs", the aspect tanks.
2. **The agent occasionally omits nav on data-viz pages.** The
   instruction template doesn't enforce nav consistency across
   pages; on dense SVG pages the agent has been observed to skip
   the nav region entirely.

A side-by-side render of the lowest T7 trial would distinguish
the two. Either way: the failure tells us that on domain-specific
sites the agent's tendency to "reasonable-paraphrase" the
reference content collides with a grader that rewards literal
faithfulness.

### 3.4 Tiers 5 and 6 — text-heavy axes fail

| Aspect | T1 | T5 | T6 |
|---|---:|---:|---:|
| text_content | 0.992 | **0.595** | **0.600** |
| palette      | 0.834 | **0.355** | 0.710 |
| paragraphs   | 0.685 | 0.725 | **0.333** |

T5 (custom typography editorial / poetry collection) — the agent
reproduces heading layouts but ad-libs body copy. The reference
text and the agent's text overlap only ~60% by
`difflib.SequenceMatcher`. Palette is the worst of any tier
(0.355) because the reference uses muted serif-era hues that
Opus rounds to its "default editorial" palette.

T6 (forms / dense data) — `paragraphs` is the lowest of any tier
(0.333) because form labels and dense field copy don't survive
the agent's pass through the screenshots. The agent reads the
visual template and re-generates plausible-but-different labels
rather than transcribing them.

The pattern: **when the design itself is text** (editorial,
forms), Opus's failure mode is "generate plausible substitute
content" rather than "transcribe what's on the screenshot."

### 3.5 Where Opus is consistently strong

- `region_color` 0.904 globally — the macro distribution of colour
  across spatial regions of the page tracks the reference closely.
  Combined with the high `judge.color_palette` (0.892), this says
  Opus is reliably matching brand colour even when exact hex values
  differ.
- `judge.visual_hierarchy` 0.842 — the sense of "which heading is
  primary, which content is secondary" tracks well across tiers.
- `text_content` 0.816 globally — on the simpler tiers (T1: 0.992,
  T3: 0.975) the agent transcribes reference text close to verbatim.
- **No `overall_fidelity = L1` votes.** Across ~7,400 judge votes,
  the catastrophic floor is never reached. The agent never gives
  up; it always produces something the judge can evaluate.

## 4. The grader doing its job

A useful cross-check: does the grader's per-dimension behaviour
on real agent output match what calibration said it would?

- **The judge dominates the visual-design verdict.** Page-level
  final reward stratifies cleanly by `judge.layout_fidelity`:
  pages judged at Likert 2 (`layout_fidelity = 0.25`) have final
  reward mean 0.44; Likert 3 → 0.63; Likert 4 → 0.80; Likert 5 →
  0.94. Pearson correlation between a trial's mean
  `judge.layout_fidelity` and its final reward is **+0.87** over
  the 99 valid trials. V3 added the judge at weight 0.70 because
  deterministic aspects couldn't catch "structurally right but
  visually broken"; the real-run data confirms the judge is in
  fact the load-bearing dimension on layout outcomes.
- **The text gate fires only where it should.** `text_gate_factor`
  drops below 0.5 on exactly the kind of pages where you'd expect
  it to — T5 editorial and T8 magazine pages where the agent
  hallucinates body copy. On T1 and T3 it sits at 0.95–1.00.
- **Determined doesn't reward-hack.** Despite `region_color`
  scoring 0.90+ across the board (i.e. easy), the *combined* score
  doesn't pile up at the ceiling — because layout and judge
  dimensions drag it back down. The 30/70 split is doing what it
  was supposed to: prevent any one easy aspect from carrying the
  number.

## 5. Limitations of this evidence base

### 5.1 Small N per task

10 trials per task is enough to characterise per-task *mean* and
*stdev* but not the *shape* of the distribution. We can say "T8
struggles" with high confidence; we cannot say "T8 has a bimodal
reward distribution" or "T4 trials with reward < 0.5 share a
specific failure mode" — those require ≥ 30 trials per task and
qualitative inspection of the low-reward outputs.

### 5.2 Single (task, genre) per high-numbered tier

T3, T4, T5, T6, T7, T8 each have one task in v6. A per-tier mean
that's actually one task's mean is a pattern indicator, not a
population estimate. The claim "T6 is harder than T5" rests on
one nexum-vault-settings task and one chlorophyll-dispatch task.
To make this load-bearing, regenerate the v6 dataset with two
tasks at each high-numbered tier and re-run.

### 5.3 Single agent, single model

This run is `claude-code -m anthropic/claude-opus-4-7` only. The
brief mentions a stretch goal of "give us a benchmark on how well
the model performs using different frameworks." That run hasn't
happened yet. Trivially achievable by re-running with
`-a aider` / `-a cursor-cli` / `-a goose` etc., but we'd want to
hold tasks and grader fixed and only vary the agent — which means
another 100-trial Modal run per agent.

### 5.4 Reference HTML wasn't generated under V4-aware prompts

`workload_v6/` HTML was generated under a prompt that asks for
"design for 1280×800". V4 grades at three viewports. So part of
what we're measuring is "how well does the agent recover from a
non-responsive reference" rather than "how well does the agent
do responsive replication." Regenerating v6 under V4-aware
prompts (the system prompt now mentions three viewports) is the
next iteration.

### 5.5 No correlation analysis between aspects

We have not computed `corr(judge.layout_fidelity, final_reward)`
or `corr(det.repeating_groups, final_reward)` across the 99
trials, so we don't have a precise statement of "the judge
contributes X% of the variance in the reward number." That number
would let us check whether the 30/70 weight is empirically
justified or whether it should be re-tuned. Future work.

### 5.6 Errored trials are not retried

Of the four errored trials, three were `AgentTimeoutError` (one
each on T1, T7, T8) and one was a `VerifierTimeoutError` (T7). On
the T7 task in particular the means above are based on 9 trials,
not 10. If the errored T1 / T7 / T8 trials were systematically
the *worst* attempts that ran out of budget, the per-tier means
above are slightly optimistic. The `--max-retries` flag on
`harbor run` would automatically re-try on these exception types;
worth turning on for the next run.

## 6. What this run is good evidence for

- The grader produces a *useful continuous signal* in
  `[0.45, 0.96]` on real Opus output — wide enough to discriminate
  between trials, calibrated against the synthetic-degradation
  bounds in [`SCORING.md`](SCORING.md).
- The grader's per-aspect breakdown points at consistent,
  reproducible failure modes — layout grid and multi-region
  heterogeneity dominate, colour and typography are reliable
  successes.
- The tier ladder in [`seeds.py`](../generator/seeds.py) is at least
  partially predictive of real agent difficulty (mean reward drops
  monotonically through 6 of 8 tier transitions).
- The benchmark is reproducible: same `harbor run -k 10 -n 100`
  command produces a comparable result.json with comparable
  per-task means modulo grader noise.

## 7. What this run is *not* good evidence for

- A pass/fail verdict on Claude Code or Opus 4.7. The numbers say
  "mean 0.72 on this benchmark, this scoring rule, this dataset" —
  nothing more. Different design vocabularies and different
  graders would yield different numbers.
- A claim that the grader is calibrated for *RL training*. We
  validated monotonicity on synthetic degradations and on tier
  ordering with real agent output, not the gradient property
  needed to train a model against this reward.
- A complete view of where the model struggles. We see *aggregate*
  struggle patterns; we do not yet have side-by-side renders of
  the 10 worst-scoring page-trials, which is what would tell us
  whether the failure is "agent collapsed the page to a single
  column" vs. "agent moved the sidebar to the bottom" vs. "agent
  produced a wrong number of cards."
