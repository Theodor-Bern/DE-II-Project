# syntax=docker/dockerfile:1.6
# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Both enricher scripts are baked in. Compose chooses which runs per container.
COPY commits_enricher.py .
COPY test_enricher.py    .

# No default CMD — compose must specify `command:` to pick a script.
# This is intentional: running the image without a command should fail loudly
# rather than silently start the "wrong" enricher.
