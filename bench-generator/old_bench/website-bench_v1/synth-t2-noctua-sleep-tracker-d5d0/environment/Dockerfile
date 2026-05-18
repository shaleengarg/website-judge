# Playwright's official Python image: Python + Chromium baked in.
# Pinned for reproducibility — build-time PNG generation and the verifier's
# runtime rendering both use the same Chromium.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# The image ships only Chromium binaries (under /ms-playwright/), NOT the
# playwright pip package. Install it explicitly; pin to the same version as
# the image tag so the browsers resolve.
RUN pip install --no-cache-dir \
        playwright==1.49.0 \
        pillow==11.0.0 \
        numpy==2.1.3 \
        scikit-image==0.24.0 \
        anthropic>=0.40

WORKDIR /app
RUN mkdir -p /app/references /app/output

# Canonical reference HTML — single source of truth.
COPY reference-pages /opt/reference-pages

# Build-time PNG generator.
COPY make.py /tmp/make.py
RUN python /tmp/make.py && rm /tmp/make.py

# Surface what was generated in build logs.
RUN ls -la /app/references/ && \
    test "$(ls /app/references/*.png 2>/dev/null | wc -l)" -ge 1 \
    || (echo "ERROR: no reference PNGs were generated" >&2 && exit 1)
