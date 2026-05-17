# Site Replication Task

A Harbor task where the agent is shown 5 screenshots of pages from one website
(Home, About, Pricing, Blog, Contact) and must recreate each in static HTML/CSS.
The verifier renders both sides with Chromium and scores visual similarity.

**Visual fidelity only.** The agent is told explicitly not to bother with
functionality — no JS, no form submission, no working nav. Just make it look
like the screenshot.

## Layout

```
css-replication-task/
├── task.toml
├── instruction.md                 # Agent's brief
├── README.md
├── environment/
│   ├── Dockerfile                 # Builds the image, runs make.py
│   ├── make.py                    # Renders reference HTML -> PNGs at BUILD time
│   └── reference-pages/           # Canonical reference HTML — single source of truth
│       ├── home/index.html
│       ├── about/index.html
│       ├── pricing/index.html
│       ├── blog/index.html
│       └── contact/index.html
├── solution/
│   └── solve.sh                   # Oracle: cp -r /opt/reference-pages/* /app/output/
└── tests/
    ├── test.sh                    # Runs score.py
    └── score.py                   # Renders, scores, builds comparison images
```

## How it works

1. **Build time** — `environment/Dockerfile` copies `reference-pages/` into
   `/opt/reference-pages/` in the image and runs `make.py`, which renders each
   page to a PNG under `/app/references/`. No host-side script. No
   "capture first" step.
2. **Agent phase** — Harbor mounts `/app/`. Agent sees `/app/references/*.png`,
   writes `/app/output/<page>/index.html`.
3. **Oracle phase** — `solution/solve.sh` runs, copies `/opt/reference-pages/*`
   into `/app/output/`. Reward 1.0.
4. **Verify phase** — `tests/score.py` runs. For each page it re-renders the
   reference from `/opt/reference-pages/` and renders the agent's output, then
   computes `0.7·SSIM + 0.3·color_hist`. Writes `/logs/verifier/reward.txt` and
   side-by-side comparison PNGs.

## Run it

```bash
harbor check .                                              # static validation
harbor run -p . -a oracle --env modal                       # should be 1.000
export ANTHROPIC_API_KEY=...
harbor run -p . -a claude-code -m anthropic/claude-opus-4-7 --env modal
```

## Where to find the visual comparisons

After every run:

```
jobs/<timestamp>/<trial>/verifier/
├── reward.txt
├── score_details.json             # per-page SSIM + color scores
├── comparisons/                   # SIDE-BY-SIDE images — open these
│   ├── home.png
│   ├── about.png
│   ├── pricing.png
│   ├── blog.png
│   └── contact.png
└── renders/                       # raw renders, in case you want to diff
    ├── home.ref.png
    ├── home.agent.png
    └── ...
```

Each `comparisons/<page>.png` is:
- **Left:** what the agent saw
- **Right:** what the agent's HTML rendered to

```bash
open jobs/*/*/verifier/comparisons/*.png     # macOS
xdg-open jobs/*/*/verifier/comparisons/home.png  # Linux
```

## Adding more pages

1. Add `environment/reference-pages/<page>/index.html`.
2. Update `instruction.md` to mention the new input/output paths.
3. `harbor run -p . -a oracle --env modal` — should still be 1.000.

That's the whole loop. No other directories to sync.

## Scoring

Per page:

    score = 0.7 * SSIM + 0.3 * color_histogram_intersection

Final reward is the mean across all 5 pages, clipped to [0, 1].

Both renders (reference + agent) happen in the same container with the same
pinned Chromium (Playwright 1.49), so the score is deterministic.

## Trade-off worth knowing

Reference HTML lives at `/opt/reference-pages/` *inside the image*. A
sufficiently nosy agent could `ls /opt/` and copy the answer directly. For a
personal/local benchmark this is fine — most agents won't think to look. If
you ever ship this to evaluate untrusted agents, you'll want to:

- set `[agent].user = "agent"` in `task.toml`,
- create a non-root `agent` user in the Dockerfile,
- `chmod 700 /opt/reference-pages` and own it as root,
- have the verifier run as root (its default).

`solve.sh` would also need to either run as root or copy from a different
location, which means re-introducing some duplication for the oracle path.
Easier to bolt on once you actually need it.
