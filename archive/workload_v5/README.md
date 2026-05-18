# Website Bench

2 HTML/CSS replication tasks, organized by tier.

## Tasks

- **synth-t7-deep-current-oceandata-4351** (tier 7, infographic): Deep Current is an interactive infographic site presenting peer-reviewed ocean health data through dense SVG charts, illustrated cross-sections, and multi-column data layouts aimed at climate researchers and educators.
- **synth-t8-folio-obscura-press-89f5** (tier 8, design-magazine): Folio Obscura is a quarterly design criticism magazine obsessed with the hidden logic of visual systems — covering typefaces, industrial objects, grid theory, and the archaeology of forgotten design movements.

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
