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
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
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

# Dedup thresholds. A candidate is rejected as a duplicate if EITHER:
#   - its brand slug has SequenceMatcher.ratio() > _NAME_DUP_THRESHOLD vs. some
#     existing seed's brand slug
#   - >=2 of its palette_hint hex colors each find a close match (RGB distance
#     < _COLOR_DUP_THRESHOLD) in some existing seed's palette
# These are tuned to catch the families we saw in the v2 batches (Ironclad/
# Ironveil at tier 3 ecommerce, three "Summit" conferences at tier 2). Lower
# = stricter = more rejections and need for over-sampling.
_NAME_DUP_THRESHOLD = 0.7
_COLOR_DUP_THRESHOLD = 0.15
# Cap the AVOID block at this many seeds so the prompt stays bounded even on
# very large datasets. Sonnet repeats within-session patterns more than across
# sessions, so the most-recent priors are the ones worth showing.
_MAX_AVOID_ENTRIES = 60


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
- The spec must be implementable using HTML + CSS only — no JavaScript, no
  external fonts, no remote images. This holds for ALL tiers, including
  tier 9 (animations are driven by CSS `@keyframes` and `animation-*`
  properties, never by JS). The codegen model is bound by those rules; do
  not ask it for things it cannot do.
"""


# ---------- Dedup: brand slug + palette similarity ----------

def _extract_brand_slug(seed: dict[str, Any]) -> str:
    """Pull the brand portion out of a synth seed id.

    Synth IDs have the form `synth-t{tier}-{slug}-{hash4}`. The slug is the
    brand name kebab-cased; the hash4 is 4 hex chars appended by `_safe_id`.
    Returns the slug, lowercased, with no prefix or suffix.
    """
    raw = (seed.get("id") or "").lower()
    raw = re.sub(r"^synth-t\d+-", "", raw)
    raw = re.sub(r"-[0-9a-f]{4}$", "", raw)
    return raw


_HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _extract_hex_colors(text: str) -> list[str]:
    """Find #RRGGBB or #RGB tokens in free-form text. Returns 6-char lowercase."""
    if not isinstance(text, str):
        return []
    out: list[str] = []
    for m in _HEX_RE.finditer(text):
        h = m.group(1).lower()
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        out.append(h)
    return out


def _rgb(hex_code: str) -> tuple[int, int, int]:
    return int(hex_code[0:2], 16), int(hex_code[2:4], 16), int(hex_code[4:6], 16)


def _color_distance(hex_a: str, hex_b: str) -> float:
    """Normalized 0-1 RGB distance between two 6-char hex codes."""
    r1, g1, b1 = _rgb(hex_a)
    r2, g2, b2 = _rgb(hex_b)
    max_dist = (3 * 255 ** 2) ** 0.5  # ~441.673
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5 / max_dist


# Saturation threshold below which a color counts as "neutral" — a white, gray,
# black, or near-grayscale color. These are shared infrastructure across many
# palettes (cream/paper/parchment all look like off-white; charcoal/ink/midnight
# all look near-black) and are not what makes palettes distinct. Compare only
# the saturated colors when checking palette duplication.
_NEUTRAL_CHROMA_THRESHOLD = 30  # max(R,G,B) - min(R,G,B) in 0-255 space


def _is_neutral(hex_code: str) -> bool:
    """True when the color is near-grayscale (white / gray / black family)."""
    r, g, b = _rgb(hex_code)
    return (max(r, g, b) - min(r, g, b)) < _NEUTRAL_CHROMA_THRESHOLD


def _saturated_colors(text: str) -> list[str]:
    """Hex colors in `text` minus the neutrals — the palette's identity colors."""
    return [c for c in _extract_hex_colors(text) if not _is_neutral(c)]


