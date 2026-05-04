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
  # Wait for the agent to finish installing — DO NOT install ourselves.
  # Earlier iterations auto-ran `pnpm install` here, which raced against
  # the agent's own `npm install` / `npm create vite` install step and
  # corrupted node_modules (the `vitest: not found` / dead-shell-session
  # failure mode). Just poll until node_modules appears, then exec vite.
  if [ ! -d node_modules ]; then
    echo "[helix-dev-runner] waiting for node_modules — agent should run \`npm install\`"
    while [ ! -d node_modules ]; do sleep 2; done
    echo "[helix-dev-runner] node_modules present — proceeding to vite"
  fi
  PORT=${HELIX_DEV_PORT:-5173}
  echo "[helix-dev-runner] starting vite on :$PORT"
  exec pnpm dev -- --host 0.0.0.0 --port "$PORT"
fi

# 3. FastAPI
if [ -f pyproject.toml ] && grep -qE "fastapi|uvicorn" pyproject.toml; then
  # Same passive-wait pattern as the Node branch above — install is the
  # agent's job, we just wait for `.venv` to appear before exec'ing.
  if [ ! -d .venv ]; then
    echo "[helix-dev-runner] waiting for .venv — agent should run \`uv sync\`"
    while [ ! -d .venv ]; do sleep 2; done
    echo "[helix-dev-runner] .venv present — proceeding to uvicorn"
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
