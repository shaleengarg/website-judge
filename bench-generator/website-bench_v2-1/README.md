# Website Bench

16 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t1-copper-kettle-recipes-2b51** (tier 1, recipe-card): Copper Kettle Recipes is a single-dish deep-dive site dedicated to a classic Hungarian Beef Goulash, walking visitors through every detail from ingredients to the cook's personal story.
- **synth-t1-ink-and-anchovy-blog-3ae0** (tier 1, personal-blog): Ink & Anchovy is the personal blog of Marta Solberg, a food writer and amateur classicist living in Bergen, Norway, who writes about Mediterranean cooking, old books, and slow travel.
- **synth-t2-hollow-creek-land-trust-6f83** (tier 2, nonprofit): Hollow Creek Land Trust is a fictional Appalachian nonprofit preserving over 12,000 acres of forested ridgeline and creek-bottom habitat through conservation easements, community partnerships, and volunteer stewardship programs.
- **synth-t2-ironclad-futures-summit-842f** (tier 2, conference): Ironclad Futures Summit is a two-day manufacturing and industrial-technology conference held in Pittsburgh, PA, bringing together engineers, policy makers, and investors around the future of domestic production.
- **synth-t3-ferroflux-api-docs-2d81** (tier 3, documentation): FerroFlux is a fictional real-time magnetic-field sensor API platform, and this documentation site covers authentication, endpoints, data schemas, versioned changelog, and live service status in a multi-column dark-mode layout.
- **synth-t3-ironveil-tactical-gear-9a55** (tier 3, ecommerce): Ironveil is a direct-to-consumer tactical and outdoor gear shop selling modular plate carriers, load-bearing vests, gloves, and accessories to civilian preparedness enthusiasts and security professionals.
- **synth-t4-lumenos-clarity-lens-3f28** (tier 4, marketing-landing): Lumenos is a B2B SaaS marketing landing site for an AI-powered document clarity analyzer that detects ambiguity, jargon, and readability gaps in legal and compliance contracts.
- **synth-t4-obsidian-cove-retreat-c24f** (tier 4, hotel-resort): Obsidian Cove Retreat is a secluded volcanic-island luxury resort website that uses layered gradients, glass-morphism cards, and a dark-gold visual language to evoke exclusivity and natural drama.
- **synth-t5-ashen-meridian-verses-e175** (tier 5, poetry-collection): Ashen Meridian is the online home of poet Céleste Vaudreuil's debut collection 'The Longitude of Smoke', presenting 23 poems about industrial grief, inherited memory, and the St. Lawrence River delta.
- **synth-t5-maison-cendree-bistro-12b3** (tier 5, restaurant-elegant): Maison Cendrée is a fictional Lyonnaise-inspired bistro in Montreal whose static site uses a deliberate typographic hierarchy—drop caps, pull quotes, and a modular scale from 0.75rem to 4rem—to evoke the atmosphere of candlelit stone dining rooms.
- **synth-t6-nucleon-gpu-benchmark-5f4f** (tier 6, comparison-table): Nucleon Benchmarks is an independent GPU comparison site presenting dense performance data, pricing tiers, and hardware specifications for eight current-generation graphics cards across five vendor lines.
- **synth-t6-vaultline-private-banking-52b7** (tier 6, signup-flow): Vaultline is a fictional boutique private-banking onboarding portal where high-net-worth applicants select an account tier, enter personal and financial data across five precision-form pages, and submit a complete application package.
- **synth-t7-deep-current-ocean-data-be0f** (tier 7, infographic): An interactive infographic site called 'Abyssal Atlas' presenting data-driven visual essays about Earth's ocean systems, using inline SVG diagrams, clipped depth cross-sections, and path-drawn marine silhouettes.
- **synth-t7-obsidian-fold-studio-0f85** (tier 7, brand-identity): Obsidian Fold is a boutique brand-identity studio whose website uses non-rectangular geometry, SVG-drawn logomarks, and clipped compositions to demonstrate the studio's obsession with precise, angular visual systems.
- **synth-t8-half-life-of-light-b6cf** (tier 8, multimedia-essay): A multimedia essay exploring how analog photography processes memory, loss, and time through five interconnected chapters that mix typographic essays, data displays, and visual diagrams.
- **synth-t8-iron-corridor-infrastructure-b16b** (tier 8, special-report): A special investigative report — 'The Iron Corridor' — examining the structural decay of North America's inland freight rail network across five densely composed editorial pages.

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
