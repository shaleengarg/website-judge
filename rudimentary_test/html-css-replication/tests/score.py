"""
Enhanced verifier that scores HTML/CSS fidelity across multiple UI aspects.

Aspects scored:
  1. pixel_ssim          – structural similarity (grayscale)
  2. color_histogram     – palette match via histogram intersection
  3. layout_structure    – card count, card positions, heading/subtitle positions
  4. navigation          – nav existence, link count, link text, position
  5. typography          – font sizes, weights, price text
  6. color_scheme        – body bg, heading color, button/border colors
  7. cards_borders       – border radius, width, badge, card sizing
  8. buttons             – text, position, bg color, border radius
  9. checkmarks_icons    – icon/SVG counts per card
 10. text_content        – heading, subtitle, plan names, feature lists
 11. spacing_padding     – card padding, inter-card gaps, button offsets

reward = weighted sum of all aspects

Writes:
  /logs/verifier/reward.txt              single float in [0, 1]
  /logs/verifier/score_details.json      per-page breakdown
  /logs/verifier/comparisons/<page>.png  side-by-side comparison
  /logs/verifier/renders/<page>.agent.png
  /logs/verifier/renders/<page>.ref.png
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright, Page, Browser
from skimage.metrics import structural_similarity as ssim

# ========================== CONFIGURATION ==========================

REFERENCE_HTML_DIR = Path("/opt/reference-pages")
INPUT_PNG_DIR = Path("/app/references")
AGENT_DIR = Path("/app/output")

LOG_DIR = Path("/logs/verifier")
REWARD_PATH = LOG_DIR / "reward.txt"
DETAILS_PATH = LOG_DIR / "score_details.json"
RENDERS_DIR = LOG_DIR / "renders"
COMPARISONS_DIR = LOG_DIR / "comparisons"

VIEWPORT = {"width": 1280, "height": 800}

# Aspect weights – must sum to 1.0
ASPECT_WEIGHTS = {
    "pixel_ssim":           0.20,
    "color_histogram":      0.10,
    "layout_structure":     0.15,
    "navigation":           0.08,
    "typography":           0.10,
    "color_scheme":         0.07,
    "cards_borders":        0.10,
    "buttons":              0.07,
    "checkmarks_icons":     0.03,
    "text_content":         0.05,
    "spacing_padding":      0.05,
}
assert abs(sum(ASPECT_WEIGHTS.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"


# ========================== RENDERING ==========================

def render_and_close(html_path: Path, out_png: Path, browser: Browser) -> None:
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    page.goto(f"file://{html_path.resolve()}", wait_until="load")
    page.wait_for_timeout(500)
    page.screenshot(path=str(out_png), full_page=False)
    context.close()


# ========================== PIXEL-LEVEL SCORING ==========================

def compute_ssim(ref: np.ndarray, agent: np.ndarray) -> float:
    ref_gray = np.asarray(Image.fromarray(ref).convert("L"))
    agent_gray = np.asarray(Image.fromarray(agent).convert("L"))
    val = float(ssim(ref_gray, agent_gray, data_range=255))
    return max(0.0, val)


def color_histogram_intersection(a: np.ndarray, b: np.ndarray) -> float:
    score = 0.0
    for c in range(3):
        ha, _ = np.histogram(a[:, :, c], bins=32, range=(0, 256))
        hb, _ = np.histogram(b[:, :, c], bins=32, range=(0, 256))
        ha = ha / (ha.sum() + 1e-9)
        hb = hb / (hb.sum() + 1e-9)
        score += float(np.minimum(ha, hb).sum())
    return score / 3.0


# ========================== DOM EXTRACTION ==========================

def extract_dom_info(page: Page) -> dict[str, Any]:
    """
    Deterministic DOM extraction. Uses stable selectors and canonical ordering.
    Every heuristic is designed so that running it twice on the same page
    produces byte-identical JSON.
    """
    return page.evaluate(r"""
    () => {
        const result = {};

        function getRect(el) {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {
                x: Math.round(r.x * 100) / 100,
                y: Math.round(r.y * 100) / 100,
                width: Math.round(r.width * 100) / 100,
                height: Math.round(r.height * 100) / 100,
                bottom: Math.round(r.bottom * 100) / 100,
                right: Math.round(r.right * 100) / 100
            };
        }

        function getStyles(el) {
            if (!el) return {};
            const s = window.getComputedStyle(el);
            // Extract individual sides to avoid shorthand inconsistencies
            return {
                fontSize: s.getPropertyValue('font-size'),
                fontWeight: s.getPropertyValue('font-weight'),
                color: s.getPropertyValue('color'),
                backgroundColor: s.getPropertyValue('background-color'),
                borderTopColor: s.getPropertyValue('border-top-color'),
                borderTopWidth: s.getPropertyValue('border-top-width'),
                borderRadius: s.getPropertyValue('border-top-left-radius'),
                paddingTop: s.getPropertyValue('padding-top'),
                paddingRight: s.getPropertyValue('padding-right'),
                paddingBottom: s.getPropertyValue('padding-bottom'),
                paddingLeft: s.getPropertyValue('padding-left'),
                textAlign: s.getPropertyValue('text-align'),
            };
        }

        // --- Navigation ---
        const nav = document.querySelector('nav') ||
                    document.querySelector('header') ||
                    document.querySelector('[role="navigation"]');
        const navLinks = [];
        if (nav) {
            const seen = new Set();
            nav.querySelectorAll('a').forEach(el => {
                const text = el.textContent.trim();
                if (text && !seen.has(text)) {
                    seen.add(text);
                    navLinks.push({
                        text: text,
                        rect: getRect(el),
                        styles: getStyles(el),
                    });
                }
            });
        }
        result.navigation = {
            exists: !!nav,
            rect: getRect(nav),
            linkCount: navLinks.length,
            links: navLinks,
        };

        // --- Main heading ---
        const h1 = document.querySelector('h1');
        const h2 = document.querySelector('h2');
        const mainHeadingEl = h1 || h2;
        result.mainHeading = {
            text: mainHeadingEl ? mainHeadingEl.textContent.trim() : '',
            rect: getRect(mainHeadingEl),
            styles: getStyles(mainHeadingEl),
        };

        // --- Subtitle: first <p> sibling/near the heading with reasonable length ---
        let subtitleEl = null;
        if (mainHeadingEl) {
            let sibling = mainHeadingEl.nextElementSibling;
            for (let i = 0; i < 5 && sibling; i++) {
                const t = sibling.textContent.trim();
                if (sibling.tagName === 'P' && t.length > 10 && t.length < 300) {
                    subtitleEl = sibling;
                    break;
                }
                sibling = sibling.nextElementSibling;
            }
        }
        if (!subtitleEl) {
            // Fallback: first <p> on the page with reasonable length
            document.querySelectorAll('p').forEach(el => {
                if (!subtitleEl) {
                    const t = el.textContent.trim();
                    if (t.length > 10 && t.length < 300) subtitleEl = el;
                }
            });
        }
        result.subtitle = {
            text: subtitleEl ? subtitleEl.textContent.trim() : '',
            rect: getRect(subtitleEl),
            styles: getStyles(subtitleEl),
        };

        // --- Pricing Cards ---
        // Strategy: collect all elements, find those containing '$' with card-like
        // dimensions, pick the innermost non-overlapping set, sort left-to-right.
        const allEls = Array.from(document.querySelectorAll('*'));
        const candidates = [];

        for (const el of allEls) {
            // Only consider direct text content that has a '$'
            const hasPrice = Array.from(el.querySelectorAll('*')).some(child => {
                return /\$\d+/.test(child.textContent);
            }) || /\$\d+/.test(el.textContent);

            if (!hasPrice) continue;

            const rect = el.getBoundingClientRect();
            if (rect.width < 150 || rect.width > 600 || rect.height < 200 || rect.height > 1000) continue;
            if (rect.width === 0 || rect.height === 0) continue;

            candidates.push({ el, area: rect.width * rect.height });
        }

        // Sort by area ascending (innermost first)
        candidates.sort((a, b) => a.area - b.area);

        const pickedEls = [];
        for (const c of candidates) {
            // Skip if this element contains or is contained by an already-picked element
            let dominated = false;
            for (const picked of pickedEls) {
                if (picked.contains(c.el) || c.el.contains(picked)) {
                    dominated = true;
                    break;
                }
            }
            if (!dominated) {
                pickedEls.push(c.el);
            }
        }

        // Build card info, sorted by x position
        const cardInfos = pickedEls.map(card => {
            const cardRect = getRect(card);
            const cardStyles = getStyles(card);

            // Plan name: first heading inside the card
            const nameEl = card.querySelector('h1, h2, h3, h4, h5, h6') ||
                           card.querySelector('strong, b');
            const planName = nameEl ? nameEl.textContent.trim() : '';

            // Price text: find the element with $XX
            let priceText = '';
            const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const t = node.textContent.trim();
                if (/\$\d+/.test(t)) {
                    // Get the parent element's full text for context
                    priceText = node.parentElement.textContent.trim();
                    break;
                }
            }

            // Features: list items
            const features = [];
            const featureSeen = new Set();
            card.querySelectorAll('li').forEach(li => {
                const t = li.textContent.trim();
                if (t && t.length < 100 && !featureSeen.has(t)) {
                    featureSeen.add(t);
                    features.push(t);
                }
            });

            // CTA button
            const btn = card.querySelector('button, a[href]');
            let btnInfo = null;
            if (btn) {
                const btnText = btn.textContent.trim();
                // Only count it as a button if it looks like a CTA
                if (btnText.length > 0 && btnText.length < 50) {
                    btnInfo = {
                        text: btnText,
                        rect: getRect(btn),
                        styles: getStyles(btn),
                    };
                }
            }

            // Badge
            let badge = null;
            card.querySelectorAll('span, div, label, p').forEach(el => {
                const t = el.textContent.trim();
                if (t.length < 30 && /most|popular|loved|best|recommended/i.test(t)) {
                    if (!badge) {
                        badge = { text: t, rect: getRect(el), styles: getStyles(el) };
                    }
                }
            });

            // Checkmarks: count SVG elements inside the card that are likely icons
            let checkmarkCount = 0;
            card.querySelectorAll('svg').forEach(svg => {
                const rect = svg.getBoundingClientRect();
                // Only count small SVGs (icons), not large decorative ones
                if (rect.width > 0 && rect.width < 40 && rect.height > 0 && rect.height < 40) {
                    checkmarkCount++;
                }
            });

            return {
                rect: cardRect,
                styles: cardStyles,
                planName,
                priceText,
                features,
                button: btnInfo,
                badge,
                checkmarkCount,
            };
        });

        // Sort left to right by x position
        cardInfos.sort((a, b) => (a.rect ? a.rect.x : 0) - (b.rect ? b.rect.x : 0));
        result.cards = cardInfos;

        // --- Body styles ---
        result.bodyStyles = getStyles(document.body);

        return result;
    }
    """)


# ========================== SCORING HELPERS ==========================

def _parse_px(val: str | None) -> float:
    """Parse '16px' -> 16.0. Returns 0.0 on failure."""
    if not val:
        return 0.0
    m = re.search(r"([\d.]+)", str(val))
    return float(m.group(1)) if m else 0.0


def _parse_color_rgb(val: str | None) -> tuple[int, int, int] | None:
    """Parse 'rgb(r, g, b)' or 'rgba(r, g, b, a)' -> (r, g, b).
    Also handles multiple values like 'rgb(0,0,0) rgb(0,0,0)' by taking the first."""
    if not val:
        return None
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", str(val))
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Euclidean distance in RGB, normalized to [0, 1]. 0 = identical."""
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))
    return d / (255.0 * math.sqrt(3.0))


