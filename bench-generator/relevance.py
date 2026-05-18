#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic>=0.40,<1.0",
#     "playwright>=1.40",
#     "Pillow>=10",
# ]
# ///
"""
Relevance check: ask Claude Sonnet (with vision) whether each generated page
actually matches the seed it was generated from.

This is the LLM-judge counterpart to sanity.py. sanity.py catches "is the page
broken?"; relevance.py catches "does the page show what the seed asked for?".

It needs:
  - The rendered screenshot of each page (re-rendered locally with Playwright
    if not provided, to keep this self-contained).
  - The seed JSON used to generate the task. By default this is read from
    `seed.json` next to the task; --seed-from-toml falls back to a synthesized
    minimal seed when the original is unavailable (old tasks).

Usage:
    python relevance.py <task_dir> [--seed-json path/to/seed.json]

Exit code: 0 if every page is "relevant", 1 otherwise.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("ERROR: pip install anthropic")


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.0  # judge should be steady, not creative

# Single-viewport gate at V4's desktop default. relevance.py just asks the LLM
# "does this page match its seed spec?" — that judgment doesn't need three
# viewports, and rendering once keeps the gate cheap.
VIEWPORT = {"width": 1440, "height": 900}

# Pass thresholds. A page passes if EVERY rubric score is >= MIN_SCORE
# AND overall_coherence is >= MIN_COHERENCE.
MIN_SCORE = 3
MIN_COHERENCE = 4


_SYSTEM_PROMPT = """\
You are a strict design reviewer. You will be shown a screenshot of one page \
of a generated benchmark website plus the spec used to generate it. Your job \
is to rate how well the screenshot matches the spec on 5 dimensions, each on \
a 1-5 Likert scale.

You output ONLY a JSON object with this exact shape:
{
  "matches_page_spec":   <int 1-5>,
  "matches_palette":     <int 1-5>,
  "matches_typography":  <int 1-5>,
  "respects_constraints":<int 1-5>,
  "overall_coherence":   <int 1-5>,
  "notes": "<one short sentence noting anything broken or unexpected>"
}

Scale: 1 = total mismatch / broken; 3 = recognizable but with issues; 5 = clean match.
Be honest. If the page looks broken, missing content, or styled completely \
differently than the spec, give low scores. Output JSON only — no markdown, \
no preamble.
"""


def _build_user_prompt(seed: dict, page_name: str) -> str:
    page_spec = seed.get("page_specs", {}).get(page_name, "(no per-page spec)")
    constraints = "\n".join(f"  - {c}" for c in seed.get("constraints", []))
    return f"""\
## Site spec

- Tier: {seed.get('tier')}
- Genre: {seed.get('genre')}
- Description: {seed.get('description')}
- Palette: {seed.get('palette_hint')}
- Typography: {seed.get('type_style')}
- Hard constraints:
{constraints}

## This page

- Name: **{page_name}**
- Spec: {page_spec}

