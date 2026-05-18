# Workloads_v4 Difficulty Validation Report

_N = 10 tasks, tier ladder T1–T7 per docs/running_notes.md_

## Composite scores vs. tier

- **composite_designbench_S** — Spearman ρ=+0.361 (p=0.306, 95% CI [-0.39, +0.90]); Kendall τ=+0.276 (p=0.277)
- **composite_axis_mean** — Spearman ρ=+0.324 (p=0.361, 95% CI [-0.44, +0.88]); Kendall τ=+0.230 (p=0.365)

Headline target: ρ ≥ 0.85, τ ≥ 0.7. Below either → tier ladder needs revision.

## Ranking by composite_designbench_S vs. tier

| Rank | Task | Tier | Genre | S | axis_mean |
|---|---|---|---|---|---|
| 1 | synth-t3-ferroflux-systems-docs-712d | T3 | documentation | +1.20 | +1.06 |
| 2 | synth-t4-obsidian-cove-retreat-6f74 | T4 | hotel-resort | +0.66 | +0.01 |
| 3 | synth-t7-deep-ocean-pressure-atlas-3d66 | T7 | infographic | +0.50 | +0.22 |
| 4 | synth-t6-nucleon-cloud-benchmark-13e6 | T6 | comparison-table | +0.49 | +0.86 |
| 5 | synth-t4-luminos-ai-copilot-055c | T4 | marketing-landing | +0.47 | +0.12 |
| 6 | synth-t7-obsidian-fold-studio-487f | T7 | brand-identity | +0.16 | -0.22 |
| 7 | synth-t3-ironbark-supply-co-0759 | T3 | ecommerce | -0.17 | +0.04 |
| 8 | synth-t2-ironclad-futures-summit-6724 | T2 | conference | -0.64 | -0.43 |
| 9 | synth-t5-ashen-meridian-verses-2521 | T5 | poetry-collection | -0.87 | -0.60 |
| 10 | synth-t1-ink-and-insomnia-blog-fea9 | T1 | personal-blog | -1.80 | -1.05 |

## Per-tier descriptives

| tier | n | designbench_S(mean) | axis_mean(mean) | DOM(mean) | cssRules(mean) | cssColors(mean) | gradients(mean) | svg_paths(mean) | edge_density(mean) |
|---|---|---|---|---|---|---|---|---|---|
| T1 | 1 | -1.80 | -1.05 | 48 | 20 | 4.0 | 0.0 | 0.0 | 0.027 |
| T2 | 1 | -0.64 | -0.43 | 126 | 52 | 11.8 | 0.4 | 0.0 | 0.033 |
| T3 | 2 | +0.52 | +0.55 | 252 | 79 | 19.1 | 1.9 | 0.0 | 0.034 |
| T4 | 2 | +0.56 | +0.06 | 131 | 86 | 27.2 | 10.3 | 0.0 | 0.023 |
| T5 | 1 | -0.87 | -0.60 | 107 | 42 | 10.2 | 0.8 | 0.0 | 0.027 |
| T6 | 1 | +0.49 | +0.86 | 240 | 81 | 18.4 | 1.6 | 0.0 | 0.035 |
| T7 | 2 | +0.33 | -0.00 | 240 | 67 | 14.6 | 1.2 | 68.3 | 0.026 |

## Adjacent-tier inversions (composite_designbench_S)

- T1 → T2: median S = -1.80 vs -0.64 (✓)
- T2 → T3: median S = -0.64 vs +0.52 (✓)
- T3 → T4: median S = +0.52 vs +0.56 (✓)
- T4 → T5: median S = +0.56 vs -0.87 (✗ inversion)
- T5 → T6: median S = -0.87 vs +0.49 (✓)
- T6 → T7: median S = +0.49 vs +0.33 (✗ inversion)

## Per-metric Spearman ρ vs. tier (10 tasks)

Each metric is expected to *jump at a specific tier boundary*, not rise monotonically T1→T7. Treat correlations as exploratory.

| Metric | ρ | p | Expected boundary |
|---|---|---|---|
| ylt.DOMelementsCount | +0.47 | 0.17 | T5→T6 (dense forms/tables) |
| ylt.DOMelementMaxDepth | +0.43 | 0.22 | T2→T3 (layout nesting) |
| ylt.iframesCount | (constant) | — | (noise — workloads use no iframes) |
| ylt.cssRules | +0.24 | 0.5 | T3→T4 (visual polish) |
| ylt.cssSelectors | +0.24 | 0.5 | T3→T4 |
| ylt.cssDeclarations | +0.24 | 0.51 | T3→T4 |
| ylt.cssComplexSelectors | +0.30 | 0.4 | T3→T4 |
| ylt.cssSpecificityIdAvg | +0.24 | 0.5 | (noise) |
| ylt.cssDuplicatedSelectors | (constant) | — | (noise) |
| ylt.cssImportants | -0.05 | 0.9 | (noise) |
| ylt.cssEmptyRules | (constant) | — | (noise) |
| ylt.cssColors | +0.15 | 0.69 | T3→T4 (palette grows) |
| ylt.nodesWithInlineCSS | +0.89 | 0.00062 | (noise) |
| svg_path_count | +0.70 | 0.025 | T6→T7 (inline SVG) |
| gradient_count | +0.40 | 0.26 | T3→T4 (visual polish) |
| html_bytes | +0.53 | 0.11 | monotone (size grows with all of the above) |
| css_bytes | +0.22 | 0.54 | monotone |
| jpeg_proxy_bytes_per_kpixel | -0.43 | 0.22 | Forsythe clutter (T4, T7) |
| edge_density | -0.24 | 0.5 | T6→T7 (SVG/forms) |
| cross_page_nav_jaccard | -0.25 | 0.49 | T1→T2 (multi-page identity) |

## Web Almanac context (where our workloads sit on the public web)

- **ylt.DOMelementsCount** — workloads_v4 range 48–368, mean 177. Public (Markup 2024): p10=180, p50=594, p90=1716.
- **ylt.cssRules** — workloads_v4 range 20–94, mean 66. Public (CSS 2022): p50=613, p90=2023.
- **ylt.DOMelementMaxDepth** — workloads_v4 range 6–8, mean 7. Public (Markup 2024): Lighthouse fails >32.

## Caveats

- N=10 workloads. Wide bootstrap CIs are honest; treat composite as headline, per-metric as exploratory.
- Per-tier N unbalanced: T1=T2=T5=T6=1; T3=T4=T7=2; T8=0. Several adjacent-tier checks reduce to a single comparison.
- Genre confound: T6 only `comparison-table`, T5 only `poetry`. Tier-correlated metrics may really measure genre.
- Visual ≠ total task difficulty. Agents also see the prompt; harder visual content may be offset by clearer text.
- DesignBench S formula validated on real pages; our LLM-generated workloads may have different distributions. Cross-check with Web Almanac context above.