def _color_similarity(c1, c2) -> float:
    """1.0 = identical, 0.0 = very different. Linear decay, NOT amplified."""
    if c1 is None and c2 is None:
        return 1.0
    if c1 is None or c2 is None:
        return 0.0
    dist = _color_distance(c1, c2)
    # Linear from 1.0 (dist=0) to 0.0 (dist>=0.5)
    return max(0.0, 1.0 - dist * 2.0)


def _rect_iou(r1: dict | None, r2: dict | None) -> float:
    """Intersection-over-Union of two bounding boxes."""
    if not r1 or not r2:
        return 0.0
    x1 = max(r1["x"], r2["x"])
    y1 = max(r1["y"], r2["y"])
    x2 = min(r1["x"] + r1["width"], r2["x"] + r2["width"])
    y2 = min(r1["y"] + r1["height"], r2["y"] + r2["height"])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    a1 = r1["width"] * r1["height"]
    a2 = r2["width"] * r2["height"]
    union = a1 + a2 - inter
    if union < 1e-9:
        return 1.0  # both zero-area
    return inter / union


def _rect_position_similarity(r1: dict | None, r2: dict | None) -> float:
    """Position + size similarity. 1.0 when identical."""
    if r1 is None and r2 is None:
        return 1.0
    if r1 is None or r2 is None:
        return 0.0
    dx = abs(r1["x"] - r2["x"]) / max(VIEWPORT["width"], 1)
    dy = abs(r1["y"] - r2["y"]) / max(VIEWPORT["height"], 1)
    pos_score = max(0.0, 1.0 - (dx + dy) * 2.0)

    w1, w2 = r1["width"], r2["width"]
    h1, h2 = r1["height"], r2["height"]
    sw = min(w1, w2) / max(w1, w2) if max(w1, w2) > 0 else 1.0
    sh = min(h1, h2) / max(h1, h2) if max(h1, h2) > 0 else 1.0
    size_score = (sw + sh) / 2.0

    return 0.5 * pos_score + 0.5 * size_score


