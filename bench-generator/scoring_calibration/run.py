#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Run the bench-generator grader template against calibration variants and report
tier separation.

For each (task, variant) the runner builds a transient workspace that mimics the
Harbor container layout, invokes `bench-generator/templates/tests/score.py` via
`_score_wrapper.py` (a subprocess that overrides hard-coded paths from env vars
without modifying score.py), and collects the reward.

Output:
  - bench-generator/scoring_calibration/results/<grader_version>.json
  - tabular summary printed to stdout
  - tier separation verdict against fixed targets (from small_checks/docs/GRADING.md):
        near_perfect >= 0.85, mediocre 0.40-0.65, bad 0.10-0.30, no inversions

Usage:
    uv run python bench-generator/scoring_calibration/run.py --grader-version v1
    uv run python bench-generator/scoring_calibration/run.py --grader-version v2 --tasks synth-t1-burnt-sage-kitchen-9322
    uv run python bench-generator/scoring_calibration/run.py --grader-version v3 --oracle-only
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
WRAPPER_PY = HERE / "_score_wrapper.py"
VERSIONS_DIR = HERE / "grader_versions"
DEGRADED_ROOT = HERE / "degraded"
RESULTS_ROOT = HERE / "results"


def resolve_score_py(version: str) -> Path:
    """Return the snapshotted score.py for `version`, or exit if missing."""
    candidate = VERSIONS_DIR / version / "score.py"
    if not candidate.exists():
        print(
            f"ERROR: no snapshot at {candidate}.\n"
            f"Snapshot the current template first:\n"
            f"    uv run bench-generator/scoring_calibration/snapshot.py {version}",
            file=sys.stderr,
        )
        sys.exit(1)
    return candidate

TIER_TARGETS = {
    "near_perfect": (0.85, 1.01),
    "mediocre": (0.40, 0.65),
    "bad": (0.10, 0.30),
}


