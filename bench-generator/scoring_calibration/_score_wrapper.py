#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "playwright>=1.40",
#     "Pillow>=10",
#     "numpy>=1.24",
#     "scikit-image>=0.21",
#     "anthropic>=0.40",
# ]
# ///
"""
Subprocess wrapper that runs `bench-generator/templates/tests/score.py` against
a calibration workspace. Lets the runner exercise the *exact* template code path
without modifying score.py to know about calibration.

It imports score.py, overrides its hard-coded container paths from env vars, then
calls main(). The V1 template stays byte-identical to the version that ships in
generated Harbor tasks.

Env vars (all required, absolute paths):
    CAL_REF_DIR        -> overrides REFERENCE_HTML_DIR (default: /opt/reference-pages)
    CAL_INPUT_PNG_DIR  -> overrides INPUT_PNG_DIR      (default: /app/references)
    CAL_AGENT_DIR      -> overrides AGENT_DIR          (default: /app/output)
    CAL_LOG_DIR        -> overrides LOG_DIR            (default: /logs/verifier)
    CAL_SCORE_PY       -> absolute path to the score.py to invoke
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_score_module(score_py: Path):
    spec = importlib.util.spec_from_file_location("score", score_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load score module from {score_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["score"] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    score_py = Path(os.environ["CAL_SCORE_PY"])
    ref_dir = Path(os.environ["CAL_REF_DIR"])
    agent_dir = Path(os.environ["CAL_AGENT_DIR"])
    log_dir = Path(os.environ["CAL_LOG_DIR"])
    input_png_dir = Path(os.environ.get("CAL_INPUT_PNG_DIR", "/nonexistent"))

    score = _load_score_module(score_py)
    score.REFERENCE_HTML_DIR = ref_dir
    score.INPUT_PNG_DIR = input_png_dir
    score.AGENT_DIR = agent_dir
    score.LOG_DIR = log_dir
    score.REWARD_PATH = log_dir / "reward.txt"
    score.DETAILS_PATH = log_dir / "score_details.json"
    score.RENDERS_DIR = log_dir / "renders"
    score.COMPARISONS_DIR = log_dir / "comparisons"

    score.main()


if __name__ == "__main__":
    main()