def _text_similarity(t1: str | None, t2: str | None) -> float:
    """Normalized text similarity. 1.0 = identical."""
    if not t1 and not t2:
        return 1.0
    if not t1 or not t2:
        return 0.0
    s1 = t1.strip()
    s2 = t2.strip()
    if s1 == s2:
        return 1.0
    # Case-insensitive exact
    if s1.lower() == s2.lower():
        return 1.0
    # Word-level Jaccard (case-insensitive)
    w1 = set(s1.lower().split())
    w2 = set(s2.lower().split())
    if not w1 and not w2:
        return 1.0
    if not w1 or not w2:
        return 0.0
    inter = w1 & w2
    union = w1 | w2
    return len(inter) / len(union)


def _font_size_similarity(s1: str | None, s2: str | None) -> float:
    """Compare two font-size strings like '32px'. Returns 1.0 when identical."""
    p1 = _parse_px(s1)
    p2 = _parse_px(s2)
    if p1 == 0 and p2 == 0:
        return 1.0
    if p1 == 0 or p2 == 0:
        return 0.0
    return min(p1, p2) / max(p1, p2)


# ========================== ASPECT SCORERS ==========================

def score_layout_structure(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    ref_count = len(ref_cards)
    agent_count = len(agent_cards)

    # Card count
    count_score = 1.0 if ref_count == agent_count else max(0.0, 1.0 - abs(ref_count - agent_count) * 0.3)
    scores.append(count_score)
    details["card_count"] = {"ref": ref_count, "agent": agent_count, "score": count_score}

    # Card positions (pairwise)
    n = min(ref_count, agent_count)
    card_pos_scores = []
    for i in range(n):
        iou = _rect_iou(ref_cards[i].get("rect"), agent_cards[i].get("rect"))
        pos_sim = _rect_position_similarity(ref_cards[i].get("rect"), agent_cards[i].get("rect"))
        card_pos_scores.append(0.5 * iou + 0.5 * pos_sim)
    if card_pos_scores:
        avg = sum(card_pos_scores) / len(card_pos_scores)
    else:
        avg = 1.0 if ref_count == 0 and agent_count == 0 else 0.0
    scores.append(avg)
    details["card_positions"] = {"per_card": card_pos_scores, "avg": avg}

    # Heading position
    h_score = _rect_position_similarity(
        ref.get("mainHeading", {}).get("rect"),
        agent.get("mainHeading", {}).get("rect")
    )
    scores.append(h_score)
    details["heading_position"] = h_score

    # Subtitle position
    s_score = _rect_position_similarity(
        ref.get("subtitle", {}).get("rect"),
        agent.get("subtitle", {}).get("rect")
    )
    scores.append(s_score)
    details["subtitle_position"] = s_score

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_navigation(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    ref_nav = ref.get("navigation", {})
    agent_nav = agent.get("navigation", {})

    # Existence
    exists_score = 1.0 if ref_nav.get("exists") == agent_nav.get("exists") else 0.0
    scores.append(exists_score)
    details["exists_match"] = exists_score

    # Link count
    ref_lc = ref_nav.get("linkCount", 0)
    agent_lc = agent_nav.get("linkCount", 0)
    lc_score = 1.0 if ref_lc == agent_lc else max(0.0, 1.0 - abs(ref_lc - agent_lc) * 0.2)
    scores.append(lc_score)
    details["link_count"] = {"ref": ref_lc, "agent": agent_lc, "score": lc_score}

    # Link text match
    ref_links = [l.get("text", "").strip() for l in ref_nav.get("links", [])]
    agent_links = [l.get("text", "").strip() for l in agent_nav.get("links", [])]
    if ref_links:
        matched = sum(1 for rl in ref_links if any(_text_similarity(rl, al) > 0.8 for al in agent_links))
        text_score = matched / len(ref_links)
    else:
        text_score = 1.0 if not agent_links else 0.0
    scores.append(text_score)
    details["link_text_match"] = text_score

    # Nav position
    ref_rect = ref_nav.get("rect")
    agent_rect = agent_nav.get("rect")
    pos_score = _rect_position_similarity(ref_rect, agent_rect)
    scores.append(pos_score)
    details["position"] = pos_score

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_typography(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    # Main heading font size
    ref_fs = ref.get("mainHeading", {}).get("styles", {}).get("fontSize")
    agent_fs = agent.get("mainHeading", {}).get("styles", {}).get("fontSize")
    fs_score = _font_size_similarity(ref_fs, agent_fs)
    scores.append(fs_score)
    details["heading_font_size"] = {"ref": ref_fs, "agent": agent_fs, "score": fs_score}

    # Heading font weight
    ref_fw = str(ref.get("mainHeading", {}).get("styles", {}).get("fontWeight", ""))
    agent_fw = str(agent.get("mainHeading", {}).get("styles", {}).get("fontWeight", ""))
    fw_score = 1.0 if ref_fw == agent_fw else 0.5
    scores.append(fw_score)
    details["heading_font_weight"] = {"ref": ref_fw, "agent": agent_fw, "score": fw_score}

    # Price text per card
    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))
    for i in range(n):
        pt_score = _text_similarity(ref_cards[i].get("priceText", ""), agent_cards[i].get("priceText", ""))
        scores.append(pt_score)
        details[f"card_{i}_price_text"] = {
            "ref": ref_cards[i].get("priceText"),
            "agent": agent_cards[i].get("priceText"),
            "score": pt_score,
        }

    # Subtitle font size
    ref_sub_fs = ref.get("subtitle", {}).get("styles", {}).get("fontSize")
    agent_sub_fs = agent.get("subtitle", {}).get("styles", {}).get("fontSize")
    sub_fs_score = _font_size_similarity(ref_sub_fs, agent_sub_fs)
    scores.append(sub_fs_score)
    details["subtitle_font_size"] = {"ref": ref_sub_fs, "agent": agent_sub_fs, "score": sub_fs_score}

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_color_scheme(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    # Body background
    ref_bg = _parse_color_rgb(ref.get("bodyStyles", {}).get("backgroundColor"))
    agent_bg = _parse_color_rgb(agent.get("bodyStyles", {}).get("backgroundColor"))
    bg_score = _color_similarity(ref_bg, agent_bg)
    scores.append(bg_score)
    details["body_background"] = {"ref": str(ref_bg), "agent": str(agent_bg), "score": bg_score}

    # Heading color
    ref_hc = _parse_color_rgb(ref.get("mainHeading", {}).get("styles", {}).get("color"))
    agent_hc = _parse_color_rgb(agent.get("mainHeading", {}).get("styles", {}).get("color"))
    hc_score = _color_similarity(ref_hc, agent_hc)
    scores.append(hc_score)
    details["heading_color"] = {"ref": str(ref_hc), "agent": str(agent_hc), "score": hc_score}

    # Button bg colors per card
    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))
    for i in range(n):
        ref_btn = ref_cards[i].get("button")
        agent_btn = agent_cards[i].get("button")
        if ref_btn and agent_btn:
            ref_btn_bg = _parse_color_rgb(ref_btn.get("styles", {}).get("backgroundColor"))
            agent_btn_bg = _parse_color_rgb(agent_btn.get("styles", {}).get("backgroundColor"))
            btn_score = _color_similarity(ref_btn_bg, agent_btn_bg)
            scores.append(btn_score)
            details[f"card_{i}_button_bg"] = {"ref": str(ref_btn_bg), "agent": str(agent_btn_bg), "score": btn_score}
        elif not ref_btn and not agent_btn:
            scores.append(1.0)
            details[f"card_{i}_button_bg"] = {"note": "both missing", "score": 1.0}

    # Card border colors (using borderTopColor which is always a single value)
    for i in range(n):
        ref_bc = _parse_color_rgb(ref_cards[i].get("styles", {}).get("borderTopColor"))
        agent_bc = _parse_color_rgb(agent_cards[i].get("styles", {}).get("borderTopColor"))
        bc_score = _color_similarity(ref_bc, agent_bc)
        scores.append(bc_score)
        details[f"card_{i}_border_color"] = {"ref": str(ref_bc), "agent": str(agent_bc), "score": bc_score}

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_cards_borders(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))

    for i in range(n):
        rc = ref_cards[i]
        ac = agent_cards[i]

        # Border radius (using borderRadius = border-top-left-radius, a single value)
        ref_br = _parse_px(rc.get("styles", {}).get("borderRadius"))
        agent_br = _parse_px(ac.get("styles", {}).get("borderRadius"))
        if ref_br > 0 or agent_br > 0:
            br_score = min(ref_br, agent_br) / max(ref_br, agent_br)
        else:
            br_score = 1.0
        scores.append(br_score)
        details[f"card_{i}_border_radius"] = {"ref": ref_br, "agent": agent_br, "score": br_score}

        # Border width (using borderTopWidth, a single value)
        ref_bw = _parse_px(rc.get("styles", {}).get("borderTopWidth"))
        agent_bw = _parse_px(ac.get("styles", {}).get("borderTopWidth"))
        bw_match = 1.0 if abs(ref_bw - agent_bw) < 0.5 else (0.5 if abs(ref_bw - agent_bw) < 2 else 0.0)
        scores.append(bw_match)
        details[f"card_{i}_border_width"] = {"ref": ref_bw, "agent": agent_bw, "score": bw_match}

        # Badge
        ref_badge = rc.get("badge")
        agent_badge = ac.get("badge")
        if ref_badge is not None:
            if agent_badge is not None:
                badge_score = _text_similarity(ref_badge.get("text", ""), agent_badge.get("text", ""))
            else:
                badge_score = 0.0
            scores.append(badge_score)
            details[f"card_{i}_badge"] = {"ref": True, "agent": agent_badge is not None, "score": badge_score}
        else:
            # No badge expected
            badge_score = 1.0 if agent_badge is None else 0.5
            scores.append(badge_score)
            details[f"card_{i}_badge"] = {"ref": False, "agent": agent_badge is not None, "score": badge_score}

        # Card size
        size_score = _rect_position_similarity(rc.get("rect"), ac.get("rect"))
        scores.append(size_score)
        details[f"card_{i}_size"] = size_score

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_buttons(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))

    for i in range(n):
        ref_btn = ref_cards[i].get("button")
        agent_btn = agent_cards[i].get("button")

        if ref_btn is not None and agent_btn is not None:
            # Text
            t_score = _text_similarity(ref_btn.get("text", ""), agent_btn.get("text", ""))
            scores.append(t_score)
            details[f"card_{i}_btn_text"] = {
                "ref": ref_btn.get("text"), "agent": agent_btn.get("text"), "score": t_score
            }

            # Position
            pos_score = _rect_position_similarity(ref_btn.get("rect"), agent_btn.get("rect"))
            scores.append(pos_score)
            details[f"card_{i}_btn_position"] = pos_score

            # Background color
            ref_bg = _parse_color_rgb(ref_btn.get("styles", {}).get("backgroundColor"))
            agent_bg = _parse_color_rgb(agent_btn.get("styles", {}).get("backgroundColor"))
            col_score = _color_similarity(ref_bg, agent_bg)
            scores.append(col_score)
            details[f"card_{i}_btn_bg_color"] = {"ref": str(ref_bg), "agent": str(agent_bg), "score": col_score}

            # Border radius
            ref_br = _parse_px(ref_btn.get("styles", {}).get("borderRadius"))
            agent_br = _parse_px(agent_btn.get("styles", {}).get("borderRadius"))
            if ref_br > 0 or agent_br > 0:
                br_score = min(ref_br, agent_br) / max(ref_br, agent_br)
            else:
                br_score = 1.0
            scores.append(br_score)
            details[f"card_{i}_btn_border_radius"] = {"ref": ref_br, "agent": agent_br, "score": br_score}

        elif ref_btn is None and agent_btn is None:
            scores.append(1.0)
            details[f"card_{i}_btn"] = {"note": "both absent", "score": 1.0}
        else:
            scores.append(0.0)
            details[f"card_{i}_btn_missing"] = {"ref": ref_btn is not None, "agent": agent_btn is not None}

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_checkmarks(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))

    for i in range(n):
        ref_cm = ref_cards[i].get("checkmarkCount", 0)
        agent_cm = agent_cards[i].get("checkmarkCount", 0)
        if ref_cm == 0 and agent_cm == 0:
            cm_score = 1.0
        elif ref_cm == 0 or agent_cm == 0:
            cm_score = 0.0
        else:
            cm_score = min(ref_cm, agent_cm) / max(ref_cm, agent_cm)
        scores.append(cm_score)
        details[f"card_{i}_checkmarks"] = {"ref": ref_cm, "agent": agent_cm, "score": cm_score}

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_text_content(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    # Main heading
    h_score = _text_similarity(
        ref.get("mainHeading", {}).get("text", ""),
        agent.get("mainHeading", {}).get("text", ""),
    )
    scores.append(h_score)
    details["heading_text"] = {
        "ref": ref.get("mainHeading", {}).get("text"),
        "agent": agent.get("mainHeading", {}).get("text"),
        "score": h_score,
    }

    # Subtitle
    s_score = _text_similarity(
        ref.get("subtitle", {}).get("text", ""),
        agent.get("subtitle", {}).get("text", ""),
    )
    scores.append(s_score)
    details["subtitle_text"] = {
        "ref": ref.get("subtitle", {}).get("text"),
        "agent": agent.get("subtitle", {}).get("text"),
        "score": s_score,
    }

    # Per-card: plan name + features
    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))

    for i in range(n):
        # Plan name
        pn_score = _text_similarity(ref_cards[i].get("planName", ""), agent_cards[i].get("planName", ""))
        scores.append(pn_score)
        details[f"card_{i}_plan_name"] = {
            "ref": ref_cards[i].get("planName"),
            "agent": agent_cards[i].get("planName"),
            "score": pn_score,
        }

        # Features
        ref_features = ref_cards[i].get("features", [])
        agent_features = agent_cards[i].get("features", [])
        if not ref_features and not agent_features:
            feat_score = 1.0
        elif not ref_features or not agent_features:
            feat_score = 0.0
        else:
            matched = 0
            for rf in ref_features:
                best = max((_text_similarity(rf, af) for af in agent_features), default=0.0)
                if best > 0.6:
                    matched += 1
            feat_score = matched / len(ref_features)
        scores.append(feat_score)
        details[f"card_{i}_features"] = {
            "ref_count": len(ref_features),
            "agent_count": len(agent_features),
            "score": feat_score,
        }

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


