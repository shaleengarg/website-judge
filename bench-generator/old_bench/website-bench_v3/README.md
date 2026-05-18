# Website Bench

12 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t1-ember-and-rye-kitchen-bf91** (tier 1, recipe-card): Ember & Rye Kitchen is a single-recipe showcase site presenting a slow-braised short rib with smoked rye whiskey glaze, laid out as a beautifully typeset digital recipe card across five focused pages.
- **synth-t1-ink-and-insomnia-blog-c198** (tier 1, personal-blog): Ink & Insomnia is the personal blog of Mara Veltri, a insomniac copywriter who writes candid essays about 3am thoughts, obscure paperback finds, and the strange comfort of empty diners.
- **synth-t2-hollow-creek-land-trust-3d55** (tier 2, nonprofit): Hollow Creek Land Trust is a regional nonprofit protecting 14,000 acres of Appalachian forest, wetland, and farmland through voluntary conservation easements and community stewardship programs.
- **synth-t2-strata-data-summit-d040** (tier 2, conference): Strata Data Summit is a two-day annual conference for data engineers and analytics leaders held in Pittsburgh, featuring keynotes, workshops, and networking sessions.
- **synth-t3-ferroflux-systems-docs-fa87** (tier 3, documentation): FerroFlux Systems is a fictional real-time magnetic sensor data pipeline SDK with full reference documentation covering installation, REST/WebSocket API endpoints, YAML configuration schemas, version history, and diagnostic guides.
- **synth-t3-obsidian-quill-bindery-711f** (tier 3, ecommerce): Obsidian Quill Bindery is an artisan stationery and bookbinding supply shop selling hand-bound journals, custom endpapers, bone folders, and leather hides to bookbinders and paper artists.
- **synth-t4-luminos-ai-copilot-9d26** (tier 4, marketing-landing): Luminos is a fictional AI writing copilot SaaS whose marketing site uses deep-navy dark-mode aesthetics, violet-to-teal gradients, layered box-shadow elevation, and glassmorphism cards to convey premium intelligence.
- **synth-t5-maison-cendree-dining-3a9f** (tier 5, restaurant-elegant): Maison Cendrée is a French-inflected fine dining restaurant in a converted 19th-century mill in Asheville, NC, serving a nightly six-course tasting menu built around wood-fire cookery and Appalachian ingredients.
- **synth-t6-obsidian-vault-finance-79c4** (tier 6, signup-flow): Obsidian Vault is a premium self-directed investment account signup flow for high-net-worth individuals, featuring multi-step registration with dense form layouts, custom-styled inputs, and a detailed plan comparison table.
- **synth-t6-vaultline-cloud-storage-aed4** (tier 6, comparison-table): Vaultline is a fictional enterprise cloud-storage comparison site that lets IT buyers pit five storage tiers—Starter, Business, Scale, Enterprise, and Sovereign—against each other across dozens of technical and commercial criteria.
- **synth-t8-deep-time-salt-flats-05b3** (tier 8, multimedia-essay): A long-form multimedia essay exploring the geology, ecology, and human history of the Bonneville Salt Flats, structured as five thematic chapters each with its own visual grammar.
- **synth-t8-deep-water-horizon-watch-92c7** (tier 8, special-report): A multi-page investigative special report by the Tethys Journalism Collective documenting five years of illegal deep-sea trawling in the South Coral Sea, combining data visualizations, field correspondent logs, and policy analysis.

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
