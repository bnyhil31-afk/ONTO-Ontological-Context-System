# ONTO — Ontological Context System
# Multi-stage build: builder installs deps, runtime image is minimal.
#
# Build:  docker build -t onto .
# Run:    docker run -p 8000:8000 --env-file .env -v ./data:/app/data onto
#
# Security hardening:
#   - python:3.12-slim base (not :latest — avoids unintended upgrades)
#   - Non-root user (onto, uid 1000) — no root access inside container
#   - Only required files copied (see .dockerignore)
#   - Health check built-in so orchestrators detect unhealthy instances

# ── Stage 1: dependency builder ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for some C extensions; not in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Create a non-root user before copying any files
RUN useradd -u 1000 -m -s /bin/false onto

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source (see .dockerignore for exclusions)
COPY --chown=onto:onto . .

# Create the data directory with correct ownership before switching user
RUN mkdir -p /app/data && chown onto:onto /app/data

# Drop to non-root
USER onto

# Expose the API port
EXPOSE 8000

# Health check — probes the public /health endpoint every 30s.
# 3 consecutive failures mark the container as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c \
    "import urllib.request, sys; \
     r = urllib.request.urlopen('http://localhost:8000/health', timeout=4); \
     sys.exit(0 if r.status == 200 else 1)" \
    || exit 1

# Default command: HTTP API server, listening on all interfaces inside
# the container (host binding is controlled by docker run -p).
CMD ["python3", "-m", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