def score_spacing_padding(ref: dict, agent: dict) -> dict:
    scores = []
    details = {}

    ref_cards = ref.get("cards", [])
    agent_cards = agent.get("cards", [])
    n = min(len(ref_cards), len(agent_cards))

    # Card internal padding (paddingTop as representative single value)
    for i in range(n):
        ref_pad = _parse_px(ref_cards[i].get("styles", {}).get("paddingTop"))
        agent_pad = _parse_px(agent_cards[i].get("styles", {}).get("paddingTop"))
        if ref_pad > 0 or agent_pad > 0:
            pad_score = min(ref_pad, agent_pad) / max(ref_pad, agent_pad)
        else:
            pad_score = 1.0
        scores.append(pad_score)
        details[f"card_{i}_padding_top"] = {"ref": ref_pad, "agent": agent_pad, "score": pad_score}

    # Horizontal gap between adjacent cards
    if n >= 2:
        for i in range(n - 1):
            ref_gap = ((ref_cards[i + 1].get("rect") or {}).get("x", 0) -
                       (ref_cards[i].get("rect") or {}).get("x", 0) -
                       (ref_cards[i].get("rect") or {}).get("width", 0))
            agent_gap = ((agent_cards[i + 1].get("rect") or {}).get("x", 0) -
                         (agent_cards[i].get("rect") or {}).get("x", 0) -
                         (agent_cards[i].get("rect") or {}).get("width", 0))
            max_gap = max(abs(ref_gap), abs(agent_gap), 1.0)
            gap_score = max(0.0, 1.0 - abs(ref_gap - agent_gap) / max_gap)
            scores.append(gap_score)
            details[f"card_gap_{i}_{i+1}"] = {"ref": ref_gap, "agent": agent_gap, "score": gap_score}

    # Vertical: heading bottom to first card top
    ref_h_bottom = (ref.get("mainHeading", {}).get("rect") or {}).get("bottom", 0)
    agent_h_bottom = (agent.get("mainHeading", {}).get("rect") or {}).get("bottom", 0)
    if ref_cards and agent_cards:
        ref_vgap = (ref_cards[0].get("rect") or {}).get("y", 0) - ref_h_bottom
        agent_vgap = (agent_cards[0].get("rect") or {}).get("y", 0) - agent_h_bottom
        max_vgap = max(abs(ref_vgap), abs(agent_vgap), 1.0)
        vgap_score = max(0.0, 1.0 - abs(ref_vgap - agent_vgap) / max_vgap)
        scores.append(vgap_score)
        details["heading_to_cards_gap"] = {"ref": ref_vgap, "agent": agent_vgap, "score": vgap_score}

    # Button bottom offset within each card
    for i in range(n):
        ref_btn = ref_cards[i].get("button")
        agent_btn = agent_cards[i].get("button")
        ref_rect = ref_cards[i].get("rect")
        agent_rect = agent_cards[i].get("rect")
        if ref_btn and agent_btn and ref_rect and agent_rect and ref_btn.get("rect") and agent_btn.get("rect"):
            ref_offset = (ref_rect["y"] + ref_rect["height"]) - (ref_btn["rect"]["y"] + ref_btn["rect"]["height"])
            agent_offset = (agent_rect["y"] + agent_rect["height"]) - (agent_btn["rect"]["y"] + agent_btn["rect"]["height"])
            max_off = max(abs(ref_offset), abs(agent_offset), 1.0)
            off_score = max(0.0, 1.0 - abs(ref_offset - agent_offset) / max_off)
            scores.append(off_score)
            details[f"card_{i}_btn_bottom_offset"] = {"ref": ref_offset, "agent": agent_offset, "score": off_score}

    combined = sum(scores) / len(scores) if scores else 1.0
    return {"score": combined, "details": details}


