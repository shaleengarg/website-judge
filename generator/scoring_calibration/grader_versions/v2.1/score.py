"""
Grader V2.1 — schema-free multi-aspect scorer with text-content gating.

Evolution chain:
- V1 was SSIM (0.7) + RGB color histogram (0.3). V1 calibration showed it
  ranks `bad > mediocre` (the wrong way) — see running_notes.md V1 results.
- V2 added DOM extraction + 11 weighted aspects + adaptive renormalization.
  Fixed the inversion (`near_perfect > mediocre > bad` now holds) but `bad`
  still scored 0.39 (target ≤ 0.15) because navigation/repeating_groups/
  pixel_ssim all gave the bad variant generous credit for "structure-still-
  there" even when content was garbage.
- V2.1 makes three changes vs V2:
  1. Weight retune — pixel_ssim 0.18→0.08, repeating_groups 0.12→0.08,
     layout_skeleton 0.10→0.06, text_content 0.10→0.32. Discriminating
     signals (palette, region_color, text_content) get more weight;
     layout/pixel signals that survive structural degradation get less.
  2. Sub-aspect sharpening — score_navigation now weights link-text 70%
     (was 25%), score_repeating_groups weights item-text 55% (was 30%).
     Catches "nav region structurally exists but labels are 'Link 1/2/3'."
  3. Multiplicative text gate — after renormalization, multiply page score
     by `0.30 + 0.70 * text_content`. Text content is a necessary condition:
     a page with lorem-ipsum visible-text cannot be a faithful replication
     no matter how perfect its structure. Caps lorem-output reward at ~42%.

Three key design choices vs V1:

1. ADAPTIVE RENORMALIZATION. Each aspect returns (score, weight_multiplier).
   Aspects that have nothing to compare (e.g., nav on a single-page site)
   return weight_multiplier=0 and contribute nothing — the remaining aspects
   renormalize against actual applied weight. Non-applicable aspects do not
   give free 1.0s the way V1's two-metric average would have.

2. SCHEMA-FREE EXTRACTION. The donor JS pulls generic primitives — every
   heading, every paragraph, every link (with `inNav` flag), every
   structurally-repeating group (children sharing tag + size bucket), every
   button/input, layout skeleton. Works across the bench-generator's t1-t3
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

import difflib
import json
import math
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


# === CONFIGURATION ===

REFERENCE_HTML_DIR = Path("/opt/reference-pages")
INPUT_PNG_DIR = Path("/app/references")
AGENT_DIR = Path("/app/output")

LOG_DIR = Path("/logs/verifier")
REWARD_PATH = LOG_DIR / "reward.txt"
DETAILS_PATH = LOG_DIR / "score_details.json"
RENDERS_DIR = LOG_DIR / "renders"
COMPARISONS_DIR = LOG_DIR / "comparisons"

VIEWPORT = {"width": 1280, "height": 800}

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

    const VIEWPORT_W = 1280, VIEWPORT_H = 800;
    function isVisible(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (r.top >= VIEWPORT_H) return false;
        if (r.bottom <= 0) return false;
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

    print(f"Scoring {len(pages)} page(s): {pages}")
    per_page: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for page_name in pages:
                ref_html = REFERENCE_HTML_DIR / page_name / "index.html"
                agent_html = AGENT_DIR / page_name / "index.html"
                input_png = INPUT_PNG_DIR / f"{page_name}.png"

                ref_render = RENDERS_DIR / f"{page_name}.ref.png"
                agent_render = RENDERS_DIR / f"{page_name}.agent.png"
                comparison_png = COMPARISONS_DIR / f"{page_name}.png"

                if not agent_html.exists():
                    print(f"[{page_name}] MISSING agent output at {agent_html}")
                    per_page[page_name] = {"final_score": 0.0, "note": "missing agent output"}
                    if input_png.exists():
                        shutil.copy(input_png, comparison_png)
                    continue

                try:
                    ctx = browser.new_context(viewport=VIEWPORT)
                    pg = ctx.new_page()
                    pg.goto(f"file://{ref_html.resolve()}", wait_until="load")
                    pg.wait_for_timeout(500)
                    pg.screenshot(path=str(ref_render), full_page=False)
                    ref_dom = extract_dom_info(pg)
                    ctx.close()
                except Exception as e:
                    print(f"[{page_name}] reference error: {e}")
                    per_page[page_name] = {"final_score": 0.0, "note": f"ref error: {e}"}
                    continue

                try:
                    ctx = browser.new_context(viewport=VIEWPORT)
                    pg = ctx.new_page()
                    pg.goto(f"file://{agent_html.resolve()}", wait_until="load")
                    pg.wait_for_timeout(500)
                    pg.screenshot(path=str(agent_render), full_page=False)
                    agent_dom = extract_dom_info(pg)
                    ctx.close()
                except Exception as e:
                    print(f"[{page_name}] agent error: {e}")
                    per_page[page_name] = {"final_score": 0.0, "note": f"agent error: {e}"}
                    continue

                result = score_page(ref_render, agent_render, ref_dom, agent_dom)
                per_page[page_name] = result

                print(f"\n[{page_name}] Final: {result['final_score']:.4f}  "
                      f"(coverage: {result['coverage']:.2f}"
                      f"{', low' if result['low_coverage'] else ''})")
                for name, info in result["aspects"].items():
                    skipped = "skipped" if info["skipped"] else f"applied {info['applied_weight']:.3f}"
                    print(f"  {name:18s} = {info['score']:.4f}  ({skipped})")

                comparison_src = input_png if input_png.exists() else ref_render
                try:
                    make_comparison(comparison_src, agent_render, comparison_png,
                                    page_name=page_name, score=result["final_score"],
                                    low_coverage=result["low_coverage"])
                except Exception as e:
                    print(f"[{page_name}] comparison build failed: {e}")
        finally:
            browser.close()

    final_scores = [s.get("final_score", 0.0) for s in per_page.values()]
    final = float(np.mean(final_scores)) if final_scores else 0.0
    final = max(0.0, min(1.0, final))

    REWARD_PATH.write_text(f"{final:.6f}\n")
    DETAILS_PATH.write_text(json.dumps({
        "final_reward": final,
        "viewport": VIEWPORT,
        "aspect_target_weights": ASPECT_TARGET_WEIGHTS,
        "coverage_flag_threshold": COVERAGE_FLAG_THRESHOLD,
        "per_page": per_page,
    }, indent=2))
    print(f"\nFinal reward: {final:.6f}  (written to {REWARD_PATH})")


if __name__ == "__main__":
    main()
