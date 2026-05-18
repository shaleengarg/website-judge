#!/bin/bash
# Verifier entry point.
set -euo pipefail

mkdir -p /logs/verifier

# Preserve the agent's raw HTML output so it ends up in the trial artifacts
# at <trial>/verifier/agent-output/<page>/index.html. Done BEFORE scoring so
# it survives even if score.py crashes.
mkdir -p /logs/verifier/agent-output
cp -r /app/output/. /logs/verifier/agent-output/ 2>/dev/null || true

if python /tests/score.py 2>&1 | tee /logs/verifier/score.log; then
    echo "Scoring completed."
else
    echo "Scoring failed; writing reward 0.0" >&2
    echo "0.0" > /logs/verifier/reward.txt
fi
