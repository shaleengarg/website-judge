#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic>=0.40,<1.0",
# ]
# ///
"""
Stage-1 of website-bench: LLM-driven seed (concept) generation.

Given a (tier, genre) pair, this calls Claude Sonnet to produce a Seed dict
matching the schema in seeds.py. The result is then handed to the existing
Stage-2 codegen in generate_dataset.py (LLM-driven HTML/CSS production).

Usage (standalone, for debugging):
    export ANTHROPIC_API_KEY=...
    python concept_gen.py --tier 1 --genre portfolio
    python concept_gen.py --tier 3 --genre dashboard

The standalone CLI prints the generated seed JSON to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import string
import sys
import uuid
from typing import Any

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("ERROR: pip install anthropic")

import seeds as seeds_mod

# Sonnet is the right tier for concept JSON: cheaper than Opus, plenty smart
# enough to produce structured spec text. Opus is reserved for codegen.
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096
_TEMPERATURE = 0.95
_MAX_RETRIES = 3


_SYSTEM_PROMPT = """\
You are a senior web designer producing concept specs for a static-website
benchmark. Your only job is to output a JSON object describing a fictional
5-page website. The JSON will be fed to a code-generation model that produces
the actual HTML/CSS.

Output rules:
- Output ONLY valid JSON. No markdown fences, no commentary, no preamble.
- All text must be specific and concrete. NEVER use "Lorem ipsum" or generic
  filler like "Welcome to our website".
- Brand names, palettes, and page content must be distinctive. Surprise me.
- The spec must be implementable using HTML + inline <style> CSS only — no JS,
  no external fonts, no remote images. The codegen model is bound by those
  rules; do not ask it for things it cannot do.
"""


def _example_seeds(tier: int, n: int = 2) -> list[dict[str, Any]]:
    """Pick up to n hand-written seeds at this tier to use as few-shot examples."""
    same_tier = [s for s in seeds_mod.SEEDS if s["tier"] == tier]
    return same_tier[:n]


def _build_user_prompt(tier: int, genre: str) -> str:
    tier_spec = seeds_mod.TIERS[tier]
    caps = "\n".join(f"  - {c}" for c in tier_spec["css_capabilities"])
    examples = _example_seeds(tier, n=2)
    examples_block = "\n\n".join(
        f"Example {i + 1} (tier {ex['tier']}, {ex['genre']}):\n"
        + json.dumps(ex, indent=2)
        for i, ex in enumerate(examples)
    )

    return f"""\
Produce a seed JSON for a tier-{tier} website in the **{genre}** genre.

## Tier {tier} — {tier_spec['name']}

{tier_spec['description']}

CSS capabilities expected at this tier:
{caps}

## Required JSON schema (exact keys, exact types)

```
{{
  "id": "<kebab-case, 3-5 words, e.g. 'verdant-ridge-coffee'>",
  "tier": {tier},
  "genre": "{genre}",
  "pages": ["<page-name>", ...],          // exactly 5 short page names, kebab-case
  "palette_hint": "<one sentence: background + text + 1-2 accent colors with hex>",
  "type_style": "<one sentence: heading/body fonts (system only), weight, feel>",
  "description": "<one sentence describing the site>",
  "constraints": ["<concrete layout/visual constraint>", ...],   // 3-5 items
  "page_specs": {{"<page-name>": "<2-3 sentence description of that page>", ...}}
}}
```

The keys of `page_specs` MUST exactly match the entries of `pages` (same order,
same names). Pick page names that fit the genre — they do NOT have to be
"home/about/contact"; a restaurant might be "menu/reservations/hours/about/find-us".

## Constraints on your output

- Match the tier's complexity envelope. Don't smuggle tier-4 features (gradients,
  shadows, decorative pseudo-elements) into a tier-1 spec.
- Palette and typography must be coherent with the genre.
- Constraints should be specific enough that two different developers reading
  them would build visually similar sites.
- Brand name in `id` should be evocative, not generic ("TechCorp" → bad,
  "Salt & Silver Bistro" → good).

## Reference examples at this tier

These show the level of detail expected. Do NOT copy them — diverge in brand,
palette, layout, page names.

{examples_block}

Now produce the JSON for your tier-{tier} {genre} site.
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _generate_id(tier: int, genre: str) -> str:
    """Synth seed ID: synth-t{tier}-{genre}-{hash4}. Filesystem-safe."""
    suffix = uuid.uuid4().hex[:4]
    return f"synth-t{tier}-{genre}-{suffix}"


