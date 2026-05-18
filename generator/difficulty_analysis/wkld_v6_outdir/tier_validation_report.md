# Workloads_v4 Difficulty Validation Report

_N = 10 tasks, tier ladder T1–T7 per docs/running_notes.md_

## Composite scores vs. tier

- **composite_designbench_S** — Spearman ρ=+0.750 (p=0.0125, 95% CI [+0.13, +0.99]); Kendall τ=+0.614 (p=0.0149)
- **composite_axis_mean** — Spearman ρ=+0.774 (p=0.00854, 95% CI [+0.20, +1.00]); Kendall τ=+0.659 (p=0.00893)

Headline target: ρ ≥ 0.85, τ ≥ 0.7. Below either → tier ladder needs revision.

## Ranking by composite_designbench_S vs. tier

| Rank | Task | Tier | Genre | S | axis_mean |
|---|---|---|---|---|---|
| 1 | synth-t7-deep-current-oceandata-64e3 | T7 | infographic | +1.34 | +0.84 |
| 2 | synth-t4-lumivex-signal-boost-c799 | T4 | marketing-landing | +0.98 | +0.44 |
| 3 | synth-t6-nexum-vault-settings-e99e | T6 | account-settings | +0.81 | +0.61 |
| 4 | synth-t3-oblique-flux-studio-dcf5 | T3 | agency | +0.28 | +0.40 |
| 5 | synth-t5-chlorophyll-dispatch-weekly-5325 | T5 | magazine-feature | +0.05 | +0.20 |
| 6 | synth-t8-forma-negra-review-11da | T8 | design-magazine | +0.02 | +0.17 |
| 7 | synth-t2-ironclad-summit-dev-c9a0 | T2 | conference | -0.39 | -0.42 |
| 8 | synth-t2-brackwater-marsh-conservancy-945d | T2 | nonprofit | -0.67 | -0.41 |
| 9 | synth-t1-copper-kettle-suppers-16cf | T1 | recipe-card | -1.18 | -0.86 |
| 10 | synth-t1-maren-solvik-design-a2db | T1 | portfolio | -1.25 | -0.98 |

## Per-tier descriptives

| tier | n | designbench_S(mean) | axis_mean(mean) | DOM(mean) | cssRules(mean) | cssColors(mean) | gradients(mean) | svg_paths(mean) | edge_density(mean) |
|---|---|---|---|---|---|---|---|---|---|
| T1 | 2 | -1.21 | -0.92 | 67 | 100 | 9.2 | 0.9 | 0.0 | 0.026 |
| T2 | 2 | -0.53 | -0.41 | 174 | 178 | 18.8 | 1.0 | 0.0 | 0.045 |
| T3 | 1 | +0.28 | +0.40 | 274 | 291 | 24.6 | 5.4 | 0.0 | 0.036 |
| T4 | 1 | +0.98 | +0.44 | 260 | 277 | 60.6 | 32.2 | 0.0 | 0.033 |
| T5 | 1 | +0.05 | +0.20 | 244 | 194 | 24.2 | 7.2 | 0.0 | 0.078 |
| T6 | 1 | +0.81 | +0.61 | 513 | 250 | 45.4 | 8.2 | 0.0 | 0.027 |
| T7 | 1 | +1.34 | +0.84 | 732 | 239 | 30.0 | 4.8 | 188.2 | 0.046 |
| T8 | 1 | +0.02 | +0.17 | 298 | 269 | 13.4 | 3.0 | 20.8 | 0.053 |

## Adjacent-tier inversions (composite_designbench_S)

- T1 → T2: median S = -1.21 vs -0.53 (✓)
- T2 → T3: median S = -0.53 vs +0.28 (✓)
- T3 → T4: median S = +0.28 vs +0.98 (✓)
- T4 → T5: median S = +0.98 vs +0.05 (✗ inversion)
- T5 → T6: median S = +0.05 vs +0.81 (✓)
- T6 → T7: median S = +0.81 vs +1.34 (✓)
- T7 → T8: median S = +1.34 vs +0.02 (✗ inversion)

## Per-metric Spearman ρ vs. tier (10 tasks)

Each metric is expected to *jump at a specific tier boundary*, not rise monotonically T1→T7. Treat correlations as exploratory.

| Metric | ρ | p | Expected boundary |
|---|---|---|---|
| ylt.DOMelementsCount | +0.91 | 0.00027 | T5→T6 (dense forms/tables) |
| ylt.DOMelementMaxDepth | +0.71 | 0.022 | T2→T3 (layout nesting) |
| ylt.iframesCount | (constant) | — | (noise — workloads use no iframes) |
| ylt.cssRules | +0.63 | 0.049 | T3→T4 (visual polish) |
| ylt.cssSelectors | +0.61 | 0.061 | T3→T4 |
| ylt.cssDeclarations | +0.69 | 0.028 | T3→T4 |
| ylt.cssComplexSelectors | +0.64 | 0.047 | T3→T4 |
| ylt.cssSpecificityIdAvg | +0.06 | 0.87 | (noise) |
| ylt.cssDuplicatedSelectors | +0.53 | 0.12 | (noise) |
| ylt.cssImportants | +0.55 | 0.1 | (noise) |
| ylt.cssEmptyRules | (constant) | — | (noise) |
| ylt.cssColors | +0.56 | 0.092 | T3→T4 (palette grows) |
| ylt.nodesWithInlineCSS | +0.84 | 0.0023 | (noise) |
| svg_path_count | +0.69 | 0.028 | T6→T7 (inline SVG) |
| gradient_count | +0.61 | 0.064 | T3→T4 (visual polish) |
| html_bytes | +0.86 | 0.0014 | monotone (size grows with all of the above) |
| css_bytes | +0.71 | 0.021 | monotone |
| jpeg_proxy_bytes_per_kpixel | +0.42 | 0.23 | Forsythe clutter (T4, T7) |
| edge_density | +0.57 | 0.083 | T6→T7 (SVG/forms) |
| cross_page_nav_jaccard | -0.57 | 0.088 | T1→T2 (multi-page identity) |

## Web Almanac context (where our workloads sit on the public web)

- **ylt.DOMelementsCount** — workloads_v4 range 66–732, mean 280. Public (Markup 2024): p10=180, p50=594, p90=1716.
- **ylt.cssRules** — workloads_v4 range 90–291, mean 208. Public (CSS 2022): p50=613, p90=2023.
- **ylt.DOMelementMaxDepth** — workloads_v4 range 5–10, mean 8. Public (Markup 2024): Lighthouse fails >32.

## Caveats

- N=10 workloads. Wide bootstrap CIs are honest; treat composite as headline, per-metric as exploratory.
- Per-tier N unbalanced: T1=T2=T5=T6=1; T3=T4=T7=2; T8=0. Several adjacent-tier checks reduce to a single comparison.
- Genre confound: T6 only `comparison-table`, T5 only `poetry`. Tier-correlated metrics may really measure genre.
- Visual ≠ total task difficulty. Agents also see the prompt; harder visual content may be offset by clearer text.
- DesignBench S formula validated on real pages; our LLM-generated workloads may have different distributions. Cross-check with Web Almanac context above.

