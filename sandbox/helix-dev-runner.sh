#!/usr/bin/env bash
# Helix dev-server runner — managed by supervisord.
#
# Auto-detects the project's stack and execs the appropriate dev server.
# Replaces the agent-driven `nohup pnpm dev` pattern: the agent kept
# forgetting to start it, killing it, or starting two copies. As a
# supervisord-managed program, the dev server is now an OS service —
# always running when the sandbox is up, auto-restart on crash.
#
# Project root: /home/ubuntu/project (the bind-mounted host volume).
# Detection priority:
#   1. .helix-runner            — explicit user override (single-line
#                                  command exec'd as-is)
#   2. package.json present     — Vite/Node: pnpm dev on port 5173
#   3. pyproject.toml + fastapi  — uvicorn --reload on port 8000
#
# Behavior while project is empty: blocks in a polling loop instead of
# exiting, so supervisord sees the program in RUNNING state and the
# sandbox readiness check (`All N services are RUNNING`) doesn't stall.
# Loop exits the moment any project file appears, then exec'd dev
# server takes over.

set -uo pipefail
PROJECT_DIR="/home/ubuntu/project"
cd "$PROJECT_DIR" 2>/dev/null || { echo "[helix-dev-runner] $PROJECT_DIR missing"; sleep 5; exit 1; }

# Wait for the agent to scaffold something. 2s polling keeps response
# time low without burning CPU. inotify would be sleeker but adds an
# apt dep — overkill for a one-shot wait.
echo "[helix-dev-runner] waiting for project files…"
while true; do
  if [ -f .helix-runner ] || [ -f package.json ] || [ -f pyproject.toml ]; then
    break
  fi
  sleep 2
done

# 1. Explicit override
if [ -f .helix-runner ]; then
  CMD=$(head -n 1 .helix-runner | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  if [ -n "$CMD" ]; then
    echo "[helix-dev-runner] using .helix-runner: $CMD"
    exec bash -lc "$CMD"
  fi
fi

# 2. Vite / Node
if [ -f package.json ]; then
  # node_modules cache may not exist on a fresh fork (we exclude it from
  # fork copy to keep it lightweight) or after a clean checkout. pnpm's
  # global store makes install fast — usually under 10 sec on cache hit.
  if [ ! -d node_modules ]; then
    echo "[helix-dev-runner] node_modules missing — running pnpm install"
    pnpm install --prefer-offline --reporter=append-only 2>&1 | tail -20 || {
      echo "[helix-dev-runner] pnpm install failed; sleeping 10s before supervisord retry"
      sleep 10
      exit 1
    }
  fi
  PORT=${HELIX_DEV_PORT:-5173}
  echo "[helix-dev-runner] starting vite on :$PORT"
  exec pnpm dev -- --host 0.0.0.0 --port "$PORT"
fi

# 3. FastAPI
if [ -f pyproject.toml ] && grep -qE "fastapi|uvicorn" pyproject.toml; then
  if [ ! -d .venv ]; then
    echo "[helix-dev-runner] .venv missing — running uv sync"
    uv sync 2>&1 | tail -20 || {
      echo "[helix-dev-runner] uv sync failed; sleeping 10s before supervisord retry"
      sleep 10
      exit 1
    }
  fi
  PORT=${HELIX_DEV_PORT:-8000}
  TARGET="app.main:app"
  echo "[helix-dev-runner] starting uvicorn on :$PORT ($TARGET)"
  exec uv run uvicorn "$TARGET" --host 0.0.0.0 --port "$PORT" --reload
fi

# Files appeared but neither stack matched — log + sleep so supervisord
# doesn't tight-loop. Likely a non-standard project; user can drop a
# `.helix-runner` file to override.
echo "[helix-dev-runner] project files detected but no recognized stack; sleeping 30s"
sleep 30
exit 1
