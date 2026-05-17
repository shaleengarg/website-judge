# Website Bench Generator (v0)

Generates a Harbor benchmark dataset of 5-page-website replication tasks at
varying difficulty tiers. The agent under test will be shown the screenshots
of the 5 reference pages and asked to recreate them in HTML/CSS.

## Layout

```
website-bench-generator/
├── generate_dataset.py            # The generator
├── seeds.py                       # Curated task specs (10 seeds, tiers 1–3)
├── templates/                     # Harness files copied into every task
│   ├── task.toml.tpl              # Templated; placeholders for name/tier/genre
│   ├── instruction.md.tpl         # Templated; placeholders for page list
│   ├── environment/
│   │   ├── Dockerfile             # Verbatim per task
│   │   └── make.py                # Verbatim per task
│   ├── solution/solve.sh          # Verbatim per task
│   └── tests/
│       ├── test.sh                # Verbatim per task
│       └── score.py               # Verbatim per task
└── README.md                      # This file
```

## How it works

For each seed in `seeds.py` (each describes a website by tier, genre, palette,
typography, page list, per-page specs):

1. The generator sends the seed to an LLM (Sonnet by default — not the same
   model under test) and asks for 5 HTML files as JSON.
2. Each HTML page is validated: parses, has `<body>`, no `<script>`, no
   `http(s)://` URLs, reasonable length.
3. If validation fails, retry up to 3 times, feeding the errors back to the
   model for a fixup pass.
4. On success, write a Harbor task directory: the 5 HTML files go under
   `environment/reference-pages/<page>/index.html`, harness files are copied
   verbatim, `task.toml` and `instruction.md` are rendered from templates.

## Run it

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...

python generate_dataset.py --count 10 --output ./website-bench
```

Useful flags:

```bash
# Just the easiest 3 tasks
python generate_dataset.py --count 3 --tier-min 1 --tier-max 1 --output ./bench-easy

# Regenerate one specific seed
python generate_dataset.py --include-id 004-saas-marketing --output ./website-bench

# See what would happen without calling the LLM
python generate_dataset.py --count 10 --output ./website-bench --dry-run

# Use a different generation model (default is sonnet)
python generate_dataset.py --count 10 --model claude-opus-4-7 --output ./website-bench
```

## After generation, validate

Always sanity-check that each generated task passes its oracle:

```bash
cd website-bench
for d in */; do
  echo "=== $d ==="
  harbor run -p "$d" -a oracle --env modal 2>&1 | tail -5
done
```

Every task should print reward ≈ 1.000. If any score lower, the verifier
isn't agreeing with itself — usually a CSS quirk causing tiny render
differences between identical inputs (shouldn't happen but worth knowing).

## Iterating on the dataset

The seed library in `seeds.py` defines the benchmark. To change difficulty,
genre coverage, or specific page specs, edit that file. Then regenerate.

Re-running `generate_dataset.py` with the same seed id **overwrites** the
existing task directory. Use `--include-id <id>` to regenerate just one.

## Where v0 ends and v1 begins

v0 (what you have now):

- 10 hardcoded seeds across tiers 1–3 and 9 genres
- One-shot LLM generation, three retry attempts on validation failure
- Basic structural validation (parse, no script, no external URLs)
- No automatic oracle check — you run it yourself after generation

v1 ideas:

- Multi-turn generation: generate → self-critique → refine
- Automatic oracle smoke test post-generation (reject tasks where oracle < 0.95)
- LLM-as-judge component in `score.py`
- Tiers 4–8 (visual polish, complex typography, forms, SVG, magazine layouts)
- More seeds per tier so `--count 50` is meaningful
- Real-screenshot ground truth (give the model a real site screenshot, have
  it produce the HTML — that becomes the task's reference)
