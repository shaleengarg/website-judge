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
        # Track <link rel="stylesheet"> hrefs so we can enforce the
        # "at most one stylesheet, must be ../_shared.css" rule.
        self.stylesheet_hrefs: list[str] = []
        self._in_style = False
        self._style_buf: list[str] = []
        self.style_imports: list[str] = []
        # Tier-9: every animated element MUST carry a data-anim="<id>" attr;
        # collected so codegen validation can confirm the page wired the ids
        # the seed asked for.
        self.data_anim_ids: list[str] = []

    def error(self, message: str) -> None:  # type: ignore[override]
        self.ok = False

    def handle_starttag(self, tag, attrs):
        if tag == "html":
            self.has_html_tag = True
        elif tag == "body":
            self.has_body_tag = True
        elif tag == "script":
            self.has_script_tag = True
        elif tag == "style":
            self._in_style = True
            self._style_buf = []
        elif tag == "link":
            attr_dict = dict(attrs)
            rel = (attr_dict.get("rel") or "").lower()
            href = attr_dict.get("href") or ""
            if "stylesheet" in rel.split():
                self.stylesheet_hrefs.append(href)
        for name, value in attrs:
            # xmlns and xmlns:* attribute values are XML namespace identifiers
            # (e.g. "http://www.w3.org/2000/svg"), not network resources. They
            # look like URLs but the browser never fetches them.
            if name == "xmlns" or (name and name.startswith("xmlns:")):
                continue
            if name == "data-anim" and isinstance(value, str) and value:
                self.data_anim_ids.append(value)
            if value and isinstance(value, str) and re.match(r"https?://", value):
                self.external_urls.append(value)

    def handle_endtag(self, tag):
        if tag == "style" and self._in_style:
            self._in_style = False
            css = "".join(self._style_buf)
            self.style_imports.extend(re.findall(r"@import\b[^;]*;", css, re.IGNORECASE))

    def handle_data(self, data):
        if self._in_style:
            self._style_buf.append(data)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_html(
    html: str,
    *,
    expected_anim_ids: list[str] | None = None,
) -> ValidationResult:
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
    # At most one <link rel="stylesheet">, and it must be ../_shared.css.
    if len(p.stylesheet_hrefs) > 1:
        errors.append(
            f"multiple <link rel=\"stylesheet\"> tags ({len(p.stylesheet_hrefs)}); "
            f"benchmark allows at most one shared stylesheet"
        )
    for href in p.stylesheet_hrefs:
        if href != "../_shared.css":
            errors.append(
                f"<link rel=\"stylesheet\"> href={href!r} is not the expected "
                f"\"../_shared.css\""
            )
    if p.style_imports:
        errors.append(
            f"@import in inline <style> not allowed (found {p.style_imports[:2]})"
        )
    if len(html) < 200:
        errors.append(f"suspiciously short HTML ({len(html)} bytes)")

    # Tier-9 motion contract: every expected animation id must appear at least
    # once as a data-anim="<id>" attribute. Missing ids mean the motion harness
    # can't locate the element and the judge has nothing to grade.
    if expected_anim_ids:
        present = set(p.data_anim_ids)
        missing = [aid for aid in expected_anim_ids if aid not in present]
        if missing:
            errors.append(
                f"missing data-anim attributes for expected animations: "
                f"{missing}"
            )

    return ValidationResult(ok=not errors, errors=errors)


