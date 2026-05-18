# Website Bench

16 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t1-ember-and-rye-kitchen-43c8** (tier 1, recipe-card): Ember & Rye Kitchen is a single-recipe showcase site presenting a definitive slow-braised short rib with smoked paprika and rye whiskey glaze, laid out as a clean vertical card experience across five focused pages.
- **synth-t1-ink-and-insomnia-blog-ab75** (tier 1, personal-blog): Ink & Insomnia is the personal blog of Maren Voss, a night-owl writer and former librarian who publishes late-night journal entries, long-form essays on memory and place, and annotated reading lists.
- **synth-t2-hollow-creek-rewilding-5cd2** (tier 2, nonprofit): Hollow Creek Rewilding is a regional nonprofit restoring native grasslands and riparian corridors across the Ozark plateau through volunteer stewardship, seed banking, and community science.
- **synth-t2-ironclad-futures-summit-b169** (tier 2, conference): Ironclad Futures Summit is a two-day industrial policy and infrastructure conference held in Pittsburgh, PA, bringing together engineers, legislators, and economists to debate the next decade of American manufacturing.
- **synth-t3-ferrolink-api-docs-6b08** (tier 3, documentation): FerroLink is a fictional industrial IoT data-pipeline API whose documentation site features a fixed left sidebar for navigation, a scrollable main content area with multi-column reference tables, sticky section headers, and dense data UI layouts throughout.
- **synth-t3-ironbark-field-supply-f270** (tier 3, ecommerce): Ironbark Field Supply is an online store selling professional bushcraft, wilderness survival, and land-management tools — axes, saws, cordage, fire-starting kits, and protective clothing — to farmers, rangers, and serious outdoor workers.
- **synth-t4-lumina-glass-studio-8c87** (tier 4, marketing-landing): Lumina Glass Studio is a boutique architectural glass art company marketing custom commission panels, decorative installations, and a signature blown-glass home collection to interior designers and high-end residential clients.
- **synth-t4-obsidian-tide-resort-098c** (tier 4, hotel-resort): Obsidian Tide Resort is a luxury cliffside retreat on the Oregon coast offering guests volcanic-rock spa pools, private tide-watch terraces, and farm-foraged Pacific Northwest cuisine — this site presents it with deep navy backdrops, gold gradients, and layered glass-card effects.
- **synth-t5-maison-corvidae-dining-dc65** (tier 5, restaurant-elegant): Maison Corvidae is a 28-seat neo-classical French supper club in a restored 1920s Portland townhouse, celebrated for its seven-course tasting menu and hand-selected Burgundy cellar.
- **synth-t5-moth-and-meridian-press-0edc** (tier 5, poetry-collection): Moth & Meridian Press is a curated online poetry collection publishing three seasonal anthologies per year, featuring emerging and established voices writing at the intersection of grief, cartography, and natural wonder.
- **synth-t6-northvault-banking-onboard-809d** (tier 6, signup-flow): NorthVault Credit Union's five-step digital account-opening flow for new members, featuring dense multi-column forms, custom-styled inputs with validation states, and a final review table.
- **synth-t6-voltwatch-battery-compare-69f5** (tier 6, comparison-table): VoltWatch is a battery-technology comparison site that lets consumers and engineers evaluate 14 lithium-ion, LFP, and solid-state battery models across chemistry, capacity, cycle life, cost-per-kWh, and safety ratings.
- **synth-t7-auric-veld-studio-0f8b** (tier 7, brand-identity): Auric Veld Studio is a Johannesburg-based brand-identity agency whose website uses aggressive SVG geometry, diagonal cuts, and masked photography stand-ins to express that brand design is simultaneously architecture and emotion.
- **synth-t7-deep-current-ocean-data-f54d** (tier 7, infographic): Deep Current is a five-page interactive infographic exploring the ocean's hidden layers — from surface temperatures to hadal trenches — using SVG-driven data visualizations and non-rectangular geometry to communicate marine science facts.
- **synth-t8-deep-fault-seismic-atlas-1f59** (tier 8, special-report): A special-report digital atlas investigating the Pacific Rim's underreported seismic corridors, combining field data, survivor testimony, and policy analysis into a five-chapter deep-dive titled 'Deep Fault: The Earthquakes Nobody Is Preparing For'.
- **synth-t8-iron-meridian-atlas-19f8** (tier 8, multimedia-essay): Iron Meridian Atlas is a long-form multimedia essay investigating the 1973 closure of the Harwick Steel Works in Pennsylvania — its economic aftermath, the families it fractured, and the contested memory of industrial labor in America.

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
