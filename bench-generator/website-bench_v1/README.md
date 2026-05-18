# Website Bench

16 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t1-burnt-sage-kitchen-9322** (tier 1, recipe-card): A single hand-written-style recipe card site for a home cook sharing her definitive slow-braised lamb shoulder with preserved lemon — one dish presented across five focused pages.
- **synth-t1-ember-and-rye-smokehouse-6bc9** (tier 1, restaurant): A no-frills Texas-style BBQ smokehouse website — dark, bold, text-driven, celebrating slow-smoked meats and honest cooking.
- **synth-t1-ink-and-altitude-blog-744b** (tier 1, personal-blog): A personal blog by a mountaineer and essayist named Petra Voss, documenting climbs, slow travel, and ideas encountered along the way.
- **synth-t1-inkwell-and-insomnia-blog-78b5** (tier 1, personal-blog): A personal blog by a night-owl writer named Vera Osei, covering late-night reflections, long-form essays, and annotated reading lists.
- **synth-t1-ironbell-founders-summit-ecd1** (tier 1, event-announcement): Ironbell Founders Summit is a one-day independent startup conference held in Detroit, announced via a stark, text-forward static site with no images.
- **synth-t1-mira-voss-printmaker-0262** (tier 1, portfolio): A printmaker and relief artist's portfolio presenting woodcut and linocut work in a plain, press-sheet aesthetic with no imagery.
- **synth-t2-inkwell-doc-platform-ba25** (tier 2, saas-marketing): Marketing site for Inkwell, a SaaS platform that turns messy internal knowledge bases into clean, searchable, auto-organized documentation hubs for mid-size engineering teams.
- **synth-t2-inkwell-quarterly-review-7ca2** (tier 2, editorial): Inkwell Quarterly is a fictional literary and cultural review publishing long-form essays, author interviews, and critical notebook entries across five editorially styled pages.
- **synth-t2-ironclad-futures-summit-b347** (tier 2, conference): A three-day industrial technology and manufacturing futures conference called IRONCLAD 2025, held in Pittsburgh, Pennsylvania.
- **synth-t2-ironwood-literacy-project-f866** (tier 2, nonprofit): A community literacy nonprofit called the Ironwood Literacy Project that provides adult reading programs across rural Appalachia.
- **synth-t2-noctua-sleep-tracker-d5d0** (tier 2, mobile-app): Marketing site for Noctua, a sleep-tracking mobile app that analyzes rest cycles and gives personalized bedtime coaching.
- **synth-t3-ferroflux-api-docs-6c28** (tier 3, documentation): API documentation site for a fictional real-time sensor data platform called FerroFlux, covering REST endpoints, SDKs, and integration guides.
- **synth-t3-inkwell-press-supplies-d2b2** (tier 3, ecommerce): An online specialty shop selling letterpress printing supplies, inks, and custom type blocks under the brand Inkwell Press Co.
- **synth-t3-ironclad-fleet-ops-9fe6** (tier 3, dashboard): Fleet operations dashboard for a fictional long-haul trucking company called Ironclad Logistics, tracking vehicle status, driver alerts, and performance reports.
- **synth-t3-ironshore-dispatch-4ece** (tier 3, news-magazine): Ironshore Dispatch is a fictional independent news magazine covering global affairs, data journalism, and opinion, styled after a classic broadsheet-meets-digital publication.
- **synth-t3-ironveil-creative-studio-4df4** (tier 3, agency): Ironveil is a fictional boutique brand-strategy and visual identity agency specializing in challenger brands, presenting its work, capabilities, and team across five densely-laid-out pages.

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