def validate_shared_css(
    css: str,
    *,
    require_keyframes: bool = False,
    require_prefers_reduced_motion: bool = False,
) -> ValidationResult:
    """Sanity check the shared stylesheet — at-most-one CSS file means the
    shared CSS itself cannot @import another stylesheet."""
    errors: list[str] = []
    imports = re.findall(r"@import\b[^;]*;", css, re.IGNORECASE)
    if imports:
        errors.append(
            f"@import not allowed in shared CSS (found {imports[:2]})"
        )
    if len(css) < 200:
        errors.append(f"suspiciously short shared CSS ({len(css)} bytes)")
    # External URLs are banned, but the W3C SVG / XLink namespace strings
    # (`http://www.w3.org/2000/svg`, `http://www.w3.org/1999/xlink`) are XML
    # vocabulary identifiers, NOT network resources — Chromium recognizes them
    # as static identifiers and never fetches them. Strip them before checking.
    _XML_NAMESPACE_PREFIXES = (
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/2000/xmlns/",
        "http://www.w3.org/XML/1998/namespace",
    )
    found = re.findall(r"https?://[^\s\"')]+", css)
    real = [u for u in found if not any(u.startswith(p) for p in _XML_NAMESPACE_PREFIXES)]
    if real:
        errors.append(f"external network URLs present in shared CSS: {real[:3]}")

    if require_keyframes and not re.search(r"@keyframes\b", css, re.IGNORECASE):
        errors.append(
            "tier-9 shared CSS must define @keyframes rules but none were found"
        )
    if require_prefers_reduced_motion and not re.search(
        r"prefers-reduced-motion", css, re.IGNORECASE,
    ):
        errors.append(
            "tier-9 shared CSS must include a `prefers-reduced-motion: reduce` "
            "media query to collapse animations to their settled state"
        )

    return ValidationResult(ok=not errors, errors=errors)


# ---------- LLM generation ----------
#
# Codegen is one LLM call PER PAGE. The previous design asked for all 5 pages
# in a single JSON response, which blew the max_tokens budget on dense tier-3
# seeds (dashboards, docs sites). Per-page calls give each page its own
# 16000-token budget and let the pages run in parallel within a single seed.
# Cross-page consistency now relies on the seed constraints + palette/type
# hints being prescriptive — sanity.py catches drift after the fact.


