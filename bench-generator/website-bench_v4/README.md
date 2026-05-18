# Website Bench

10 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t1-ink-and-insomnia-blog-fea9** (tier 1, personal-blog): Ink & Insomnia is the personal blog of Mara Solène, a late-night writer documenting her thoughts on literature, solitude, and city life in Montreal.
- **synth-t2-ironclad-futures-summit-6724** (tier 2, conference): Ironclad Futures Summit is a three-day conference on industrial resilience and supply-chain innovation held annually in Pittsburgh, PA, targeting operations directors, logistics engineers, and policy makers.
- **synth-t3-ferroflux-systems-docs-712d** (tier 3, documentation): FerroFlux Systems is a fictional industrial IoT middleware platform; this documentation site covers its Rust-based SDK, REST API, configuration DSL, and troubleshooting workflows for embedded sensor networks.
- **synth-t3-ironbark-supply-co-0759** (tier 3, ecommerce): Ironbark Supply Co. is an Australian-themed outdoor and bushcraft goods store selling axes, fire-starters, canvas bags, and field tools via a dense catalog with sidebar filtering and full cart management.
- **synth-t4-luminos-ai-copilot-055c** (tier 4, marketing-landing): Luminos is an AI writing copilot for product teams that turns messy Notion docs and Jira tickets into polished release notes, changelogs, and customer emails in seconds.
- **synth-t4-obsidian-cove-retreat-6f74** (tier 4, hotel-resort): Obsidian Cove Retreat is a fictional clifftop resort on the Aegean coast offering 24 private suites, a sea-cave dining grotto, and curated coastal experiences — presented through a visually rich dark-luxury website.
- **synth-t5-ashen-meridian-verses-2521** (tier 5, poetry-collection): Ashen Meridian is the digital home of poet Solenne Vray's debut collection 'The Hour That Eats Itself,' seventeen poems about industrial grief, inherited silence, and the geography of eastern French mill towns.
- **synth-t6-nucleon-cloud-benchmark-13e6** (tier 6, comparison-table): Nucleon Cloud Benchmark is a detailed side-by-side comparison site for five competing cloud hosting tiers — Nano, Micro, Standard, Pro, and Enterprise — covering compute specs, storage pricing, network limits, and a live cost estimator form.
- **synth-t7-deep-ocean-pressure-atlas-3d66** (tier 7, infographic): Hadal Cartography is a five-page interactive infographic atlas exploring ocean depth zones, pressure physics, and life at extreme depths, rendered entirely through inline SVG diagrams, clipped depth-band visuals, and path-drawn creature illustrations.
- **synth-t7-obsidian-fold-studio-487f** (tier 7, brand-identity): Obsidian Fold is a boutique brand-identity studio that crafts visual systems for cultural institutions and independent luxury labels, presenting its own identity through angular SVG geometry and clipped compositions.

## Running a task

```bash
harbor check ./001-minimal-portfolio
harbor run -p ./001-minimal-portfolio -a oracle --env modal
harbor run -p ./001-minimal-portfolio -a claude-code \
  -m anthropic/claude-opus-4-7 --env modal
```

## Running all tasks

There's no built-in dataset wrapping yet; iterate with a shell loop:

```bash
for d in */; do
  harbor run -p "$d" -a oracle --env modal
done
```
