#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic>=0.40,<1.0",
# ]
# ///
"""
Generate a Harbor benchmark dataset of website-replication tasks.

Each task: a 5-page website at a specified difficulty tier and genre. Seeds
are LLM-generated on demand by concept_gen.py — there is no hardcoded seed
list. Codegen then drives an LLM to produce 5 HTML files per task (one call
per page) and wraps them in the Harbor task harness (Dockerfile, score.py,
etc.) copied from templates/.

Usage with uv (recommended — uv handles deps automatically):
    export ANTHROPIC_API_KEY=...
    uv run generate_dataset.py --count 10 --output ./website-bench

Other flags:
    --model       Codegen model (default: claude-opus-4-7). Concepts always
                  use claude-sonnet-4-6.
    --tier-min N  Minimum tier to include (default: lowest static tier)
    --tier-max N  Maximum tier to include (default: highest static tier;
                  motion-required tiers like 9 are excluded by default)
    --synth-seed K  RNG seed for tier/genre selection (default: random per run)
    --max-retries N  Per-page retries on HTML validation failure (default: 3)
    --concurrency N  Outer parallelism. Peak in-flight calls = 5N during codegen.
    --templates-dir  Path to templates/ (default: ./templates next to script)
    --seeds-module   Python module providing TIERS/GENRES (default: ./seeds.py)

Determinism: identical --synth-seed + tier range + count produces the same
(tier, genre) pair sequence. The LLM calls within each pair are not
deterministic.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
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
import concept_gen


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
        for name, value in attrs:
            # xmlns and xmlns:* attribute values are XML namespace identifiers
            # (e.g. "http://www.w3.org/2000/svg"), not network resources. They
            # look like URLs but the browser never fetches them.
            if name == "xmlns" or (name and name.startswith("xmlns:")):
                continue
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
#
# Codegen is one LLM call PER PAGE. The previous design asked for all 5 pages
# in a single JSON response, which blew the max_tokens budget on dense tier-3
# seeds (dashboards, docs sites). Per-page calls give each page its own
# 16000-token budget and let the pages run in parallel within a single seed.
# Cross-page consistency now relies on the seed constraints + palette/type
# hints being prescriptive — sanity.py catches drift after the fact.


def call_llm_one_page(
    client: Anthropic,
    model: str,
    seed: dict,
    page_name: str,
    attempt: int = 1,
    prior_errors: list[str] | None = None,
) -> str:
    """Single LLM call for one page; returns raw HTML. May raise ValueError."""
    user = prompts.build_page_prompt(seed, page_name, prior_errors=prior_errors)

    print(f"  [{seed['id']}/{page_name}] LLM call (attempt {attempt})")
    resp = client.messages.create(
        model=model,
        # 16000 tokens per page is plenty for tier-3 dashboards and docs.
        # Sonnet/Opus 4.6+ supports up to 64k output if a future tier needs it.
        max_tokens=16000,
        system=prompts.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )

    text = "".join(b.text for b in resp.content if hasattr(b, "text"))

    # Detect truncation explicitly. Without this, downstream HTML validation
    # reports a parser error instead of the real cause.
    stop_reason = getattr(resp, "stop_reason", None)
    if stop_reason == "max_tokens":
        raise ValueError(
            f"output truncated at max_tokens ({len(text)} chars produced)."
        )

    # Strip any markdown fences the model snuck in (it's told not to, but).
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html|json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    if not text:
        raise ValueError("LLM returned empty output")
    if not text.lstrip().startswith("<"):
        raise ValueError(f"LLM did not return HTML; got: {text[:200]!r}")

    return text


def _generate_one_page_with_retries(
    client: Anthropic,
    model: str,
    seed: dict,
    page_name: str,
    max_retries: int,
) -> str:
    """Generate + validate one page with retries on validation failure."""
    prior_errors: list[str] = []
    for attempt in range(1, max_retries + 1):
        try:
            html = call_llm_one_page(
                client, model, seed, page_name,
                attempt=attempt,
                prior_errors=prior_errors or None,
            )
        except ValueError as e:
            print(f"  [{seed['id']}/{page_name}] generation error on attempt {attempt}: {e}")
            prior_errors = [str(e)]
            continue

        result = validate_html(html)
        if result.ok:
            return html

        prior_errors = result.errors
        print(f"  [{seed['id']}/{page_name}] validation failed on attempt {attempt}:")
        for e in prior_errors:
            print(f"    - {e}")

    raise RuntimeError(
        f"giving up on {seed['id']}/{page_name} after {max_retries} attempts"
    )


def generate_pages_for_seed(
    client: Anthropic,
    model: str,
    seed: dict,
    max_retries: int,
) -> dict[str, str]:
    """Generate all 5 pages for one seed, running per-page calls in parallel.

    Each page has an independent retry loop, so a single flaky page no longer
    forces re-generation of the other four.

    Note on concurrency: this opens a nested ThreadPoolExecutor with up to 5
    workers inside the outer per-seed pool. With --concurrency 16 outside,
    that's up to 16*5 = 80 in-flight API calls. Drop --concurrency if you
    hit 429s.
    """
    page_names = list(seed["page_specs"].keys())
    results: dict[str, str] = {}
    first_error: BaseException | None = None

    with ThreadPoolExecutor(max_workers=len(page_names)) as pool:
        futures = {
            pool.submit(
                _generate_one_page_with_retries,
                client, model, seed, name, max_retries,
            ): name
            for name in page_names
        }
        for fut in as_completed(futures):
            page_name = futures[fut]
            try:
                results[page_name] = fut.result()
            except BaseException as e:
                # Record the first failure and cancel anything still pending;
                # one dead page means the whole task is unusable.
                if first_error is None:
                    first_error = e
                for other in futures:
                    if not other.done():
                        other.cancel()

    if first_error is not None:
        raise first_error

    return results


# ---------- Template rendering ----------

def render_template(text: str, replacements: dict[str, str]) -> str:
    out = text
    for key, value in replacements.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def compute_template_hash(templates_dir: Path) -> str:
    """Content hash of the templates/ directory tree.

    Walks all files under `templates_dir` in sorted-path order and hashes
    each file's relative path + content into a single SHA256. Any change to
    a templated file (Dockerfile, make.py, score.py, task.toml.tpl, etc.)
    produces a different hash.

    Used as a freshness stamp on each generated task: write_task drops the
    hash into `<task>/template_version.txt`, and `scripts/check_freshness.py`
    flags any task whose stamp doesn't match the current `templates/` hash.

    Excludes hidden files (.DS_Store, .pyc, etc.) and __pycache__.
    """
    h = hashlib.sha256()
    root = templates_dir.resolve()
    paths = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
        and "__pycache__" not in p.parts
    )
    for p in paths:
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00\x00")
    return h.hexdigest()


def apply_templates_to_task(
    seed: dict,
    page_names: list[str],
    templates_dir: Path,
    task_dir: Path,
) -> None:
    """Copy templates and render .tpl files into an existing task_dir.

    Overwrites: solution/, tests/, environment/Dockerfile, environment/make.py,
                task.toml, instruction.md, template_version.txt.
    Preserves:  environment/reference-pages/ (LLM HTML), seed.json.

    Used by both write_task (initial generation) and scripts/upgrade_tasks.py
    (refresh a stale task without re-running the LLM).
    """
    # solution/ and tests/ are pure verbatim subtrees — wipe & recopy.
    for sub in ("solution", "tests"):
        target = task_dir / sub
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(templates_dir / sub, target)

    env_dir = task_dir / "environment"
    env_dir.mkdir(exist_ok=True)
    for fname in ("Dockerfile", "make.py"):
        shutil.copy(templates_dir / "environment" / fname, env_dir / fname)

    # Render task.toml + instruction.md from .tpl files using seed data.
    n_pages = len(page_names)
    # V4: per-viewport reference PNGs. Group by viewport in the listing so
    # the agent reads "all three desktop refs, then all three tablet refs,
    # then all three phone refs" rather than interleaving.
    _viewport_labels = ("desktop", "tablet", "phone")
    input_list = "\n".join(
        "\n".join(f"- `/app/references/{vp}/{name}.png`" for name in page_names)
        for vp in _viewport_labels
    )
    output_list = "\n".join(
        f"- `/app/output/{name}/index.html`" for name in page_names
    )

    task_id = seed["id"]
    task_name = f"workloads/{task_id}"
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

    # Stamp the templates/ content hash so we can detect stale tasks later.
    # scripts/check_freshness.py compares this against the current hash and
    # flags any task that needs re-applying templates.
    (task_dir / "template_version.txt").write_text(
        compute_template_hash(templates_dir) + "\n", encoding="utf-8"
    )


def write_task(seed: dict, pages: dict[str, str], templates_dir: Path,
               output_root: Path) -> Path:
    task_id = seed["id"]
    task_dir = output_root / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    # Write the LLM-generated reference pages first (so apply_templates can
    # leave them untouched).
    (task_dir / "environment").mkdir()
    ref_root = task_dir / "environment" / "reference-pages"
    ref_root.mkdir()
    for page_name, html in pages.items():
        page_dir = ref_root / page_name
        page_dir.mkdir()
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    # Drop the originating seed alongside the task. relevance.py reads this
    # so the VLM judge gets the full palette/typography/constraints — not
    # just whatever survived into task.toml.
    (task_dir / "seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

    # Copy templates, render .tpl files, stamp template_version.txt.
    apply_templates_to_task(seed, list(pages.keys()), templates_dir, task_dir)

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
    parser.add_argument("--count", type=int, default=10,
                        help="Number of synthetic tasks to generate.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory. Required unless --list-tiers.")
    parser.add_argument("--model", default="claude-opus-4-7",
                        help="Codegen model (Stage 2). Concepts always use sonnet.")
    parser.add_argument("--tier-min", type=int, default=None,
                        help="Minimum tier to include "
                             "(default: lowest static tier in seeds.py)")
    parser.add_argument("--tier-max", type=int, default=None,
                        help="Maximum tier to include "
                             "(default: highest static tier — motion-required "
                             "tiers are excluded unless you set this explicitly)")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Per-page codegen retries on HTML validation failure.")
    parser.add_argument("--templates-dir", type=Path, default=here / "templates")
    parser.add_argument("--seeds-module", type=Path, default=here / "seeds.py",
                        help="Python module providing TIERS and GENRES.")
    parser.add_argument("--concurrency", "-j", type=int, default=8,
                        help="Outer parallel workers (default: 8). Peak in-flight "
                             "calls during codegen = 5 * concurrency because "
                             "each task fans out to 5 per-page calls.")
    parser.add_argument("--synth-seed", type=int, default=None,
                        help="RNG seed for tier/genre selection. Default: random.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan without calling the LLM.")
    parser.add_argument("--list-tiers", action="store_true",
                        help="Print tier definitions from seeds.py and exit.")
    args = parser.parse_args()

    seeds_mod = load_seeds_module(args.seeds_module)

    # Handle --list-tiers and exit.
    if args.list_tiers:
        for tier_num in sorted(seeds_mod.TIERS):
            t = seeds_mod.TIERS[tier_num]
            n_genres = len(seeds_mod.GENRES.get(tier_num, []))
            gated = " [MOTION — not yet generatable]" if seeds_mod.is_motion_tier(tier_num) else ""
            print(f"\nTier {tier_num}: {t['name']}  ({n_genres} genres){gated}")
            print(f"  {t['description']}")
            print(f"  Capabilities:")
            for cap in t["css_capabilities"]:
                print(f"    - {cap}")
            if n_genres:
                print(f"  Genres: {', '.join(seeds_mod.GENRES[tier_num])}")
        return

    if args.output is None:
        sys.exit("ERROR: --output is required (use --list-tiers to inspect tiers).")

    # Default tier range excludes motion-required tiers.
    tier_min_default, tier_max_default = seeds_mod.tier_range()
    tier_min = args.tier_min if args.tier_min is not None else tier_min_default
    tier_max = args.tier_max if args.tier_max is not None else tier_max_default

    # Gate motion tiers. If the requested range hits a motion-required tier,
    # bail with a clear error — the codegen path for motion (clock virtualization,
    # frame grids, motion judge) isn't built yet.
    motion_hits = [
        t for t in range(tier_min, tier_max + 1)
        if t in seeds_mod.TIERS and seeds_mod.is_motion_tier(t)
    ]
    if motion_hits:
        sys.exit(
            f"ERROR: tier(s) {motion_hits} require the motion harness which "
            f"is not yet implemented (clock virtualization, frame-grid capture, "
            f"motion judge). The tier and its genres are defined for forward "
            f"compatibility, but generation is gated. Restrict --tier-max to "
            f"{tier_max_default} (or lower) to proceed."
        )

    if args.count <= 0:
        sys.exit("ERROR: --count must be > 0.")

    if not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")

    rng = random.Random(args.synth_seed)
    pairs = concept_gen.pick_tier_genre_pairs(
        args.count, tier_min, tier_max, rng=rng,
    )
    print(f"\nSynthesizing {len(pairs)} seed(s) via concept_gen:")
    for tier, genre in pairs:
        print(f"  - tier {tier} / {genre}")

    if args.dry_run:
        # In dry-run we don't call the LLM at all.
        return

    # Parallel concept stage. Runs in waves of `--concurrency` so each wave's
    # AVOID block sees survivors from prior waves; within-wave collisions are
    # caught by post-hoc dedup. See concept_gen.generate_seeds_batch.
    synth_client = Anthropic()
    synth_concurrency = max(1, min(args.concurrency, len(pairs)))
    print(f"  synth concurrency: {synth_concurrency} (wave size)")

    seeds = concept_gen.generate_seeds_batch(
        synth_client,
        pairs,
        concurrency=synth_concurrency,
        max_retries=args.max_retries,
    )

    if not seeds:
        sys.exit("All seed synthesis attempts failed.")

    # Sort for stable downstream ordering.
    seeds.sort(key=lambda s: s["id"])

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