# ========================== MASTER SCORER ==========================

def score_all_aspects(
    ref_png: Path, agent_png: Path,
    ref_dom: dict, agent_dom: dict,
) -> dict:
    # --- Pixel-level ---
    ref_img = np.array(Image.open(ref_png).convert("RGB"))
    agent_img = np.array(Image.open(agent_png).convert("RGB"))
    if agent_img.shape != ref_img.shape:
        agent_pil = Image.open(agent_png).convert("RGB").resize(
            (ref_img.shape[1], ref_img.shape[0]), Image.LANCZOS
        )
        agent_img = np.array(agent_pil)

    pixel_ssim = compute_ssim(ref_img, agent_img)
    color_hist = color_histogram_intersection(ref_img, agent_img)

    # --- DOM-level ---
    layout = score_layout_structure(ref_dom, agent_dom)
    navigation = score_navigation(ref_dom, agent_dom)
    typography = score_typography(ref_dom, agent_dom)
    color_scheme = score_color_scheme(ref_dom, agent_dom)
    cards_borders = score_cards_borders(ref_dom, agent_dom)
    buttons = score_buttons(ref_dom, agent_dom)
    checkmarks = score_checkmarks(ref_dom, agent_dom)
    text_content = score_text_content(ref_dom, agent_dom)
    spacing = score_spacing_padding(ref_dom, agent_dom)

    aspect_scores = {
        "pixel_ssim":       pixel_ssim,
        "color_histogram":  color_hist,
        "layout_structure": layout["score"],
        "navigation":       navigation["score"],
        "typography":       typography["score"],
        "color_scheme":     color_scheme["score"],
        "cards_borders":    cards_borders["score"],
        "buttons":          buttons["score"],
        "checkmarks_icons": checkmarks["score"],
        "text_content":     text_content["score"],
        "spacing_padding":  spacing["score"],
    }

    final = sum(ASPECT_WEIGHTS[k] * aspect_scores[k] for k in ASPECT_WEIGHTS)
    final = max(0.0, min(1.0, final))

    return {
        "final_score": final,
        "aspect_scores": aspect_scores,
        "aspect_details": {
            "layout_structure": layout["details"],
            "navigation": navigation["details"],
            "typography": typography["details"],
            "color_scheme": color_scheme["details"],
            "cards_borders": cards_borders["details"],
            "buttons": buttons["details"],
            "checkmarks_icons": checkmarks["details"],
            "text_content": text_content["details"],
            "spacing_padding": spacing["details"],
        },
    }


