#!/usr/bin/env python3
"""
Build-time asset generator (V4 + motion).

Reads reference HTML from /opt/reference-pages/<page>/index.html and renders
each page at every viewport defined in VIEWPORTS, full-page, saving the PNGs
to /app/references/<viewport_label>/<page>.png.

When /opt/motion.json declares `expected_animations` for a page (tier-9 only),
ALSO produces a 2x3 frame-grid PNG at
/app/references/<viewport_label>/<page>.motion.png — six timestamped frames
sampled across the page's animation window via Playwright clock virtualization.
The static `<page>.png` for motion pages uses `prefers-reduced-motion: reduce`
so deterministic aspects still see a meaningful settled-state image.

Runs once during Docker build. After this the image has every reference
artifact baked in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# The motion-capture helper lives at /opt/ so both build-time (this script)
# and verifier-time (tests/score.py) can import it from the same source.
# make.py runs from /tmp/ during the Docker build, so /opt isn't on sys.path
# by default — splice it in before the import.
sys.path.insert(0, "/opt")

from playwright.sync_api import sync_playwright

import _motion_capture  # type: ignore[import-not-found]

REF_DIR = Path("/opt/reference-pages")
OUT_DIR = Path("/app/references")
MOTION_SIDECAR = Path("/opt/motion.json")

# MUST match VIEWPORTS in tests/score.py.
VIEWPORTS: list[tuple[str, dict[str, int]]] = [
    ("desktop", {"width": 1440, "height": 900}),
    ("tablet",  {"width": 768,  "height": 1024}),
    ("phone",   {"width": 390,  "height": 844}),
]


def _load_motion_spec() -> dict[str, dict]:
    """Return {page_name: {"animations": [...], "frame_window_ms": int}} or {}."""
    if not MOTION_SIDECAR.is_file():
        return {}
    try:
        blob = json.loads(MOTION_SIDECAR.read_text())
    except json.JSONDecodeError:
        return {}
    return blob.get("expected_animations") or {}


def _render_static(browser, html: Path, viewport: dict[str, int], out_path: Path) -> None:
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    try:
        page.goto(f"file://{html.resolve()}", wait_until="load")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_path), full_page=True)
    finally:
        context.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pages = sorted(p for p in REF_DIR.iterdir() if p.is_dir())
    if not pages:
        raise SystemExit(f"no reference-page directories found under {REF_DIR}")

    for label, _vp in VIEWPORTS:
        (OUT_DIR / label).mkdir(parents=True, exist_ok=True)

    motion_spec = _load_motion_spec()
    if motion_spec:
        print(f"motion sidecar: {len(motion_spec)} page(s) have expected_animations")

    with sync_playwright() as p:
        # --no-sandbox required because the build runs as root in Docker.
        # --disable-dev-shm-usage avoids the 64MB /dev/shm limit Docker imposes.
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for page_dir in pages:
                html = page_dir / "index.html"
                if not html.exists():
                    print(f"skip {page_dir.name}: no index.html")
                    continue
                page_motion = motion_spec.get(page_dir.name)

                for label, viewport in VIEWPORTS:
                    static_out = OUT_DIR / label / f"{page_dir.name}.png"
                    if page_motion:
                        # Tier-9: static baseline uses prefers-reduced-motion so
                        # text/palette/layout aspects see a settled snapshot,
                        # and a separate frame-grid PNG carries the motion signal.
                        _motion_capture.capture_reduced_motion_static(
                            browser, html, viewport, static_out,
                        )
                        motion_out = OUT_DIR / label / f"{page_dir.name}.motion.png"
                        offsets = _motion_capture.capture_motion_grid(
                            browser, html, viewport,
                            frame_window_ms=int(page_motion.get("frame_window_ms", 1200)),
                            out_path=motion_out,
                        )
                        print(
                            f"rendered {page_dir.name} @ {label} -> "
                            f"{static_out.name} + {motion_out.name} "
                            f"(frames at {offsets} ms)"
                        )
                    else:
                        _render_static(browser, html, viewport, static_out)
                        print(f"rendered {page_dir.name} @ {label} -> {static_out}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