def call_llm_shared_css(client: Anthropic, model: str, seed: dict) -> str:
    """Generate the site's shared stylesheet. One LLM call per seed, run BEFORE
    per-page HTML codegen. Returns raw CSS. May raise ValueError.

    Streaming is mandatory because the shared stylesheet for a dense T7/T8 site
    can easily exceed Anthropic's 10-minute non-streaming response timeout.
    """
    user = prompts.build_shared_css_prompt(seed)
    print(f"  [{seed['id']}/_shared.css] LLM call")
    with client.messages.stream(
        model=model,
        max_tokens=32000,
        system=prompts.SHARED_CSS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        resp = stream.get_final_message()
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    stop_reason = getattr(resp, "stop_reason", None)
    if stop_reason == "max_tokens":
        raise ValueError(
            f"shared CSS truncated at max_tokens ({len(text)} chars produced)."
        )
    text = text.strip()
    # Strip any markdown fences the model snuck in.
    if text.startswith("```"):
        text = re.sub(r"^```(?:css)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    if not text:
        raise ValueError("shared CSS LLM call returned empty output")
    return text


def call_llm_one_page(
    client: Anthropic,
    model: str,
    seed: dict,
    page_name: str,
    shared_css: str = "",
    attempt: int = 1,
    prior_errors: list[str] | None = None,
) -> str:
    """Single LLM call for one page; returns raw HTML. May raise ValueError."""
    user = prompts.build_page_prompt(
        seed, page_name, shared_css=shared_css, prior_errors=prior_errors,
    )

    print(f"  [{seed['id']}/{page_name}] LLM call (attempt {attempt})")
    # Per-page output budget. T7 infographic pages with 30+ SVG primitives
    # plus tier-4 polish blew the original 16k cap (all 5 pages truncated
    # at ~34k chars). 32k tokens (~96k chars) gives enough headroom for
    # the densest T7/T8 pages. Opus 4.6+ supports up to 64k if needed.
    #
    # Streaming is mandatory once max_tokens exceeds what the API can return
    # within its 10-minute non-streaming timeout. Dense T7 pages routinely
    # cross that threshold even at 32k.
    with client.messages.stream(
        model=model,
        max_tokens=32000,
        system=prompts.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        resp = stream.get_final_message()

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
    shared_css: str,
    max_retries: int,
) -> str:
    """Generate + validate one page with retries on validation failure."""
    prior_errors: list[str] = []
    page_anims = (seed.get("expected_animations") or {}).get(page_name) or []
    expected_anim_ids = [a["id"] for a in page_anims] if page_anims else None

    for attempt in range(1, max_retries + 1):
        try:
            html = call_llm_one_page(
                client, model, seed, page_name,
                shared_css=shared_css,
                attempt=attempt,
                prior_errors=prior_errors or None,
            )
        except ValueError as e:
            print(f"  [{seed['id']}/{page_name}] generation error on attempt {attempt}: {e}")
            prior_errors = [str(e)]
            continue

        result = validate_html(html, expected_anim_ids=expected_anim_ids)
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
) -> tuple[str, dict[str, str]]:
    """Generate the site's shared CSS, then all 5 pages in parallel.

    Returns (shared_css, {page_name: html}). The shared CSS is authored once
    (single LLM call) and threaded into every per-page call so pages can
    reference its tokens and classes rather than redefine them inline. This
    cuts per-page output tokens enough that dense T7/T8 pages fit under the
    API streaming threshold.

    Each page has an independent retry loop, so a single flaky page no longer
    forces re-generation of the other four. Shared-CSS generation itself does
    not retry — if it fails, the whole seed fails.

    Note on concurrency: this opens a nested ThreadPoolExecutor with up to 5
    workers inside the outer per-seed pool. With --concurrency 16 outside,
    that's up to 16*5 = 80 in-flight API calls. Drop --concurrency if you
    hit 429s.
    """
    # Stage 1: shared CSS — sequential, before any per-page work. The
    # benchmark allows at most one CSS file per website, so the shared
    # stylesheet itself must be self-contained (no @import, no external URLs).
    is_motion = bool(seed.get("expected_animations"))
    shared_css = call_llm_shared_css(client, model, seed)
    css_check = validate_shared_css(
        shared_css,
        require_keyframes=is_motion,
        require_prefers_reduced_motion=is_motion,
    )
    if not css_check.ok:
        raise RuntimeError(
            f"shared CSS for {seed['id']} failed validation: {css_check.errors}"
        )

    # Stage 2: per-page HTML in parallel, each seeing the shared CSS.
    page_names = list(seed["page_specs"].keys())
    results: dict[str, str] = {}
    first_error: BaseException | None = None

    with ThreadPoolExecutor(max_workers=len(page_names)) as pool:
        futures = {
            pool.submit(
                _generate_one_page_with_retries,
                client, model, seed, name, shared_css, max_retries,
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

    return shared_css, results


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
    for fname in ("Dockerfile", "make.py", "_motion_capture.py"):
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

    # Tier-9 verifier captures ~90 extra screenshots per task (6 frames × 3
    # viewports × 5 pages on the agent side), each preceded by a clock
    # fast-forward. Headroom past the static 1200s budget keeps a slow run
    # from falling off the cliff on the very first concurrent 429 backoff.
    is_motion = bool(seed.get("expected_animations"))
    verifier_timeout = "1800.0" if is_motion else "1200.0"

    task_toml = render_template(
        (templates_dir / "task.toml.tpl").read_text(),
        {
            "TASK_NAME": task_name,
            "TASK_DESCRIPTION": task_description,
            "DIFFICULTY_EXPLANATION": difficulty,
            "GENRE": seed["genre"],
            "TIER": str(seed["tier"]),
            "VERIFIER_TIMEOUT_SEC": verifier_timeout,
        },
    )
    (task_dir / "task.toml").write_text(task_toml)

    motion_section = _build_motion_instruction_section(seed) if is_motion else ""
    instruction = render_template(
        (templates_dir / "instruction.md.tpl").read_text(),
        {
            "N_PAGES": str(n_pages),
            "INPUT_LIST": input_list,
            "OUTPUT_LIST": output_list,
            "MOTION_SECTION": motion_section,
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


def write_task(seed: dict, pages: dict[str, str], shared_css: str,
               templates_dir: Path, output_root: Path) -> Path:
    task_id = seed["id"]
    task_dir = output_root / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    # Write the LLM-generated reference pages first (so apply_templates can
    # leave them untouched). Shared CSS (if any) sits at the ref_root and is
    # linked by every page via <link rel="stylesheet" href="../_shared.css">.
    (task_dir / "environment").mkdir()
    ref_root = task_dir / "environment" / "reference-pages"
    ref_root.mkdir()
    if shared_css:
        (ref_root / "_shared.css").write_text(shared_css, encoding="utf-8")
    for page_name, html in pages.items():
        page_dir = ref_root / page_name
        page_dir.mkdir()
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    # Drop the originating seed alongside the task. relevance.py reads this
    # so the VLM judge gets the full palette/typography/constraints — not
    # just whatever survived into task.toml.
    (task_dir / "seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

    # Tier-9 motion sidecar: write the per-page animation specs into the
    # Docker build context so the in-image make.py and verifier-time score.py
    # can branch on motion vs static without needing the full seed.json. Files
    # outside `environment/` are not visible to the build, so it lives here.
    motion_blob = build_motion_sidecar(seed)
    (task_dir / "environment" / "motion.json").write_text(
        json.dumps(motion_blob, indent=2), encoding="utf-8",
    )

    # Copy templates, render .tpl files, stamp template_version.txt.
    apply_templates_to_task(seed, list(pages.keys()), templates_dir, task_dir)

    return task_dir


def _approximate_duration(ms: int) -> str:
    """Render a duration as approximate prose so the agent doesn't aim for exact ms.

    The grader judges visual fidelity, not exact timing — a 1200ms entrance
    that comes back as 1500ms is fine if the motion reads similarly. Showing
    exact millis in the instruction implies a precision the grader doesn't
    enforce and biases agents toward over-specifying durations.
    """
    if ms < 500:
        return "very fast (under half a second)"
    if ms < 1000:
        return "fast (under a second)"
    if ms < 1800:
        return "around 1-2 seconds"
    if ms < 3000:
        return "around 2-3 seconds"
    if ms < 4500:
        return "around 3-4 seconds"
    return "slow (around 4-5 seconds)"


def _build_motion_instruction_section(seed: dict) -> str:
    """Tier-9 instruction.md insert: explains the motion artifacts and rules."""
    anims = seed.get("expected_animations") or {}
    per_page_lines: list[str] = []
    for page_name in seed.get("pages", []):
        page_anims = anims.get(page_name) or []
        if not page_anims:
            continue
        per_page_lines.append(f"- **{page_name}**:")
        for a in page_anims:
            per_page_lines.append(
                f"  - `data-anim=\"{a['id']}\"` on the {a['target_description']} "
                f"({a['kind']}, {_approximate_duration(int(a['duration_ms']))}) "
                f"— {a['description']}"
            )

    per_page = "\n".join(per_page_lines)
    return f"""
## This is an animated site

In addition to the static screenshots above, each page also has a **motion
frame grid** at `/app/references/<viewport>/<page>.motion.png` — a 2x3
composite of six equidistant frames sampled across the page's animation
window. Your output is graded against these grids by a motion-aware judge.

The static `.png` reference uses `prefers-reduced-motion: reduce` and shows
the **settled final state** (loops paused, entrances complete) — useful as a
layout reference.

### Animation contract

You must implement these animations using **CSS only** (`@keyframes`,
`animation-*`, `transform`, `opacity`, `filter`, `background-position`).
Every animated element must carry a `data-anim="<id>"` attribute matching the
id below.

The grader judges visual fidelity, not exact millisecond timing. Hit the
right *kind* of motion (translate vs fade vs scale vs rotate vs ambient)
on the right element, and approximate the listed pacing — close enough is
good enough.

{per_page}

### Hard rules

- **No JavaScript** of any kind — including for animations. Use CSS keyframes.
- **No interaction triggers**: `:hover`, `:focus`, `:active`, `:checked`, and
  scroll-linked motion are all disallowed. Animations must start on load and
  run autonomously.
- **Every animation must complete one full cycle (loop) or full settle
  (entrance) within about 5 seconds.** The judge samples 6 equidistant frames
  across the page's animation window — a 30-second marquee would leave all
  the entrance motion squashed into the first tile.
- **Include `@media (prefers-reduced-motion: reduce)`** in your shared
  stylesheet to disable every animation and force settled final states — the
  grader uses this to capture the static baseline.
"""


def build_motion_sidecar(seed: dict) -> dict:
    """Build the small motion.json blob baked into each task's Docker image.

    For non-motion seeds returns `{"expected_animations": {}}` so the harness
    can always read the file and just check whether the dict is empty. For
    tier-9 seeds returns the per-page animation specs plus the page-level
    `max_duration_ms` value the capture step uses to size its frame window.
    """
    expected = seed.get("expected_animations") or {}
    if not expected:
        return {"expected_animations": {}, "motion_style": None}

    # Compute per-page frame window. concept_gen.py caps every animation at
    # 5000ms total cycle (loop) or full settle (entrance), so window = the
    # longest declared duration plus a small padding to ensure entrance
    # animations show their settled state in the final frame.
    _WINDOW_MIN_MS = 1500
    _WINDOW_MAX_MS = 5500
    _WINDOW_PAD_MS = 300
    sized: dict[str, dict] = {}
    for page_name, anims in expected.items():
        max_dur = max((int(a.get("duration_ms", 0)) for a in anims), default=0)
        window = max(_WINDOW_MIN_MS, min(_WINDOW_MAX_MS, max_dur + _WINDOW_PAD_MS))
        sized[page_name] = {
            "animations": anims,
            "frame_window_ms": window,
        }
    return {
        "expected_animations": sized,
        "motion_style": seed.get("motion_style"),
    }


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
    example_task = manifest[0]["id"] if manifest else "<task-id>"
    readme.extend([
        "",
        "## Running a task",
        "",
        "The grader's multimodal-LLM judge (70% of the reward) requires",
        "`ANTHROPIC_API_KEY` inside the verifier container. Pass it through",
        "with `--ve` (or `--env-file`). Without it, every trial returns 0.0",
        "because `tests/test.sh` writes a zero on any verifier crash.",
        "",
        "```bash",
        f"harbor check ./{example_task}",
        f"harbor run -p ./{example_task} -a oracle --env modal \\",
        "  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY",
        f"harbor run -p ./{example_task} -a claude-code \\",
        "  -m anthropic/claude-opus-4-7 --env modal \\",
        "  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY",
        "```",
        "",
        "## Running all tasks",
        "",
        "There's no built-in dataset wrapping yet; iterate with a shell loop",
        "or pass the whole dataset directory:",
        "",
        "```bash",
        "harbor run -p . -a oracle --env modal -n 10 \\",
        "  --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY",
        "",
        "# or per-task:",
        "for d in synth-*/; do",
        '  harbor run -p "$d" -a oracle --env modal \\',
        '    --ve ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY',
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

    # Default tier range excludes motion-required tiers (opt-in via --tier-max).
    tier_min_default, tier_max_default = seeds_mod.tier_range()
    tier_min = args.tier_min if args.tier_min is not None else tier_min_default
    tier_max = args.tier_max if args.tier_max is not None else tier_max_default

    motion_hits = [
        t for t in range(tier_min, tier_max + 1)
        if t in seeds_mod.TIERS and seeds_mod.is_motion_tier(t)
    ]
    if motion_hits:
        print(
            f"  Note: tier(s) {motion_hits} use the motion-capture branch "
            f"(frame-grid PNGs + motion judge). Each tier-9 task takes ~6× "
            f"longer to verify than a static task."
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
            shared_css, pages = generate_pages_for_seed(
                client, args.model, seed, max_retries=args.max_retries,
            )
            task_dir = write_task(
                seed, pages, shared_css, args.templates_dir, args.output,
            )
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