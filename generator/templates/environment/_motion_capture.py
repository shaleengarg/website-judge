"""
Motion-capture helper for tier-9 (animated) tasks.

Given a Playwright `Browser` and a path to a rendered HTML page, samples six
frames of the page at evenly-spaced offsets across the page's natural frame
window, stitches them into a labeled 2x3 grid PNG, and returns the output
path. Also captures a single `prefers-reduced-motion: reduce` baseline that
the static-screenshot path uses as the per-page `.png`.

Why a labeled grid (not a video)? The grading judge consumes images via the
Anthropic vision API, which doesn't natively accept video files. A single
labeled grid PNG sent as one `image/png` block preserves the existing 6-image
per-page judge budget exactly while giving the model enough temporal context
to grade motion presence, target element, character, and timing fidelity.

Why clock virtualization? `page.clock.install()` virtualizes the document
timeline that CSS animations are driven by. After `install + pause_at(0)`,
`fast_forward(delta_ms)` advances the timeline deterministically without any
real wall-clock sleeps. Without this, sampling six frames in quick succession
would race the animation and produce near-identical tiles.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


# Number of frames to capture per (page, viewport). Six gives the judge enough
# temporal context to read motion direction and character without bloating the
# grid past the JUDGE_IMAGE_MAX_DIM ceiling in score.py.
N_FRAMES = 6
GRID_ROWS = 2
GRID_COLS = 3
assert N_FRAMES == GRID_ROWS * GRID_COLS

# Floor for the sampling window. seeds.py + concept_gen.py enforce that every
# animation completes one full cycle (loop) or settle (entrance) within 5000ms,
# so the window almost always lands in [1000, 5500]ms. The floor exists so a
# page declaring only a single 300ms entrance still gets a 1.5s window — six
# frames inside 300ms would be useless.
MIN_FRAME_WINDOW_MS = 1500


def _font(size: int) -> ImageFont.ImageFont:
    """Return a font for tile timestamp labels — DejaVu in the Playwright image."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _frame_offsets(frame_window_ms: int) -> list[int]:
    """Six equidistant offsets across [0, max(window, MIN_FRAME_WINDOW_MS)].

    Both endpoints inclusive: frame 0 is the on-load state; frame N-1 is at
    the full window. Equidistant sampling is the right schedule because
    concept_gen.py + seeds.py cap every animation at 5000ms total cycle, so
    the window is always tight enough that linear samples spread across
    visible motion changes for both entrances and loops.
    """
    window = max(frame_window_ms, MIN_FRAME_WINDOW_MS)
    return [round(window * i / (N_FRAMES - 1)) for i in range(N_FRAMES)]


def _compose_grid(
    frames: list[tuple[int, bytes]],
    out_path: Path,
) -> None:
    """Stitch six (offset_ms, PNG bytes) frames into a 2x3 labeled grid."""
    import io

    if len(frames) != N_FRAMES:
        raise ValueError(f"expected {N_FRAMES} frames, got {len(frames)}")

    images = [Image.open(io.BytesIO(b)).convert("RGB") for _t, b in frames]
    tile_w = max(img.width for img in images)
    tile_h = max(img.height for img in images)
    # Normalize tile sizes so the grid is uniform even if a viewport produced
    # a slightly-different screenshot height (full_page=False keeps it stable
    # in practice, but defensively resize anything off-spec).
    images = [
        img if img.size == (tile_w, tile_h) else img.resize((tile_w, tile_h), Image.LANCZOS)
        for img in images
    ]

    gap = 6
    label_h = 28
    grid_w = GRID_COLS * tile_w + (GRID_COLS - 1) * gap
    grid_h = GRID_ROWS * (tile_h + label_h) + (GRID_ROWS - 1) * gap

    canvas = Image.new("RGB", (grid_w, grid_h), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(16)

    for i, ((offset_ms, _b), img) in enumerate(zip(frames, images)):
        row = i // GRID_COLS
        col = i % GRID_COLS
        x = col * (tile_w + gap)
        y = row * (tile_h + label_h + gap)
        # Label band at the top of each tile so the judge can read temporal
        # order without inferring it from layout.
        draw.rectangle([x, y, x + tile_w, y + label_h], fill="#0e1014")
        draw.text(
            (x + 8, y + 4),
            f"frame {i+1}/{N_FRAMES}  ·  t = {offset_ms}ms",
            fill="#f4f1ea",
            font=font,
        )
        canvas.paste(img, (x, y + label_h))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)


def capture_motion_grid(
    browser: Any,
    html_path: Path,
    viewport: dict[str, int],
    frame_window_ms: int,
    out_path: Path,
) -> list[int]:
    """Capture six frames of `html_path` at `viewport` and stitch a grid PNG.

    Returns the list of offsets (ms) used. `browser` is a Playwright Browser
    instance — synchronous API; the caller owns its lifecycle.
    """
    offsets = _frame_offsets(frame_window_ms)
    context = browser.new_context(viewport=viewport)
    # Install the fake clock BEFORE navigation. The clock starts paused at the
    # given time; CSS animations advance only when we call `fast_forward`.
    # Without this, the wall clock would tick during `goto` and the first
    # capture would land somewhere mid-animation depending on machine speed.
    context.clock.install(time=0)
    page = context.new_page()
    try:
        page.goto(f"file://{html_path.resolve()}", wait_until="load")

        frames: list[tuple[int, bytes]] = []
        last_offset = 0
        for offset_ms in offsets:
            delta = offset_ms - last_offset
            if delta > 0:
                context.clock.fast_forward(delta)
            last_offset = offset_ms
            # full_page=False: motion grids should stay viewport-sized so the
            # composed grid fits under JUDGE_IMAGE_MAX_DIM. Static aspects
            # already use full_page=True via the separate baseline screenshot.
            png_bytes = page.screenshot(full_page=False)
            frames.append((offset_ms, png_bytes))
    finally:
        context.close()

    _compose_grid(frames, out_path)
    return offsets


def capture_reduced_motion_static(
    browser: Any,
    html_path: Path,
    viewport: dict[str, int],
    out_path: Path,
) -> None:
    """Capture one static frame with `prefers-reduced-motion: reduce`.

    Tier-9 reference pages MUST define a reduced-motion media query that
    collapses every animation to its settled final state. This is what we
    use as the `<page>.png` baseline so static deterministic aspects (DOM
    structure, palette, text content) still have a meaningful single image
    to compare against.
    """
    context = browser.new_context(
        viewport=viewport,
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        page.goto(f"file://{html_path.resolve()}", wait_until="load")
        # Long enough for any forwards-fill entrance to settle even if the
        # reduced-motion query somehow missed an animation.
        page.wait_for_timeout(500)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_path), full_page=True)
    finally:
        context.close()
