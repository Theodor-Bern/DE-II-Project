# syntax=docker/dockerfile:1.6
# ─── Stage 1: builder ────────────────────────────────────────────────────────
# Build pulsar-client's C extensions in an isolated venv. Toolchain stays
# out of the final image.
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

# Copy the prebuilt venv from the builder stage
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Bake the producer code into the image
COPY producer.py .

# Single script, single entrypoint. Compose can still override via `command:`
# if we need to, but it's not expected.
CMD ["python", "producer.py"]
