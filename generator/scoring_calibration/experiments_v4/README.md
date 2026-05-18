# V4 multi-task calibration experiment

Defends the claim "higher V4 grader scores correspond to better website
replications" by running the V4 grader against 5 tasks × 5 manufactured
quality tiers (= 25 graded variants) spanning tiers 1, 3, 5, 6, 7 and
visibly different design languages, then producing 4 plots.

The tasks live in [`tasks.txt`](tasks.txt). Swap a task by editing that
file and re-running `./reproduce.sh`.

## Reproduce

```bash
cd generator/scoring_calibration/experiments_v4
export ANTHROPIC_API_KEY=sk-ant-...
./reproduce.sh
```

What `./reproduce.sh` does, in order:

1. Verifies `ANTHROPIC_API_KEY` is set and every task in `tasks.txt`
   has a `reference-pages/` directory on disk.
2. Calls `../degrade.py` on each task that doesn't already have a
   `../degraded/<task>/` directory. Produces 5 degraded HTML variants
   per task (`near_perfect`, `mediocre`, `plain`, `adversarial`, `bad`).
3. Backs up `../results/v4.0.json` to `v4.0.json.bak` if it exists.
4. Calls `../run.py --grader-version v4.0` to grade all 25 variants.
   Overwrites `../results/v4.0.json` with the multi-task results +
   summary block.
5. Calls `./make_plots.sh` to produce the 4 PNGs.
6. Prints a one-line summary of inversion count, per-tier means, and
   the 4 output paths.

Expected wall-clock: ~30–40 minutes (sequential grader runs).
Expected API cost: ~$5–15 in Opus vision calls.

## Replot only (cheap)

If the calibration JSON already exists and you only want to regenerate
the plots (e.g. after editing styling in `_common.py`):

```bash
./make_plots.sh
```

## Outputs

PNGs are written to the top-level `docs/img/` (consumed by `docs/SCORING.md`):

| File | What it shows | What it argues |
|---|---|---|
| `calibration_ladder.png` | One row per tier on the X-axis; each row shows the range (min–max) across the 5 tasks plus 5 colored dots (one per task) and a tick at the mean. Target bands shaded behind. | The grader produces a clean staircase from `near_perfect` to `bad`, and every individual variant lands inside its target band — not just the average. |
| `calibration_per_task.png` | A 5-panel grid, one panel per task, each showing the 5-tier mini-ladder for that task. Shared 0–1 Y-axis. | The ladder shape repeats across very different sites (recipe, dashboard, editorial, banking, SVG). The grader isn't tuned to one design language. |
| `calibration_dimensions.png` | Heatmap. Rows = the 5 judge criteria + 11 deterministic aspects. Columns = the 5 tiers. Cells = mean score across tasks × pages, colored red→green. | Each dimension fires on the failure modes it was designed to catch (e.g. `text_content` collapses on `bad`, `judge.typography` collapses on `adversarial`). Confirms each dimension is doing its job. |
| `calibration_versions.png` | Line chart. X-axis = grader versions V1 → V4. Lines = one per tier. Target bands shaded behind. | Each grader version closed a specific gap: V1 had a `bad > mediocre` inversion; V2 fixed monotonicity but ran high; the V3 judge fixed the `adversarial` blind spot. |

## Cost details

Per graded variant (≈ 5 pages × 3 viewports × 3-call Opus ensemble for
each judge criterion): ~45 Opus vision calls and ~$0.30–0.60.

25 variants → ~1,100 Opus calls → ~$8–15 typical, ~$5 best case.

The deterministic side (rendering + 11 aspects + text gate) is free —
Playwright renders run locally on CPU.

## What's NOT in this experiment

- Real-agent reward distribution (the eventual Modal run) — separate
  experiment, blocked on Modal infra.
- Spearman ρ between dimensions and total reward — needs real-agent
  data.
- Oracle ceiling on held-out tasks — needs real-agent infra.
- Per-viewport breakdown of the heatmap (desktop / tablet / phone) —
  future refinement.

## Files in this directory

| File | Purpose |
|---|---|
| `README.md` | This file |
| `tasks.txt` | One task name per line — the calibration set |
| `reproduce.sh` | End-to-end: degrade → grade → plot |
| `make_plots.sh` | Plots-only (cheap; assumes calibration JSON exists) |
| `_common.py` | Shared utilities (tier order, target bands, colors, JSON loader) |
| `plot_ladder.py` | Plot A+B — range-and-dots ladder |
| `plot_per_task.py` | Plot C — per-task small multiples |
| `plot_dimension_heatmap.py` | Plot D — per-dimension behavior heatmap |
| `plot_version_evolution.py` | Plot F — V1 → V4 evolution |
