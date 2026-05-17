"""
Render the reference HTML and the agent's HTML at a fixed viewport, then compute
a perceptual similarity score per page. Also produces side-by-side comparison
PNGs (input screenshot vs agent's rendered output) so a human can eyeball how
the agent did.

reward = mean over pages of (0.7 * SSIM + 0.3 * color_histogram_intersection)

Writes:
  /logs/verifier/reward.txt              single float in [0, 1]
  /logs/verifier/score_details.json      per-page breakdown
  /logs/verifier/comparisons/<page>.png  side-by-side: input | agent output
  /logs/verifier/renders/<page>.agent.png   raw agent render
  /logs/verifier/renders/<page>.ref.png     raw reference render (verifier-side)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
from skimage.metrics import structural_similarity as ssim

REFERENCE_HTML_DIR = Path("/opt/reference-pages")  # baked into the image by environment/Dockerfile
INPUT_PNG_DIR = Path("/app/references")
AGENT_DIR = Path("/app/output")

LOG_DIR = Path("/logs/verifier")
REWARD_PATH = LOG_DIR / "reward.txt"
DETAILS_PATH = LOG_DIR / "score_details.json"
RENDERS_DIR = LOG_DIR / "renders"
COMPARISONS_DIR = LOG_DIR / "comparisons"

VIEWPORT = {"width": 1280, "height": 800}
SSIM_WEIGHT = 0.7
COLOR_WEIGHT = 0.3


# ---------- Rendering ----------

def render(html_path: Path, out_png: Path, browser) -> None:
    """Render an HTML file at the configured viewport and save a screenshot."""
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    page.goto(f"file://{html_path.resolve()}", wait_until="load")
    page.wait_for_timeout(500)  # let layout/fonts settle
    page.screenshot(path=str(out_png), full_page=False)
    context.close()


# ---------- Scoring ----------

def color_histogram_intersection(a: np.ndarray, b: np.ndarray) -> float:
    """Mean per-channel histogram intersection in [0, 1]. 1.0 = identical palette."""
    score = 0.0
    for c in range(3):
        ha, _ = np.histogram(a[:, :, c], bins=32, range=(0, 256))
        hb, _ = np.histogram(b[:, :, c], bins=32, range=(0, 256))
        ha = ha / (ha.sum() + 1e-9)
        hb = hb / (hb.sum() + 1e-9)
        score += float(np.minimum(ha, hb).sum())
    return score / 3.0


def score_pair(ref_png: Path, agent_png: Path) -> dict:
    ref = np.array(Image.open(ref_png).convert("RGB"))
    agent = np.array(Image.open(agent_png).convert("RGB"))

    if agent.shape != ref.shape:
        agent_pil = Image.open(agent_png).convert("RGB").resize(
            (ref.shape[1], ref.shape[0]), Image.LANCZOS
        )
        agent = np.array(agent_pil)

    ref_gray = np.asarray(Image.fromarray(ref).convert("L"))
    agent_gray = np.asarray(Image.fromarray(agent).convert("L"))
    structural = float(ssim(ref_gray, agent_gray, data_range=255))
    structural = max(0.0, structural)

    color = color_histogram_intersection(ref, agent)
    combined = max(0.0, min(1.0, SSIM_WEIGHT * structural + COLOR_WEIGHT * color))
    return {"ssim": structural, "color_histogram": color, "combined": combined}


# ---------- Comparison image ----------

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
    input_png: Path,
    agent_png: Path,
    out_path: Path,
    page_name: str,
    score: float,
) -> None:
    """Stack input screenshot and agent output side by side with labels."""
    left = Image.open(input_png).convert("RGB")
    right = Image.open(agent_png).convert("RGB")

    # Normalize heights
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
    draw.text((pad, 44),
              "INPUT (what the agent saw)",
              fill="#666666", font=label_font)
    draw.text((pad + left.width + gap, 44),
              "AGENT OUTPUT (rendered from HTML)",
              fill="#666666", font=label_font)

    canvas.save(out_path)


# ---------- Main ----------

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
        # --no-sandbox is required because the verifier runs as root in Docker.
        # --disable-dev-shm-usage avoids the 64MB /dev/shm limit Docker imposes.
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for page in pages:
                ref_html = REFERENCE_HTML_DIR / page / "index.html"
                agent_html = AGENT_DIR / page / "index.html"
                input_png = INPUT_PNG_DIR / f"{page}.png"

                ref_render = RENDERS_DIR / f"{page}.ref.png"
                agent_render = RENDERS_DIR / f"{page}.agent.png"
                comparison_png = COMPARISONS_DIR / f"{page}.png"

                if not agent_html.exists():
                    print(f"[{page}] MISSING agent output at {agent_html}")
                    per_page[page] = {"combined": 0.0, "note": "missing agent output"}
                    # Even on miss, show input alone so reviewer sees what was expected.
                    if input_png.exists():
                        shutil.copy(input_png, comparison_png)
                    continue

                # Render reference (verifier-side) for clean apples-to-apples SSIM.
                try:
                    render(ref_html, ref_render, browser)
                except Exception as e:
                    print(f"[{page}] reference render failed: {e}")
                    per_page[page] = {"combined": 0.0, "note": f"ref render error: {e}"}
                    continue

                # Render agent's HTML.
                try:
                    render(agent_html, agent_render, browser)
                except Exception as e:
                    print(f"[{page}] agent render failed: {e}")
                    per_page[page] = {"combined": 0.0, "note": f"agent render error: {e}"}
                    continue

                scores = score_pair(ref_render, agent_render)
                per_page[page] = scores
                print(
                    f"[{page}] ssim={scores['ssim']:.3f} "
                    f"color={scores['color_histogram']:.3f} "
                    f"combined={scores['combined']:.3f}"
                )

                # Comparison uses the *original input* PNG (what the agent saw)
                # on the left, and the agent's rendered output on the right.
                comparison_src = input_png if input_png.exists() else ref_render
                try:
                    make_comparison(
                        comparison_src, agent_render, comparison_png,
                        page_name=page, score=scores["combined"],
                    )
                except Exception as e:
                    print(f"[{page}] comparison build failed: {e}")

        finally:
            browser.close()

    combined_values = [s["combined"] for s in per_page.values()]
    final = float(np.mean(combined_values)) if combined_values else 0.0
    final = max(0.0, min(1.0, final))

    REWARD_PATH.write_text(f"{final:.6f}\n")
    DETAILS_PATH.write_text(
        json.dumps(
            {
                "final_reward": final,
                "viewport": VIEWPORT,
                "weights": {"ssim": SSIM_WEIGHT, "color": COLOR_WEIGHT},
                "per_page": per_page,
            },
            indent=2,
        )
    )
    print(f"\nFinal reward: {final:.6f}  (written to {REWARD_PATH})")
    print(f"Comparisons: {COMPARISONS_DIR}")


if __name__ == "__main__":
    main()
