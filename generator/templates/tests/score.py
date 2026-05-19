"""
Grader V3 — V2.1 deterministic aspects + a multimodal-LLM judge.

Evolution chain:
- V1 was SSIM (0.7) + RGB color histogram (0.3). V1 calibration ranked
  `bad > mediocre` (the wrong way) — see running_notes.md V1 results.
- V2 added DOM extraction + 11 weighted aspects + adaptive renormalization.
  Fixed the inversion but `bad` still scored 0.39 (target ≤ 0.15) because
  several aspects gave bad output generous credit for "structure-still-there"
  even when content was garbage.
- V2.1 retuned weights, sharpened sub-aspects (link text 70% inside
  navigation; item text 55% inside repeating_groups), and added a
  multiplicative text-content gate. Three of the four calibration tiers HIT
  cleanly (near_perfect 0.999 / mediocre 0.538 / bad 0.112). But the
  `adversarial` tier — DOM primitives all preserved, only visual
  presentation sabotaged (Comic Sans, neon palette, 96px headings) —
  MISSed at 0.441 because no deterministic combination of pixel histograms,
  IoU overlaps, and string-similarity metrics can see "this looks broken."
- V3 adds the missing eyes: Claude Opus 4.7 with vision (a multimodal LLM)
  is called per page with the reference and agent screenshots plus a short
  checklist of design-fidelity criteria. The judge dimension carries 0.70
  of the total reward; the V2.1 pipeline carries the remaining 0.30, all
  internals unchanged. The judge is REQUIRED: if `ANTHROPIC_API_KEY` is
  missing, or any judge call fails, the grader raises and exits non-zero.
  We refuse to silently fall back to V2.1-only because that would produce
  a smaller-but-still-plausible reward number that hides a serious infra
  failure and makes scores incomparable across runs.

Single 1280x800 viewport for both ref and agent in this version, but the
judge API plumbing accepts an arbitrary list of (viewport_label, image)
pairs per page so adding laptop / tablet / phone renders later is a matter
of populating the list at the orchestration layer — no judge-side changes.
Same for the criteria phrasing: they speak to the agent's *rendering* and
the reference *design*, not to "the screenshot," so they extend cleanly
when more viewports are added.

Three key design choices vs V1:

1. ADAPTIVE RENORMALIZATION. Each aspect returns (score, weight_multiplier).
   Aspects that have nothing to compare (e.g., nav on a single-page site)
   return weight_multiplier=0 and contribute nothing — the remaining aspects
   renormalize against actual applied weight. Non-applicable aspects do not
   give free 1.0s the way V1's two-metric average would have.

2. SCHEMA-FREE EXTRACTION. The donor JS pulls generic primitives — every
   heading, every paragraph, every link (with `inNav` flag), every
   structurally-repeating group (children sharing tag + size bucket), every
   button/input, layout skeleton. Works across the generator's t1-t3
   tiers without per-genre hard-coding.

3. PER-ASPECT BREAKDOWN. score_details.json exposes every aspect's score,
   applied weight, and details — an operator can see *what* failed, not
   just the combined number.

I/O contract (unchanged from V1):
  reads
    /opt/reference-pages/<page>/index.html
    /app/output/<page>/index.html
    /app/references/<page>.png  (optional, for comparison label)
  writes
    /logs/verifier/reward.txt              single float in [0, 1]
    /logs/verifier/score_details.json      per-page breakdown with aspect details
    /logs/verifier/comparisons/<page>.png  side-by-side: input | agent output
    /logs/verifier/renders/<page>.{ref,agent}.png

What V2 still does not address (sets up V3):
- No semantic design judgment — right primitives in the right places is not
  the same as "looks like the reference" (typography pairing, vertical rhythm,
  brand vibe).
- No responsive testing — still 1280x800 only.
- Source HTML is never inspected — reward hacking like embedding the input
  PNG as <img> still slips through.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright
from skimage.metrics import structural_similarity as ssim

# Motion-capture helper. Lives at /opt/_motion_capture.py (copied by the
# Dockerfile) and is imported by both make.py (build-time references) and
# this verifier-time grader (agent-side frame grids). Splice /opt/ onto
# sys.path so the import resolves regardless of cwd.
sys.path.insert(0, "/opt")
try:
    import _motion_capture  # type: ignore[import-not-found]
except ImportError:
    _motion_capture = None  # type: ignore[assignment]


# === CONFIGURATION ===

REFERENCE_HTML_DIR = Path("/opt/reference-pages")
INPUT_PNG_DIR = Path("/app/references")
AGENT_DIR = Path("/app/output")
MOTION_SIDECAR = Path("/opt/motion.json")

LOG_DIR = Path("/logs/verifier")
REWARD_PATH = LOG_DIR / "reward.txt"
DETAILS_PATH = LOG_DIR / "score_details.json"
RENDERS_DIR = LOG_DIR / "renders"
COMPARISONS_DIR = LOG_DIR / "comparisons"

# V4: three viewports. Each page is rendered at all three and graded
# independently; the deterministic aspects average across viewports, the
# judge sees all six images (3 ref + 3 agent) in a single call per page.
# Reference PNGs live at /app/references/{viewport}/{page}.png; agent
# HTML stays at /app/output/{page}/index.html (one HTML per page, rendered
# three times at grade time).
VIEWPORTS: list[tuple[str, dict[str, int]]] = [
    ("desktop", {"width": 1440, "height": 900}),
    ("tablet",  {"width": 768,  "height": 1024}),
    ("phone",   {"width": 390,  "height": 844}),
]
# Backwards-compat shim — some helper functions still take a single
# viewport dict for legacy DOM-extraction sizing. Default to the desktop
# entry so V3.x-era helpers still produce sensible numbers when called
# without an explicit viewport.
VIEWPORT = VIEWPORTS[0][1]

# V3 top-level dimension weights. The V2.1 deterministic pipeline (the 11
# aspects below + text gate) becomes one of two dimensions, with the
# multimodal-LLM judge as the other. The grader requires the judge to run;
# if ANTHROPIC_API_KEY is missing the grader raises (no silent fallback).
V3_JUDGE_WEIGHT = 0.70
V3_DETERMINISTIC_WEIGHT = 0.30

JUDGE_MODEL = "claude-opus-4-7"
JUDGE_MAX_TOKENS = 2048
# Number of judge calls per page. Median (Likert) / majority vote (binary)
# across the ensemble smooths LLM run-to-run noise. Bumped from 1 (iteration
# speed) to 3 (production stability) once the V3.1 pipeline calibrated
# cleanly — three samples cut one-Likert-step variance roughly in half.
JUDGE_ENSEMBLE_SIZE = 3
# V4: each judge call now sends 6 PNGs per page (3 ref + 3 agent across
# desktop/tablet/phone) instead of 2, so the per-image cap drops from 4000
# to 2400 to keep the total request payload under Anthropic's per-request
# size budget (~32 MB). Anything taller than 2400 along the longest side
# gets proportionally downscaled before base64-encoding.
JUDGE_IMAGE_MAX_DIM = 2400

# Target weights — sum to 1.0 when every aspect is applicable. Aspects that
# skip (weight_multiplier=0) cause the rest to renormalize at scoring time.
# V2.1 retune (vs V2): demoted layout-preserving signals (pixel_ssim,
# repeating_groups, layout_skeleton) and promoted discriminating signals
# (text_content, region_color, palette). See running_notes.md for the
# per-aspect bad-tier contributions that motivated this.
ASPECT_TARGET_WEIGHTS: dict[str, float] = {
    "pixel_ssim":       0.08,  # V2 was 0.18 — grayscale SSIM is forgiving of color/text
    "color_histogram":  0.05,  # V2 was 0.07
    "region_color":     0.10,  # V2 was 0.08 — correctly tanks for wrong palettes
    "palette":          0.07,  # V2 was 0.05 — correctly tanks for wrong palettes
    "headings":         0.08,  # V2 was 0.10
    "paragraphs":       0.05,  # V2 was 0.07
    "navigation":       0.07,  # V2 was 0.08
    "repeating_groups": 0.08,  # V2 was 0.12 — fires on tag+size-bucket alone, too forgiving
    "interactive":      0.04,  # V2 was 0.05
    "layout_skeleton":  0.06,  # V2 was 0.10 — IoU matches survive structural rewrites
    "text_content":     0.32,  # V2 was 0.10 — text content is the single best discriminator
}
assert abs(sum(ASPECT_TARGET_WEIGHTS.values()) - 1.0) < 1e-6

# If less than this fraction of total weight applies to a page, flag it as
# partial info. Pixel aspects alone are ~0.38 of total weight, so 0.50 means
# anything pixel-only or worse triggers the flag.
COVERAGE_FLAG_THRESHOLD = 0.50


# === DOM EXTRACTION ===

# Single JS snippet that pulls everything we need in one round-trip.
EXTRACTION_JS = r"""
() => {
    const round = (n) => Math.round(n * 100) / 100;
    function getRect(el) {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {
            x: round(r.x), y: round(r.y),
            width: round(r.width), height: round(r.height),
            bottom: round(r.bottom), right: round(r.right),
            area: round(r.width * r.height),
        };
    }
    function getStyles(el) {
        if (!el) return {};
        const s = window.getComputedStyle(el);
        return {
            fontSize: s.fontSize,
            fontWeight: s.fontWeight,
            fontFamily: s.fontFamily,
            color: s.color,
            backgroundColor: s.backgroundColor,
            display: s.display,
            position: s.position,
            borderTopColor: s.borderTopColor,
            borderRightColor: s.borderRightColor,
            borderBottomColor: s.borderBottomColor,
            borderLeftColor: s.borderLeftColor,
            borderTopWidth: s.borderTopWidth,
            borderRightWidth: s.borderRightWidth,
            borderBottomWidth: s.borderBottomWidth,
            borderLeftWidth: s.borderLeftWidth,
            borderTopLeftRadius: s.borderTopLeftRadius,
            borderTopRightRadius: s.borderTopRightRadius,
            borderBottomLeftRadius: s.borderBottomLeftRadius,
            borderBottomRightRadius: s.borderBottomRightRadius,
            paddingTop: s.paddingTop,
            paddingRight: s.paddingRight,
            paddingBottom: s.paddingBottom,
            paddingLeft: s.paddingLeft,
            marginTop: s.marginTop,
            marginRight: s.marginRight,
            marginBottom: s.marginBottom,
            marginLeft: s.marginLeft,
            textAlign: s.textAlign,
            boxShadow: s.boxShadow,
            backgroundImage: s.backgroundImage,
        };
    }

    // V4: no fold-based culling. We capture full_page=True at every viewport,
    // so every element with a non-zero rect and a non-hidden computed style
    // is in-scope, regardless of vertical position.
    function isVisible(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        return true;
    }

    const out = {};

    // ---- HEADINGS (h1..h6) ----
    const headings = [];
    for (const tag of ['h1','h2','h3','h4','h5','h6']) {
        document.querySelectorAll(tag).forEach(el => {
            if (!isVisible(el)) return;
            const text = el.textContent.trim();
            if (!text) return;
            headings.push({ tag, text, rect: getRect(el), styles: getStyles(el) });
        });
    }
    out.headings = headings;

    // ---- PARAGRAPHS ----
    const paragraphs = [];
    document.querySelectorAll('p, blockquote').forEach(el => {
        if (!isVisible(el)) return;
        const text = el.textContent.trim();
        if (!text || text.length < 3) return;
        paragraphs.push({ text, length: text.length, rect: getRect(el), styles: getStyles(el) });
    });
    out.paragraphs = paragraphs;

    // ---- LINKS ----
    const links = [];
    document.querySelectorAll('a').forEach(el => {
        if (!isVisible(el)) return;
        const text = el.textContent.trim();
        if (!text) return;
        const inNav = !!el.closest('nav, header, [role="navigation"], aside');
        links.push({ text, inNav, rect: getRect(el), styles: getStyles(el) });
    });
    out.links = links;

    // ---- BUTTONS + FORM INPUTS ----
    const interactive = [];
    document.querySelectorAll('button, input, textarea, select').forEach(el => {
        if (!isVisible(el)) return;
        interactive.push({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            text: (el.textContent || el.getAttribute('placeholder') || el.getAttribute('value') || '').trim(),
            rect: getRect(el),
            styles: getStyles(el),
        });
    });
    out.interactive = interactive;

    // ---- NAV REGIONS ----
    const navCandidates = new Set();
    document.querySelectorAll('nav, header, aside, [role="navigation"]').forEach(el => {
        if (isVisible(el)) navCandidates.add(el);
    });
    document.querySelectorAll('*').forEach(el => {
        if (navCandidates.has(el) || !isVisible(el)) return;
        const childLinks = Array.from(el.children).filter(c => c.tagName === 'A');
        const liLinks = el.querySelectorAll(':scope > li > a, :scope > ul > li > a, :scope > ol > li > a');
        if (childLinks.length >= 4 || liLinks.length >= 4) navCandidates.add(el);
    });
    const navRegions = [];
    navCandidates.forEach(el => {
        const innerLinks = [];
        el.querySelectorAll('a').forEach(a => {
            const t = a.textContent.trim();
            if (t && isVisible(a)) innerLinks.push({ text: t, rect: getRect(a) });
        });
        navRegions.push({
            tag: el.tagName.toLowerCase(),
            rect: getRect(el),
            linkCount: innerLinks.length,
            links: innerLinks,
            styles: getStyles(el),
        });
    });
    out.navRegions = navRegions;

    // ---- REPEATING GROUPS ----
    function structuralKey(el) {
        const r = el.getBoundingClientRect();
        const wBucket = Math.round(r.width / 50);
        const hBucket = Math.round(r.height / 50);
        return el.tagName + '|' + wBucket + 'x' + hBucket;
    }
    const groups = [];
    document.querySelectorAll('*').forEach(el => {
        if (!isVisible(el)) return;
        const children = Array.from(el.children).filter(c => isVisible(c));
        if (children.length < 2) return;
        const contentChildren = children.filter(c =>
            !['SCRIPT', 'STYLE', 'NOSCRIPT', 'BR', 'HR'].includes(c.tagName)
        );
        if (contentChildren.length < 2) return;

        const keys = contentChildren.map(structuralKey);
        const keyCounts = {};
        for (const k of keys) keyCounts[k] = (keyCounts[k] || 0) + 1;
        const dominant = Object.entries(keyCounts).sort((a,b) => b[1] - a[1])[0];
        if (dominant[1] < 2) return;
        if (dominant[1] / contentChildren.length < 0.6) return;

        let nested = false;
        for (const existing of groups) {
            if (existing._el && existing._el.contains(el)) { nested = true; break; }
            if (existing._el && el.contains(existing._el)) { nested = true; break; }
        }
        if (nested) return;

        const groupRect = getRect(el);
        if (!groupRect || groupRect.area < 5000) return;
        const xs = contentChildren.map(c => c.getBoundingClientRect().x);
        const ys = contentChildren.map(c => c.getBoundingClientRect().y);
        const xRange = Math.max(...xs) - Math.min(...xs);
        const yRange = Math.max(...ys) - Math.min(...ys);
        const direction = xRange > yRange ? 'horizontal' : 'vertical';

        const items = contentChildren.map(c => {
            const text = c.textContent.trim().slice(0, 200);
            const childImgs = c.querySelectorAll('img, svg');
            const childButtons = c.querySelectorAll('button, a[href]');
            return {
                tag: c.tagName.toLowerCase(),
                text,
                textLength: c.textContent.trim().length,
                rect: getRect(c),
                styles: getStyles(c),
                imageCount: childImgs.length,
                interactiveCount: childButtons.length,
            };
        });

        groups.push({
            _el: el,
            tag: el.tagName.toLowerCase(),
            rect: groupRect,
            direction,
            itemCount: items.length,
            items,
        });
    });
    for (const g of groups) delete g._el;
    groups.sort((a, b) => (b.rect.area || 0) - (a.rect.area || 0));
    out.repeatingGroups = groups;

    // ---- BODY ----
    out.bodyStyles = getStyles(document.body);
    out.htmlRect = getRect(document.documentElement);

    // ---- ALL VISIBLE TEXT (sequence-aware similarity input) ----
    const textWalker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const allText = [];
    let tn;
    while ((tn = textWalker.nextNode())) {
        const parent = tn.parentElement;
        if (!parent) continue;
        if (!isVisible(parent)) continue;
        if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName)) continue;
        const t = tn.textContent.trim();
        if (t) allText.push(t);
    }
    out.visibleText = allText.join(' ').slice(0, 20000);

    return out;
}
"""


def extract_dom_info(page: Page) -> dict[str, Any]:
    return page.evaluate(EXTRACTION_JS)


# === COMPARISON HELPERS ===

def _parse_px(val: str | None) -> float:
    if not val:
        return 0.0
    m = re.search(r"([-+]?[\d.]+)", str(val))
    return float(m.group(1)) if m else 0.0


def _parse_color_rgb(val: str | None) -> tuple[int, int, int, float] | None:
    """Return (r, g, b, alpha). None on unparseable or 'transparent'."""
    if not val:
        return None
    s = str(val).strip()
    if s in ("transparent", "rgba(0, 0, 0, 0)"):
        return None
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", s)
    if not m:
        return None
    a = float(m.group(4)) if m.group(4) else 1.0
    if a == 0:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), a)


def _color_distance(c1, c2) -> float:
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])))
    return d / (255.0 * math.sqrt(3.0))


def _color_similarity(c1, c2) -> float:
    if c1 is None and c2 is None:
        return 1.0
    if c1 is None or c2 is None:
        return 0.0
    return max(0.0, 1.0 - _color_distance(c1, c2) * 2.0)


def _text_similarity(t1: str | None, t2: str | None) -> float:
    """Sequence-aware similarity via difflib. Order matters."""
    s1 = (t1 or "").strip().lower()
    s2 = (t2 or "").strip().lower()
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    return difflib.SequenceMatcher(a=s1, b=s2, autojunk=False).ratio()


def _rect_iou(r1, r2) -> float:
    if not r1 or not r2:
        return 0.0
    x1 = max(r1["x"], r2["x"])
    y1 = max(r1["y"], r2["y"])
    x2 = min(r1["x"] + r1["width"], r2["x"] + r2["width"])
    y2 = min(r1["y"] + r1["height"], r2["y"] + r2["height"])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = r1["width"] * r1["height"] + r2["width"] * r2["height"] - inter
    if union < 1e-9:
        return 1.0
    return inter / union


def _rect_position_similarity(r1, r2) -> float:
    if r1 is None and r2 is None:
        return 1.0
    if r1 is None or r2 is None:
        return 0.0
    dx = abs(r1["x"] - r2["x"]) / max(VIEWPORT["width"], 1)
    dy = abs(r1["y"] - r2["y"]) / max(VIEWPORT["height"], 1)
    pos = max(0.0, 1.0 - (dx + dy) * 2.0)
    w1, w2 = r1["width"], r2["width"]
    h1, h2 = r1["height"], r2["height"]
    sw = min(w1, w2) / max(w1, w2) if max(w1, w2) > 0 else 1.0
    sh = min(h1, h2) / max(h1, h2) if max(h1, h2) > 0 else 1.0
    return 0.5 * pos + 0.5 * (sw + sh) / 2


def _ratio_similarity(a: float, b: float) -> float:
    if a == 0 and b == 0:
        return 1.0
    if a == 0 or b == 0:
        return 0.0
    return min(a, b) / max(a, b)


# === ASPECT RESULT ===

@dataclass
class AspectResult:
    score: float
    weight_multiplier: float  # 0.0 = skip, 1.0 = full weight
    details: dict[str, Any]


# === PIXEL ASPECTS ===

def score_pixel_ssim(ref_img: np.ndarray, agent_img: np.ndarray) -> AspectResult:
    ref_gray = np.asarray(Image.fromarray(ref_img).convert("L"))
    agent_gray = np.asarray(Image.fromarray(agent_img).convert("L"))
    val = max(0.0, float(ssim(ref_gray, agent_gray, data_range=255)))
    return AspectResult(score=val, weight_multiplier=1.0, details={"ssim": val})


def score_color_histogram(ref_img: np.ndarray, agent_img: np.ndarray) -> AspectResult:
    total = 0.0
    per_channel = {}
    for c, name in enumerate(["r", "g", "b"]):
        ha, _ = np.histogram(ref_img[:, :, c], bins=32, range=(0, 256))
        hb, _ = np.histogram(agent_img[:, :, c], bins=32, range=(0, 256))
        ha = ha / (ha.sum() + 1e-9)
        hb = hb / (hb.sum() + 1e-9)
        ch = float(np.minimum(ha, hb).sum())
        per_channel[name] = ch
        total += ch
    return AspectResult(score=total / 3.0, weight_multiplier=1.0, details=per_channel)


def score_region_color(ref_img: np.ndarray, agent_img: np.ndarray) -> AspectResult:
    """3x3 spatial bins; mean color match per bin. Catches 'right palette, wrong placement'."""
    H, W = ref_img.shape[:2]
    rows, cols = 3, 3
    bin_scores = []
    details = {}
    for ri in range(rows):
        for ci in range(cols):
            y1, y2 = H * ri // rows, H * (ri + 1) // rows
            x1, x2 = W * ci // cols, W * (ci + 1) // cols
            ref_mean = ref_img[y1:y2, x1:x2].mean(axis=(0, 1))
            ag_mean = agent_img[y1:y2, x1:x2].mean(axis=(0, 1))
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(ref_mean, ag_mean)))
            s = max(0.0, 1.0 - d / (255.0 * math.sqrt(3.0)) * 2.0)
            bin_scores.append(s)
            details[f"bin_{ri}_{ci}"] = round(s, 4)
    return AspectResult(score=sum(bin_scores) / len(bin_scores),
                        weight_multiplier=1.0, details=details)


def score_palette(ref_img: np.ndarray, agent_img: np.ndarray) -> AspectResult:
    """Top-K dominant colors via 6-bit quantization, area-weighted overlap."""
    def palette(img, k=8):
        q = (img // 32).astype(np.uint8)
        idx = q[:, :, 0].astype(int) * 64 + q[:, :, 1].astype(int) * 8 + q[:, :, 2].astype(int)
        counts = np.bincount(idx.ravel(), minlength=512)
        top = np.argsort(counts)[::-1][:k]
        total = counts.sum()
        return [(int(t), float(counts[t]) / float(total)) for t in top if counts[t] > 0]

    p1 = palette(ref_img)
    p2 = palette(agent_img)
    d1 = dict(p1); d2 = dict(p2)
    common = set(d1) | set(d2)
    overlap = sum(min(d1.get(b, 0.0), d2.get(b, 0.0)) for b in common)
    return AspectResult(score=overlap, weight_multiplier=1.0,
                        details={"top_ref": p1[:5], "top_agent": p2[:5], "overlap": overlap})


# === STRUCTURAL ASPECTS ===

def score_headings(ref: dict, agent: dict) -> AspectResult:
    ref_h = ref.get("headings", [])
    agent_h = agent.get("headings", [])
    if not ref_h and not agent_h:
        return AspectResult(score=1.0, weight_multiplier=0.0,
                            details={"note": "no headings on either side"})

    def by_tag(hs):
        d = {}
        for h in hs:
            d[h["tag"]] = d.get(h["tag"], 0) + 1
        return d
    ref_by = by_tag(ref_h)
    agent_by = by_tag(agent_h)
    all_tags = set(ref_by) | set(agent_by)
    count_scores = [_ratio_similarity(ref_by.get(t, 0), agent_by.get(t, 0)) for t in all_tags]

    def biggest(hs):
        return max(hs, key=lambda h: (h.get("rect") or {}).get("area", 0)) if hs else None
    ref_big = biggest(ref_h)
    agent_big = biggest(agent_h)
    text_score = _text_similarity(
        (ref_big or {}).get("text", ""), (agent_big or {}).get("text", "")
    )
    pos_score = _rect_position_similarity(
        (ref_big or {}).get("rect"), (agent_big or {}).get("rect")
    )

    def top_n(hs, n):
        return sorted(hs, key=lambda h: -(h.get("rect") or {}).get("area", 0))[:n]
    ref_top = top_n(ref_h, 5)
    agent_top = top_n(agent_h, 5)
    additional_text_scores = []
    used = set()
    for rh in ref_top[1:]:
        best_score = 0.0
        best_idx = -1
        for i, ah in enumerate(agent_top[1:]):
            if i in used:
                continue
            s = _text_similarity(rh.get("text", ""), ah.get("text", ""))
            if s > best_score:
                best_score = s
                best_idx = i
        if best_idx >= 0:
            used.add(best_idx)
        additional_text_scores.append(best_score)

    parts = count_scores + [text_score, pos_score] + additional_text_scores
    score = sum(parts) / len(parts)
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_count_by_tag": ref_by,
        "agent_count_by_tag": agent_by,
        "biggest_text_score": text_score,
        "biggest_position_score": pos_score,
        "additional_text_scores": additional_text_scores,
    })


def score_paragraphs(ref: dict, agent: dict) -> AspectResult:
    ref_p = ref.get("paragraphs", [])
    agent_p = agent.get("paragraphs", [])
    if not ref_p and not agent_p:
        return AspectResult(score=1.0, weight_multiplier=0.0,
                            details={"note": "no paragraphs"})

    count_score = _ratio_similarity(len(ref_p), len(agent_p))

    def length_buckets(ps):
        buckets = {"short": 0, "medium": 0, "long": 0}
        for p in ps:
            n = p.get("length", 0)
            if n < 50: buckets["short"] += 1
            elif n < 200: buckets["medium"] += 1
            else: buckets["long"] += 1
        return buckets
    ref_b = length_buckets(ref_p)
    agent_b = length_buckets(agent_p)
    bucket_scores = [_ratio_similarity(ref_b[k], agent_b[k]) for k in ref_b]

    score = (count_score + sum(bucket_scores) / len(bucket_scores)) / 2
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_count": len(ref_p),
        "agent_count": len(agent_p),
        "ref_buckets": ref_b,
        "agent_buckets": agent_b,
    })


def score_navigation(ref: dict, agent: dict) -> AspectResult:
    ref_n = ref.get("navRegions", [])
    agent_n = agent.get("navRegions", [])
    if not ref_n and not agent_n:
        return AspectResult(score=1.0, weight_multiplier=0.0,
                            details={"note": "no nav-like regions"})

    def biggest(navs):
        return max(navs, key=lambda n: (n.get("rect") or {}).get("area", 0)) if navs else None
    ref_primary = biggest(ref_n)
    agent_primary = biggest(agent_n)

    pos_score = _rect_position_similarity(
        (ref_primary or {}).get("rect"), (agent_primary or {}).get("rect")
    )

    ref_links = (ref_primary or {}).get("links", [])
    agent_links = (agent_primary or {}).get("links", [])
    count_score = _ratio_similarity(len(ref_links), len(agent_links))

    if ref_links and agent_links:
        link_scores = []
        for rl in ref_links:
            best = max((_text_similarity(rl.get("text", ""), al.get("text", "")) for al in agent_links), default=0.0)
            link_scores.append(best)
        text_score = sum(link_scores) / len(link_scores)
    elif not ref_links and not agent_links:
        text_score = 1.0
    else:
        text_score = 0.0

    region_count_score = _ratio_similarity(len(ref_n), len(agent_n))

    # V2.1: text dominates. A nav region whose links read "Link One / Link Two"
    # is degenerate even when its position and link count match the reference.
    score = (
        0.70 * text_score
        + 0.10 * pos_score
        + 0.10 * count_score
        + 0.10 * region_count_score
    )
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_nav_count": len(ref_n),
        "agent_nav_count": len(agent_n),
        "primary_position_score": pos_score,
        "primary_link_count": {"ref": len(ref_links), "agent": len(agent_links)},
        "primary_link_text_score": text_score,
    })


def score_repeating_groups(ref: dict, agent: dict) -> AspectResult:
    ref_g = ref.get("repeatingGroups", [])
    agent_g = agent.get("repeatingGroups", [])

    if not ref_g and not agent_g:
        return AspectResult(score=1.0, weight_multiplier=0.0,
                            details={"note": "no repeating groups on either side"})

    if not ref_g or not agent_g:
        return AspectResult(score=0.0, weight_multiplier=1.0, details={
            "ref_groups": len(ref_g),
            "agent_groups": len(agent_g),
            "note": "one side has no groups",
        })

    used = set()
    per_group_scores = []
    details = []
    for rg in ref_g[:5]:
        best_iou = 0.0
        best_idx = -1
        for i, ag in enumerate(agent_g):
            if i in used: continue
            iou = _rect_iou(rg.get("rect"), ag.get("rect"))
            if iou > best_iou:
                best_iou = iou
                best_idx = i
        if best_idx == -1:
            per_group_scores.append(0.0)
            details.append({"matched": False, "ref_items": rg.get("itemCount", 0)})
            continue
        used.add(best_idx)
        ag = agent_g[best_idx]
        item_count_score = _ratio_similarity(rg.get("itemCount", 0), ag.get("itemCount", 0))
        dir_score = 1.0 if rg.get("direction") == ag.get("direction") else 0.5
        pos_score = _rect_position_similarity(rg.get("rect"), ag.get("rect"))

        ref_items = rg.get("items", [])
        agent_items = ag.get("items", [])
        n = min(len(ref_items), len(agent_items))
        def order(items):
            return sorted(items, key=lambda it: ((it.get("rect") or {}).get("y", 0),
                                                 (it.get("rect") or {}).get("x", 0)))
        ref_items_o = order(ref_items)
        agent_items_o = order(agent_items)
        item_text_scores = []
        item_image_scores = []
        item_interactive_scores = []
        for i in range(n):
            item_text_scores.append(_text_similarity(
                ref_items_o[i].get("text", ""), agent_items_o[i].get("text", ""),
            ))
            item_image_scores.append(_ratio_similarity(
                ref_items_o[i].get("imageCount", 0), agent_items_o[i].get("imageCount", 0),
            ))
            item_interactive_scores.append(_ratio_similarity(
                ref_items_o[i].get("interactiveCount", 0), agent_items_o[i].get("interactiveCount", 0),
            ))

        item_text_avg = sum(item_text_scores) / len(item_text_scores) if item_text_scores else 1.0
        item_image_avg = sum(item_image_scores) / len(item_image_scores) if item_image_scores else 1.0
        item_inter_avg = sum(item_interactive_scores) / len(item_interactive_scores) if item_interactive_scores else 1.0

        # V2.1: item text dominates. A repeating group whose cards still
        # share tag+size_bucket but whose content is all lorem is degenerate.
        group_score = (
            0.10 * item_count_score
            + 0.05 * dir_score
            + 0.10 * pos_score
            + 0.55 * item_text_avg
            + 0.10 * item_image_avg
            + 0.10 * item_inter_avg
        )
        per_group_scores.append(group_score)
        details.append({
            "matched": True,
            "item_count": {"ref": rg.get("itemCount"), "agent": ag.get("itemCount")},
            "direction_match": dir_score,
            "position_score": pos_score,
            "item_text_avg": item_text_avg,
            "item_image_avg": item_image_avg,
            "item_interactive_avg": item_inter_avg,
        })

    unmatched = len(ref_g[:5]) - len(used)
    if unmatched > 0:
        per_group_scores.extend([0.0] * unmatched)

    score = sum(per_group_scores) / len(per_group_scores) if per_group_scores else 0.0
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_group_count": len(ref_g),
        "agent_group_count": len(agent_g),
        "per_group": details,
    })


def score_interactive(ref: dict, agent: dict) -> AspectResult:
    ref_i = ref.get("interactive", [])
    agent_i = agent.get("interactive", [])
    if not ref_i and not agent_i:
        return AspectResult(score=1.0, weight_multiplier=0.0,
                            details={"note": "no interactive elements"})

    count_score = _ratio_similarity(len(ref_i), len(agent_i))

    def by_kind(items):
        d = {}
        for it in items:
            key = it["tag"] + ":" + (it.get("type") or "")
            d[key] = d.get(key, 0) + 1
        return d
    ref_b = by_kind(ref_i)
    agent_b = by_kind(agent_i)
    all_kinds = set(ref_b) | set(agent_b)
    kind_scores = [_ratio_similarity(ref_b.get(k, 0), agent_b.get(k, 0)) for k in all_kinds]
    kind_score = sum(kind_scores) / len(kind_scores) if kind_scores else 1.0

    def top_buttons(items, n=5):
        bs = [it for it in items if it["tag"] == "button" or it.get("text")]
        return sorted(bs, key=lambda it: -(it.get("rect") or {}).get("area", 0))[:n]
    ref_btns = top_buttons(ref_i)
    agent_btns = top_buttons(agent_i)
    if ref_btns and agent_btns:
        btn_text_scores = []
        for rb in ref_btns:
            best = max(
                (_text_similarity(rb.get("text", ""), ab.get("text", "")) for ab in agent_btns),
                default=0.0,
            )
            btn_text_scores.append(best)
        text_score = sum(btn_text_scores) / len(btn_text_scores)
    elif not ref_btns and not agent_btns:
        text_score = 1.0
    else:
        text_score = 0.0

    score = (count_score + kind_score + text_score) / 3
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_count": len(ref_i),
        "agent_count": len(agent_i),
        "ref_kinds": ref_b,
        "agent_kinds": agent_b,
        "button_text_score": text_score,
    })


def score_layout_skeleton(ref: dict, agent: dict) -> AspectResult:
    """Bounding-box map of major elements grouped by type. Tests overall page shape."""
    def skeleton(d):
        out = []
        if d.get("headings"):
            big = max(d["headings"], key=lambda h: (h.get("rect") or {}).get("area", 0))
            r = big.get("rect")
            if r: out.append(("heading", r))
        if d.get("navRegions"):
            big = max(d["navRegions"], key=lambda n: (n.get("rect") or {}).get("area", 0))
            r = big.get("rect")
            if r: out.append(("nav", r))
        for g in d.get("repeatingGroups", [])[:5]:
            r = g.get("rect")
            if r: out.append(("group", r))
        ps = sorted(d.get("paragraphs", []), key=lambda p: -(p.get("rect") or {}).get("area", 0))[:3]
        for p in ps:
            r = p.get("rect")
            if r: out.append(("paragraph", r))
        return out

    ref_sk = skeleton(ref)
    agent_sk = skeleton(agent)
    if not ref_sk and not agent_sk:
        return AspectResult(score=1.0, weight_multiplier=0.0,
                            details={"note": "no skeleton elements"})

    used = set()
    scores = []
    matches = []
    for kind, rect in ref_sk:
        best = 0.0
        best_idx = -1
        for i, (a_kind, a_rect) in enumerate(agent_sk):
            if i in used or a_kind != kind:
                continue
            iou = _rect_iou(rect, a_rect)
            if iou > best:
                best = iou
                best_idx = i
        if best_idx >= 0:
            used.add(best_idx)
        scores.append(best)
        matches.append({"kind": kind, "iou": round(best, 3)})

    extras = len(agent_sk) - len(used)
    if extras > 0:
        scores.extend([max(0.0, 1.0 - 0.1) for _ in range(min(extras, 5))])

    score = sum(scores) / len(scores) if scores else 0.0
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_skeleton_size": len(ref_sk),
        "agent_skeleton_size": len(agent_sk),
        "matches": matches,
        "extras_in_agent": max(0, extras),
    })


def score_text_content(ref: dict, agent: dict) -> AspectResult:
    """Sequence-aware similarity over ALL visible text."""
    ref_text = (ref.get("visibleText") or "").lower()
    agent_text = (agent.get("visibleText") or "").lower()
    if not ref_text and not agent_text:
        return AspectResult(score=1.0, weight_multiplier=0.0, details={"note": "no text"})
    score = _text_similarity(ref_text, agent_text)
    return AspectResult(score=score, weight_multiplier=1.0, details={
        "ref_chars": len(ref_text),
        "agent_chars": len(agent_text),
    })


# === JUDGE (multimodal LLM) ===

# The judge dimension. For each page we send the reference rendering and the
# agent rendering to Claude Opus 4.7 with a short checklist of design-
# fidelity criteria. The judge returns an integer per criterion; we
# aggregate across an ensemble (majority vote on binary, median on Likert)
# and normalize to [0, 1] for the page.
#
# Criteria are kept short and page-agnostic. The deterministic V2.1
# pipeline already measures everything that can be measured by string-
# match, IoU, and pixel histogram. The judge is the place to ask the
# questions the deterministic side cannot — does the visual hierarchy
# work, does the typography pair, does it feel like the same brand. Six
# criteria total, phrased to describe the *rendering* rather than any
# specific screenshot so the same wording works once we feed multiple
# viewports per page.

# === MOTION JUDGE (tier-9 only) ===
#
# Tier-9 tasks send the judge a single frame-grid PNG per (page, viewport)
# instead of a single static screenshot. The grid is a 2x3 composite of six
# frames sampled across the page's animation window via Playwright clock
# virtualization (see _motion_capture.py). The criteria below replace the
# static JUDGE_CRITERIA when motion.json declares animations — the static
# criteria assume single-frame visuals and would penalize legitimate motion
# (e.g. layout_fidelity tanks if frame-1 mid-transform doesn't match frame-6
# settled).
#
# For motion tasks the V2.1 deterministic block is also bypassed: single-
# frame pixel SSIM and palette histograms across animated frames are noise.
# Reward = mean of motion-judge medians across pages.

MOTION_JUDGE_CRITERIA: list[dict[str, Any]] = [
    {
        "id": "motion_presence",
        "scoring": "likert_5",
        "question": (
            "How much visible motion is there in the AGENT's grid across "
            "the six frames? Compare tiles 1-6: do elements shift, scale, "
            "fade, rotate, or translate? Partial credit is fine for "
            "subtle/localized motion. 5 = clear, multi-element motion "
            "across the grid; 3 = subtle or single-area motion that's "
            "still visible; 1 = grid is essentially static."
        ),
    },
    {
        "id": "target_element",
        "scoring": "likert_5",
        "question": (
            "Does the motion in the agent's grid affect the SAME elements "
            "as the reference grid (e.g. headline staggers in both, marquee "
            "in both, background orb in both)? 5 = same elements move; "
            "1 = different elements move, or no motion at all."
        ),
    },
    {
        "id": "motion_character",
        "scoring": "likert_5",
        "question": (
            "Does the STYLE of motion match the reference — direction, "
            "easing, scale of transform, opacity range, rotation, drift? "
            "5 = same character (subtle drift vs subtle drift, dramatic "
            "stagger vs dramatic stagger); 1 = wildly different feel."
        ),
    },
    {
        "id": "timing_fidelity",
        "scoring": "likert_5",
        "question": (
            "Does the PACE of motion across frames 1-6 match the reference? "
            "Are entrance animations finished by the same frame, are loop "
            "animations at similar phases? 5 = synchronized progression; "
            "1 = agent finishes way faster or way slower, or skips beats."
        ),
    },
    {
        "id": "settled_state",
        "scoring": "likert_5",
        "question": (
            "Compare ONLY the last tile (frame 6) of each grid. Does the "
            "agent's settled state match the reference's settled state — "
            "same layout, same elements present, same final positions? "
            "5 = indistinguishable; 1 = unmistakably different."
        ),
    },
    {
        "id": "overall_motion_fidelity",
        "scoring": "likert_5",
        "question": (
            "Overall: if both grids were shown side-by-side to a motion "
            "designer, would they accept the agent's animation as a faithful "
            "replication of the reference's? 5 = essentially indistinguishable; "
            "1 = unmistakably broken."
        ),
    },
]


def _load_motion_spec() -> dict[str, dict]:
    """Return per-page motion specs from /opt/motion.json, or empty dict.

    Shape: `{page_name: {"animations": [...], "frame_window_ms": int}}`.
    Empty means the task is static — no motion branch needed.
    """
    if not MOTION_SIDECAR.is_file():
        return {}
    try:
        blob = json.loads(MOTION_SIDECAR.read_text())
    except json.JSONDecodeError:
        return {}
    return blob.get("expected_animations") or {}


# Pixel-diff threshold for "the agent's grid clearly has motion."
#
# Calibrated from the v2 oracle run (synth-t9-solaris-drift-observatory): a
# rotating-ring page sits at 0.7% changed pixels and reads as perfect motion
# to the judge; a slide-up-and-settle page sits at 1.8% but reads as static
# (motion happens early then frames 3-6 are identical). The pixel ratio
# doesn't predict judge perception — it just bounds the easy positive cases.
#
# We use it ONLY to lift motion_presence when the judge missed visible
# motion (auto-credit). We do NOT use it to drop motion_presence — the judge
# can correctly identify motion in 0.4%-pixel-change grids where pixel
# tally alone would say "static." Trusting the judge downward, correcting
# it upward.
MOTION_PIXEL_CHANGE_CREDIT_THRESHOLD = 0.005


def _split_grid_into_tiles(grid_path: Path) -> list[Any]:
    """Crop a 2x3 motion grid back into its six frame tiles for pixel diffing.

    Tile geometry mirrors `_compose_grid` in /opt/_motion_capture.py: 28px
    label band on top of each tile, 6px gap between tiles, 3 cols × 2 rows.
    Returns RGB numpy arrays in reading order (frame 1 .. frame 6).
    """
    img = Image.open(grid_path)
    W, H = img.size
    label_h, gap, cols, rows = 28, 6, 3, 2
    tile_w = (W - (cols - 1) * gap) // cols
    tile_h = (H - rows * label_h - (rows - 1) * gap) // rows
    tiles: list[Any] = []
    for r in range(rows):
        for c in range(cols):
            x = c * (tile_w + gap)
            y = r * (tile_h + label_h + gap) + label_h
            tiles.append(np.array(img.crop((x, y, x + tile_w, y + tile_h)).convert("RGB"), dtype=np.int16))
    return tiles


def measure_grid_motion(grid_path: Path) -> dict[str, float]:
    """Pre-flight pixel-level motion measurement on a frame-grid PNG.

    Returns `{"max_changed_fraction": float, "mean_diff": float}` — the
    fraction of pixels in the most-different tile relative to tile 0
    (RGB delta > 30/255), and the mean absolute RGB delta across all
    tile-vs-tile-0 comparisons.

    Used by `score.py` to short-circuit two cases before calling the judge:
      - Agent grid is essentially static → motion_presence floored at 0
      - Agent grid shows clear motion    → motion_presence floored at 0.5
    """
    if not grid_path.is_file():
        return {"max_changed_fraction": 0.0, "mean_diff": 0.0}
    tiles = _split_grid_into_tiles(grid_path)
    base = tiles[0]
    max_changed = 0.0
    mean_diff_sum = 0.0
    for t in tiles[1:]:
        delta = np.abs(t - base)
        per_pixel = delta.sum(axis=2)
        changed = float((per_pixel > 30).mean())
        max_changed = max(max_changed, changed)
        mean_diff_sum += float(delta.mean())
    n = max(1, len(tiles) - 1)
    return {
        "max_changed_fraction": max_changed,
        "mean_diff": mean_diff_sum / n,
    }


# Patterns we expect to see in a motion-task agent's HTML+CSS sources.
# Absence is a strong signal the agent didn't try to animate at all —
# cheaper and more diagnostic than letting VLM consensus catch it.
_MOTION_PRIMITIVE_PATTERNS = (
    r"@keyframes\b",
    r"\banimation\s*:",
    r"\banimation-name\s*:",
)


def scan_agent_motion_primitives(
    agent_dir: Path,
    page_name: str,
    expected_anim_ids: list[str],
) -> dict[str, Any]:
    """Check the agent's HTML + shared CSS for animation primitives + data-anim ids.

    Returns:
      {
        "has_keyframes_or_animation": bool,
        "expected_anim_ids_present": list[str],   # subset of expected_anim_ids
        "expected_anim_ids_missing": list[str],
        "primitive_coverage": float,  # 0..1, fraction of expected ids wired
      }

    Used as a deterministic sub-signal alongside the motion judge: an agent
    that omitted every `@keyframes` rule and every `data-anim` attribute
    can't legitimately animate anything, regardless of what the VLM says.
    """
    html_path = agent_dir / page_name / "index.html"
    css_path = agent_dir / "_shared.css"
    sources = []
    if html_path.is_file():
        sources.append(html_path.read_text(errors="replace"))
    if css_path.is_file():
        sources.append(css_path.read_text(errors="replace"))
    combined = "\n".join(sources)

    has_primitives = any(
        re.search(p, combined, re.IGNORECASE) for p in _MOTION_PRIMITIVE_PATTERNS
    )
    present = [
        aid for aid in expected_anim_ids
        if re.search(rf'data-anim\s*=\s*"{re.escape(aid)}"', combined)
    ]
    missing = [aid for aid in expected_anim_ids if aid not in present]
    coverage = len(present) / len(expected_anim_ids) if expected_anim_ids else 1.0
    return {
        "has_keyframes_or_animation": has_primitives,
        "expected_anim_ids_present": present,
        "expected_anim_ids_missing": missing,
        "primitive_coverage": coverage,
    }


JUDGE_CRITERIA: list[dict[str, Any]] = [
    {
        "id": "visual_hierarchy",
        "scoring": "likert_5",
        "question": (
            "Compare the visual hierarchy of the agent's rendering against "
            "the reference design. Are the right elements drawing the eye "
            "first? Is the body type recessive enough relative to the "
            "headings? 5 = matches; 1 = hierarchy is broken or inverted."
        ),
    },
    {
        "id": "color_palette",
        "scoring": "likert_5",
        "question": (
            "How close is the agent's color palette (backgrounds, accents, "
            "text colors) to the reference's? 5 = on-brand and consistent; "
            "1 = wildly clashing or off-brand colors."
        ),
    },
    {
        "id": "typography",
        "scoring": "likert_5",
        "question": (
            "Do the typeface choices, sizes, and weights in the agent's "
            "rendering match the reference design? 5 = same typographic "
            "voice; 1 = jarring (e.g., Comic Sans on body text, absurd "
            "sizes, rotated headings)."
        ),
    },
    {
        "id": "layout_fidelity",
        "scoring": "likert_5",
        "question": (
            "How closely does the agent's layout — positions, spacing, "
            "alignment, density — track the reference design? 5 = the same "
            "page; 1 = collapsed, centered-everywhere, or otherwise "
            "structurally unlike the reference."
        ),
    },
    # `content_present` was removed in V3.1: text-content correctness is
    # already measured by V2.1's deterministic `text_content` aspect (with
    # its multiplicative gate). Having it in the judge double-counted text
    # and gave the adversarial tier a free 1.0 on one of six criteria —
    # see running_notes.md V3 results for the empirical motivation.
    {
        "id": "overall_fidelity",
        "scoring": "likert_5",
        "question": (
            "Overall: if both were shown side-by-side to a designer, would "
            "they accept the agent's rendering as a faithful replication "
            "of the reference? 5 = essentially indistinguishable; "
            "1 = unmistakably broken."
        ),
    },
]


def _encode_png_for_judge(path: Path, max_dim: int = JUDGE_IMAGE_MAX_DIM) -> str | None:
    """Read a PNG, downscale if longest side exceeds max_dim, return base64 string."""
    if not path.is_file():
        return None
    import base64
    import io
    img = Image.open(path).convert("RGB")
    longest = max(img.width, img.height)
    if longest > max_dim:
        scale = max_dim / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _build_judge_messages(
    ref_images: list[tuple[str, str]],
    agent_images: list[tuple[str, str]],
    *,
    criteria: list[dict[str, Any]] | None = None,
    motion: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    """Build (system_prompt, user content blocks) for one judge call.

    `ref_images` and `agent_images` are each a list of (viewport_label, base64_png).
    For static tasks each tuple's image is one full-page screenshot per viewport.
    For motion tasks each image is a 2x3 frame-grid composite — `motion=True`
    swaps in a system-prompt sentence telling the model how to read the grid.
    `criteria` defaults to JUDGE_CRITERIA (static) but can be overridden with
    MOTION_JUDGE_CRITERIA for tier-9 grading.
    """
    crits = criteria if criteria is not None else JUDGE_CRITERIA

    motion_preamble = (
        " Each image is a 2x3 grid of frames sampled at fixed timestamps "
        "burned into each tile's header; read left-to-right, top-to-bottom "
        "(frame 1 at t=0ms up to frame 6 at the animation window end). "
        "When judging motion you are comparing two grids of six frames each, "
        "not two single screenshots."
        if motion else ""
    )
    system = (
        "You are an expert visual design judge. You will be shown the "
        "REFERENCE design and the AGENT's rendering of the same web page, "
        f"possibly across multiple viewports.{motion_preamble} Score each "
        "criterion strictly but fairly based ONLY on what you can see; do "
        "not infer intent.\n\n"
        "Scoring scales:\n"
        "  - binary: 1 (yes / present / correct), 0 (no / absent / incorrect)\n"
        "  - likert_5: 1 (very poor) to 5 (excellent match)\n"
    )

    content: list[dict[str, Any]] = [
        {"type": "text", "text": "**REFERENCE design:**"},
    ]
    for label, b64 in ref_images:
        content.append({"type": "text", "text": f"_{label}_"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        })

    content.append({"type": "text", "text": "**AGENT's rendering (the page being graded):**"})
    for label, b64 in agent_images:
        content.append({"type": "text", "text": f"_{label}_"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        })

    criteria_text = "Score these criteria for the agent's rendering vs. the reference:\n\n"
    for c in crits:
        scale = "0/1" if c["scoring"] == "binary" else "1-5"
        criteria_text += f"  - **{c['id']}** ({c['scoring']}, {scale}): {c['question']}\n"
    criteria_text += (
        "\nCall the `submit_scores` tool with one entry per criterion. "
        "Use the exact criterion IDs above."
    )
    content.append({"type": "text", "text": criteria_text})

    return system, content


_JUDGE_TOOL_SCHEMA: dict[str, Any] = {
    "name": "submit_scores",
    "description": "Submit a score for every criterion on the checklist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "integer"},
                    },
                    "required": ["id", "score"],
                },
            },
        },
        "required": ["scores"],
    },
}


async def _judge_call_once(
    client: Any,
    ref_images: list[tuple[str, str]],
    agent_images: list[tuple[str, str]],
    *,
    criteria: list[dict[str, Any]] | None = None,
    motion: bool = False,
) -> dict[str, int]:
    """Make one judge API call. Returns {criterion_id: int score}; empty on failure."""
    system, content = _build_judge_messages(
        ref_images, agent_images, criteria=criteria, motion=motion,
    )
    response = await client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=JUDGE_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": content}],
        tools=[_JUDGE_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "submit_scores"},
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            raw = getattr(block, "input", {}) or {}
            return {
                entry["id"]: int(entry["score"])
                for entry in raw.get("scores", [])
                if "id" in entry and "score" in entry
            }
    return {}


def _aggregate_judge_answers(
    answers: list[dict[str, int]],
    *,
    criteria: list[dict[str, Any]] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Combine ensemble answers into one page-level score [0,1] + breakdown."""
    import statistics
    valid = [a for a in answers if a]
    if not valid:
        return 0.0, {"error": "all judge calls failed"}

    crits = criteria if criteria is not None else JUDGE_CRITERIA
    per_criterion: dict[str, dict[str, Any]] = {}
    normalized: list[float] = []
    for spec in crits:
        cid = spec["id"]
        raw = [a[cid] for a in valid if cid in a]
        if not raw:
            continue
        if spec["scoring"] == "binary":
            voted = 1 if sum(raw) > len(raw) / 2 else 0
            n = float(voted)
        else:
            med = statistics.median(raw)
            n = max(0.0, min(1.0, (med - 1.0) / 4.0))
        per_criterion[cid] = {"raw": raw, "aggregated": round(n, 4), "scoring": spec["scoring"]}
        normalized.append(n)

    overall = sum(normalized) / len(normalized) if normalized else 0.0
    return overall, {"per_criterion": per_criterion, "ensemble_size": len(valid)}