def _validate_seed_shape(data: Any, tier: int, genre: str) -> list[str]:
    """Schema-level validation. Returns list of error strings; empty = ok."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"top-level is {type(data).__name__}, expected dict"]

    required = {"id", "tier", "genre", "pages", "palette_hint",
                "type_style", "description", "constraints", "page_specs"}
    missing = required - set(data.keys())
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")

    if data.get("tier") != tier:
        errors.append(f"tier mismatch: got {data.get('tier')!r}, expected {tier}")
    if data.get("genre") != genre:
        errors.append(f"genre mismatch: got {data.get('genre')!r}, expected {genre!r}")

    pages = data.get("pages")
    if not isinstance(pages, list) or len(pages) != 5:
        errors.append(f"pages must be a list of 5 names; got {pages!r}")
    elif not all(isinstance(p, str) and p for p in pages):
        errors.append("pages must all be non-empty strings")

    page_specs = data.get("page_specs")
    if not isinstance(page_specs, dict):
        errors.append(f"page_specs must be a dict; got {type(page_specs).__name__}")
    elif isinstance(pages, list) and list(page_specs.keys()) != pages:
        errors.append(
            f"page_specs keys {list(page_specs.keys())!r} do not match "
            f"pages {pages!r} (order and names must match exactly)"
        )

    constraints = data.get("constraints")
    if not isinstance(constraints, list) or len(constraints) < 3:
        errors.append(f"constraints must be a list of >=3 items; got {constraints!r}")

    for k in ("palette_hint", "type_style", "description"):
        if not isinstance(data.get(k), str) or not data.get(k):
            errors.append(f"{k} must be a non-empty string")

    return errors


def _safe_id(raw_id: str, tier: int, genre: str) -> str:
    """Sanitize the LLM-suggested id to a filesystem-safe form, prefixed for traceability."""
    allowed = set(string.ascii_lowercase + string.digits + "-")
    cleaned = "".join(c if c in allowed else "-" for c in raw_id.lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = _generate_id(tier, genre)
    # Always prefix with synth-t{tier}- so synthetic seeds are distinguishable
    # from hand-written ones, even if the model picked a perfectly good id.
    prefix = f"synth-t{tier}-"
    if not cleaned.startswith(prefix):
        cleaned = prefix + cleaned
    suffix = uuid.uuid4().hex[:4]
    return f"{cleaned}-{suffix}"


def generate_seed(
    client: Anthropic,
    tier: int,
    genre: str,
    *,
    model: str = _MODEL,
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """Generate a Seed dict for (tier, genre). Raises RuntimeError on giving up."""
    if tier not in seeds_mod.TIERS:
        raise ValueError(f"unknown tier {tier!r}; known: {sorted(seeds_mod.TIERS)}")
    if genre not in seeds_mod.GENRES.get(tier, []):
        # Don't hard-fail — the LLM can still try — but warn loudly.
        print(
            f"  [concept_gen] WARNING: genre {genre!r} not in GENRES[{tier}] "
            f"(known: {seeds_mod.GENRES.get(tier, [])})",
            file=sys.stderr,
        )

    system = _SYSTEM_PROMPT
    base_user = _build_user_prompt(tier, genre)
    prior_errors: list[str] = []

    for attempt in range(1, max_retries + 1):
        user = base_user
        if prior_errors:
            user += (
                "\n\n## Previous attempt failed validation\n"
                + "\n".join(f"  - {e}" for e in prior_errors)
                + "\n\nFix every issue above and regenerate the full JSON."
            )

        print(f"  [concept_gen] tier={tier} genre={genre} attempt {attempt}")
        resp = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        text = _strip_fences(text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            prior_errors = [f"output was not valid JSON: {e}"]
            continue

        # Always overwrite the id with our prefixed/uniquified form, even if
        # the model produced something fine. This guarantees no collision with
        # hand-written seeds and makes synthetic seeds traceable.
        raw_id = data.get("id", "")
        data["id"] = _safe_id(raw_id if isinstance(raw_id, str) else "", tier, genre)

        errs = _validate_seed_shape(data, tier, genre)
        if errs:
            print(f"  [concept_gen] validation failed on attempt {attempt}:")
            for e in errs:
                print(f"    - {e}")
            prior_errors = errs
            continue

        return data

    raise RuntimeError(
        f"giving up on tier={tier} genre={genre} after {max_retries} attempts: "
        f"last errors: {prior_errors}"
    )


def pick_tier_genre_pairs(
    n: int,
    tier_min: int,
    tier_max: int,
    *,
    rng: random.Random | None = None,
) -> list[tuple[int, str]]:
    """Pick N (tier, genre) pairs with even genre distribution per tier.

    Tiers are cycled in order across picks. Within each tier, genres are
    drawn from a shuffled per-tier "deck" that is reshuffled whenever
    exhausted — so for K picks at a given tier you get floor(K/G) complete
    cycles of all G genres plus a final partial cycle. No genre repeats
    until every other genre at that tier has been used at least the same
    number of times.

    Determinism: with a fixed `rng` (i.e. `--synth-seed`), the pair sequence
    is reproducible across runs.
    """
    rng = rng or random.Random()
    tiers = [t for t in sorted(seeds_mod.TIERS) if tier_min <= t <= tier_max]
    if not tiers:
        raise ValueError(f"no tiers in range [{tier_min}, {tier_max}]")

    decks: dict[int, list[str]] = {t: [] for t in tiers}

    def draw_genre(tier: int) -> str:
        if not decks[tier]:
            genres = list(seeds_mod.GENRES.get(tier, []))
            if not genres:
                raise ValueError(f"no genres defined for tier {tier}")
            rng.shuffle(genres)
            decks[tier] = genres
        return decks[tier].pop()

    pairs: list[tuple[int, str]] = []
    for i in range(n):
        tier = tiers[i % len(tiers)]
        pairs.append((tier, draw_genre(tier)))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a single seed JSON for debugging.")
    parser.add_argument("--tier", type=int, required=True)
    parser.add_argument("--genre", required=True)
    parser.add_argument("--model", default=_MODEL)
    parser.add_argument("--max-retries", type=int, default=_MAX_RETRIES)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")

    client = Anthropic()
    seed = generate_seed(
        client, args.tier, args.genre,
        model=args.model, max_retries=args.max_retries,
    )
    print(json.dumps(seed, indent=2))


if __name__ == "__main__":
    main()
