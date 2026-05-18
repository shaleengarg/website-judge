#!/usr/bin/env python3
"""
Build-time asset generator.

Reads reference HTML from /opt/reference-pages/<page>/index.html and renders
each one with headless Chromium at the canonical viewport, saving the PNG to
/app/references/<page>.png.

Runs once during Docker build. After this the image has every reference
screenshot baked in.
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

REF_DIR = Path("/opt/reference-pages")
OUT_DIR = Path("/app/references")

# MUST match VIEWPORT in tests/score.py.
VIEWPORT = {"width": 1280, "height": 800}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pages = sorted(p for p in REF_DIR.iterdir() if p.is_dir())
    if not pages:
        raise SystemExit(f"no reference-page directories found under {REF_DIR}")

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
                context = browser.new_context(viewport=VIEWPORT)
                page = context.new_page()
                page.goto(f"file://{html.resolve()}", wait_until="load")
                page.wait_for_timeout(500)
                out_path = OUT_DIR / f"{page_dir.name}.png"
                page.screenshot(path=str(out_path), full_page=False)
                context.close()
                print(f"rendered {page_dir.name} -> {out_path}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