def run_one(
    task_id: str, variant: str, ref_pages: Path, agent_pages: Path, score_py: Path
) -> dict:
    """Set up a transient workspace, run the wrapper, return parsed score details."""
    with tempfile.TemporaryDirectory(prefix=f"cal-{task_id}-{variant}-") as tmp_str:
        tmp = Path(tmp_str)
        ref_dir = tmp / "reference-pages"
        agent_dir = tmp / "agent-output"
        log_dir = tmp / "logs"
        input_png_dir = tmp / "input-pngs"  # left empty; score.py handles missing pngs

        shutil.copytree(ref_pages, ref_dir)
        shutil.copytree(agent_pages, agent_dir)
        log_dir.mkdir(parents=True)
        input_png_dir.mkdir(parents=True)

        env = {
            "CAL_SCORE_PY": str(score_py),
            "CAL_REF_DIR": str(ref_dir),
            "CAL_AGENT_DIR": str(agent_dir),
            "CAL_LOG_DIR": str(log_dir),
            "CAL_INPUT_PNG_DIR": str(input_png_dir),
            "PATH": __import__("os").environ.get("PATH", ""),
            "HOME": __import__("os").environ.get("HOME", ""),
        }
        # forward ANTHROPIC_API_KEY when present (needed for V3 judge)
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY")
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key

        try:
            proc = subprocess.run(
                ["uv", "run", str(WRAPPER_PY)],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return {"reward": 0.0, "error": "timeout"}

        if proc.returncode != 0:
            return {
                "reward": 0.0,
                "error": f"score exited {proc.returncode}",
                "stderr": proc.stderr[-2000:],
                "stdout": proc.stdout[-2000:],
            }

        reward_file = log_dir / "reward.txt"
        details_file = log_dir / "score_details.json"
        if not reward_file.exists():
            return {"reward": 0.0, "error": "no reward.txt produced", "stdout": proc.stdout[-2000:]}

        reward = float(reward_file.read_text().strip())
        details = json.loads(details_file.read_text()) if details_file.exists() else {}
        return {"reward": reward, "details": details}


def discover_tasks(filter_ids: list[str] | None) -> list[tuple[str, Path]]:
    """List (task_id, near_perfect_dir) for every task that has all 3 variants."""
    tasks: list[tuple[str, Path]] = []
    if not DEGRADED_ROOT.exists():
        return tasks
    for task_dir in sorted(DEGRADED_ROOT.iterdir()):
        if not task_dir.is_dir():
            continue
        if filter_ids and task_dir.name not in filter_ids:
            continue
        if all((task_dir / v).is_dir() for v in ("near_perfect", "mediocre", "bad")):
            tasks.append((task_dir.name, task_dir))
    return tasks


def find_reference_pages(task_id: str) -> Path | None:
    """Locate the original reference-pages dir for a task across dataset versions."""
    for dataset in ("website-bench_v1", "website-bench_v0"):
        candidate = REPO / "bench-generator" / dataset / task_id / "environment" / "reference-pages"
        if candidate.exists():
            return candidate
    return None


def aggregate_table(results: dict) -> dict:
    """Compute per-variant mean/stdev and inversion count from per-task rewards."""
    summary = {}
    for variant in ("near_perfect", "mediocre", "bad"):
        values = [
            t[variant]["reward"]
            for t in results.values()
            if variant in t and "reward" in t[variant]
        ]
        summary[variant] = {
            "mean": statistics.mean(values) if values else 0.0,
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "n": len(values),
        }

    # Inversions: per-task pair (near_perfect > mediocre > bad) must hold.
    inversions = 0
    for task_id, variants in results.items():
        np_ = variants.get("near_perfect", {}).get("reward", 0.0)
        md_ = variants.get("mediocre", {}).get("reward", 0.0)
        bd_ = variants.get("bad", {}).get("reward", 0.0)
        if not (np_ > md_):
            inversions += 1
        if not (md_ > bd_):
            inversions += 1
    summary["inversions"] = inversions
    return summary


def print_report(grader_version: str, results: dict, summary: dict) -> None:
    print()
    print(f"=== Calibration report ({grader_version}) ===")
    print()
    print(f"{'task':<48} {'near_perfect':>14} {'mediocre':>11} {'bad':>9}")
    print("-" * 84)
    for task_id, variants in sorted(results.items()):
        np_ = variants.get("near_perfect", {}).get("reward", float("nan"))
        md_ = variants.get("mediocre", {}).get("reward", float("nan"))
        bd_ = variants.get("bad", {}).get("reward", float("nan"))
        print(f"{task_id:<48} {np_:>14.3f} {md_:>11.3f} {bd_:>9.3f}")

    print("-" * 84)
    for variant in ("near_perfect", "mediocre", "bad"):
        s = summary[variant]
        lo, hi = TIER_TARGETS[variant]
        hit = "HIT " if (lo <= s["mean"] <= hi) else "MISS"
        print(
            f"  {variant:<14} mean={s['mean']:.3f}  stdev={s['stdev']:.3f}  "
            f"n={s['n']:<2}  target=[{lo:.2f}, {hi:.2f}]  {hit}"
        )
    print(f"  inversions: {summary['inversions']} (target: 0)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grader-version",
        required=True,
        help="Tag for this run (v1, v2, v3...) — used as the results filename",
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        help="Restrict to a subset of task ids (default: all under degraded/)",
    )
    parser.add_argument(
        "--oracle-only",
        action="store_true",
        help="Only run the near_perfect tier (cheap ceiling check)",
    )
    args = parser.parse_args()

    score_py = resolve_score_py(args.grader_version)
    print(f"grader: {score_py.relative_to(REPO)}")

    tasks = discover_tasks(args.tasks)
    if not tasks:
        print("ERROR: no calibration tasks found under degraded/", file=sys.stderr)
        print(
            "Generate variants first: uv run python bench-generator/scoring_calibration/degrade.py "
            "--task bench-generator/website-bench_v1/<id> --out bench-generator/scoring_calibration/degraded/",
            file=sys.stderr,
        )
        sys.exit(1)

    variants = ("near_perfect",) if args.oracle_only else ("near_perfect", "mediocre", "bad")
    results: dict[str, dict[str, dict]] = {}
    for task_id, task_dir in tasks:
        ref_pages = find_reference_pages(task_id)
        if ref_pages is None:
            print(f"WARN: cannot locate reference-pages for {task_id}; skipping", file=sys.stderr)
            continue
        print(f"=== {task_id} ===")
        results[task_id] = {}
        for variant in variants:
            print(f"  [{variant}] running...")
            result = run_one(task_id, variant, ref_pages, task_dir / variant, score_py)
            results[task_id][variant] = result
            tag = f"reward={result['reward']:.3f}"
            if "error" in result:
                tag += f"  ERROR: {result['error']}"
            print(f"  [{variant}] {tag}")

    summary = aggregate_table(results) if not args.oracle_only else None
    if summary:
        print_report(args.grader_version, results, summary)

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_ROOT / f"{args.grader_version}.json"
    out_path.write_text(
        json.dumps({"grader_version": args.grader_version, "results": results, "summary": summary}, indent=2)
    )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
