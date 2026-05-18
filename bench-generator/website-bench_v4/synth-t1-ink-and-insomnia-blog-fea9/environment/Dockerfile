# Playwright's official Python image: Python + Chromium baked in.
# Pinned for reproducibility — build-time PNG generation and the verifier's
# runtime rendering both use the same Chromium.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# The image ships only Chromium binaries (under /ms-playwright/), NOT the
# playwright pip package. Install it explicitly; pin to the same version as
# the image tag so the browsers resolve. `anthropic` is needed by tests/score.py
# for the Claude-Opus judge step (deterministic scoring + ensemble judge);
# ANTHROPIC_API_KEY is supplied at runtime by the verifier env, not baked in.
RUN pip install --no-cache-dir \
        playwright==1.49.0 \
        pillow==11.0.0 \
        numpy==2.1.3 \
        scikit-image==0.24.0 \
        "anthropic>=0.40,<1.0"

WORKDIR /app
RUN mkdir -p /app/references /app/output

# Canonical reference HTML — single source of truth.
COPY reference-pages /opt/reference-pages

# Build-time PNG generator.
COPY make.py /tmp/make.py
RUN python /tmp/make.py && rm /tmp/make.py

# Surface what was generated in build logs. V4 make.py writes
# /app/references/<viewport>/<page>.png (one subdir per viewport), so we
# recurse instead of looking only at the top level. Expect at least 5
# PNGs per task — one page × 3 viewports already exceeds that for any
# real seed.
RUN find /app/references -type f -name '*.png' | sort && \
    test "$(find /app/references -type f -name '*.png' | wc -l)" -ge 5 \
    || (echo "ERROR: too few reference PNGs were generated" >&2 && exit 1)
