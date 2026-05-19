# Bonus 2 — Multi-Framework Support (React / Solid / Tailwind)

How the current HTML/CSS-only pipeline would be extended to also generate,
build, render, and grade websites written in three additional stacks:

1. **React JS + plain CSS**
2. **React JS + Tailwind CSS**
3. **Solid JS + Tailwind CSS**

For the static-site pipeline this builds on, see
[ARCHITECTURE.md](ARCHITECTURE.md). For the motion extension that introduced
the "concept-stage-stays, codegen+harness fork" pattern this proposal
generalizes, see [BONUS1.md](BONUS1.md).

---

## 1. The thesis in one paragraph

The framework is already cleanly layered: the **concept layer** describes a
*site* (palette, typography, page specs, constraints), the **codegen layer**
turns that description into source files, the **harness layer** builds and
renders those files into PNGs, and the **grader** scores the agent's PNGs
against reference PNGs. The concept layer and the grader are framework-agnostic
because they speak in pixels and design intent, not file extensions. The
codegen layer and the harness layer are framework-specific. Adding a new
stack means: keep the seed schema, add a parallel codegen path, add a parallel
template set, and add a build step inside the harness. The grader does not
move.

The right mental model is therefore **multi-track**, not multi-pipeline:
one `--track` flag selects `(codegen prompt set, template set, build
recipe)`. Tracks share the seed schema, the relevance judge, the sanity
checker (mostly), and the scoring harness (entirely, after build).

---

## 2. What stays the same vs. what forks

### 2.1 Stays the same (no change required)

| Component | Why it doesn't need to change |
|-----------|-------------------------------|
| [seeds.py](../generator/seeds.py) `TIERS`/`GENRES`/`Seed` schema | Describes a *site*, not an implementation. Palette, typography, page list, constraints are framework-agnostic. |
| [concept_gen.py](../generator/concept_gen.py) | Stage-1 LLM still emits the same Seed shape. The genre/tier round-robin is unchanged. |
| [relevance.py](../generator/relevance.py) | VLM judge looks at *screenshots*, not source. Same seed → same rubric. |
| Grader's pixel/judge layer in [score.py](../generator/templates/tests/score.py) | Compares agent PNGs to reference PNGs. Source language is invisible at this layer. |
| Reference-side PNG generation (conceptually) | Reference is still authored by the codegen LLM; renderer still emits PNGs at three viewports. Only the *renderer* changes to add a build step. |

### 2.2 Forks (track-specific copies/branches needed)

| Component | What forks |
|-----------|-----------|
| [prompts.py](../generator/prompts.py) | New system prompts and per-page/component prompt builders for each track. |
| [generate_dataset.py](../generator/generate_dataset.py) | New `--track` flag; per-track validator; per-track packaging (file layout differs). |
| [templates/](../generator/templates/) | New subdirectory per track: `templates/react-css/`, `templates/react-tailwind/`, `templates/solid-tailwind/`. |
| Dockerfile per track | Adds Node, npm, and the framework toolchain (Vite, Tailwind CLI, etc.). |
| `make.py` per track | Runs `npm install && npm run build` then renders the *built* output, not raw source. |
| Agent's `instruction.md` | Tells the agent the target structure of the project (file layout, build command). |
| [sanity.py](../generator/sanity.py) | Renders the **built** output, not source. Some structural checks (script-tag bans, inline-CSS expectations) become inapplicable. |
| Oracle [solve.sh](../generator/templates/solution/solve.sh) | Copies reference *project source*, not reference HTML — and the verifier needs to build it. |
| `validate_html()` in [generate_dataset.py](../generator/generate_dataset.py) | Replaced by `validate_project()` per track — JSX/TSX parse check, package.json presence, tailwind config presence, no network-fetching imports, etc. |

The hard problem is not any single fork — each fork is straightforward in
isolation. The hard problem is the **build step**: PNGs no longer flow
directly from source. A failed `npm install` or `vite build` is a new
failure mode that didn't exist when source was a single self-contained HTML
file.

