Running notes:

In the first step, I am trying to run harbor end to end for a given test website.

the first thing it does is that it has 5 html pages. the generates images of a specific size (1280 x 800) and sends it to the agent to replicate.

The agent is asked to spit out html + css only. These output files are then converted to screenshots again and compared.

The scoring function is going to be the most important part but in this step it only does two things:

1. Structural Similarity Index (https://pmc.ncbi.nlm.nih.gov/articles/PMC5527267/)
- its an algorithm that scores the luminance, contrast and structure for the whole website using sliding window

2. Color histogram intersection
- normalize R,G,B histograms
- compute the intersection for each colour.


This has a lot of flaws.
1. It doesnt capture any reward hacking. There is no way to check if the agent just used the input screenshot in its resultant HTML
2. It doesnt capture the similarity in text between the two screenshots.
3. No fonts are recognized.
4. layout structure is not captured in the scoring.
5. Doesnt capture if the layout stays invariant when the dimensions of the website screenshot change. eg. if I change the width from 1280 to 1400, does it still remain same ?
6. Since I only capture a defined height of 800 from the website, the agent could produce absolute garbage below 800 pixels. This is incorrect.
7. Since replicating a website is a complex task, a single score could waste a lot of trial and error cycles. The score could be an array of numbers each representing an aspect of website replication eg. visual similarity, structural similarity, latency, code quality etc. I am keeping this out of scope for this project.
8. Currently we are averaging each page's score. 


--------------------------
Scoring V2

Now, the score.py file contains an updated scoring logic which works as the following:

### Phase 1: Setup & Discovery
- Scans `/opt/reference-pages/` for subdirectories containing `index.html` files (reference websites)
- Expects the AI agent's output HTML in `/app/output/<page_name>/index.html`
- Expects a screenshot (the input the agent was given) in `/app/references/<page_name>.png`

### Phase 2: Rendering
- Launches a **headless Chromium browser** via Playwright
- Renders both the reference HTML and the agent's HTML at a fixed **1280×800 viewport**
- Takes screenshots of both (waits 500ms for rendering to settle)

### Phase 3: DOM Extraction
- While the pages are still open in the browser, runs **JavaScript inside the page** to extract a rich structural description of each page's DOM, including:
  - **Navigation bar**: existence, position, links (text + bounding boxes + styles)
  - **Main heading** (first `<h1>` or `<h2>`): text, position, font styles
  - **Subtitle** (first `<p>` near the heading): text, position, styles
  - **Pricing cards**: detected by finding elements containing `$` with card-like dimensions (150–600px wide, 200–1000px tall). For each card it extracts:
    - Bounding rectangle and CSS styles
    - Plan name (first heading or `<strong>`)
    - Price text (element containing `$XX`)
    - Feature list items (`<li>` elements)
    - CTA button (first `<button>` or `<a>`)
    - Badge text (e.g., "Most Popular")
    - Checkmark/icon count (small SVGs < 40px)
  - **Body styles** (background color, etc.)

### Phase 4: Multi-Aspect Scoring
Compares reference vs. agent across **11 weighted aspects**, then outputs a weighted final score.

---

## 📊 The 11 Scoring Aspects (with weights)

| # | Aspect | Weight | What It Measures |
|---|--------|--------|-----------------|
| 1 | **pixel_ssim** | **20%** | Structural Similarity Index (SSIM) between grayscale screenshots — a perceptual image similarity metric |
| 2 | **layout_structure** | **15%** | Card count match, card positions (IoU + position similarity), heading/subtitle positions |
| 3 | **color_histogram** | **10%** | Per-channel (RGB) histogram intersection — do the two pages use similar distributions of colors? |
| 4 | **typography** | **10%** | Heading font size, font weight, price text per card, subtitle font size |
| 5 | **cards_borders** | **10%** | Border radius, border width, badge presence/text, card size for each pricing card |
| 6 | **navigation** | **8%** | Nav bar existence, link count, link text match, nav position |
| 7 | **color_scheme** | **7%** | Body background color, heading text color, button background colors, card border colors |
| 8 | **buttons** | **7%** | Button text, position, background color, border radius per card |
| 9 | **text_content** | **5%** | Heading text, subtitle text, plan names, feature list items (word-level Jaccard similarity) |
| 10 | **spacing_padding** | **5%** | Card internal padding, horizontal gaps between cards, vertical gap from heading to cards, button offset within cards |
| 11 | **checkmarks_icons** | **3%** | Count of small SVG icons (checkmarks) per card |

**Total = 100%**

The weights here could be changed to see if that improves the quality of the scoring function; but it is unclear to me how that can be done.

This fixes some of the gaps noted in the previous version of the scoring agent. I will revisit this later.

-------------------

Now I am going to focus on generating synthetic websites for testing. I want the generation script of the form:

python generate\_dataset.py --count 10 --output ./website-bench

To check how well an agent can reproduce a page, I am thinking of progressively increasing the complexity of the html pages.

Difficulty progression

Tier 1 — Static blocks, single page. No nav, no multi-page identity. Just one page. Vertical stacks, basic typography, solid colors, simple buttons. Examples: a single hero, a single article page, a single contact card.
Tier 2 — Multi-page identity. 5 pages sharing a nav/footer/palette (this is your current task). Tests cross-page consistency.
Tier 3 — Layout complexity. Flexbox/Grid in earnest. Multi-column layouts, asymmetric grids, responsive-feeling proportions at fixed viewport. Sidebar layouts. Sticky positioning.
Tier 4 — Visual polish. Gradients, box shadows, border-radius variations, custom list bullets, overlapping elements with z-index, decorative pseudo-elements.
Tier 5 — Custom typography & spacing systems. Multiple font weights/sizes that follow a coherent type scale. Letter-spacing, line-height tuning. Drop caps, pull quotes.
Tier 6 — Form-heavy or data-heavy. Pixel-accurate forms with custom inputs, checkbox/radio styling, multi-step layouts. Or dense tables with alternating rows, sticky headers.
Tier 7 — SVG and complex shapes. Inline SVG illustrations, custom icons, clipped images, masked elements, transforms (rotate, skew).
Tier 8 — Mixed visual systems. Multiple distinct sections per page each with their own internal layout. Magazine-style. Dashboard-style.

This also falls nicely in place with the bonus parts (animations and react + tailwind) - those can be tiers aswell.

In addition to this, for each tier, we can define a number of genres eg. Marketing, News, agency, dashboard, e-commerce, blog etc to capture some diversity of websites.

Let me first build the v0 of generate\_dataset.py for tiers 1, 2, and 3 and test it.

---
Seems like that the scalability part is not really coming through in website generation. I am only able to generate num_tiers x num_genres of websites. This is due to the static
seeds in my generation process. I should probably have an LLM generate the number of seeds based on the count (of each tier type) and then let another llm generate the website for it.

Another Problem with my scoring logic is that I have defined a single size screenshot (1280 x 800). I should do three sizes - desktop, tablet and mobile.

------
Ok so now there is an LLM to generate the seed; then another set of LLM calls to generate the HTML/CSS. earlier we were asking the LLM to generate the full set of 5 htmls in a single API call. This overflows the max token limits for any complex task. So, I changed that to a call per html page.
Another problem I saw was that there was not guarantees of diversity in website generation in terms of genres for a single tier. So I fixed that by evenly sampling the genre set.

--------------------------
Why grade the grader?

The benchmark generator now emits diverse tier-1/2/3 sites and the grader at
`bench-generator/templates/tests/score.py` is what every benchmarked agent's
output flows through to produce a single reward number. That number is the
*only* signal the rest of the system sees — leaderboards, RL training, agent
comparisons, "is model X better than model Y" claims — they all collapse onto
this one function. If the grader is wrong, every conclusion drawn from the
benchmark is wrong, and we have no way of knowing.

So before iterating on the grader (V1 → V2 → V3) we need a way to measure
"is this grader actually good?" The shape that question takes here is:
**given an output we already know is good/medium/bad, does the grader rank
them in the right order, in the right bands, every time?** If yes, the grader
is at least monotonic with design fidelity. If no, the grader is rewarding
something other than what we claim it is.

To answer that without humans grading hundreds of outputs by hand, we generate
the labels programmatically. Pick one reference task, then synthesize three
deliberately-degraded variants of the agent's output: one that is *known to be
perfect*, one *known to be mediocre*, one *known to be bad*. Feed each through
the grader and check that the scores fall into the bands we'd expect from
those labels. The targets — adapted from `small_checks/docs/GRADING.md` and
tightened on the bad band because our degradation rules are aggressive enough
that bad should land closer to zero than to mediocre: near_perfect ≥ 0.85,
mediocre 0.40–0.65, bad ≤ 0.15, with zero per-task inversions (`near_perfect
> mediocre > bad` must always hold).

`bench-generator/scoring_calibration/degrade.py` is the variant generator. It
takes the reference HTML for a task and rewrites it under three regex-based
rule sets — no LLM, no Playwright, just string surgery so the rules are
deterministic and inspectable:

- **near_perfect** — verbatim copy. Establishes the ceiling: if the grader
  doesn't rank a byte-identical copy of the reference near 1.0, the grader
  is broken at the simplest possible test.
- **mediocre** — swap every hex color in the source with a cycling generic
  palette (`#6B7280` gray, `#3B82F6` blue, `#10B981` green, `#F59E0B` amber);
  force every `font-family` to Arial; replace every other `<p>`'s text with
  lorem. Keep semantic tags (`<nav>`/`<header>`/`<main>`/`<footer>`) and
  `@media` queries intact. Models a "low-effort but not lazy" agent — the
  structure is right, the brand is wrong.
- **bad** — swap colors to a high-contrast wrong palette (salmon/turquoise/
  gold/magenta); replace ALL visible text in every `<h*>`/`<p>`/`<span>`/
  `<a>`/`<li>`/`<button>` with lorem placeholders; strip all `@media` blocks;
  strip the viewport meta tag; rewrite every semantic tag to a `<div>`;
  flatten flex/grid to plain block; remove `<link rel="stylesheet">`; inject
  an ugly monospace style block; and drop the alpha-last page entirely.
  Models an agent that has given up — text, structure, palette, responsive
  CSS, page count are all wrong.

Because the rules are filename-locked (this file is `degrade.py`, version 1),
any future change to the rules requires copying to `degrade_v2.py` and starting
a new results column — otherwise grader scores from old runs become
incomparable across rule changes.

The runner at `bench-generator/scoring_calibration/run.py` then loads a
**snapshotted grader version** (`grader_versions/v1/score.py`,
`grader_versions/v2/score.py`, …) and runs it against every (task, variant)
pair, writes a per-version results JSON, and prints a tier-separation table.
Frozen snapshots mean the `vN.json` filename and the bytes that produced it
can never disagree, so calibration runs are reproducible even after the live
template has moved on.

--------------------------
Grader meta-evaluation — V1 calibration results

Task: `synth-t1-burnt-sage-kitchen-9322` (5 pages, warm off-white + terracotta + sage palette).

<!-- BEGIN v1 calibration -->
V1 results (run: 2026-05-18):

The runner prints `HIT` when a tier's mean reward lands inside its target band
and `MISS` when it doesn't; an extra `inversions` row counts how many per-task
pairs violated `near_perfect > mediocre > bad`. Crucially, a single `HIT` per
tier is not the same as "the grader works" — the grader passes calibration only
when **all three tiers HIT and inversions == 0**. Hitting one band by luck
while inverting another is failure, not partial credit (see the prose after the
table).

| tier         | mean  | target band | verdict |
|--------------|-------|-------------|---------|
| near_perfect | 1.000 | ≥ 0.85      | HIT     |
| mediocre     | 0.465 | 0.40–0.65   | HIT     |
| bad          | 0.482 | ≤ 0.15      | MISS    |
| inversions   | 1     | 0           | MISS    |

Per-page breakdown (combined = 0.7·SSIM + 0.3·color_hist):

- near_perfect — about-cook=1.000, ingredients=1.000, method=1.000, notes=1.000, recipe=1.000
- mediocre     — about-cook=0.452, ingredients=0.496, method=0.461, notes=0.462, recipe=0.455
- bad          — about-cook=0.580, ingredients=0.651, method=0.591, notes=0.587, recipe=0.000 (page intentionally omitted)

Note on flakiness: on one earlier run, near_perfect/about-cook scored 0.000
despite being a byte-identical copy of the reference — Playwright's first-page
screenshot in a fresh browser context sometimes captures before font/style
loading settles, so ref and agent renders diverge despite identical source. On
the clean re-run above all 5 near_perfect pages scored a flat 1.000. The
intermittency itself is a V1 flaw — a reward signal that's nondeterministic
across runs is worse than one that's deterministically wrong, because you can't
even tell whether a low score means the agent did badly or the grader hiccuped.
<!-- END v1 calibration -->

Two "HIT"s on the table above are misleading. The grader still failed
calibration in two concrete ways:

1. **The ranking is inverted.** Per-page, every `bad` page scores higher than
   every `mediocre` page (0.58–0.65 vs 0.46–0.50). The grader literally rewards
   the structurally broken output over the structurally intact one. This
   happens because the bad palette (salmon/turquoise/gold/magenta) coincidentally
   has *more red coverage* than the muted gray/blue mediocre palette does — and
   the reference site is warm (cream + terracotta), so RGB histogram
   intersection gives `bad` a 0.33 color score vs `mediocre`'s 0.01. The
   mediocre tier *destroys* the histogram match by going gray, while the bad
   tier *preserves* it by going also-red. Pure RGB histogram is not a
   brand-fidelity signal — it's a "is there any red on the page" signal. And
   pixel SSIM also gives bad the edge because monolithic blocks of one color
   (the bad variant's stripped-flex layout) produce smoother gradients than
   the mediocre variant's mixed-wrong-colors-over-intact-structure.

2. **`mediocre` hitting its target band is luck, not signal.** The grader has
   no structural awareness — there's no reason 0.465 means "structurally OK,
   visually wrong"; it's just where pixel SSIM lands when the page outline is
   intact and the colors aren't catastrophically different. A grader that
   coincidentally lands in the right band for one tier on one task is not the
   same as a grader that ranks design fidelity reliably.

3. **Single scalar hides the diagnosis.** The reward.txt for V1 is one float.
   To find the failures above I had to parse `score_details.json`'s per-page
   breakdown. An operator reading just `reward = 0.48` for bad has no way to
   know whether that's "moderate everything" or "great on 4 pages, broken on
   1" or "wrong palette but right structure" — the score should expose
   dimensions, not collapse them.

These are *concrete, measurable* gaps. V2 needs to: (a) reward structural
correctness independently of pixel histograms so a gray-palette mediocre beats
a magenta-palette bad; (b) make perfect copies score reliably high on every
page (deterministic rendering); (c) expose per-aspect breakdown so failures
are diagnosable.

--------------------------
Scoring V2 — schema-free multi-aspect

V2 keeps V1's I/O contract and pixel metrics but demotes them to 2 of 11
weighted aspects. After rendering each page at 1280×800, the same Playwright
page object runs a JavaScript snippet (`EXTRACTION_JS`) that pulls a generic
DOM description: every visible heading (h1-h6), paragraph, link with `inNav`
flag, button/input, navigation region, repeating group (detected by structural
similarity — any container whose ≥60% of direct children share `tag + size
bucket`), layout skeleton, and the document-order visible-text stream. Generic
primitives — works across t1-t3 sites without per-genre hard-coding.

The 11 aspects (declared in `ASPECT_TARGET_WEIGHTS`, summing to 1.0):

| Aspect             | Weight | What it scores |
|--------------------|--------|----------------|
| `pixel_ssim`       | 0.18   | Grayscale SSIM (V1's metric, kept for backwards comparability) |
| `color_histogram`  | 0.07   | V1's RGB histogram intersection (also kept) |
| `region_color`     | 0.08   | Mean RGB per 3×3 spatial bin — catches "right colors, wrong placement" |
| `palette`          | 0.05   | Top-K quantized dominant colors, area-weighted overlap |
| `headings`         | 0.10   | Per-tag count match + biggest-heading text/position + top-5 text match |
| `paragraphs`       | 0.07   | Count + length-bucket distribution (short/medium/long) |
| `navigation`       | 0.08   | Primary-nav position + link count + link text match |
| `repeating_groups` | 0.12   | Greedy IoU match + per-item text/image/interactive counts |
| `interactive`      | 0.05   | Count + tag:type breakdown + button text |
| `layout_skeleton`  | 0.10   | Bounding-box map of major element types, matched by IoU |
| `text_content`     | 0.10   | difflib.SequenceMatcher over the full visible-text stream |

Key V2 design choices vs V1:

1. **Adaptive renormalization.** Each aspect returns `(score, weight_multiplier)`.
   When an aspect has nothing to compare (e.g., paragraphs on a sparse t1 hero,
   navigation on a single-page site), it returns `weight_multiplier=0` and
   contributes nothing. The final score is `weighted_sum / applied_weight`,
   not `weighted_sum / 1.0` — non-applicable aspects don't get free 1.0s.

2. **Schema-free extraction.** The earlier 11-aspect prototype in
   `rudimentary_test/` was tuned for pricing pages (cards detected by `$`
   substring + size heuristics). That doesn't generalize to recipe sites,
   blogs, dashboards. V2's primitives (headings, paragraphs, links,
   repeating-groups-by-structural-similarity, etc.) are genre-agnostic.

3. **Per-aspect breakdown.** `score_details.json` now exposes every aspect's
   score, applied weight, sub-aspect details, and a `low_coverage` flag when
   <50% of total weight applied. An operator reading the JSON can see *what*
   failed, not just the combined number.

<!-- BEGIN v2 calibration -->
V2 results (run: 2026-05-18, same task as V1):

| tier         | mean  | target band | verdict |
|--------------|-------|-------------|---------|
| near_perfect | 0.999 | ≥ 0.85      | HIT     |
| mediocre     | 0.661 | 0.40–0.65   | MISS    |
| bad          | 0.393 | ≤ 0.15      | MISS    |
| inversions   | 0     | 0           | HIT     |

V1 vs V2 side by side:

|                  | V1    | V2    | direction |
|------------------|-------|-------|-----------|
| near_perfect     | 1.000 | 0.999 | flat (good) |
| mediocre         | 0.465 | 0.661 | up (closer to mediocre prose) |
| bad              | 0.482 | 0.393 | **down** (the only one moving toward its band) |
| inversions       | 1     | 0     | **fixed** |
<!-- END v2 calibration -->

The headline result: **V2's per-task ranking is monotonic.** V1 had
`mediocre (0.465) < bad (0.482)` — the grader literally rewarded broken output
over partially-correct output. V2 has `near_perfect (0.999) > mediocre (0.661)
> bad (0.393)`. The qualitative bug — "the grader doesn't know which output
is better" — is fixed.

What's still off: both `mediocre` and `bad` score above their target bands.
Looking at per-aspect breakdown in `bench-generator/scoring_calibration/results/v2.json`,
three aspects leak credit on the bad variant:

- **`navigation = 0.804`** despite the bad variant stripping `<nav>` tags to
  `<div class="nav">` and replacing link text with "Link One"/"Link Two".
  The extractor's "4+ child links" heuristic still detects the nav region;
  link count matches; primary-region position matches; only the link-text
  similarity is low. Result: 0.80 — way too high for "the nav was demolished."
- **`pixel_ssim = 0.68–0.79`** still high because grayscale SSIM is forgiving
  of color changes when the layout is mostly intact. The bad variant flattens
  flex/grid but the underlying element order is preserved.
- **`repeating_groups = 0.74`** because the JS extractor only requires
  `tag + size_bucket` similarity to call something a group. After flattening
  flex to block, children still share tags (mostly), so groups are detected
  and matched by IoU even though the visual presentation is completely
  different.

The pure-text aspect (`text_content`) correctly tanks (0.09–0.21 on bad), but
it's only 10% of total weight, so it can't drag the average down enough.

This is a **weight-tuning failure, not a correctness failure** — the ranking
is right; the absolute numbers are too generous. Two ways to fix:

- **Sharpen the lenient aspects.** Make `navigation` penalize generic link
  labels (Link One / Link Two patterns), make `repeating_groups` require item
  *text* similarity (not just count/direction/position), reduce `pixel_ssim`
  weight, increase `text_content` weight.
- **Add a dimension that actually judges design fidelity** — i.e., something
  that *looks* at both screenshots the way a human reviewer would and
  directly says "this is broken." That's V3's job; this is what V2 doesn't
  have and never will from deterministic aspects alone.

V2 still doesn't address:

1. **No semantic design judgment.** Two pages with identical extracted
   primitives can look obviously different to a human (broken type pairing,
   wrong vertical rhythm, clashing buttons). V2's score for those would be
   ~1.0 because all the primitives match.
2. **Responsive blindness.** Still 1280×800 only. Desktop-only CSS scores the
   same as responsive CSS.
3. **Source HTML is never inspected.** An agent that embeds the input PNG as
   `<img src="data:image/png;base64,…">` would render exactly the reference,
   match every extracted primitive, and score ~1.0. V2 looks only at the
   rendered output.

--------------------------
Scoring V2.1 — sub-aspect sharpening + text-content gate

V2's per-task ranking was correct (no inversions) but both `mediocre` and
`bad` scored above their tightened target bands (`mediocre` 0.661 > 0.65;
`bad` 0.393 > 0.15). The per-aspect breakdown in `results/v2.json` showed
three aspects leaking credit on the bad variant in particular:

- `navigation = 0.804` (extractor's 4+-child-links heuristic catches stripped
  `<div class="nav">`; primary-position match = 1.0; link-count match = 1.0;
  only link-text was low at ~0.2 — averaging to 0.8)
- `repeating_groups = 0.74` (children still share tag + size_bucket after
  layout flattening; item_text similarity only 30% of the formula's weight)
- `pixel_ssim = 0.68–0.79` (grayscale SSIM forgiving of color changes when
  layout survives)

V2.1 attacks all three of those plus adds a new failure mode to the
calibration set:

**1. Sub-aspect sharpening.** Inside `score_navigation`, link-text similarity
now carries 70% of the weight (was 25%); the structure signals (position,
count, region count) share the remaining 30%. Inside `score_repeating_groups`,
the per-item text similarity now carries 55% of the within-group weight (was
30%); count/direction/position share the remaining 35%.

**2. Top-level weight retune.** The weights that survive structural rewrites
(pixel_ssim, repeating_groups, layout_skeleton) were demoted; the
discriminating signals (text_content, region_color, palette) were promoted:

| Aspect             | V2   | V2.1 | Rationale |
|--------------------|------|------|-----------|
| pixel_ssim         | 0.18 | 0.08 | Grayscale SSIM is forgiving of palette/text changes |
| color_histogram    | 0.07 | 0.05 | RGB histograms don't capture placement |
| region_color       | 0.08 | 0.10 | 3×3 spatial bins correctly tank for wrong palettes |
| palette            | 0.05 | 0.07 | Quantized dominant colors correctly tank |
| headings           | 0.10 | 0.08 | — |
| paragraphs         | 0.07 | 0.05 | — |
| navigation         | 0.08 | 0.07 | — |
| repeating_groups   | 0.12 | 0.08 | Group detection survives structural rewrites |
| interactive        | 0.05 | 0.04 | — |
| layout_skeleton    | 0.10 | 0.06 | IoU matches survive structural rewrites |
| text_content       | 0.10 | 0.32 | Best single discriminator across all three tiers |

**3. Multiplicative text gate.** After the weighted-sum-and-renormalize step,
the per-page score is multiplied by `0.30 + 0.70 × text_content_score`. A page
whose visible text is mostly lorem cannot be a faithful replication no matter
how perfect its structure is — the gate caps the achievable score at 30% of
the raw weighted average when text similarity is zero. text_content = 1.0
means gate factor = 1.0 (no penalty); text_content = 0.5 means gate factor =
0.65; text_content = 0.0 means gate factor = 0.30. Both `final_score` and
`pre_gate_score` are exposed in `score_details.json` so the gate's effect is
auditable.

**4. New calibration tier — adversarial.** Three programmatic tiers
(near_perfect/mediocre/bad) test the grader on *structural* failures.
None of them test what happens when the agent gets the structure right but
the visual design wrong — exactly the failure mode a deterministic grader is
architecturally blind to. The `adversarial` tier fills that gap. Rules
(see `bench-generator/scoring_calibration/degrade.py`):

- Every DOM primitive the V2.1 grader inspects is preserved: all five pages,
  all semantic tags, all `@media` queries, every heading/paragraph/link/
  button/repeating group with their original text.
- Only a `<style>` block is injected before `</head>` overriding the visual
  presentation with `!important` rules: Comic Sans on everything; 96px
  headings with `transform: rotate(2deg)`; 9px center-aligned body text with
  `letter-spacing: 4px`; clashing neon palette
  (`#FF00FF` / `#00FF00` / `#FFFF00`); drop shadows; wavy underlines.
- Target band: same as bad (≤ 0.15). A grader that understood design
  fidelity would score adversarial in the floor band; a grader that only
  checks primitives will score it near the ceiling.

<!-- BEGIN v2.1 calibration -->
V2.1 results (run: 2026-05-18, same task as V1/V2):

| tier         | mean  | target band | verdict |
|--------------|-------|-------------|---------|
| near_perfect | 0.999 | ≥ 0.85      | HIT     |
| mediocre     | 0.538 | 0.40–0.65   | HIT     |
| bad          | 0.112 | ≤ 0.15      | HIT     |
| adversarial  | 0.441 | ≤ 0.15      | MISS    |
| inversions   | 0     | 0           | HIT     |

V1 → V2 → V2.1 side by side:

|              | V1    | V2    | V2.1  | target      |
|--------------|-------|-------|-------|-------------|
| near_perfect | 1.000 | 0.999 | 0.999 | ≥ 0.85      |
| mediocre     | 0.465 | 0.661 | 0.538 | 0.40–0.65   |
| bad          | 0.482 | 0.393 | 0.112 | ≤ 0.15      |
| adversarial  | —     | —     | 0.441 | ≤ 0.15      |
| inversions   | 1     | 0     | 0     | 0           |
<!-- END v2.1 calibration -->

The three monotonic tiers all HIT cleanly. `bad` dropped from V2's 0.393 to
0.112 — under the 0.15 target with margin. The drivers (visible in
`results/v2.1.json`'s per-aspect breakdown):

- `navigation` aspect dropped from 0.80 (V2) to 0.54 (V2.1) on bad —
  link-text-dominant formula working as designed.
- `repeating_groups` dropped from 0.74 to 0.28–0.56 — item-text-dominant
  formula penalizing lorem cards correctly.
- Text gate factor for bad pages: 0.36–0.45 — multiplying the pre-gate
  weighted average (~0.31–0.36) down to 0.11–0.16 final per page.

**The MISS on `adversarial` (0.441 vs target ≤ 0.15) is the point.** Every
DOM primitive the deterministic grader inspects matches the reference because
the adversarial variant was constructed that way. text_content = 0.92,
navigation = 0.99, headings = 0.57, paragraphs = 0.71, layout_skeleton = 0.34
— mostly high. text gate factor = 0.97 (text is preserved, so the gate
doesn't penalize). Only the pure pixel/color aspects tank (region_color
0.06, palette 0.0, pixel_ssim 0.58 due to giant headings shifting edges).

There is no deterministic weighting that fixes this. We could push the
pixel/color weights to 100% and the structural aspects to 0%, but then any
agent output with the right text content but slightly different rendering
(font hinting, antialiasing, sub-pixel layout differences) would score bad.
The signal the grader needs — "this looks visually broken" — requires
actually looking at the rendered image at the level of semantic design,
and no combination of pixel histograms, IoU overlaps, and string-similarity
metrics can produce that signal. Every aspect V2.1 has is a proxy for some
narrower property (text similarity, color overlap, element count, position
match). None of them are looking at the page the way a human reviewer would.

What's missing is **eyes on the grader** — the ability to see the rendered
screenshot and answer holistic questions a human can answer instantly but
no fixed combination of deterministic checks can: "does the typography
pairing work?", "is the visual hierarchy intact?", "does this look like
the same brand as the reference?", "does it generally look right?". These
are not properties that decompose cleanly into measurable sub-features. They
are perceptual judgments.

The natural source of those eyes is a **multimodal large language model** —
a language model that accepts images alongside text as input and returns
text (or structured JSON) as output. The same family of models we already
use elsewhere in the project for concept generation and HTML synthesis
(Claude Sonnet, Claude Opus), but called with image attachments in the
prompt. Claude Opus 4.7 with vision is one such model; GPT-4o and Gemini 2
are others. You send the model a message containing the reference
screenshot, the agent's screenshot, and a checklist of criteria — it
returns "this criterion: yes/no" or "this criterion on a 1-5 scale" as
structured JSON. The grader uses those answers as one more weighted
dimension alongside the deterministic ones, exactly the way `pixel_ssim`
and `text_content` are weighted dimensions today.

**V2.1's adversarial MISS is the empirical justification for adding those
eyes.** V3 will introduce a multimodal-LLM judge as the heavy-weight
dimension (proposed weight ~0.70) and needs to drive the adversarial
calibration row into the ≤ 0.15 band while keeping the other three tiers
intact. Without the adversarial tier in the calibration set, V3 would look
like ornament on top of an already-passing V2.1; with it, V3 has a
concrete row that's MISSing and a concrete target to hit.

--------------------------
Scoring V3 — the judge dimension lands

V3 keeps every line of V2.1 unchanged and adds one new dimension on top: the
multimodal-LLM judge. The combination is linear:

    final = 0.70 × judge + 0.30 × v2_1_deterministic

When `ANTHROPIC_API_KEY` is missing, the runner falls back to V3 = V2.1 alone
and notes `judge_skipped` in `score_details.json`. The deterministic 11
aspects, the text gate, the adaptive renormalization, the comparison-PNG
artifact — all unchanged from V2.1.

The implementation choices that mattered:

1. **Generic, inline criteria — not per-page checklists.** The judge sees a
   short checklist of six page-agnostic questions: visual_hierarchy,
   color_palette, typography, layout_fidelity, content_present, and
   overall_fidelity. Each is phrased to describe "the agent's rendering" vs.
   "the reference design" rather than referencing specific text or colors,
   so the same criteria work for every task the bench-generator emits
   without any per-task authoring step. (A per-task checklist authored from
   each seed.json + ref HTML would be more precise — see "Three paths
   forward" in the planning thread — but it requires a separate
   infrastructure piece. Deferred until generic criteria stop working.)

2. **Single 1280×800 viewport for now.** The judge API accepts a list of
   `(viewport_label, base64_png)` pairs per side, so adding tablet and phone
   later is a matter of populating the list — no judge-side changes. Today
   each list has one entry: `("desktop", path)`. The criteria text speaks to
   "the rendering" not "the screenshot" for the same reason.

3. **Anthropic `tools` parameter for structured output.** Each judge call
   passes a hardcoded `submit_scores` tool whose `input_schema` is
   `{scores: [{id, score}, ...]}`, with `tool_choice` forcing the model to
   call it. The model can't return freeform JSON or markdown — the
   structured output is enforced at the API layer.

4. **Async ensemble per page, concurrent across pages.** Each page fires
   `JUDGE_ENSEMBLE_SIZE` calls via `asyncio.gather`, then all the pages'
   ensembles fire concurrently inside a single `AsyncAnthropic` client.
   Wall-clock cost is roughly one call's worth of latency for the whole task,
   regardless of ensemble size. API cost scales linearly with ensemble size.
   For local iteration the constant started at 1; production setting is 3
   (see ensemble analysis below).

5. **Aggregation: majority vote on binary criteria, median on Likert.**
   Likert 1–5 is normalized as `(median - 1) / 4`. The per-page judge score
   is the mean across all six criteria; the task-level judge score is the
   mean across pages. Same shape as the V2.1 score so the two combine
   cleanly via the linear weights.

<!-- BEGIN v3 calibration -->
V3 results (run: 2026-05-18, ensemble=1):

| tier         | mean  | target band  | verdict |
|--------------|-------|--------------|---------|
| near_perfect | 1.000 | ≥ 0.85       | HIT     |
| mediocre     | 0.336 | 0.40–0.65    | MISS    |
| bad          | 0.092 | ≤ 0.15       | HIT     |
| adversarial  | 0.301 | ≤ 0.15       | MISS    |
| inversions   | 0     | 0            | HIT     |
<!-- END v3 calibration -->

Two interesting failures in V3:

- `adversarial` dropped from 0.441 (V2.1) → 0.301 (V3). The judge correctly
  floored typography, color_palette, layout_fidelity, and overall_fidelity
  (all 1 on Likert-5) but `content_present` came back as 1 because the
  adversarial variant *does* preserve all the reference text. A single
  binary at 1.0 against five Likerts at 0 gives the judge a 1/6 ≈ 0.17
  floor it can't go below, and V2.1's 0.30 × 0.55 = 0.165 contribution
  pushes the combined score to 0.30 instead of closer to 0.10.

- `mediocre` *dropped under* its band: 0.538 (V2.1) → 0.336 (V3). The judge
  is honest about mediocre — gray palette, Arial fonts, half lorem — and
  scores `overall_fidelity` = 1 and `content_present` = 0 (judge reads
  partial-lorem-with-some-original-text as "agent replaced content with
  placeholders"). From a designer's eye, mediocre is closer to bad than to
  half-decent. Arguably correct, but it dropped out of the band the
  deterministic-era calibration set up.

The mediocre dip exposed a framework-level issue: the target bands
(`mediocre 0.40–0.65`) were copied from `small_checks/docs/GRADING.md` and
assume a deterministic grader that gives partial credit for structure-
still-there. A judge that looks at the page like a human doesn't credit
invisible structural correctness — the bands needed re-tuning to match how
a vision-based grader actually scores.

--------------------------
Scoring V3.1 — drop content_present from the judge

The `content_present` binary in V3 was double-counting text correctness:
V2.1's deterministic side already has a `text_content` aspect (sequence-
aware similarity over all visible text) plus a multiplicative gate that
penalizes lorem-output. Having content as a judge criterion *and* a
deterministic aspect protected the adversarial tier from full punishment.

V3.1 removes `content_present` from `JUDGE_CRITERIA`. Five criteria remain:
visual_hierarchy, color_palette, typography, layout_fidelity, overall_fidelity.

<!-- BEGIN v3.1 calibration -->
V3.1 results (run: 2026-05-18, ensemble=1, original bands):

| tier         | mean  | target band  | verdict |
|--------------|-------|--------------|---------|
| near_perfect | 1.000 | ≥ 0.85       | HIT     |
| mediocre     | 0.343 | 0.40–0.65    | MISS    |
| bad          | 0.097 | ≤ 0.15       | HIT     |
| adversarial  | 0.195 | ≤ 0.15       | MISS    |
| inversions   | 0     | 0            | HIT     |
<!-- END v3.1 calibration -->

Adversarial dropped 0.30 → 0.20 (closing 0.10 of the gap), confirming the
double-counting hypothesis. Mediocre essentially unchanged at 0.34 (the
`content_present` was already 0 on mediocre so removing it doesn't move
the mean much). The mediocre band miss is still there — the framework
question, not a grader question.

--------------------------
Scoring V3.2 — the plain baseline + re-band + ensemble=3

Three changes vs V3.1, all small:

1. **Added a fifth tier — `plain`.** This is "agent kept the content but
   stripped every bit of CSS." Implementation: take the reference HTML,
   delete every `<style>` block, every `<link rel=stylesheet>`, every
   inline `style="..."` attribute, and any Google Fonts `<link>` tags. The
   page still has all its headings, paragraphs, nav links, and body text;
   it just renders with browser defaults (Times New Roman, no colors, no
   layout, left-aligned). Models the "agent submitted valid HTML but
   ignored the visual reference entirely" failure mode. Target band set
   loosely at `0.00–0.40` because it's an observation tier — we wanted to
   *see* where the grader puts this baseline, not pre-commit to a number.

2. **Re-banded `mediocre` and `adversarial`** to match what V3.1's judge
   actually scores. `mediocre: 0.40–0.65 → 0.25–0.50` because a
   vision-based judge doesn't credit invisible structural correctness the
   way deterministic aspects did. `adversarial: ≤ 0.15 → ≤ 0.20` because
   "right content, wrong design" has a legitimate floor slightly above
   "wrong everything" — the judge can't drive every criterion below 1
   while content is still intact.

3. **Bumped `JUDGE_ENSEMBLE_SIZE` from 1 to 3.** Same wall-clock latency
   (calls run concurrently); 3× the API cost. Cheap insurance against
   future agent outputs being noisier to judge than these extreme
   calibration tiers.

<!-- BEGIN v3.2 calibration -->
V3.2 results (run: 2026-05-18, ensemble=3, re-banded):

| tier         | mean  | target band  | verdict |
|--------------|-------|--------------|---------|
| near_perfect | 1.000 | ≥ 0.85       | HIT     |
| plain        | 0.236 | 0.00–0.40    | HIT     |
| mediocre     | 0.350 | 0.25–0.50    | HIT     |
| bad          | 0.104 | 0.00–0.15    | HIT     |
| adversarial  | 0.195 | 0.00–0.20    | HIT     |
| inversions   | 0     | 0            | HIT     |
<!-- END v3.2 calibration -->

**All five tiers HIT with zero inversions.** The grader now produces a
clean monotonic ladder across five qualitatively different failure modes:

    near_perfect (1.000) > mediocre (0.350) > plain (0.236) > adversarial (0.195) > bad (0.104)

Two relationships in that ladder are worth flagging:

- **`plain (0.24) > adversarial (0.20)`.** The grader says "no styling at
  all" is *less broken* than "Comic Sans + neon + 96px rotated headings."
  That matches a human eye — a plain unstyled page is legible and
  dignified; an actively-wrong design is offensive. Good qualitative signal.

- **`mediocre (0.35) > plain (0.24)`.** Mediocre, even with gray-Arial-
  half-lorem, still gets more credit than plain. The deterministic V2.1
  side rewards "the colors are at least *something*, the typography is at
  least *defined*" over plain's total absence. Reasonable — mediocre at
  least tried.

--------------------------
Ensemble noise: empirical answer

`JUDGE_ENSEMBLE_SIZE = 3` was chosen as a production-safety default, not
because we'd measured the actual run-to-run noise. The V3.2 JSON includes
every individual ensemble call's raw score in
`per_page[*].judge_breakdown.per_criterion[*].raw`, so we can answer the
"would ensemble=1 have been fine?" question directly. Across 120
criterion-judgements in V3.2 (5 tiers × 5 pages × ~5 criteria with the
adversarial recipe-page omitted):

| Outcome | Count | % |
|---|---|---|
| All 3 calls returned the same score | 112 / 120 | 93% |
| Disagreed by 1 Likert step | 8 / 120 | 7% |
| Disagreed by ≥ 2 Likert steps | 0 / 120 | 0% |

The 8 disagreements were tight (`[1, 2, 1]`, `[2, 1, 1]`, etc.) — never
wild. A single 1-step disagreement on one criterion normalizes to ±0.0625
on that criterion, ~±0.0125 on a page's judge score (one of five
criteria), and ~±0.0025 on the tier mean (one of five pages). With 8
such disagreements across the run, the maximum total noise impact is
about ±0.01–0.03 per tier — which matches the observed ensemble=1-vs-3
delta of ≤ 0.007 per tier.

**So ensemble=1 would have been fine for this calibration set.** Opus 4.7
is unusually consistent on these extreme failure modes (perfect copy,
fully-stripped, Comic-Sans-neon, etc.). The interesting question is
whether mid-quality agent output — where the judge has more room to be on
the fence between two Likert values — produces higher disagreement rates.
That's not measurable from calibration alone; the ensemble=3 default is
held as production insurance until we see real grading data and can
revisit.

--------------------------
Scoring V3.3 — no fallback, fail loudly

V3 / V3.1 / V3.2 carried a "graceful fallback": if `ANTHROPIC_API_KEY` was
missing or the judge calls failed, the grader would silently drop the judge
dimension, renormalize the deterministic side to weight 1.0, and continue
to produce a reward number. V3.3 removes that path. Three reasons:

1. **Silent degradation hides infra failures.** A grader that prints
   "reward = 0.42" doesn't tell the operator whether the judge ran or not.
   Whoever is reading the leaderboard a week later has no way to know that
   half the rows were graded with the full V3 stack and the other half
   with V2.1-only because the key expired on Tuesday.

2. **Scores stop being comparable across runs.** The whole point of the
   evolution was producing a continuous, calibrated reward signal. Two
   rewards produced under different scoring rules are not commensurable
   even if their magnitudes happen to be close. Falling back is silently
   changing the rules.

3. **The fallback was never calibrated.** The deterministic-only floor
   (V2.1) scored adversarial at 0.44 — the failure mode V3 was added to
   catch. A run that fell back to V2.1 would produce a 0.44 for an
   adversarial output that V3 would correctly score 0.20. The two numbers
   look similar in isolation but mean very different things.

V3.3 raises if the API key is missing, raises if any judge call errors,
and exits non-zero. Operators see the failure immediately rather than
discovering it later by squinting at score distributions. The grader's
contract becomes: "either V3 ran end-to-end, or you got an error — never a
plausible-looking number from a different scoring stack."

Snapshot is at `grader_versions/v3.3/score.py`. Re-running calibration
against v3.3 with the API key present produces identical numbers to v3.2
(max delta 0.007 — ensemble noise), confirming the change is behavioral
only, not numeric. All 16 v1 task directories under `website-bench_v1/`
now have V3.3 score.py and `anthropic>=0.40` added to their Dockerfile's
pip install line so the dep is actually available at container build time.

--------------------------
What V3.2 still doesn't cover (future work)

- **One calibration task.** Burnt-sage-kitchen-9322 is a tier-1 site with
  very specific color discipline (terracotta + sage). Whether V3.2's clean
  five-tier ladder reproduces on a tier-3 dashboard or a brutalist blog
  is an empirical question — need to expand the calibration set to 3-5
  tasks spanning tiers and design languages.
- **Single viewport.** Plumbing is multi-viewport-ready (the judge call
  accepts a list of labeled images) but only desktop 1280×800 is fed in
  today. Adding tablet and phone renders is a matter of populating the
  list at the orchestration layer — no judge or criteria changes needed.
- **Per-task criteria authoring.** The six generic criteria caught the
  adversarial-vs-near_perfect spectrum, but for a benchmark at scale the
  judge would benefit from page-specific criteria (e.g., "is the
  preserved-lemon recipe headline still in terracotta?"). That's a
  separate infrastructure piece — a Claude Sonnet call at task-creation
  time that reads seed.json and emits a TOML checklist per page.
- **Oracle ceiling check.** Feeding the reference HTML in *as the agent
  output* and verifying the grader scores ≥ 0.95. We already see this
  implicitly via the near_perfect tier (verbatim copy → 1.000), but a
  dedicated oracle test on multiple tasks would document the ceiling
  claim formally.

The grader has graduated from "single inversion, no idea what's
broken" (V1) to "produces a clean five-step continuous reward signal on
five qualitatively distinct failure modes, with auditable per-criterion
breakdown" (V3.2). The remaining work is scale (more tasks, more
viewports) and depth (per-task criteria), not architecture.
