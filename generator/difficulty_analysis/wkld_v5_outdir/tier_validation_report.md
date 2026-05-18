# Workloads_v4 Difficulty Validation Report

_N = 10 tasks, tier ladder T1–T7 per docs/running_notes.md_

## Composite scores vs. tier

- **composite_designbench_S** — Spearman ρ=+0.854 (p=0.00167, 95% CI [+0.37, +1.00]); Kendall τ=+0.705 (p=0.00519)
- **composite_axis_mean** — Spearman ρ=+0.762 (p=0.0104, 95% CI [+0.19, +1.00]); Kendall τ=+0.659 (p=0.00893)

Headline target: ρ ≥ 0.85, τ ≥ 0.7. Below either → tier ladder needs revision.

## Ranking by composite_designbench_S vs. tier

| Rank | Task | Tier | Genre | S | axis_mean |
|---|---|---|---|---|---|
| 1 | synth-t7-deep-current-oceandata-4351 | T7 | infographic | +2.30 | +0.80 |
| 2 | synth-t8-folio-obscura-press-89f5 | T8 | design-magazine | +0.40 | +0.88 |
| 3 | synth-t6-ironclad-maritime-registry-65fc | T6 | application-form | +0.29 | +0.18 |
| 4 | synth-t3-ferroflux-systems-docs-712d | T3 | documentation | +0.23 | +0.53 |
| 5 | synth-t4-obsidian-cove-retreat-6f74 | T4 | hotel-resort | -0.10 | -0.31 |
| 6 | synth-t4-luminos-ai-copilot-055c | T4 | marketing-landing | -0.18 | -0.07 |
| 7 | synth-t5-obsidian-fold-gallery-6047 | T5 | gallery-exhibition | -0.28 | -0.28 |
| 8 | synth-t3-ironbark-supply-co-0759 | T3 | ecommerce | -0.53 | -0.22 |
| 9 | synth-t2-ironclad-futures-summit-6724 | T2 | conference | -0.76 | -0.61 |
| 10 | synth-t1-ink-and-insomnia-blog-fea9 | T1 | personal-blog | -1.36 | -0.90 |

## Per-tier descriptives

| tier | n | designbench_S(mean) | axis_mean(mean) | DOM(mean) | cssRules(mean) | cssColors(mean) | gradients(mean) | svg_paths(mean) | edge_density(mean) |
|---|---|---|---|---|---|---|---|---|---|
| T1 | 1 | -1.36 | -0.90 | 48 | 20 | 4.0 | 0.0 | 0.0 | 0.027 |
| T2 | 1 | -0.76 | -0.61 | 126 | 52 | 11.8 | 0.4 | 0.0 | 0.033 |
| T3 | 2 | -0.15 | +0.15 | 252 | 79 | 19.1 | 1.9 | 0.0 | 0.034 |
| T4 | 2 | -0.14 | -0.19 | 131 | 86 | 27.2 | 10.3 | 0.0 | 0.023 |
| T5 | 1 | -0.28 | -0.28 | 196 | 89 | 12.2 | 4.0 | 0.0 | 0.043 |
| T6 | 1 | +0.29 | +0.18 | 432 | 100 | 15.4 | 3.0 | 0.0 | 0.051 |
| T7 | 1 | +2.30 | +0.80 | 636 | 315 | 45.0 | 0.6 | 226.0 | 0.043 |
| T8 | 1 | +0.40 | +0.88 | 323 | 228 | 17.0 | 1.8 | 36.8 | 0.073 |

## Adjacent-tier inversions (composite_designbench_S)

- T1 → T2: median S = -1.36 vs -0.76 (✓)
- T2 → T3: median S = -0.76 vs -0.15 (✓)
- T3 → T4: median S = -0.15 vs -0.14 (✓)
- T4 → T5: median S = -0.14 vs -0.28 (✗ inversion)
- T5 → T6: median S = -0.28 vs +0.29 (✓)
- T6 → T7: median S = +0.29 vs +2.30 (✓)
- T7 → T8: median S = +2.30 vs +0.40 (✗ inversion)

## Per-metric Spearman ρ vs. tier (10 tasks)

Each metric is expected to *jump at a specific tier boundary*, not rise monotonically T1→T7. Treat correlations as exploratory.

| Metric | ρ | p | Expected boundary |
|---|---|---|---|
| ylt.DOMelementsCount | +0.72 | 0.019 | T5→T6 (dense forms/tables) |
| ylt.DOMelementMaxDepth | +0.49 | 0.15 | T2→T3 (layout nesting) |
| ylt.iframesCount | (constant) | — | (noise — workloads use no iframes) |
| ylt.cssRules | +0.94 | 5.6e-05 | T3→T4 (visual polish) |
| ylt.cssSelectors | +0.94 | 5.6e-05 | T3→T4 |
| ylt.cssDeclarations | +0.96 | 7.5e-06 | T3→T4 |
| ylt.cssComplexSelectors | +0.55 | 0.096 | T3→T4 |
| ylt.cssSpecificityIdAvg | +0.00 | 1 | (noise) |
| ylt.cssDuplicatedSelectors | (constant) | — | (noise) |
| ylt.cssImportants | -0.15 | 0.69 | (noise) |
| ylt.cssEmptyRules | (constant) | — | (noise) |
| ylt.cssColors | +0.50 | 0.14 | T3→T4 (palette grows) |
| ylt.nodesWithInlineCSS | +0.84 | 0.0026 | (noise) |
| svg_path_count | +0.69 | 0.028 | T6→T7 (inline SVG) |
| gradient_count | +0.35 | 0.32 | T3→T4 (visual polish) |
| html_bytes | +0.75 | 0.012 | monotone (size grows with all of the above) |
| css_bytes | +0.21 | 0.57 | monotone |
| jpeg_proxy_bytes_per_kpixel | +0.41 | 0.24 | Forsythe clutter (T4, T7) |
| edge_density | +0.65 | 0.043 | T6→T7 (SVG/forms) |
| cross_page_nav_jaccard | -0.33 | 0.35 | T1→T2 (multi-page identity) |

## Web Almanac context (where our workloads sit on the public web)

- **ylt.DOMelementsCount** — workloads_v4 range 48–636, mean 253. Public (Markup 2024): p10=180, p50=594, p90=1716.
- **ylt.cssRules** — workloads_v4 range 20–315, mean 113. Public (CSS 2022): p50=613, p90=2023.
- **ylt.DOMelementMaxDepth** — workloads_v4 range 6–8, mean 7. Public (Markup 2024): Lighthouse fails >32.

## Caveats

- N=10 workloads. Wide bootstrap CIs are honest; treat composite as headline, per-metric as exploratory.
- Per-tier N unbalanced: T1=T2=T5=T6=1; T3=T4=T7=2; T8=0. Several adjacent-tier checks reduce to a single comparison.
- Genre confound: T6 only `comparison-table`, T5 only `poetry`. Tier-correlated metrics may really measure genre.
- Visual ≠ total task difficulty. Agents also see the prompt; harder visual content may be offset by clearer text.
- DesignBench S formula validated on real pages; our LLM-generated workloads may have different distributions. Cross-check with Web Almanac context above.