---

## 3. The proposed architecture

```text
                  Seed (framework-agnostic)
                       │
                       ▼
      ┌─────────────────────────────────────────────┐
      │ codegen dispatcher                          │
      │   --track html-css        → existing path   │
      │   --track react-css       → JSX + CSS       │
      │   --track react-tailwind  → JSX + utility   │
      │   --track solid-tailwind  → Solid + utility │
      └────────────────┬────────────────────────────┘
                       │
                       ▼
      ┌─────────────────────────────────────────────┐
      │ per-track codegen (prompts.py per track)    │
      │   - shared "design tokens" call (once/seed) │
      │     emits CSS variables or tailwind.config  │
      │   - per-page/per-route component call       │
      │     emits one route component + its CSS     │
      │   - shared layout (nav/footer) call         │
      └────────────────┬────────────────────────────┘
                       │
                       ▼
      ┌─────────────────────────────────────────────┐
      │ per-track validation                        │
      │   parse JSX/TSX, check imports allowlist,   │
      │   ensure route components exist, no remote  │
      │   URLs, tailwind classes present, etc.      │
      └────────────────┬────────────────────────────┘
                       │
                       ▼
      ┌─────────────────────────────────────────────┐
      │ per-track packaging                         │
      │   write project tree into                   │
      │   environment/reference-project/            │
      │   plus task.toml, instruction.md, etc.      │
      └────────────────┬────────────────────────────┘
                       │
                       ▼ (build-time, inside Docker)
      ┌─────────────────────────────────────────────┐
      │ make.py (per-track)                         │
      │   npm install (cached layer)                │
      │   npm run build       → dist/<route>.html   │
      │   for each viewport: render dist → PNG      │
      └────────────────┬────────────────────────────┘
                       │
                       ▼ (verifier-time, inside Docker)
      ┌─────────────────────────────────────────────┐
      │ score.py (UNCHANGED from current)           │
      │   builds agent project the same way         │
      │   then compares agent PNG vs ref PNG        │
      └─────────────────────────────────────────────┘
```

Key invariants this preserves:

- Reference PNGs are still baked into the Docker image at build time.
- Agent output is still **PNGs of rendered pages** before the grader runs.
- The grader is byte-identical to the HTML/CSS path once both sides are PNGs.
- One task = one website. Tracks do not multiply the number of tasks; a
  given seed can be materialized in any track.

---

## 4. Per-track design notes

### 4.1 React + plain CSS

**Project shape** (minimal Vite + React, no Tailwind):

```text
reference-project/
├── package.json            # vite + react + react-dom only
├── vite.config.js          # SSG plugin (vite-plugin-ssr or vite-react-ssg)
├── index.html              # mount node
├── src/
│   ├── main.jsx            # router + mount
│   ├── App.jsx             # shell (nav + outlet + footer)
│   ├── routes/
│   │   ├── home.jsx
│   │   ├── work.jsx
│   │   ├── writing.jsx
│   │   ├── about.jsx
│   │   └── contact.jsx
│   └── styles/
│       ├── tokens.css      # CSS variables for palette/typography
│       ├── shell.css       # nav + footer
│       └── routes/<page>.css
```

**Build → render contract:** the reference (and the agent) must produce one
static HTML file per route. Two options:

1. **Pre-render via `vite-react-ssg` / `vite-plugin-ssr`.** `npm run build`
   emits `dist/<route>/index.html` with critical CSS inlined. Renderer just
   navigates to `file://.../dist/<route>/index.html`. Cleanest path; no JS
   needs to execute at render time.
2. **CSR with `wait_until="networkidle"`.** Build emits a single SPA bundle;
   the renderer navigates to the SPA URL with a hash route and waits for
   React to commit. Brittle: timing-dependent, breaks under flaky hydration,
   inconsistent screenshots if any animation hasn't settled.

