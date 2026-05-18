# Website Bench

10 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t1-copper-kettle-suppers-16cf** (tier 1, recipe-card): Copper Kettle Suppers is a single-recipe showcase site presenting a definitive slow-braised lamb shank with white bean ragout, walking visitors through every detail from pantry list to plating notes.
- **synth-t1-maren-solvik-design-a2db** (tier 1, portfolio): The personal portfolio of Maren Solvik, a Norwegian-born graphic designer specializing in brand identity and print work for cultural institutions.
- **synth-t2-brackwater-marsh-conservancy-945d** (tier 2, nonprofit): Brackwater Marsh Conservancy is a Gulf Coast nonprofit dedicated to restoring tidal wetlands, educating the public about estuarine ecosystems, and funding community-led habitat projects.
- **synth-t2-ironclad-summit-dev-c9a0** (tier 2, conference): Ironclad Summit is a two-day systems engineering and infrastructure conference held annually in Pittsburgh, PA, featuring deep-dive technical talks, workshops, and a hardware expo.
- **synth-t3-oblique-flux-studio-dcf5** (tier 3, agency): Oblique Flux Studio is a boutique brand strategy and digital experience agency specializing in science, technology, and cultural institutions.
- **synth-t4-lumivex-signal-boost-c799** (tier 4, marketing-landing): Lumivex is a B2B signal-intelligence platform that helps growth teams identify high-intent leads before competitors do, marketed through a richly decorated five-page landing site.
- **synth-t5-chlorophyll-dispatch-weekly-5325** (tier 5, magazine-feature): Chlorophyll Dispatch is a premium long-form environmental journalism magazine covering ecological science, land politics, and biodiversity stories from the field.
- **synth-t6-nexum-vault-settings-e99e** (tier 6, account-settings): Nexum Vault is a fictional enterprise secrets-management platform offering exhaustive account settings across profile identity, multi-factor security, subscription billing, granular notification preferences, and a full tamper-evident audit log.
- **synth-t7-deep-current-oceandata-64e3** (tier 7, infographic): Deep Current is an interactive infographic journal translating NOAA and peer-reviewed ocean science into dense, visually rich data stories spanning coral bleaching, plastic accumulation, sea temperature anomalies, and conservation response zones.
- **synth-t8-forma-negra-review-11da** (tier 8, design-magazine): Forma Negra Review is a biannual critical design journal covering graphic systems, spatial typography, and material culture, presented as a dense multi-module web edition with the visual weight of a printed broadsheet.

## Running a task

The grader's multimodal-LLM judge (70% of the reward) requires
`ANTHROPIC_API_KEY` inside the verifier container. Pass it through
with `--ve` (or `--env-file`). Without it, every trial returns 0.0
because `tests/test.sh` writes a zero on any verifier crash.

```bash
harbor check ./synth-t1-copper-kettle-suppers-16cf
harbor run -p ./synth-t1-copper-kettle-suppers-16cf -a oracle --env modal \
  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
harbor run -p ./synth-t1-copper-kettle-suppers-16cf -a claude-code \
  -m anthropic/claude-opus-4-7 --env modal \
  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
```

## Running all tasks

There's no built-in dataset wrapping yet; iterate with a shell loop
or pass the whole dataset directory:

```bash
harbor run -p . -a oracle --env modal -n 10 \
  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY

# or per-task:
for d in synth-*/; do
  harbor run -p "$d" -a oracle --env modal \
    --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
done
```
