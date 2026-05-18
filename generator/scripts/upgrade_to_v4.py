#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
One-shot in-place upgrade of generated benchmark tasks to V4.

For each `synth-*` task under the dataset roots passed on the CLI, this script:

  1. Overwrites `tests/score.py` with the current V4 template
     (`generator/templates/tests/score.py`).
  2. Overwrites `environment/make.py` with the current V4 template
     (`generator/templates/environment/make.py`).
  3. Re-renders `instruction.md` from the V4 template
     (`generator/templates/instruction.md.tpl`) using the task's
     existing reference-pages list. The {{INPUT_LIST}} expansion uses the
     new per-viewport layout (`/app/references/{viewport}/{page}.png`).

The task's actual reference HTML (`environment/reference-pages/*/index.html`)
is NOT touched — those are the ground truth for grading and stay frozen.
Dockerfiles aren't touched either (v2 / v2-1 already have `anthropic` in
their pip install line; verified before running).

Usage:
    uv run generator/scripts/upgrade_to_v4.py \\
        archive/old_bench/website-bench_v2 \\
        archive/old_bench/website-bench_v2-1
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = REPO / "generator" / "templates"
SCORE_PY_SRC = TEMPLATES_DIR / "tests" / "score.py"
MAKE_PY_SRC = TEMPLATES_DIR / "environment" / "make.py"
INSTRUCTION_TPL = TEMPLATES_DIR / "instruction.md.tpl"


def render_template(text: str, replacements: dict[str, str]) -> str:
    out = text
    for key, value in replacements.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def build_input_list(page_names: list[str]) -> str:
    """V4: per-viewport reference PNG paths grouped by viewport label."""
    viewport_labels = ("desktop", "tablet", "phone")
    return "\n".join(
        "\n".join(f"- `/app/references/{vp}/{name}.png`" for name in page_names)
        for vp in viewport_labels
    )


def build_output_list(page_names: list[str]) -> str:
    return "\n".join(f"- `/app/output/{name}/index.html`" for name in page_names)


def upgrade_task(task_dir: Path) -> None:
    name = task_dir.name
    refs = task_dir / "environment" / "reference-pages"
    if not refs.is_dir():
        print(f"  SKIP {name}: no environment/reference-pages dir")
        return

    page_names = sorted(
        p.name for p in refs.iterdir()
        if p.is_dir() and (p / "index.html").exists()
    )
    if not page_names:
        print(f"  SKIP {name}: no pages found under {refs}")
        return

    # 1. score.py
    dest_score = task_dir / "tests" / "score.py"
    dest_score.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCORE_PY_SRC, dest_score)

    # 2. make.py
    dest_make = task_dir / "environment" / "make.py"
    shutil.copy2(MAKE_PY_SRC, dest_make)

    # 3. instruction.md
    instruction = render_template(
        INSTRUCTION_TPL.read_text(),
        {
            "N_PAGES": str(len(page_names)),
            "INPUT_LIST": build_input_list(page_names),
            "OUTPUT_LIST": build_output_list(page_names),
        },
    )
    (task_dir / "instruction.md").write_text(instruction)

    print(f"  OK   {name}  ({len(page_names)} pages)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    roots = [REPO / arg if not Path(arg).is_absolute() else Path(arg) for arg in sys.argv[1:]]
    total = 0
    for root in roots:
        if not root.is_dir():
            print(f"WARN: {root} is not a directory; skipping", file=sys.stderr)
            continue
        print(f"=== {root.relative_to(REPO)} ===")
        tasks = sorted(
            p for p in root.iterdir() if p.is_dir() and p.name.startswith("synth-")
        )
        for task_dir in tasks:
            upgrade_task(task_dir)
            total += 1
    print(f"\nUpgraded {total} task(s) to V4.")
    print(f"  score.py   <- {SCORE_PY_SRC.relative_to(REPO)}")
    print(f"  make.py    <- {MAKE_PY_SRC.relative_to(REPO)}")
    print(f"  instruction.md re-rendered from {INSTRUCTION_TPL.relative_to(REPO)}")


if __name__ == "__main__":
    main()