**Recommendation: pre-render.** The benchmark is "make these screenshots
match," not "ship a working SPA." Pre-rendering makes the render step
deterministic and removes JS execution from the screenshot critical path.

**Codegen split:** one call per route component + one call for `App.jsx` +
`tokens.css` + `shell.css` (the design system equivalent of the existing
shared-CSS stage). Five route calls + one shared-design call = six calls
per seed, vs. six today (5 pages + 1 shared CSS).

**Token budget:** JSX adds noise (`className=`, `<>...</>`) but routes can
import the shared shell and styles, so per-component output is *shorter*
than the equivalent single-file HTML. Net even, possibly better.

### 4.2 React + Tailwind

Same project shape as 4.1 but `styles/` collapses to `index.css` carrying
`@tailwind base; @tailwind components; @tailwind utilities;` plus a
`tailwind.config.js` carrying the seed's palette + typography as design
tokens, plus optional `@layer components` for repeated patterns (cards,
nav items, buttons).

**Why a separate track at all?** Tailwind shifts the codegen problem from
"write CSS rules" to "compose utility classes." The token budget per
component *shrinks* — a Tailwind card is `<div class="rounded-xl shadow-lg
p-6 bg-white">` vs. 8-12 lines of CSS. But the LLM has to be told to:

- Use only utilities derivable from a constrained `tailwind.config.js`.
- Avoid arbitrary values (`p-[37px]`) unless the seed explicitly demands
  off-grid measurements.
- Not import `@apply` cascades that defeat the purpose of utility-first.

**Codegen split:** one call generates `tailwind.config.js` carrying the seed
palette as `theme.extend.colors`, typography as `theme.extend.fontFamily`,
and a small set of design-system tokens (spacing scale, container widths,
shadow scale). Then per-route component calls reference those tokens. This
is the analog of the current shared-CSS stage but moved into the build
toolchain.

**Render contract:** same as 4.1 — pre-render to static HTML. Tailwind's
build step (`tailwindcss -i ./src/index.css -o ./dist/index.css --minify`)
runs inside `npm run build`; the renderer never sees raw `@tailwind`
directives.

### 4.3 Solid + Tailwind

**Why include Solid?** It tests whether the pipeline genuinely generalizes
or just supports React-shaped frameworks. Solid's JSX looks identical to
React's at a glance but its reactivity model is different (signals vs.
state) and the build toolchain differs (`solid-start` vs. `vite-plugin-ssr`).
A track that works for Solid demonstrates the harness is framework-
isolated, not React-shaped.

**Project shape:**

```text
reference-project/
├── package.json            # solid-js + @solidjs/start + tailwindcss
├── app.config.ts           # Solid Start config (pre-render: true)
├── tailwind.config.js
├── src/
│   ├── app.tsx             # shell
│   ├── routes/
│   │   ├── index.tsx       # home
│   │   ├── work.tsx
│   │   ├── ...
│   └── styles/index.css    # tailwind directives
```