# ========================== COMPARISON IMAGE ==========================

def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_comparison(
    input_png: Path, agent_png: Path, out_path: Path,
    page_name: str, score: float,
) -> None:
    left = Image.open(input_png).convert("RGB")
    right = Image.open(agent_png).convert("RGB")

    h = min(left.height, right.height)
    if left.height != h:
        left = left.resize((int(left.width * h / left.height), h), Image.LANCZOS)
    if right.height != h:
        right = right.resize((int(right.width * h / right.height), h), Image.LANCZOS)

    pad = 16
    gap = 20
    header = 70
    W = left.width + right.width + gap + 2 * pad
    H = h + header + pad

    canvas = Image.new("RGB", (W, H), "white")
    canvas.paste(left, (pad, header))
    canvas.paste(right, (pad + left.width + gap, header))

    draw = ImageDraw.Draw(canvas)
    title_font = _font(22)
    label_font = _font(18)

    draw.text((pad, 12), f"{page_name.upper()}  ·  score = {score:.3f}",
              fill="#1a2332", font=title_font)
    draw.text((pad, 44), "INPUT (what the agent saw)", fill="#666666", font=label_font)
    draw.text((pad + left.width + gap, 44),
              "AGENT OUTPUT (rendered from HTML)", fill="#666666", font=label_font)

    canvas.save(out_path)


