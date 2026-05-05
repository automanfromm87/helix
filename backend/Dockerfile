# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

WORKDIR /app

# Keep apt's package cache in a BuildKit cache mount.
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
        > /etc/apt/apt.conf.d/keep-cache

# curl + git (plan-versioning auto-commits) + Node 22 in one apt update.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl git ca-certificates gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs

# uv (cached pip)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Backend python deps (cached uv downloads stay warm across rebuilds)
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Application source last — code edits don't bust the deps cache.
COPY . .

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