async def judge_page(
    client: Any,
    ref_images: list[tuple[str, str]],
    agent_images: list[tuple[str, str]],
    *,
    criteria: list[dict[str, Any]] | None = None,
    motion: bool = False,
) -> dict[str, Any]:
    """Run the ensemble for one page, return {score, per_criterion, ...}."""
    import asyncio
    if not ref_images or not agent_images:
        return {"score": 0.0, "error": "missing renders"}
    tasks = [
        _judge_call_once(client, ref_images, agent_images, criteria=criteria, motion=motion)
        for _ in range(JUDGE_ENSEMBLE_SIZE)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    answers: list[dict[str, int]] = []
    errors: list[str] = []
    for r in results:
        if isinstance(r, BaseException):
            errors.append(f"{type(r).__name__}: {r}")
        else:
            answers.append(r)
    score, breakdown = _aggregate_judge_answers(answers, criteria=criteria)
    if errors:
        breakdown["errors"] = errors
    return {"score": score, **breakdown}


async def run_judge_for_pages(
    page_renders: dict[str, dict[str, list[tuple[str, Path]]]],
    *,
    criteria: list[dict[str, Any]] | None = None,
    motion: bool = False,
) -> dict[str, dict[str, Any]]:
    """Run the judge concurrently across all pages.

    `page_renders[page_name]` is `{"ref": [(label, path), ...], "agent": [...]}`.
    For static tasks the paths point at full-page screenshots; for tier-9
    motion tasks they point at frame-grid PNGs and `motion=True` swaps the
    judge prompt and criteria accordingly.
    """
    import asyncio
    import anthropic
    encoded: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for name, renders in page_renders.items():
        ref_enc: list[tuple[str, str]] = []
        for label, path in renders.get("ref", []):
            b64 = _encode_png_for_judge(path)
            if b64 is not None:
                ref_enc.append((label, b64))
        agent_enc: list[tuple[str, str]] = []
        for label, path in renders.get("agent", []):
            b64 = _encode_png_for_judge(path)
            if b64 is not None:
                agent_enc.append((label, b64))
        encoded[name] = {"ref": ref_enc, "agent": agent_enc}

    out: dict[str, dict[str, Any]] = {}
    async with anthropic.AsyncAnthropic() as client:
        names = list(encoded.keys())
        tasks = [
            judge_page(
                client, encoded[n]["ref"], encoded[n]["agent"],
                criteria=criteria, motion=motion,
            )
            for n in names
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            out[name] = {"score": 0.0, "error": f"{type(result).__name__}: {result}"}
        else:
            out[name] = result
    return out


# === ORCHESTRATION (V2.1) ===

# Multiplicative text-content gate parameters. Text is a necessary condition
# for faithful replication — a page whose visible text is all lorem cannot be
# correct no matter how well its structure matches. The gate scales the
# post-renormalization score by `TEXT_GATE_FLOOR + (1 - TEXT_GATE_FLOOR) * text_score`,
# so text_score=1.0 → no penalty, text_score=0.0 → 30% of raw score retained.
TEXT_GATE_FLOOR = 0.30


def score_page(
    ref_png: Path, agent_png: Path,
    ref_dom: dict, agent_dom: dict,
) -> dict:
    ref_img = np.array(Image.open(ref_png).convert("RGB"))
    agent_img = np.array(Image.open(agent_png).convert("RGB"))
    if agent_img.shape != ref_img.shape:
        agent_pil = Image.open(agent_png).convert("RGB").resize(
            (ref_img.shape[1], ref_img.shape[0]), Image.LANCZOS
        )
        agent_img = np.array(agent_pil)

    aspects: dict[str, AspectResult] = {
        "pixel_ssim":       score_pixel_ssim(ref_img, agent_img),
        "color_histogram":  score_color_histogram(ref_img, agent_img),
        "region_color":     score_region_color(ref_img, agent_img),
        "palette":          score_palette(ref_img, agent_img),
        "headings":         score_headings(ref_dom, agent_dom),
        "paragraphs":       score_paragraphs(ref_dom, agent_dom),
        "navigation":       score_navigation(ref_dom, agent_dom),
        "repeating_groups": score_repeating_groups(ref_dom, agent_dom),
        "interactive":      score_interactive(ref_dom, agent_dom),
        "layout_skeleton":  score_layout_skeleton(ref_dom, agent_dom),
        "text_content":     score_text_content(ref_dom, agent_dom),
    }

    applied_weight = 0.0
    weighted_sum = 0.0
    aspect_report = {}
    for name, result in aspects.items():
        target = ASPECT_TARGET_WEIGHTS[name]
        effective = target * result.weight_multiplier
        applied_weight += effective
        if effective > 0:
            weighted_sum += effective * result.score
        aspect_report[name] = {
            "score": round(result.score, 4),
            "target_weight": target,
            "applied_weight": round(effective, 4),
            "skipped": result.weight_multiplier == 0,
            "details": result.details,
        }

    if applied_weight < 1e-6:
        pre_gate = 0.0
        coverage = 0.0
    else:
        pre_gate = weighted_sum / applied_weight
        coverage = applied_weight

    # V2.1 multiplicative text gate. Skipped pages (no text on either side) get
    # gate_factor=1.0 (no penalty). Pages where text_content was computed get
    # scaled by `floor + (1 - floor) * text_score`.
    text_aspect = aspects["text_content"]
    if text_aspect.weight_multiplier > 0:
        gate_factor = TEXT_GATE_FLOOR + (1.0 - TEXT_GATE_FLOOR) * text_aspect.score
    else:
        gate_factor = 1.0
    final = max(0.0, min(1.0, pre_gate * gate_factor))

    return {
        "final_score": final,
        "pre_gate_score": round(pre_gate, 4),
        "text_gate_factor": round(gate_factor, 4),
        "coverage": round(coverage, 4),
        "low_coverage": coverage < COVERAGE_FLAG_THRESHOLD,
        "aspects": aspect_report,
    }


def score_page_multi(
    viewport_results: list[tuple[str, Path, Path, dict, dict]],
) -> dict:
    """V4: run V2.1's score_page() once per viewport, average across.

    `viewport_results` is a list of `(viewport_label, ref_png, agent_png,
    ref_dom, agent_dom)` tuples — typically 3 entries (desktop / tablet /
    phone). Each entry is scored independently using the full V2.1 pipeline,
    then the per-aspect scores are averaged across viewports, the text gate
    is re-applied at the averaged level, and the final reward + per-viewport
    breakdown is returned.

    Why average per-aspect rather than averaging the final scores? Because
    different viewports might skip different aspects (e.g., `navigation`
    skips on phone if the hamburger menu hides the nav links). Averaging
    after renormalization means each viewport's contribution is weighted by
    its applied weight, which would mis-handle skips. Averaging
    *per-aspect* over only the viewports that ran that aspect lets each
    aspect contribute the right amount.
    """
    if not viewport_results:
        return {
            "final_score": 0.0,
            "pre_gate_score": 0.0,
            "text_gate_factor": 1.0,
            "coverage": 0.0,
            "low_coverage": True,
            "aspects": {},
            "per_viewport": {},
        }

    per_viewport: dict[str, dict] = {}
    for label, ref_png, agent_png, ref_dom, agent_dom in viewport_results:
        per_viewport[label] = score_page(ref_png, agent_png, ref_dom, agent_dom)

    # Average each aspect across viewports that actually ran it.
    aspect_avg: dict[str, dict] = {}
    for aspect_name in ASPECT_TARGET_WEIGHTS.keys():
        scores: list[float] = []
        applied_weights: list[float] = []
        skip_count = 0
        for vp_result in per_viewport.values():
            info = vp_result["aspects"].get(aspect_name, {})
            if info.get("skipped", False):
                skip_count += 1
                continue
            scores.append(info.get("score", 0.0))
            applied_weights.append(info.get("applied_weight", 0.0))
        n_viewports = len(per_viewport)
        if not scores:
            aspect_avg[aspect_name] = {
                "score": 1.0,
                "target_weight": ASPECT_TARGET_WEIGHTS[aspect_name],
                "applied_weight": 0.0,
                "skipped": True,
                "skipped_in_viewports": skip_count,
            }
        else:
            aspect_avg[aspect_name] = {
                "score": round(sum(scores) / len(scores), 4),
                "target_weight": ASPECT_TARGET_WEIGHTS[aspect_name],
                # Applied weight is averaged the same way: viewports where the
                # aspect skipped contribute 0; the rest contribute their
                # target weight. Divide by total viewport count.
                "applied_weight": round(sum(applied_weights) / n_viewports, 4),
                "skipped": False,
                "skipped_in_viewports": skip_count,
            }

    # Recompute the post-renormalization (pre-gate) score from averaged aspects.
    applied = sum(a["applied_weight"] for a in aspect_avg.values())
    if applied < 1e-6:
        pre_gate = 0.0
        coverage = 0.0
    else:
        weighted = sum(a["applied_weight"] * a["score"] for a in aspect_avg.values())
        pre_gate = weighted / applied
        coverage = applied

    # Apply the V2.1 text gate at the averaged level.
    text_avg = aspect_avg["text_content"]
    if not text_avg["skipped"]:
        gate_factor = TEXT_GATE_FLOOR + (1.0 - TEXT_GATE_FLOOR) * text_avg["score"]
    else:
        gate_factor = 1.0
    final = max(0.0, min(1.0, pre_gate * gate_factor))

    return {
        "final_score": final,
        "pre_gate_score": round(pre_gate, 4),
        "text_gate_factor": round(gate_factor, 4),
        "coverage": round(coverage, 4),
        "low_coverage": coverage < COVERAGE_FLAG_THRESHOLD,
        "aspects": aspect_avg,
        "per_viewport": per_viewport,
    }


# === COMPARISON IMAGE ===

def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_comparison(input_png: Path, agent_png: Path, out_path: Path,
                    page_name: str, score: float, low_coverage: bool) -> None:
    left = Image.open(input_png).convert("RGB")
    right = Image.open(agent_png).convert("RGB")
    h = min(left.height, right.height)
    if left.height != h:
        left = left.resize((int(left.width * h / left.height), h), Image.LANCZOS)
    if right.height != h:
        right = right.resize((int(right.width * h / right.height), h), Image.LANCZOS)

    pad, gap, header = 16, 20, 70
    W = left.width + right.width + gap + 2 * pad
    H = h + header + pad
    canvas = Image.new("RGB", (W, H), "white")
    canvas.paste(left, (pad, header))
    canvas.paste(right, (pad + left.width + gap, header))

    draw = ImageDraw.Draw(canvas)
    flag = "  [low coverage]" if low_coverage else ""
    draw.text((pad, 12), f"{page_name.upper()}  ·  score = {score:.3f}{flag}",
              fill="#1a2332", font=_font(22))
    draw.text((pad, 44), "INPUT (what the agent saw)", fill="#666666", font=_font(18))
    draw.text((pad + left.width + gap, 44), "AGENT OUTPUT (rendered from HTML)",
              fill="#666666", font=_font(18))
    canvas.save(out_path)


# === MAIN ===

def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    COMPARISONS_DIR.mkdir(parents=True, exist_ok=True)

    pages = sorted(
        p.name for p in REFERENCE_HTML_DIR.iterdir()
        if p.is_dir() and (p / "index.html").exists()
    )
    if not pages:
        print(f"No reference pages found under {REFERENCE_HTML_DIR}", file=sys.stderr)
        REWARD_PATH.write_text("0.0\n")
        return

    motion_spec = _load_motion_spec()
    is_motion_task = bool(motion_spec)
    if is_motion_task:
        if _motion_capture is None:
            raise RuntimeError(
                "tier-9 task declared expected_animations but the motion-"
                "capture helper at /opt/_motion_capture.py is missing or "
                "failed to import. Check the Dockerfile."
            )
        print(
            f"Scoring {len(pages)} page(s) with MOTION branch: {pages}  "
            f"(animations on {len(motion_spec)} page(s))"
        )
    else:
        print(f"Scoring {len(pages)} page(s): {pages}")

    per_page: dict[str, dict] = {}
    # Pages that rendered successfully — eligible for the judge dimension.
    # For static tasks each tuple is one full-page screenshot per viewport;
    # for motion tasks it's a frame-grid PNG per viewport.
    judge_inputs: dict[str, dict[str, list[tuple[str, Path]]]] = {}

    def _render_one(browser, html_path: Path, out_png: Path, viewport: dict[str, int]):
        """Open html_path at the given viewport, screenshot full_page, return DOM dict.

        For motion tasks we capture under prefers-reduced-motion so the DOM
        snapshot and full-page screenshot reflect the settled state, matching
        the make.py-baked reference baseline (which also uses reduced-motion).
        """
        ctx = browser.new_context(
            viewport=viewport,
            reduced_motion="reduce" if is_motion_task else "no-preference",
        )
        pg = ctx.new_page()
        try:
            pg.goto(f"file://{html_path.resolve()}", wait_until="load")
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(out_png), full_page=True)
            dom = extract_dom_info(pg)
        finally:
            ctx.close()
        return dom

    def _render_motion(browser, html_path: Path, viewport: dict[str, int],
                       viewport_label: str, page_name: str, role: str) -> Path:
        """Capture a motion frame grid for the agent or reference side.

        `role` is "ref" or "agent" — used only to disambiguate output paths.
        Frame window comes from the seed-side motion sidecar so ref and agent
        get sampled at the same offsets.
        """
        page_motion = motion_spec.get(page_name) or {}
        window_ms = int(page_motion.get("frame_window_ms", 1200))
        out_path = RENDERS_DIR / f"{page_name}.{viewport_label}.{role}.motion.png"
        _motion_capture.capture_motion_grid(  # type: ignore[union-attr]
            browser, html_path, viewport, frame_window_ms=window_ms, out_path=out_path,
        )
        return out_path

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for page_name in pages:
                ref_html = REFERENCE_HTML_DIR / page_name / "index.html"
                agent_html = AGENT_DIR / page_name / "index.html"

                if not agent_html.exists():
                    print(f"[{page_name}] MISSING agent output at {agent_html}")
                    per_page[page_name] = {"final_score": 0.0, "note": "missing agent output"}
                    # Comparison artifact uses desktop ref if available
                    desktop_ref_png = INPUT_PNG_DIR / "desktop" / f"{page_name}.png"
                    comparison_png = COMPARISONS_DIR / f"{page_name}.desktop.png"
                    if desktop_ref_png.exists():
                        shutil.copy(desktop_ref_png, comparison_png)
                    continue

                # Render ref + agent at every viewport, extract DOM per viewport.
                viewport_renders: list[tuple[str, Path, Path, dict, dict]] = []
                judge_ref_paths: list[tuple[str, Path]] = []
                judge_agent_paths: list[tuple[str, Path]] = []
                render_failed = False

                for label, viewport in VIEWPORTS:
                    ref_render = RENDERS_DIR / f"{page_name}.{label}.ref.png"
                    agent_render = RENDERS_DIR / f"{page_name}.{label}.agent.png"

                    try:
                        ref_dom = _render_one(browser, ref_html, ref_render, viewport)
                    except Exception as e:
                        print(f"[{page_name}/{label}] reference render error: {e}")
                        per_page[page_name] = {
                            "final_score": 0.0,
                            "note": f"ref render error ({label}): {e}",
                        }
                        render_failed = True
                        break

                    try:
                        agent_dom = _render_one(browser, agent_html, agent_render, viewport)
                    except Exception as e:
                        print(f"[{page_name}/{label}] agent render error: {e}")
                        per_page[page_name] = {
                            "final_score": 0.0,
                            "note": f"agent render error ({label}): {e}",
                        }
                        render_failed = True
                        break

                    viewport_renders.append((label, ref_render, agent_render, ref_dom, agent_dom))

                    if is_motion_task and page_name in motion_spec:
                        # Tier-9: ref grid was baked into /app/references at
                        # build time; render the agent grid here so both grids
                        # were composed by the same code path with the same
                        # power-curve schedule. The grids — not the static
                        # screenshots — go to the judge.
                        ref_grid = INPUT_PNG_DIR / label / f"{page_name}.motion.png"
                        try:
                            agent_grid = _render_motion(
                                browser, agent_html, viewport, label, page_name, "agent",
                            )
                        except Exception as e:
                            print(f"[{page_name}/{label}] agent motion-capture error: {e}")
                            per_page[page_name] = {
                                "final_score": 0.0,
                                "note": f"agent motion capture error ({label}): {e}",
                            }
                            render_failed = True
                            break
                        if not ref_grid.is_file():
                            print(f"[{page_name}/{label}] missing reference motion grid at {ref_grid}")
                            per_page[page_name] = {
                                "final_score": 0.0,
                                "note": f"missing ref motion grid ({label})",
                            }
                            render_failed = True
                            break
                        judge_ref_paths.append((label, ref_grid))
                        judge_agent_paths.append((label, agent_grid))
                    else:
                        judge_ref_paths.append((label, ref_render))
                        judge_agent_paths.append((label, agent_render))

                if render_failed:
                    continue

                if is_motion_task:
                    # V2.1 deterministic aspects (pixel SSIM, palette histogram,
                    # DOM extraction on a single frame) all degrade to noise on
                    # animated pages — the reduced-motion settled frame can
                    # match perfectly while the actual animation is broken, or
                    # vice versa. Skip the deterministic block entirely and let
                    # the motion judge carry the per-page score.
                    per_page[page_name] = {
                        "final_score": 0.0,  # filled in after the judge runs
                        "deterministic_skipped": True,
                    }
                else:
                    result = score_page_multi(viewport_renders)
                    per_page[page_name] = result

                judge_inputs[page_name] = {
                    "ref": judge_ref_paths,
                    "agent": judge_agent_paths,
                }

                if is_motion_task:
                    print(f"\n[{page_name}] motion-capture grids ready for judge "
                          f"(deterministic V2.1 skipped — see motion_judge below).")
                else:
                    print(f"\n[{page_name}] V2.1 deterministic (avg across {len(VIEWPORTS)} viewports): "
                          f"{result['final_score']:.4f}  (coverage: {result['coverage']:.2f}"
                          f"{', low' if result['low_coverage'] else ''})")
                    for aname, info in result["aspects"].items():
                        skipped = (
                            "skipped" if info["skipped"]
                            else f"applied {info['applied_weight']:.3f}"
                        )
                        print(f"  {aname:18s} = {info['score']:.4f}  ({skipped})")

                # Comparison artifact: one PNG per viewport. Source side uses
                # the rendered reference (we no longer always have a pre-built
                # input PNG at the same viewport). For motion tasks the side-
                # by-side comparison stitches the reduced-motion baselines so
                # the operator still gets a quick visual diff; the motion
                # grids live separately at <renders>/<page>.<vp>.{ref,agent}.motion.png.
                comparison_score = (
                    0.0 if is_motion_task else result["final_score"]
                )
                comparison_low_coverage = (
                    False if is_motion_task else result["low_coverage"]
                )
                for label, ref_render, agent_render, _rd, _ad in viewport_renders:
                    comparison_png = COMPARISONS_DIR / f"{page_name}.{label}.png"
                    try:
                        make_comparison(
                            ref_render, agent_render, comparison_png,
                            page_name=f"{page_name} · {label}",
                            score=comparison_score,
                            low_coverage=comparison_low_coverage,
                        )
                    except Exception as e:
                        print(f"[{page_name}/{label}] comparison build failed: {e}")
        finally:
            browser.close()

    # --- V3: multimodal judge dimension (required — no fallback) ---
    # The judge is the dominant signal (0.70 weight). Silently degrading to
    # V2.1-only when the API is unreachable would produce a smaller-but-
    # still-plausible reward number that hides a serious infra failure and
    # makes scores incomparable across runs. We fail loudly instead.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "V3 grader requires ANTHROPIC_API_KEY in the environment for the "
            "multimodal-LLM judge dimension. The container needs to forward "
            "this env var. No fallback to V2.1-only — fix the key plumbing."
        )
    if not judge_inputs:
        raise RuntimeError(
            "V3 grader requires at least one page to have rendered successfully "
            "for the judge to run, but no pages produced renders. Check the "
            "Playwright errors above."
        )

    judge_mode = "MOTION" if is_motion_task else "static"
    judge_criteria = MOTION_JUDGE_CRITERIA if is_motion_task else JUDGE_CRITERIA
    print(f"\nRunning {judge_mode} judge ({JUDGE_MODEL}, "
          f"ensemble={JUDGE_ENSEMBLE_SIZE}) across {len(judge_inputs)} page(s)...")
    judge_results = asyncio.run(
        run_judge_for_pages(
            judge_inputs, criteria=judge_criteria, motion=is_motion_task,
        )
    )
    for name, info in judge_results.items():
        print(f"  [{name}] judge={info.get('score', 0.0):.4f}"
              + (f"  err: {info['error']}" if "error" in info else ""))

    # Any per-page error from the judge is a hard failure too. We refuse to
    # combine a partial judge result with the deterministic side because the
    # resulting reward would silently weight some pages differently than
    # others.
    judge_errors = {n: info["error"] for n, info in judge_results.items() if "error" in info}
    if judge_errors:
        raise RuntimeError(
            f"V3 judge errored on {len(judge_errors)} of {len(judge_results)} "
            f"page(s): {judge_errors}. Refusing to combine partial judge "
            "results. Fix the underlying API failure and re-run."
        )

    # --- Combine deterministic + judge into per-page final scores ---
    for page_name in pages:
        page = per_page.get(page_name)
        if page is None:
            continue
        judge_info = judge_results.get(page_name)
        if judge_info is None:
            # Page never rendered — keep its zero / missing-output state.
            continue
        judge_score = float(judge_info.get("score", 0.0))
        if is_motion_task:
            # Motion-task scoring layers:
            #   1. Pre-flight pixel-diff on the agent's frame grid. If the
            #      grid is essentially static, the agent did not animate at
            #      all — short-circuit motion_presence to 0 regardless of
            #      what the judge said. If the grid shows clear motion, the
            #      judge cannot legitimately rate motion_presence below
            #      "subtle but visible" (likert 3) — apply a floor.
            #   2. Agent-source motion-primitive scan. An agent missing all
            #      `@keyframes`/`animation:` declarations or all expected
            #      `data-anim` ids cannot legitimately animate the right
            #      elements — apply a multiplicative penalty.
            # The judge's other criteria (target_element, motion_character,
            # settled_state, etc.) are passed through; only motion_presence
            # gets clamped by pre-flight evidence.
            page_motion = motion_spec.get(page_name) or {}
            expected_ids = [a["id"] for a in page_motion.get("animations", [])]
            scan = scan_agent_motion_primitives(AGENT_DIR, page_name, expected_ids)

            # Average pre-flight motion across viewports so a single noisy
            # viewport doesn't flip the floor.
            preflights = [
                measure_grid_motion(p)
                for _label, p in judge_inputs[page_name]["agent"]
            ]
            avg_changed = (
                sum(pf["max_changed_fraction"] for pf in preflights) / len(preflights)
                if preflights else 0.0
            )

            adjusted_judge = judge_score
            breakdown = {k: v for k, v in judge_info.items() if k != "score"}
            per_crit = breakdown.get("per_criterion", {}) if isinstance(breakdown, dict) else {}

            # Auto-credit motion_presence when pixel evidence disagrees with
            # the judge. Never auto-fail: if the judge says motion is present,
            # trust it even when pixel change is small (a tight rotating
            # ring legitimately scores ~0.7% pixel change).
            mp = per_crit.get("motion_presence")
            if mp is not None and "aggregated" in mp:
                original = mp["aggregated"]
                if original < 0.5 and avg_changed > MOTION_PIXEL_CHANGE_CREDIT_THRESHOLD:
                    mp["aggregated"] = 0.5
                    mp["clamped_by_preflight"] = (
                        f"pixel_diff_{avg_changed:.4f}_lifts_motion_presence_to_0.5"
                    )
                    # Recompute the page's mean across criteria.
                    normalized = [
                        v["aggregated"] for v in per_crit.values() if "aggregated" in v
                    ]
                    if normalized:
                        adjusted_judge = sum(normalized) / len(normalized)

            # Apply the agent-source coverage penalty multiplicatively. An
            # agent that wired 0/3 data-anim ids and has no @keyframes can't
            # score above 30% of the judge's reading, regardless of grids.
            coverage = scan["primitive_coverage"]
            has_prims = scan["has_keyframes_or_animation"]
            if not has_prims:
                source_factor = 0.3
            elif coverage < 1.0:
                source_factor = 0.5 + 0.5 * coverage
            else:
                source_factor = 1.0
            final = max(0.0, min(1.0, adjusted_judge * source_factor))

            page["judge_score"] = round(judge_score, 4)
            page["motion_judge_score_adjusted"] = round(adjusted_judge, 4)
            page["motion_preflight"] = {
                "avg_changed_fraction": round(avg_changed, 4),
                "per_viewport": preflights,
            }
            page["motion_source_scan"] = scan
            page["motion_source_factor"] = round(source_factor, 4)
            page["judge_breakdown"] = breakdown
            page["final_score"] = final
            continue
        det_score = page.get("final_score", 0.0)
        combined = V3_DETERMINISTIC_WEIGHT * det_score + V3_JUDGE_WEIGHT * judge_score
        page["deterministic_score"] = round(det_score, 4)
        page["judge_score"] = round(judge_score, 4)
        page["judge_breakdown"] = {k: v for k, v in judge_info.items() if k != "score"}
        page["final_score"] = max(0.0, min(1.0, combined))

    final_scores = [s.get("final_score", 0.0) for s in per_page.values()]
    final = float(np.mean(final_scores)) if final_scores else 0.0
    final = max(0.0, min(1.0, final))

    REWARD_PATH.write_text(f"{final:.6f}\n")
    DETAILS_PATH.write_text(json.dumps({
        "final_reward": final,
        "viewports": [
            {"label": label, "width": vp["width"], "height": vp["height"]}
            for label, vp in VIEWPORTS
        ],
        "v3_weights": {
            "deterministic": V3_DETERMINISTIC_WEIGHT,
            "judge": V3_JUDGE_WEIGHT,
        },
        "aspect_target_weights": ASPECT_TARGET_WEIGHTS,
        "coverage_flag_threshold": COVERAGE_FLAG_THRESHOLD,
        "judge_model": JUDGE_MODEL,
        "judge_ensemble_size": JUDGE_ENSEMBLE_SIZE,
        "judge_image_max_dim": JUDGE_IMAGE_MAX_DIM,
        "judge_criteria": [c["id"] for c in JUDGE_CRITERIA],
        "per_page": per_page,
    }, indent=2, default=str))
    print(f"\nFinal reward: {final:.6f}  (written to {REWARD_PATH})")


if __name__ == "__main__":
    main()