# ========================== MAIN ==========================

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

                # --- Render & extract reference ---
                try:
                    ref_ctx = browser.new_context(viewport=VIEWPORT)
                    ref_page = ref_ctx.new_page()
                    ref_page.goto(f"file://{ref_html.resolve()}", wait_until="load")
                    ref_page.wait_for_timeout(500)
                    ref_page.screenshot(path=str(ref_render), full_page=False)
                    ref_dom = extract_dom_info(ref_page)
                    ref_ctx.close()
                except Exception as e:
                    print(f"[{page_name}] reference render failed: {e}")
                    per_page[page_name] = {"final_score": 0.0, "note": f"ref render error: {e}"}
                    continue

                # --- Render & extract agent ---
                try:
                    agent_ctx = browser.new_context(viewport=VIEWPORT)
                    agent_page = agent_ctx.new_page()
                    agent_page.goto(f"file://{agent_html.resolve()}", wait_until="load")
                    agent_page.wait_for_timeout(500)
                    agent_page.screenshot(path=str(agent_render), full_page=False)
                    agent_dom = extract_dom_info(agent_page)
                    agent_ctx.close()
                except Exception as e:
                    print(f"[{page_name}] agent render failed: {e}")
                    per_page[page_name] = {"final_score": 0.0, "note": f"agent render error: {e}"}
                    continue

                # --- Score ---
                result = score_all_aspects(ref_render, agent_render, ref_dom, agent_dom)
                per_page[page_name] = result

                print(f"\n[{page_name}] Final: {result['final_score']:.4f}")
                for aspect, val in result["aspect_scores"].items():
                    w = ASPECT_WEIGHTS.get(aspect, 0)
                    print(f"  {aspect:25s} = {val:.4f}  (weight {w:.2f}, contribution {w*val:.4f})")

                # --- Comparison image ---
                comparison_src = input_png if input_png.exists() else ref_render
                try:
                    make_comparison(
                        comparison_src, agent_render, comparison_png,
                        page_name=page_name, score=result["final_score"],
                    )
                except Exception as e:
                    print(f"[{page_name}] comparison build failed: {e}")

        finally:
            browser.close()

    # --- Aggregate ---
    final_scores = [s.get("final_score", 0.0) for s in per_page.values()]
    final = float(np.mean(final_scores)) if final_scores else 0.0
    final = max(0.0, min(1.0, final))

    REWARD_PATH.write_text(f"{final:.6f}\n")
    DETAILS_PATH.write_text(
        json.dumps(
            {
                "final_reward": final,
                "viewport": VIEWPORT,
                "aspect_weights": ASPECT_WEIGHTS,
                "per_page": per_page,
            },
            indent=2,
        )
    )
    print(f"\nFinal reward: {final:.6f}  (written to {REWARD_PATH})")
    print(f"Comparisons: {COMPARISONS_DIR}")


if __name__ == "__main__":
    main()