Now rate the attached screenshot against this spec.
"""


# ---------- Seed loading ----------

def _try_load_sidecar_seed(task_dir: Path) -> dict | None:
    """Look for a seed.json sidecar saved alongside the task. Returns None if absent."""
    candidates = [
        task_dir / "seed.json",
        task_dir / ".seed.json",
        task_dir / "environment" / "seed.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def _seed_from_task_toml(task_dir: Path) -> dict:
    """Reconstruct a minimal seed from task.toml + page directory listing.

    Used as a fallback when no seed.json sidecar exists. Only fills in the
    fields the judge prompt uses; palette/typography/constraints will be empty,
    which means those rubric scores become softer (the model can't verify
    something it isn't told).
    """
    toml = (task_dir / "task.toml").read_text(encoding="utf-8")

    def _pick(key: str) -> str:
        m = re.search(rf'^{key}\s*=\s*"(.*)"\s*$', toml, re.MULTILINE)
        return m.group(1) if m else ""

    def _pick_int(key: str) -> int:
        m = re.search(rf'^{key}\s*=\s*"?(\d+)"?\s*$', toml, re.MULTILINE)
        return int(m.group(1)) if m else 0

    ref_root = task_dir / "environment" / "reference-pages"
    pages = sorted(p.name for p in ref_root.iterdir()
                   if p.is_dir() and (p / "index.html").exists())

    return {
        "id": task_dir.name,
        "tier": _pick_int("tier"),
        "genre": _pick("genre"),
        "description": _pick("description"),
        "palette_hint": "",
        "type_style": "",
        "constraints": [],
        "pages": pages,
        "page_specs": {p: "(spec unavailable; judge with general expectations)" for p in pages},
    }


def load_seed(task_dir: Path, override: Path | None = None) -> dict:
    if override is not None:
        return json.loads(override.read_text(encoding="utf-8"))
    sidecar = _try_load_sidecar_seed(task_dir)
    if sidecar is not None:
        return sidecar
    return _seed_from_task_toml(task_dir)


# ---------- Rendering ----------

def _render_page(browser, html_path: Path, out_png: Path) -> None:
    ctx = browser.new_context(viewport=VIEWPORT)
    page = ctx.new_page()
    page.goto(f"file://{html_path.resolve()}", wait_until="load", timeout=15_000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(out_png), full_page=True)
    ctx.close()


def _ensure_screenshots(task_dir: Path, shots_dir: Path) -> dict[str, Path]:
    """Render each page once and return {page_name: png_path}."""
    ref_root = task_dir / "environment" / "reference-pages"
    pages = sorted(p.name for p in ref_root.iterdir()
                   if p.is_dir() and (p / "index.html").exists())
    shots_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for name in pages:
                shot = shots_dir / f"{name}.png"
                _render_page(browser, ref_root / name / "index.html", shot)
                out[name] = shot
        finally:
            browser.close()
    return out


# ---------- Judge call ----------

@dataclass
class PageScore:
    page: str
    matches_page_spec: int = 0
    matches_palette: int = 0
    matches_typography: int = 0
    respects_constraints: int = 0
    overall_coherence: int = 0
    notes: str = ""
    error: str | None = None

    def passes(self) -> bool:
        if self.error:
            return False
        rubric = [
            self.matches_page_spec, self.matches_palette,
            self.matches_typography, self.respects_constraints,
        ]
        return all(s >= MIN_SCORE for s in rubric) and self.overall_coherence >= MIN_COHERENCE


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _judge_page(client: Anthropic, seed: dict, page_name: str, png: Path) -> PageScore:
    score = PageScore(page=page_name)
    image_b64 = base64.standard_b64encode(png.read_bytes()).decode("ascii")
    user_prompt = _build_user_prompt(seed, page_name)

    try:
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64,
                    }},
                    {"type": "text", "text": user_prompt},
                ],
            }],
        )
    except Exception as e:
        score.error = f"API error: {type(e).__name__}: {e}"
        return score

    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    text = _strip_fences(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        score.error = f"non-JSON response ({e}): {text[:200]!r}"
        return score

    for k in ("matches_page_spec", "matches_palette", "matches_typography",
              "respects_constraints", "overall_coherence"):
        v = data.get(k)
        if not isinstance(v, int) or not (1 <= v <= 5):
            score.error = f"missing or invalid {k}: {v!r}"
            return score
        setattr(score, k, v)
    score.notes = str(data.get("notes", ""))[:280]
    return score


# ---------- Public API ----------

@dataclass
class RelevanceResult:
    task_dir: Path
    scores: list[PageScore] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.scores) and all(s.passes() for s in self.scores)


def check_task(
    task_dir: Path,
    *,
    seed_override: Path | None = None,
    screenshots_dir: Path | None = None,
    client: Anthropic | None = None,
) -> RelevanceResult:
    seed = load_seed(task_dir, override=seed_override)
    shots_dir = screenshots_dir or (task_dir / ".relevance-shots")
    shots = _ensure_screenshots(task_dir, shots_dir)

    client = client or Anthropic()
    result = RelevanceResult(task_dir=task_dir)
    for page, png in shots.items():
        result.scores.append(_judge_page(client, seed, page, png))
    return result


# ---------- Reporting ----------

def _print_result(result: RelevanceResult) -> None:
    name = result.task_dir.name
    bad = [s for s in result.scores if not s.passes()]
    if not bad:
        avg = sum(s.overall_coherence for s in result.scores) / max(len(result.scores), 1)
        print(f"  PASS  {name}  (avg coherence={avg:.2f})")
        return
    print(f"  FAIL  {name}  ({len(bad)}/{len(result.scores)} pages below threshold)")
    for s in result.scores:
        marker = "x" if not s.passes() else "."
        if s.error:
            print(f"    [{marker}] {s.page}: ERROR {s.error}")
        else:
            print(f"    [{marker}] {s.page}: spec={s.matches_page_spec} "
                  f"pal={s.matches_palette} type={s.matches_typography} "
                  f"con={s.respects_constraints} coh={s.overall_coherence} "
                  f"— {s.notes}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dirs", type=Path, nargs="+")
    parser.add_argument("--seed-json", type=Path, default=None,
                        help="Override seed JSON path. If a single task is given, "
                             "this file is used for it directly. If multiple, "
                             "the same file is reused (unusual).")
    parser.add_argument("--json", action="store_true",
                        help="Print a machine-readable JSON summary at the end.")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")

    client = Anthropic()
    results: list[RelevanceResult] = []
    for task_dir in args.task_dirs:
        if not task_dir.is_dir() or not (task_dir / "task.toml").exists():
            print(f"  SKIP  {task_dir} (not a task dir)", file=sys.stderr)
            continue
        result = check_task(task_dir, seed_override=args.seed_json, client=client)
        results.append(result)
        _print_result(result)

    n_pass = sum(1 for r in results if r.ok)
    n_fail = len(results) - n_pass
    print(f"\nrelevance: {n_pass}/{len(results)} tasks passed, {n_fail} failed")

    if args.json:
        summary = {
            "total": len(results),
            "passed": n_pass,
            "failed": n_fail,
            "tasks": [
                {
                    "task": r.task_dir.name,
                    "ok": r.ok,
                    "pages": [
                        {
                            "page": s.page,
                            "matches_page_spec": s.matches_page_spec,
                            "matches_palette": s.matches_palette,
                            "matches_typography": s.matches_typography,
                            "respects_constraints": s.respects_constraints,
                            "overall_coherence": s.overall_coherence,
                            "notes": s.notes,
                            "error": s.error,
                            "passes": s.passes(),
                        }
                        for s in r.scores
                    ],
                }
                for r in results
            ],
        }
        print(json.dumps(summary, indent=2))

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
