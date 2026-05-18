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
those labels. The targets (from `small_checks/docs/GRADING.md`, where the same
approach was used at larger scale): near_perfect ≥ 0.85, mediocre 0.40–0.65,
bad 0.10–0.30, with zero per-task inversions (`near_perfect > mediocre > bad`
must always hold).

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
| bad          | 0.482 | 0.10–0.30   | MISS    |
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
