#!/usr/bin/env python3
"""
Refresh stale tasks by re-applying the current templates/ — without burning
any LLM tokens.

A task is stale when its `template_version.txt` doesn't match the current
hash of templates/. This happens whenever any file under templates/ is
edited (Dockerfile, make.py, score.py, task.toml.tpl, etc.) and the task
directories were generated against the prior version. This script:

  1. Reads each task's seed.json sidecar (must exist).
  2. Wipes and re-copies templates/solution/ and templates/tests/.
  3. Overwrites templates/environment/Dockerfile and templates/environment/make.py.
  4. Re-renders task.toml and instruction.md from the current .tpl files
     using the seed.json data.
  5. Re-stamps template_version.txt with the current hash.

It does NOT touch:
  - environment/reference-pages/ (the LLM-generated HTML — preserved verbatim)
  - seed.json (the originating spec — preserved verbatim)

Usage:
    python scripts/upgrade_tasks.py <dataset_dir>
    python scripts/upgrade_tasks.py <dataset_dir> --only-stale  # skip fresh tasks
    python scripts/upgrade_tasks.py <dataset_dir> --templates ./templates

Exit code:
    0 — every task upgraded (or already fresh)
    1 — at least one task failed to upgrade
    2 — usage/IO error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_dataset import apply_templates_to_task, compute_template_hash  # noqa: E402


def _load_seed(task_dir: Path) -> dict | None:
    """Return the seed.json contents, or None if missing/unreadable."""
    sidecar = task_dir / "seed.json"
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ERROR reading {sidecar}: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("--templates", type=Path,
                        default=Path(__file__).resolve().parent.parent / "templates",
                        help="Path to templates/ (default: ../templates).")
    parser.add_argument("--only-stale", action="store_true",
                        help="Skip tasks whose template_version.txt already matches.")
    args = parser.parse_args()

    if not args.dataset_dir.is_dir():
        print(f"ERROR: {args.dataset_dir} is not a directory", file=sys.stderr)
        return 2
    if not args.templates.is_dir():
        print(f"ERROR: {args.templates} is not a directory", file=sys.stderr)
        return 2

    current_hash = compute_template_hash(args.templates)
    print(f"target template hash: {current_hash[:12]}...")
    print(f"upgrading tasks under: {args.dataset_dir}")
    print()

    task_dirs = sorted(
        d for d in args.dataset_dir.iterdir()
        if d.is_dir() and (d / "task.toml").exists()
    )
    if not task_dirs:
        print(f"no task directories under {args.dataset_dir}", file=sys.stderr)
        return 2

    n_upgraded = 0
    n_skipped_fresh = 0
    n_skipped_no_seed = 0
    n_failed = 0

    for task_dir in task_dirs:
        stamp_path = task_dir / "template_version.txt"
        observed = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.exists() else None

        if args.only_stale and observed == current_hash:
            print(f"  fresh  {task_dir.name}")
            n_skipped_fresh += 1
            continue

        seed = _load_seed(task_dir)
        if seed is None:
            print(f"  SKIP   {task_dir.name}  (no readable seed.json — can't re-render task.toml)")
            n_skipped_no_seed += 1
            continue

        page_names = list(seed.get("pages") or seed.get("page_specs", {}).keys())
        if not page_names:
            print(f"  SKIP   {task_dir.name}  (seed.json has no pages list)")
            n_skipped_no_seed += 1
            continue

        try:
            apply_templates_to_task(seed, page_names, args.templates, task_dir)
            label = "UPGRADED" if observed != current_hash else "re-stamped"
            print(f"  {label}  {task_dir.name}")
            n_upgraded += 1
        except Exception as e:
            print(f"  FAILED {task_dir.name}: {type(e).__name__}: {e}", file=sys.stderr)
            n_failed += 1

    print()
    print(f"upgraded:       {n_upgraded}")
    print(f"skipped fresh:  {n_skipped_fresh}")
    print(f"skipped no-seed:{n_skipped_no_seed}")
    print(f"failed:         {n_failed}")

    return 1 if n_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
