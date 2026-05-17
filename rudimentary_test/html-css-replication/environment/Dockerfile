# Playwright's official Python image: Python 3 + Playwright + Chromium ready to go.
# Pinned for reproducibility — both build-time PNG generation and the verifier's
# runtime rendering use the same Chromium.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Scoring deps used by the verifier later.
RUN pip install --no-cache-dir \
        playwright==1.49.0 \
        pillow==11.0.0 \
        numpy==2.1.3 \
        scikit-image==0.24.0

WORKDIR /app
RUN mkdir -p /app/references /app/output

# Canonical reference HTML — single source of truth for this task.
# Lives at /opt/reference-pages/ in the image so both the oracle (solve.sh) and
# the verifier (score.py) can read from one place; no duplication on the host.
COPY reference-pages /opt/reference-pages

# Build-time PNG generator. Runs once during build to produce /app/references/.
COPY make.py /tmp/make.py
# IMPORTANT: this image ships Playwright inside a venv exposed as `python` (and
# `pip`). The system `python3` does NOT have playwright. Always use `python`.
RUN python /tmp/make.py && rm /tmp/make.py

# Show what got generated so build logs are useful when something's off.
RUN ls -la /app/references/ && \
    test "$(ls /app/references/*.png 2>/dev/null | wc -l)" -ge 1 \
    || (echo "ERROR: no reference PNGs were generated" >&2 && exit 1)
