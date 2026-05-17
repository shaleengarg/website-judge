#!/bin/bash
# Verifier entry point. Runs scoring and tees output to a log.
# score.py writes /logs/verifier/reward.txt (the value Harbor reads).
set -euo pipefail

mkdir -p /logs/verifier

# Always exit 0 — the reward file communicates success, not the exit code.
# If the scorer crashes, fall back to reward 0.0 so Harbor still records a result.
if python /tests/score.py 2>&1 | tee /logs/verifier/score.log; then
    echo "Scoring completed."
else
    echo "Scoring failed; writing reward 0.0" >&2
    echo "0.0" > /logs/verifier/reward.txt
fi