**Build → render contract:** Solid Start's `vinxi build --preset
static` pre-renders every route to static HTML. Same as React tracks once
built — `dist/<route>/index.html` lands somewhere predictable and the
renderer navigates to it.

**Codegen risk:** the LLM has stronger priors on React than on Solid.
Expect more `useState` / `useEffect` slip-ups on retry-1; the validator's
import-allowlist (`solid-js` only, no `react`) catches them and the
per-component retry loop fixes them. This is a real cost — expect 1.5-2×
the per-page retry rate vs. the React tracks, at least until prompt
iteration catches up.

---

## 5. Concrete touch list

This mirrors §10 in [BONUS1.md](BONUS1.md). For each track the additions
are roughly parallel.

| Layer | New / modified |
|-------|----------------|
| Concept | (none — Seed schema unchanged) |
| Codegen prompts | `prompts.py` grows three new system prompts + builders, OR more cleanly: a new `prompts/` package with one module per track |
| Codegen orchestration | `generate_dataset.py` gains `--track {html-css,react-css,react-tailwind,solid-tailwind}`, dispatches to per-track codegen, runs per-track validator |
| Validation | New `validate_project()` per track. Parses JSX with a lenient parser (e.g. `tree-sitter-typescript`), checks import allowlist, checks tailwind config exists for tailwind tracks, checks every required route component exists |
| Templates | New dirs: `templates/react-css/`, `templates/react-tailwind/`, `templates/solid-tailwind/`. Each contains its own `environment/Dockerfile`, `environment/make.py`, `solution/solve.sh`, `tests/test.sh`, `tests/score.py` (mostly symlinked or unchanged from the html-css one) |
| Dockerfile per track | Adds `RUN apt-get install -y nodejs npm` (or uses `node:20-bullseye` base image and reinstalls Playwright). Layer-cache `npm install` separately from source so iteration is fast |
| Build step | `make.py` per track runs `npm ci` + `npm run build` before the Playwright render loop |
| Render | Unchanged — `page.goto(file://.../dist/<route>/index.html)` then screenshot at three viewports |
| Oracle | `solve.sh` copies `/opt/reference-project/` to `/app/output/`. The verifier then builds the agent's project (because the agent ships source, not built output) |
| Verifier build | `score.py` (or a pre-`score.py` step) runs `npm ci && npm run build` on `/app/output/` before rendering and grading |
| `task.toml` | New keyword `track-<name>`; `verifier.timeout_sec` bumped because `npm ci` adds 30-90s, `npm run build` adds 10-30s |
| Instruction | Per-track `instruction.md.tpl` describing the project layout the agent must produce, the build command, and the route → output path mapping |
| Sanity | `sanity.py` renders the built `dist/`; some checks (e.g. "no `<script>` tag") flip from forbidden to expected for SPA tracks. Tier-1 → tier-8 structural checks still apply to the *rendered* DOM |
| Relevance | (no change — operates on PNGs + seed) |

Estimated LOC: ~400-600 net new lines per track for codegen + validation +
templates, plus ~150 lines of dispatcher glue in `generate_dataset.py`. Most
of it is template copies and prompt strings — the harness changes are small.

---

## 6. Problems, in priority order

The novel risks vs. the html-css path. Ordered by how likely they are to
bite first.

### 6.1 The build step is now a failure surface

**Today:** if codegen produces a syntactically-valid HTML file, the Docker
build succeeds and the page renders. There is no compilation step.

**Tomorrow:** `npm install` can fail (registry timeout, peer-dep conflict),
`vite build` can fail (JSX syntax error, missing import, type error if TS).
A bad codegen output now breaks the Docker image build, not just one page's
render.

**Mitigations:**

- **Pre-build validation.** Run a syntactic parse (`@babel/parser` for JSX,
  `tree-sitter` for TSX) before packaging. Cheap, catches most errors.
- **Trial build at generation time.** Spin up a transient Docker container,
  run `npm ci && npm run build`, and only persist the task if it
  succeeds. Costs ~1-2 minutes per task and adds Docker-in-loop to
  `generate_dataset.py`. Pricey but the most reliable gate.
- **Pinned lockfiles.** Ship `package-lock.json` with every template so
  `npm ci` is deterministic and the registry is the only network dep.
- **Local registry mirror.** Optional — for batch builds, point npm at a
  Verdaccio proxy that caches the dep tree. Eliminates registry flake.

Pick at least one of "pre-build validation" + "pinned lockfiles" as the
minimum bar. Trial build is the gold standard but only worth it if early
runs show high build-failure rates.

### 6.2 Per-task Docker image grows fast

The current image is ~600 MB (Playwright + Chromium + Python + a handful
of pip deps). Adding Node + `node_modules` adds another 200-400 MB *per
task* because every task gets its own image.

**Mitigations:**

- **Base image with Node pre-installed.** Switch to a custom Playwright
  base that already includes Node 20 and a global pnpm cache. One-time
  bake; downstream tasks inherit.
- **Lockfile-aware layer caching.** Order Dockerfile so `COPY
  package.json package-lock.json /tmp/proj/` and `RUN cd /tmp/proj &&
  npm ci` precede `COPY src/`. Same lockfile across tasks of the same
  track → near-zero `npm ci` cost from layer cache.
- **Shared `node_modules` volume at verifier time.** If the runtime
  supports it, mount a shared cache so the verifier's `npm ci` on agent
  output reuses the host's lockfile-keyed cache.

This is the single biggest cost driver of the bonus. Without layer
discipline, batch runs will exhaust disk on builders that handled the
html-css path comfortably.

### 6.3 Render determinism under hydration

Pre-rendering sidesteps most of this, but two cases still bite:

- **Animations on mount.** A `<Hero>` component with an entrance fade-in
  using `motion.div` will be in mid-animation when Playwright captures.
  The fix is the same as the html-css path uses for tier-9: a
  `prefers-reduced-motion: reduce` media query and CSS that collapses
  animations to their settled state. Codegen prompts must enforce this.
- **Font loading flicker.** System-fonts-only is still enforced, so this
  is a non-issue if the prompt rule survives the track change. If we
  ever lift the system-fonts rule to allow web fonts, `page.evaluate(()
  => document.fonts.ready)` becomes mandatory before screenshot.

**Mitigation:** keep the system-font + no-animation rule from the
html-css prompt verbatim. Add a `wait_for_load_state('networkidle')`
guard in `make.py` per-track as a belt-and-braces measure.

### 6.4 Output structure validation is harder

`validate_html()` today is ~30 lines: parse, check `<body>` exists, no
`<script>`, no `http(s)://`, length floor. For a React project the
equivalent is:

- Every required route component file exists.
- Each route component default-exports a function.
- Imports resolve to a small allowlist (`react`, `react-dom`, the project's
  own files, no `axios`/`lodash`/etc unless explicitly allowed).
- `tailwind.config.js` parses and exports an object with `theme.extend.colors`
  pulling from the seed's palette.
- No `<script src="https://">` in the built HTML (the build can technically
  produce this if the LLM imports a CDN bundle).

**Mitigation:** invest in a real per-track `validate_project()` that uses
`@babel/parser` for JSX, runs as a subprocess from `generate_dataset.py`,
returns structured errors that feed into the retry prompt. ~200-300 LOC of
careful work per track but reusable across React-CSS and React-Tailwind.

### 6.5 The agent's project might not build, but their HTML files might still render

Edge case: the agent ships `dist/` directly instead of source. We need to
decide: is that cheating, or is the contract "produce a static site"?

**Recommendation:** the instruction explicitly forbids it for these tracks
("you must ship source under `/app/output/src/`; the verifier builds
it"). The verifier enforces by deleting any `/app/output/dist/` before
building. This keeps the benchmark honest — we're grading the *framework
skill*, not "can you copy a bundle."

### 6.6 Sanity checks no longer map 1:1

`sanity.py`'s tier-conditional checks read computed styles from the rendered
DOM. Those checks transfer to React/Solid output unchanged *if* we render
the built dist. But:

- Tier 1+ checks ("no `<script>` tag") are inverted: SPA tracks will have
  `<script type="module">` in `dist/<route>/index.html`. Adapt the check
  to "no `<script>` with `src` pointing outside the project" instead.
- Cross-page checks (nav/footer drift, palette ΔE) carry over unchanged.
  Pre-rendered HTML is just HTML.

**Mitigation:** parameterize `sanity.py` by track. The structural checks
are 90% identical; the `<script>` rule is the main divergence.

### 6.7 Verifier-side build adds latency and cost

The verifier (`score.py`) currently takes ~3-5 minutes per task. Adding
`npm ci` (~30-90s) + `npm run build` (~10-30s) per agent submission
adds 1-2 minutes. With ensemble-of-3 judges per page × 3 viewports already
in flight, the verifier could push to 6-8 minutes per task.

**Mitigations:**

- Pre-warm `node_modules` in the Docker image at build time, with the
  reference project's lockfile. The agent's project usually shares deps;
  `npm ci` against the existing cache is fast.
- Bump `verifier.timeout_sec` in `task.toml` from 1200s → 1800s (motion
  tier's existing value works here too).
- Consider building once at start-of-verifier and reusing across pages
  rather than once per page.

### 6.8 LLM is uneven across frameworks

Anthropic models are strong on React, weaker on Solid. Expect:

- React-CSS and React-Tailwind: similar retry rates to html-css, possibly
  better thanks to Tailwind's per-component brevity.
- Solid-Tailwind: 1.5-2× the retry rate, especially around lifecycle
  primitives. The validator's import-allowlist (no `react`) and the
  per-component retry prompt with prior errors will recover most of it,
  but per-task wall-clock and cost rise.

**Mitigation:** allow a per-track `--max-retries` override (default 3 for
React tracks, 5 for Solid). Track per-track retry rates in the registry
and tune from there.

### 6.9 Grading is "fair" across tracks only because PNGs hide the source

A subtle point: the grader judges PNGs. So a great Tailwind site and a
great hand-written CSS site that produce identical PNGs get identical
scores. This is the right thing — we're grading what users see, not what
developers like. But it has two implications:

- Cross-track score comparisons are meaningful (`agent X scored 0.82 on the
  react-tailwind track and 0.79 on the html-css track on the same seed`).
- A track might be *easier* for agents because the framework's conventions
  reduce design choices. Expect React-Tailwind to outscore html-css for a
  median agent simply because Tailwind's defaults are good.

**Mitigation:** none needed at the grader. Report per-track median scores
separately in dataset summaries and treat track choice as a benchmark
dimension, not a normalization target.

### 6.10 Tooling churn

Node, Vite, Tailwind, and SolidStart all evolve fast. The current html-css
pipeline can sit unchanged for years (HTML5 is stable). The new tracks
will need version bumps every 6-12 months as deps shift.

**Mitigation:** pin every dep version in `package.json` and `package-
lock.json`. Treat the template directory as a sealed artifact; bump it
deliberately, never via `^` ranges. Document the bump procedure in a
short `templates/<track>/README.md`.

---

## 7. Effort estimate

Rough scoping. "Solo engineer, no calendar interruptions" units.

| Phase | Effort | Notes |
|-------|--------|-------|
| Track abstraction (`--track` flag, dispatcher in `generate_dataset.py`) | 1 day | Plumbing only; touches `generate_dataset.py`, `prompts.py` re-organization |
| React-CSS track (codegen prompts, validator, templates, Dockerfile, make.py) | 3-4 days | The first new track does the heaviest lifting (figuring out the build → render contract, layer caching) |
| React-Tailwind track | 1-2 days | Almost-free given React-CSS exists; mainly the codegen prompt rewrite for utilities + the `tailwind.config.js` generation |
| Solid-Tailwind track | 2-3 days | Codegen prompts need real iteration; toolchain divergence (SolidStart) adds setup time |
| Verifier build path (`npm ci` + build in score.py path) | 1 day | Mostly tweaking timeouts and adding the build invocation |
| Calibration runs (~3 oracle trials per track) | 2-3 days | Iterating until oracle scores ~1.0 on each track |
| Documentation + sanity checks adaptation | 1 day | Update ARCHITECTURE.md, parameterize sanity.py |
| **Total** | **~11-15 working days** | Single engineer, sequential; lots of room to parallelize prompt iteration with infra work |

The dominant risk to this estimate is **calibration time**. BONUS1 took
three full oracle trials to land on the credit-only pre-flight + source-
scan design. Each track here will need its own oracle calibration sweep
to confirm the grader is fair (i.e. oracle scores ~1.0). Budget
generously for that phase.

---

## 8. Recommended sequencing

If the goal is "get to three tracks shipped," the cheapest path is:

1. **Land the `--track` abstraction first**, with `html-css` as the only
   value. This is a pure refactor — no new behavior, but it forces every
   per-track seam (codegen dispatch, template dir lookup, validator
   dispatch) to exist. The change is reviewable in isolation and zero-risk
   because the existing tests still pass.
2. **React-CSS next**, not Tailwind. The hard problems (build step,
   verifier latency, lockfile discipline, render contract) are the same as
   Tailwind's but the *codegen prompt* is closer to the html-css prompt
   (write actual CSS), so the LLM struggles less. Solve the harness once.
3. **React-Tailwind after.** The infra is reused from step 2; only prompts
   and templates change.
4. **Solid-Tailwind last.** This is the track that proves generalization
   but also has the highest LLM-quality risk. Worth doing once the React
   tracks are stable so the iteration is purely on prompts, not infra.

The "land the abstraction first, even with one implementation" pattern
mirrors how tier 9 was structured in [BONUS1.md](BONUS1.md): the gating
existed (and the orchestrator refused tier 9 with a clear error) before
the motion harness was implemented. Same playbook here.

---

## 9. Open questions

These are decisions I'd ask the team before implementing, not blockers:

- **CSR vs SSG.** Pre-render is recommended throughout this doc. Confirm
  before building — if the team wants to grade *runtime* React (hydration,
  client-side routing transitions), the harness needs a Playwright wait-
  for-hydrated probe and the grader changes. The recommended path tests
  *output fidelity*, not *runtime behavior*.
- **Tailwind config: LLM-generated or templated?** The cleanest design has
  the LLM emit a `tailwind.config.js` from the seed. The cheaper design
  uses a fixed config and tells the LLM to use only its tokens. The
  fixed-config path is more deterministic and 3× cheaper at codegen but
  constrains design diversity.
- **TypeScript or JavaScript?** TS catches more agent errors at build time
  (free validation!) but inflates the per-route token budget by ~15-20%
  and adds a tsc step. Recommendation: JSX/JS for codegen simplicity, TSX
  later if validation gains warrant it.
- **Internet access at verifier time.** The current `task.toml` sets
  `allow_internet = true` already (the judge needs Anthropic API). `npm
  ci` works inside this envelope. Confirm the runtime's network policy
  for batch jobs.
- **One Docker image per track, or one image per task?** Currently one
  image per task. A per-track shared base with task-specific source as a
  thin layer would cut total disk usage 10× for batch builds. Probably
  worth it; out of scope for the bonus's first cut.

---

## 10. Summary

The pipeline was built with this exact extension in mind:
[ARCHITECTURE.md §9.3](ARCHITECTURE.md) already names "React + Tailwind"
as a planned extension and describes the right shape (new codegen prompt,
new template set, new build step in `make.py`, a `--track` flag). This
document fleshes out that one paragraph into a concrete plan across three
tracks and surfaces the actual problems (build-step failure modes, Docker
image bloat, verifier latency, LLM unevenness across frameworks) that the
original paragraph elides.

The work is non-trivial — ~11-15 engineering days for all three tracks
including calibration — but the architecture supports it cleanly. The
seed schema and the grader carry over unchanged; the codegen and harness
layers fork along a single `--track` axis. The biggest unknowns are
calibration cost and Solid-specific LLM quality, neither of which can be
quantified without a first oracle run on each track.

If only one track is shipped, **React + Tailwind** is the highest-value
single addition: it's the dominant modern frontend stack, agents have
strong priors on it, and the Tailwind constraint gives the codegen LLM a
narrower target than free-form CSS. It also lays the infra for the other
two tracks at near-zero marginal cost.
