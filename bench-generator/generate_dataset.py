#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic>=0.40,<1.0",
# ]
# ///
"""
Generate a Harbor benchmark dataset of website-replication tasks.

Each task: a 5-page website at a specified difficulty tier and genre. The
generator drives an LLM to produce 5 HTML files per task, then wraps them in
the Harbor task harness (Dockerfile, score.py, etc.) copied from templates/.

Usage with uv (recommended — uv handles deps automatically):
    export ANTHROPIC_API_KEY=...
    uv run generate_dataset.py --count 10 --output ./website-bench

Usage without uv:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python generate_dataset.py --count 10 --output ./website-bench

Other flags:
    --model       LLM model name (default: claude-sonnet-4-6)
    --tier-min N  Minimum tier to include (default: 1)
    --tier-max N  Maximum tier to include (default: 3)
    --start-index N   Skip the first N matching seeds (for resuming)
    --max-retries N   How many times to retry generation if validation fails (default: 3)
    --templates-dir   Path to templates/ (default: ./templates relative to script)
    --seeds-module    Python module providing SEEDS list (default: ./seeds.py)

The generator is deterministic given the same seeds — re-running on the same
seed produces a new task directory (overwriting), so you can re-run to refresh
a single task by passing --include-id 001-minimal-portfolio.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("ERROR: pip install anthropic")

# Prompts live in prompts.py so they can be edited without diving into
# generator logic. See the module docstring there for the "if you change X
# also change Y" invariants.
import prompts


# ---------- HTML validation ----------

class _HTMLValidator(HTMLParser):
    """Best-effort HTML parser for sanity checks."""
    def __init__(self) -> None:
        super().__init__()
        self.ok = True
        self.has_html_tag = False
        self.has_body_tag = False
        self.has_script_tag = False
        self.external_urls: list[str] = []

    def error(self, message: str) -> None:  # type: ignore[override]
        self.ok = False

    def handle_starttag(self, tag, attrs):
        if tag == "html":
            self.has_html_tag = True
        elif tag == "body":
            self.has_body_tag = True
        elif tag == "script":
            self.has_script_tag = True
        for _, value in attrs:
            if value and isinstance(value, str) and re.match(r"https?://", value):
                self.external_urls.append(value)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_html(html: str) -> ValidationResult:
    errors: list[str] = []
    p = _HTMLValidator()
    try:
        p.feed(html)
    except Exception as e:
        errors.append(f"HTML parse error: {e}")
        return ValidationResult(False, errors)
    if not p.ok:
        errors.append("HTML parser reported errors")
    if not p.has_body_tag:
        errors.append("missing <body> tag")
    if p.has_script_tag:
        errors.append("<script> tag present (task says no JS)")
    if p.external_urls:
        errors.append(f"external network URLs present: {p.external_urls[:3]}")
    if len(html) < 200:
        errors.append(f"suspiciously short HTML ({len(html)} bytes)")
    return ValidationResult(ok=not errors, errors=errors)


# ---------- LLM generation ----------


def call_llm(client: Anthropic, model: str, seed: dict, attempt: int = 1,
             prior_errors: list[str] | None = None) -> dict[str, str]:
    """Single LLM call; returns dict of page_name -> html. May raise."""
    user = prompts.build_user_prompt(seed, prior_errors=prior_errors)

    print(f"  [{seed['id']}] LLM call (attempt {attempt})")
    resp = client.messages.create(
        model=model,
        # 16000 fits even the most content-dense seeds (e.g., dashboards with
        # sidebars + tables + KPI cards across 5 pages). Sonnet 4.6 supports
        # up to 64k output. Bump higher if you add tier 6+ seeds with forms,
        # SVG illustrations, or magazine layouts.
        max_tokens=16000,
        system=prompts.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )

    # Concatenate text blocks (defensive — should only be one).
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))

    # Detect truncation explicitly. The API tells us in stop_reason when it
    # ran out of room. If we don't catch this here, the next stage tries to
    # parse a truncated string and reports a misleading "Unterminated string"
    # error that doesn't hint at the real cause.
    stop_reason = getattr(resp, "stop_reason", None)
    if stop_reason == "max_tokens":
        raise ValueError(
            f"output truncated at max_tokens ({len(text)} chars produced). "
            f"Either raise max_tokens in generate_dataset.py or simplify the seed."
        )

    # The model is told to return strict JSON. Strip markdown fences just in
    # case it slipped any in.
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}\n---\n{text[:500]}")

    if not isinstance(data, dict):
        raise ValueError(f"LLM returned a {type(data).__name__}, expected dict")

    expected = set(seed["page_specs"].keys())
    got = set(data.keys())
    if got != expected:
        missing = expected - got
        extra = got - expected
        raise ValueError(f"key mismatch — missing: {missing}, extra: {extra}")

    return data


def generate_pages_for_seed(client: Anthropic, model: str, seed: dict,
                            max_retries: int) -> dict[str, str]:
    """Generate and validate pages for one seed, retrying on validation failures."""
    prior_errors: list[str] = []
    for attempt in range(1, max_retries + 1):
        try:
            pages = call_llm(client, model, seed, attempt=attempt,
                             prior_errors=prior_errors or None)
        except ValueError as e:
            print(f"  [{seed['id']}] generation error on attempt {attempt}: {e}")
            prior_errors = [str(e)]
            continue

        # Validate every page; collect failures.
        per_page_errors: dict[str, list[str]] = {}
        for name, html in pages.items():
            result = validate_html(html)
            if not result.ok:
                per_page_errors[name] = result.errors

        if not per_page_errors:
            return pages

        # Build a fixup prompt with the specific failures.
        prior_errors = []
        for page, errs in per_page_errors.items():
            for err in errs:
                prior_errors.append(f"[{page}] {err}")
        print(f"  [{seed['id']}] validation failed on attempt {attempt}:")
        for e in prior_errors:
            print(f"    - {e}")

    raise RuntimeError(f"giving up on {seed['id']} after {max_retries} attempts")


# ---------- Template rendering ----------

def render_template(text: str, replacements: dict[str, str]) -> str:
    out = text
    for key, value in replacements.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def write_task(seed: dict, pages: dict[str, str], templates_dir: Path,
               output_root: Path) -> Path:
    task_id = seed["id"]
    task_dir = output_root / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    # Copy harness directories verbatim.
    for sub in ["solution", "tests"]:
        shutil.copytree(templates_dir / sub, task_dir / sub)
    (task_dir / "environment").mkdir()
    shutil.copy(templates_dir / "environment" / "Dockerfile",
                task_dir / "environment" / "Dockerfile")
    shutil.copy(templates_dir / "environment" / "make.py",
                task_dir / "environment" / "make.py")

    # Write the generated pages.
    ref_root = task_dir / "environment" / "reference-pages"
    ref_root.mkdir()
    for page_name, html in pages.items():
        page_dir = ref_root / page_name
        page_dir.mkdir()
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    # Render templated files.
    n_pages = len(pages)
    page_names = list(pages.keys())
    input_list = "\n".join(f"- `/app/references/{name}.png`" for name in page_names)
    output_list = "\n".join(
        f"- `/app/output/{name}/index.html`" for name in page_names
    )

    task_name = f"website-bench/{task_id}"
    task_description = seed["description"].replace('"', '\\"')
    difficulty = (
        f"Tier {seed['tier']} ({seed['genre']}): {seed['description']}"
    ).replace('"', '\\"')

    task_toml = render_template(
        (templates_dir / "task.toml.tpl").read_text(),
        {
            "TASK_NAME": task_name,
            "TASK_DESCRIPTION": task_description,
            "DIFFICULTY_EXPLANATION": difficulty,
            "GENRE": seed["genre"],
            "TIER": str(seed["tier"]),
        },
    )
    (task_dir / "task.toml").write_text(task_toml)

    instruction = render_template(
        (templates_dir / "instruction.md.tpl").read_text(),
        {
            "N_PAGES": str(n_pages),
            "INPUT_LIST": input_list,
            "OUTPUT_LIST": output_list,
        },
    )
    (task_dir / "instruction.md").write_text(instruction)

    # Ensure scripts are executable.
    for script in [task_dir / "solution" / "solve.sh", task_dir / "tests" / "test.sh"]:
        script.chmod(0o755)

    return task_dir


# ---------- Dataset registry ----------

def write_registry(output_root: Path, manifest: list[dict]) -> None:
    """Writes a simple summary of generated tasks. Not a true Harbor registry."""
    (output_root / "registry.json").write_text(
        json.dumps({"tasks": manifest}, indent=2)
    )
    readme = [
        "# Website Bench",
        "",
        f"{len(manifest)} HTML/CSS replication tasks, organized by tier.",
        "",
        "## Tasks",
        "",
    ]
    for entry in manifest:
        readme.append(
            f"- **{entry['id']}** (tier {entry['tier']}, {entry['genre']}): "
            f"{entry['description']}"
        )
    readme.extend([
        "",
        "## Running a task",
        "",
        "```bash",
        "harbor check ./001-minimal-portfolio",
        "harbor run -p ./001-minimal-portfolio -a oracle --env modal",
        "harbor run -p ./001-minimal-portfolio -a claude-code \\",
        "  -m anthropic/claude-opus-4-7 --env modal",
        "```",
        "",
        "## Running all tasks",
        "",
        "There's no built-in dataset wrapping yet; iterate with a shell loop:",
        "",
        "```bash",
        "for d in */; do",
        '  harbor run -p \"$d\" -a oracle --env modal',
        "done",
        "```",
        "",
    ])
    (output_root / "README.md").write_text("\n".join(readme))


# ---------- CLI ----------

def load_seeds_module(path: Path):
    spec = importlib.util.spec_from_file_location("seeds_mod", str(path))
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load seeds module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--tier-min", type=int, default=None,
                        help="Minimum tier to include (default: lowest defined in seeds.py)")
    parser.add_argument("--tier-max", type=int, default=None,
                        help="Maximum tier to include (default: highest defined in seeds.py)")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--templates-dir", type=Path, default=here / "templates")
    parser.add_argument("--seeds-module", type=Path, default=here / "seeds.py")
    parser.add_argument("--include-id", action="append", default=[],
                        help="Only generate the named seed id(s). Repeatable.")
    parser.add_argument("--concurrency", "-j", type=int, default=8,
                        help="Number of seeds to generate in parallel (default: 8). "
                             "Each one is an independent LLM call.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan without calling the LLM.")
    parser.add_argument("--list-tiers", action="store_true",
                        help="Print tier definitions from seeds.py and exit.")
    args = parser.parse_args()

    seeds_mod = load_seeds_module(args.seeds_module)

    # Validate the seed library before anything else.
    seed_errors = seeds_mod.validate_seeds()
    if seed_errors:
        print("ERROR: seeds.py has problems:", file=sys.stderr)
        for e in seed_errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Handle --list-tiers and exit.
    if args.list_tiers:
        for tier_num in sorted(seeds_mod.TIERS):
            t = seeds_mod.TIERS[tier_num]
            n_seeds = sum(1 for s in seeds_mod.SEEDS if s["tier"] == tier_num)
            print(f"\nTier {tier_num}: {t['name']}  ({n_seeds} seeds)")
            print(f"  {t['description']}")
            print(f"  Capabilities:")
            for cap in t["css_capabilities"]:
                print(f"    - {cap}")
        return

    # Default tier range comes from seeds.py, not hardcoded here.
    tier_min_default, tier_max_default = seeds_mod.tier_range()
    tier_min = args.tier_min if args.tier_min is not None else tier_min_default
    tier_max = args.tier_max if args.tier_max is not None else tier_max_default

    if not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")

    seeds = seeds_mod.get_seeds(
        count=None,
        tier_range=(tier_min, tier_max),
    )
    if args.include_id:
        seeds = [s for s in seeds if s["id"] in args.include_id]
    seeds = seeds[args.start_index : args.start_index + args.count]

    if not seeds:
        sys.exit("No seeds matched the filters.")

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating {len(seeds)} task(s) into {args.output}")
    print(f"  Model: {args.model}")
    print(f"  Tier range: {tier_min}..{tier_max}")
    for s in seeds:
        print(f"  - {s['id']} (tier {s['tier']}, {s['genre']})")
    print()

    if args.dry_run:
        return

    client = Anthropic()
    manifest: list[dict] = []
    failures: list[str] = []
    manifest_lock = threading.Lock()
    completed = 0
    completed_lock = threading.Lock()

    def process_one(i: int, seed: dict) -> tuple[str, dict | None, Exception | None]:
        """Worker: generate one seed end-to-end. Returns (seed_id, manifest_entry|None, error|None)."""
        prefix = f"[{seed['id']}]"
        start = time.time()
        try:
            # Reuse log noise reduction: the helper functions print() inside;
            # they prefix with seed id implicitly via the seed argument's id.
            # To keep parallel logs readable we re-prefix here.
            print(f"{prefix} starting...")
            pages = generate_pages_for_seed(
                client, args.model, seed, max_retries=args.max_retries,
            )
            task_dir = write_task(seed, pages, args.templates_dir, args.output)
            elapsed = time.time() - start

            entry = {
                "id": seed["id"],
                "tier": seed["tier"],
                "genre": seed["genre"],
                "description": seed["description"],
                "n_pages": len(pages),
            }
            print(f"{prefix} done in {elapsed:.1f}s -> {task_dir.name}")
            return seed["id"], entry, None
        except Exception as e:
            print(f"{prefix} FAILED: {e}")
            return seed["id"], None, e

    total = len(seeds)
    concurrency = max(1, min(args.concurrency, total))
    print(f"Running {total} task(s) with concurrency={concurrency}")

    overall_start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(process_one, i, seed): seed
            for i, seed in enumerate(seeds, 1)
        }
        for future in as_completed(futures):
            seed_id, entry, error = future.result()
            with completed_lock:
                completed += 1
                position = completed
            if entry:
                with manifest_lock:
                    manifest.append(entry)
                print(f"  ({position}/{total}) ok: {seed_id}")
            else:
                failures.append(seed_id)
                print(f"  ({position}/{total}) fail: {seed_id}")

    # Keep manifest order stable across runs: sort by seed id.
    manifest.sort(key=lambda e: e["id"])
    write_registry(args.output, manifest)

    overall_elapsed = time.time() - overall_start
    print(f"\nDone in {overall_elapsed:.1f}s. "
          f"{len(manifest)} succeeded, {len(failures)} failed.")
    if failures:
        print(f"  Failed: {failures}")


if __name__ == "__main__":
    main()