def is_duplicate(
    candidate: dict[str, Any],
    existing: list[dict[str, Any]],
    *,
    name_threshold: float = _NAME_DUP_THRESHOLD,
    color_threshold: float = _COLOR_DUP_THRESHOLD,
) -> tuple[bool, str | None]:
    """Return (is_dup, reason) for a candidate seed against accepted seeds.

    Two rejection rules, either triggers (whichever fires first):
      1. **Brand slug**: SequenceMatcher.ratio() on lowercase slugs exceeds
         `name_threshold`. Catches "Ironclad Summit" vs "Ironclad Futures
         Summit" — they share substring structure.
      2. **Palette overlap on saturated colors**: candidate has >=2 *saturated*
         hex colors (neutrals excluded — see _is_neutral) that each find a
         close match (RGB distance < `color_threshold`) in some prior seed's
         saturated palette. Comparing only the identity-bearing colors avoids
         flagging "cream + black" vs "parchment + ink" as a duplicate just
         because both share near-white and near-black infrastructure.

    `reason` is human-readable when `is_dup` is True; None otherwise.
    """
    cand_slug = _extract_brand_slug(candidate)
    cand_colors = _saturated_colors(candidate.get("palette_hint", ""))

    for prev in existing:
        prev_slug = _extract_brand_slug(prev)
        if cand_slug and prev_slug:
            ratio = SequenceMatcher(None, cand_slug, prev_slug).ratio()
            if ratio > name_threshold:
                return True, (
                    f"brand slug {cand_slug!r} too similar to {prev['id']!r} "
                    f"(ratio={ratio:.2f}, threshold={name_threshold:.2f})"
                )

        prev_colors = _saturated_colors(prev.get("palette_hint", ""))
        if len(cand_colors) >= 2 and len(prev_colors) >= 2:
            matches = sum(
                1 for cc in cand_colors
                if any(_color_distance(cc, pc) < color_threshold for pc in prev_colors)
            )
            if matches >= 2:
                return True, (
                    f"saturated palette overlaps {prev['id']!r} "
                    f"({matches} colors within RGB distance {color_threshold:.2f})"
                )

    return False, None


def _format_avoid_block(existing: list[dict[str, Any]]) -> str:
    """Format an 'AVOID these' section for the user prompt.

    Capped at _MAX_AVOID_ENTRIES most-recent entries — Sonnet repeats
    within-session patterns more than across sessions, so recency is the right
    selection. Empty string if no priors.
    """
    if not existing:
        return ""
    recent = existing[-_MAX_AVOID_ENTRIES:]
    lines = []
    for s in recent:
        slug = _extract_brand_slug(s)
        colors = _extract_hex_colors(s.get("palette_hint", ""))
        color_str = f" — palette: {', '.join('#' + c for c in colors[:3])}" if colors else ""
        lines.append(f"  - {slug}{color_str}")
    n_total = len(existing)
    omitted_note = (
        f" (showing the {len(recent)} most recent of {n_total})"
        if n_total > len(recent) else ""
    )
    return (
        "\n\n## AVOID Duplicating These Existing Concepts\n"
        f"The following brand slugs and palettes have already been used in this "
        f"dataset{omitted_note}. Your seed MUST differ in BOTH:\n"
        "  - **Brand**: pick a name whose kebab-case slug is not similar in "
        "spelling, sound, theme, or shared substrings to any below.\n"
        "  - **Palette**: pick hex codes that sit visibly far from every "
        "palette below in RGB space — no near-duplicates.\n"
        "\n" + "\n".join(lines)
    )


# ---------- Prompt builders ----------

