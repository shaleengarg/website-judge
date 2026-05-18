#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Snapshot the current grader template into a versioned directory.

After making changes to generator/templates/tests/score.py, run:

    uv run generator/scoring_calibration/snapshot.py v2

This copies the *current* templates/tests/score.py into

    generator/scoring_calibration/grader_versions/v2/score.py

so future calibration runs against `--grader-version v2` always execute the
exact bytes you snapshotted today — even if you keep editing the live template.

The runner refuses to run a grader version that hasn't been snapshotted, so the
calibration results filename and the code that produced it can never disagree.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_SCORE = HERE.parent / "templates" / "tests" / "score.py"
VERSIONS_DIR = HERE / "grader_versions"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Label for this snapshot (e.g. v1, v2, v3)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing snapshot at grader_versions/<version>/",
    )
    args = parser.parse_args()

    if not TEMPLATE_SCORE.exists():
        print(f"ERROR: template not found at {TEMPLATE_SCORE}", file=sys.stderr)
        sys.exit(1)

    dest_dir = VERSIONS_DIR / args.version
    dest = dest_dir / "score.py"
    if dest.exists() and not args.force:
        print(
            f"ERROR: snapshot already exists at {dest}. "
            f"Pass --force to overwrite, or pick a different version label.",
            file=sys.stderr,
        )
        sys.exit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE_SCORE, dest)
    size = dest.stat().st_size
    print(f"snapshotted {TEMPLATE_SCORE} -> {dest} ({size} bytes)")


if __name__ == "__main__":
    main()
