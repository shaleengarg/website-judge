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