def _build_user_prompt(
    tier: int,
    genre: str,
    *,
    existing: list[dict[str, Any]] | None = None,
) -> str:
    tier_spec = seeds_mod.TIERS[tier]
    caps = "\n".join(f"  - {c}" for c in tier_spec["css_capabilities"])
    is_motion = bool(tier_spec.get("requires_motion", False))

    # Tier-9 seeds carry two extra top-level keys (`motion_style`,
    # `expected_animations`) that drive the motion-capture harness. Splice the
    # extra schema fragment and constraints into the base prompt rather than
    # forking the template.
    motion_schema_fragment = ""
    motion_constraints_fragment = ""
    if is_motion:
        motion_schema_fragment = (
            ',\n'
            '  "motion_style": "<one of: subtle | playful | dramatic>",\n'
            '  "expected_animations": {\n'
            '    "<page-name>": [\n'
            '      {\n'
            '        "id": "<kebab-case animation id, unique within the page>",\n'
            '        "target_description": "<the element it animates, e.g. \'main headline\' or \'cta button\'>",\n'
            '        "kind": "<entrance | loop>",\n'
            '        "duration_ms": <int, 200..15000>,\n'
            '        "description": "<one sentence: what moves and how>"\n'
            '      }\n'
            '    ]\n'
            '  }'
        )
        motion_constraints_fragment = """

## Tier-9 motion constraints (binding)

- `motion_style` controls the overall feel: subtle = small fades and slow
  drifts; playful = springy translates, slight rotation; dramatic = larger
  transforms, longer staggers, bigger opacity swings.
- `expected_animations` MUST be keyed by EVERY page name in `pages`. Each
  page MUST list 1-3 animations.
- Each page MUST include at least one `entrance` (on-load reveal that settles)
  AND at least one `loop` (continuous motion). A single-animation page is
  insufficient — entrance gives you a settled final frame, loop gives the
  motion harness something to sample across time.
- `duration_ms` is the animation's natural cycle (loop) or settle time
  (entrance). **Hard cap: 200ms-5000ms.** Every animation — including slow
  ambient loops like marquees or background drifts — MUST complete one full
  cycle or full settle within 5000ms. The frame-grid capture samples 6
  EQUIDISTANT frames across max(durations) + padding, so a 28s marquee would
  leave all entrance motion squashed into the first tile. Speed loops up
  (e.g. a marquee at 4s, an orb drift at 3s) and they remain visually slow
  to the human eye while becoming legible across the grid.
- All motion must be driven by CSS only: `@keyframes`, `animation-*`
  properties, `transform`, `opacity`, `filter`, `background-position`. NO
  JavaScript, NO `:hover` / `:focus` / `:active` / `:checked` triggers, NO
  scroll-linked motion.
- Every animated element must carry a `data-anim="<id>"` attribute where
  `<id>` matches the animation id you list here. The codegen LLM reads this
  spec, so the ids you choose become contracts.
- Include `@media (prefers-reduced-motion: reduce)` rules that collapse every
  animation to its settled final state — the harness uses this to capture a
  static baseline alongside the motion grid."""

    prompt = f"""\
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
  "page_specs": {{"<page-name>": "<2-3 sentence description of that page>", ...}}{motion_schema_fragment}
}}
```

The keys of `page_specs` MUST exactly match the entries of `pages` (same order,
same names). Pick page names that fit the genre — they do NOT have to be
"home/about/contact"; a restaurant might be "menu/reservations/hours/about/find-us".{motion_constraints_fragment}

## Constraints on your output

- Match the tier's complexity envelope. Use the CSS capabilities listed above
  as your ceiling; do not smuggle in features from higher tiers (e.g. don't
  add gradients or shadows to a tier-1 spec).
- Palette and typography must be coherent with the genre.
- Constraints should be specific enough that two different developers reading
  them would build visually similar sites. Include concrete numbers
  (max-widths, padding values, color hex codes) where it matters.
- Brand name in `id` should be evocative, not generic ("TechCorp" → bad,
  "Salt & Silver Bistro" → good). The brand should feel like it could exist.
- Never use Lorem ipsum or generic placeholder text. Every constraint and
  page_spec should reference real, specific content.

Now produce the JSON for your tier-{tier} {genre} site.
"""

    prompt += _format_avoid_block(existing or [])
    return prompt


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


_MOTION_STYLES = {"subtle", "playful", "dramatic"}
_ANIMATION_KINDS = {"entrance", "loop"}


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

    if seeds_mod.is_motion_tier(tier):
        errors.extend(_validate_motion_fields(data, pages if isinstance(pages, list) else []))

    return errors


