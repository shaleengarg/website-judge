#!/usr/bin/env python3
"""
Check whether every task directory in a dataset matches the current templates/.

Tasks copy the templates/ tree verbatim at generation time, so any change to
templates/{environment/Dockerfile,environment/make.py,tests/score.py,...} is
silently NOT applied to already-on-disk tasks. This script reads each task's
template_version.txt (stamped by generate_dataset.py via compute_template_hash)
and compares it against the current templates/ hash. Stale tasks are listed.

Usage:
    python scripts/check_freshness.py <dataset_dir>
    python scripts/check_freshness.py <dataset_dir> --templates ./templates

Exit code:
    0 — every task is fresh
    1 — at least one task is stale, or some task is missing its stamp
    2 — usage/IO error

To fix stale tasks, run scripts/upgrade_tasks.py on the dataset.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import the hash helper from the generator so the algorithm stays in
# lockstep — if compute_template_hash changes shape, both sides update
# together.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_dataset import compute_template_hash  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("dataset_dir", type=Path,
                        help="Directory containing generated task subdirs.")
    parser.add_argument("--templates", type=Path,
                        default=Path(__file__).resolve().parent.parent / "templates",
                        help="Path to templates/ to compare against "
                             "(default: ../templates next to this script).")
    args = parser.parse_args()

    if not args.dataset_dir.is_dir():
        print(f"ERROR: {args.dataset_dir} is not a directory", file=sys.stderr)
        return 2
    if not args.templates.is_dir():
        print(f"ERROR: {args.templates} is not a directory", file=sys.stderr)
        return 2

    current_hash = compute_template_hash(args.templates)
    print(f"current templates hash: {current_hash[:12]}...")
    print(f"scanning {args.dataset_dir}")
    print()

    fresh: list[str] = []
    stale: list[tuple[str, str]] = []  # (task, observed_hash)
    missing: list[str] = []

    task_dirs = sorted(
        d for d in args.dataset_dir.iterdir()
        if d.is_dir() and (d / "task.toml").exists()
    )
    if not task_dirs:
        print(f"no task directories under {args.dataset_dir}", file=sys.stderr)
        return 2

    for task_dir in task_dirs:
        stamp_path = task_dir / "template_version.txt"
        if not stamp_path.exists():
            missing.append(task_dir.name)
            continue
        observed = stamp_path.read_text(encoding="utf-8").strip()
        if observed == current_hash:
            fresh.append(task_dir.name)
        else:
            stale.append((task_dir.name, observed))

    total = len(task_dirs)
    print(f"  fresh:   {len(fresh)}/{total}")
    print(f"  stale:   {len(stale)}/{total}")
    print(f"  missing: {len(missing)}/{total}  (no template_version.txt)")
    print()

    if stale:
        print("STALE tasks (different stamp than current templates/):")
        for name, observed in stale:
            print(f"  - {name}  (stamp: {observed[:12]}...)")
        print()
    if missing:
        print("MISSING-STAMP tasks (pre-stamp generation, treat as stale):")
        for name in missing:
            print(f"  - {name}")
        print()

    if stale or missing:
        print("Run scripts/upgrade_tasks.py on the dataset to re-apply templates.")
        return 1
    print("All tasks fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
