#!/bin/bash
# Oracle solution: copies the reference HTML into the expected output path.
# Should produce reward 1.0.
set -euo pipefail

mkdir -p /app/output
cp -r /opt/reference-pages/* /app/output/

echo "Oracle: wrote $(find /app/output -name 'index.html' | wc -l) files to /app/output/"
ls -R /app/output