def _validate_motion_fields(data: dict[str, Any], pages: list[str]) -> list[str]:
    """Validate the tier-9-only motion_style + expected_animations fields."""
    errors: list[str] = []

    style = data.get("motion_style")
    if style not in _MOTION_STYLES:
        errors.append(
            f"motion_style must be one of {sorted(_MOTION_STYLES)}; got {style!r}"
        )

    anims = data.get("expected_animations")
    if not isinstance(anims, dict):
        errors.append(
            f"expected_animations must be a dict keyed by page name; got "
            f"{type(anims).__name__}"
        )
        return errors

    if pages and set(anims.keys()) != set(pages):
        errors.append(
            f"expected_animations keys {sorted(anims.keys())!r} must match "
            f"pages {pages!r} exactly"
        )

    seen_ids_per_page: dict[str, set[str]] = {}
    for page, page_anims in anims.items():
        if not isinstance(page_anims, list) or not (1 <= len(page_anims) <= 3):
            errors.append(
                f"expected_animations[{page!r}] must be a list of 1-3 items; "
                f"got {page_anims!r}"
            )
            continue

        kinds_present: set[str] = set()
        seen_ids: set[str] = set()
        for i, anim in enumerate(page_anims):
            label = f"expected_animations[{page!r}][{i}]"
            if not isinstance(anim, dict):
                errors.append(f"{label} must be a dict; got {type(anim).__name__}")
                continue
            for k in ("id", "target_description", "kind", "duration_ms", "description"):
                if k not in anim:
                    errors.append(f"{label} missing key {k!r}")
            anim_id = anim.get("id")
            if not isinstance(anim_id, str) or not anim_id:
                errors.append(f"{label}.id must be a non-empty string")
            elif anim_id in seen_ids:
                errors.append(f"{label}.id={anim_id!r} duplicated within page")
            else:
                seen_ids.add(anim_id)
            kind = anim.get("kind")
            if kind not in _ANIMATION_KINDS:
                errors.append(
                    f"{label}.kind must be one of {sorted(_ANIMATION_KINDS)}; got {kind!r}"
                )
            else:
                kinds_present.add(kind)
            duration = anim.get("duration_ms")
            # Hard cap at 5000ms. The motion harness captures 6 equidistant
            # frames across max(duration) + padding. If a single animation
            # took 28s to complete a cycle (e.g. a slow marquee), the
            # capture window would stretch to ~28s and the entrance
            # animations on the same page would all live inside the first
            # frame — undersampled. Bounding every animation to one full
            # cycle (loop) or full settle (entrance) within 5s keeps the
            # window tight enough for all motions on the page to be
            # legible across six frames.
            if not isinstance(duration, int) or not (200 <= duration <= 5000):
                errors.append(
                    f"{label}.duration_ms must be an int in [200, 5000]; got {duration!r} "
                    f"(every animation must complete one full cycle or settle within 5000ms)"
                )
            for k in ("target_description", "description"):
                v = anim.get(k)
                if not isinstance(v, str) or not v:
                    errors.append(f"{label}.{k} must be a non-empty string")
        seen_ids_per_page[page] = seen_ids

        if kinds_present != _ANIMATION_KINDS and len(page_anims) >= 1:
            missing = _ANIMATION_KINDS - kinds_present
            errors.append(
                f"expected_animations[{page!r}] must include at least one "
                f"entrance AND one loop; missing kind(s): {sorted(missing)}"
            )

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
    existing: list[dict[str, Any]] | None = None,
    model: str = _MODEL,
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """Generate a Seed dict for (tier, genre). Raises RuntimeError on giving up.

    `existing` is an optional list of previously-accepted seeds. When non-empty,
    the user prompt gets an AVOID block listing them (proactive avoidance), and
    any output that lands too close to one of them by brand-slug or palette
    triggers a retry with feedback (reactive rejection). Schema failures and
    duplicate failures share the same retry budget.
    """
    if tier not in seeds_mod.TIERS:
        raise ValueError(f"unknown tier {tier!r}; known: {sorted(seeds_mod.TIERS)}")
    if genre not in seeds_mod.GENRES.get(tier, []):
        # Don't hard-fail — the LLM can still try — but warn loudly.
        print(
            f"  [concept_gen] WARNING: genre {genre!r} not in GENRES[{tier}] "
            f"(known: {seeds_mod.GENRES.get(tier, [])})",
            file=sys.stderr,
        )

    existing = list(existing or [])
    system = _SYSTEM_PROMPT
    base_user = _build_user_prompt(tier, genre, existing=existing)
    prior_errors: list[str] = []

    for attempt in range(1, max_retries + 1):
        user = base_user
        if prior_errors:
            user += (
                "\n\n## Previous attempt failed\n"
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
            print(f"  [concept_gen] schema failed on attempt {attempt}:")
            for e in errs:
                print(f"    - {e}")
            prior_errors = errs
            continue

        # Reactive rejection: check against priors. Distinct retry message so
        # the model can tell schema failure (fix structure) from duplicate
        # failure (diverge brand + palette) apart.
        is_dup, reason = is_duplicate(data, existing)
        if is_dup:
            print(f"  [concept_gen] duplicate on attempt {attempt}: {reason}")
            prior_errors = [
                f"DUPLICATE: {reason}. Produce a brand and palette that are "
                "distinctly different from every seed in the AVOID block above."
            ]
            continue

        return data

    raise RuntimeError(
        f"giving up on tier={tier} genre={genre} after {max_retries} attempts: "
        f"last errors: {prior_errors}"
    )


def generate_seeds_batch(
    client: Anthropic,
    pairs: list[tuple[int, str]],
    *,
    concurrency: int = 8,
    model: str = _MODEL,
    max_retries: int = _MAX_RETRIES,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate seeds for all (tier, genre) pairs with cross-call dedup.

    Runs in **waves** of `concurrency` parallel workers, not all-at-once. Each
    wave's prompts include an AVOID block listing every seed accepted by prior
    waves (plus any `existing` priors passed in). Within a wave, workers all
    see the same snapshot of priors — within-wave collisions are caught by
    post-hoc dedup after the wave completes.

    Wave-based scheduling is the key bit: without it, all N workers in a fresh
    `--count N --concurrency N` batch see an empty AVOID block, and proactive
    avoidance does nothing. Waves give later workers visibility into earlier
    survivors. Cost: marginally higher wall-clock (waves complete sequentially);
    benefit: dramatically better within-batch diversity.

    Returns only the newly-accepted seeds (not the `existing` priors). May be
    shorter than `len(pairs)` if some calls failed or were dropped as duplicates.
    """
    accepted: list[dict[str, Any]] = list(existing or [])
    base_count = len(accepted)
    n_dropped_dup = 0
    n_failed = 0

    for wave_start in range(0, len(pairs), concurrency):
        wave_pairs = pairs[wave_start:wave_start + concurrency]
        wave_priors = list(accepted)  # frozen snapshot for this wave

        # Run the wave in parallel; collect (input_idx, seed_or_exception).
        wave_results: list[tuple[int, dict[str, Any] | Exception]] = []
        with ThreadPoolExecutor(max_workers=len(wave_pairs)) as pool:
            futures = {
                pool.submit(
                    generate_seed, client, tier, genre,
                    existing=wave_priors, model=model, max_retries=max_retries,
                ): i
                for i, (tier, genre) in enumerate(wave_pairs)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    wave_results.append((idx, fut.result()))
                except Exception as e:
                    wave_results.append((idx, e))

        # Walk in input order so the post-hoc dedup is deterministic given a
        # fixed --synth-seed, regardless of which future completed first.
        wave_results.sort(key=lambda x: x[0])

        for idx, result in wave_results:
            tier, genre = wave_pairs[idx]
            if isinstance(result, Exception):
                print(f"  [concept_gen] FAILED tier={tier} genre={genre}: {result}",
                      file=sys.stderr)
                n_failed += 1
                continue
            # Even with the AVOID block, two workers in the same wave can land
            # on overlapping outputs (they both saw the same priors). Catch
            # those here.
            is_dup, reason = is_duplicate(result, accepted)
            if is_dup:
                print(f"  [concept_gen] dropped within-wave duplicate "
                      f"{result['id']!r}: {reason}")
                n_dropped_dup += 1
                continue
            accepted.append(result)
            print(f"  [concept_gen] accepted: {result['id']} "
                  f"(tier {tier}, {genre})")

    new_count = len(accepted) - base_count
    target = len(pairs)
    print(
        f"  [concept_gen] batch complete: {new_count}/{target} accepted "
        f"(failed={n_failed}, dropped_dup={n_dropped_dup})"
    )

    return accepted[base_count:]


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
