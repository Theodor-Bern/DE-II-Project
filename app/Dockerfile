# ─── Stage 1: builder ────────────────────────────────────────────────────────
# Installs dependencies in an isolated venv so build tools don't bloat the final image.
FROM python:3.11-slim AS builder

WORKDIR /build

# Build tools needed only for compiling pulsar-client's C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

# Create venv, install deps into it
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ─── Stage 2: runtime ────────────────────────────────────────────────────────
# Minimal runtime — just Python + the venv from stage 1 + our application code.
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy the prebuilt venv from the builder stage
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Application code is copied in by each component's docker-compose via volume mount
# at runtime, so the image stays generic. (For production we'd COPY the code in,
# but mounting makes iteration faster during development.)

# Default command does nothing — each compose file overrides with the right script.
CMD ["python", "--version"]
