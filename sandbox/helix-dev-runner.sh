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
#   2. package.json present     — Vite/Node: npm install + npm run dev on
#                                  port 5173. npm because helixcli scaffolds
#                                  npm workspaces; pnpm 9 doesn't recognise
#                                  npm's `workspaces` field.
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

# Detection. helixcli scaffolds a two-app monorepo:
#   apps/web/  — Vite + React (npm workspace at root)
#   apps/api/  — uv + FastAPI
# Single-app projects (legacy or `--frontend-only` / `--backend-only`)
# keep their package.json / pyproject.toml at the project root.
WEB_DIR=""
if [ -f apps/web/package.json ]; then
  WEB_DIR="apps/web"  # workspace mode — root package.json drives install
elif [ -f package.json ]; then
  WEB_DIR="."
fi
API_DIR=""
if [ -f apps/api/pyproject.toml ] && grep -qE "fastapi|uvicorn" apps/api/pyproject.toml; then
  API_DIR="apps/api"
elif [ -f pyproject.toml ] && grep -qE "fastapi|uvicorn" pyproject.toml; then
  API_DIR="."
fi

# Backend goes first, in the background, so the foreground process
# (Vite, when present) is the one supervisord watches for restart.
# When only the API exists, uvicorn runs in the foreground.
start_api_bg() {
  (
    cd "$PROJECT_DIR/$API_DIR"
    if [ ! -f .venv/pyvenv.cfg ]; then
      echo "[helix-dev-runner] .venv missing in $API_DIR — running uv sync"
      uv sync 2>&1 | tail -10 || exit 1
    fi
    PORT=${HELIX_API_PORT:-8000}
    echo "[helix-dev-runner] starting uvicorn on :$PORT in $API_DIR"
    exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
  ) &
}

if [ -n "$WEB_DIR" ] && [ -n "$API_DIR" ]; then
  start_api_bg
fi

# 2. Vite / Node (foreground when present)
if [ -n "$WEB_DIR" ]; then
  # helixcli init creates `node_modules/<workspace>` SYMLINKS at scaffold
  # time (workspace structure), so `[ ! -d node_modules ]` is fooled into
  # thinking deps are installed even on a fresh project. Use the
  # presence of `package-lock.json` as the real marker — that file only
  # exists after a real `npm install` has completed at the project root.
  if [ ! -f package-lock.json ]; then
    echo "[helix-dev-runner] package-lock.json missing — running npm install"
    npm install --no-audit --no-fund --loglevel=error 2>&1 | tail -20 || {
      echo "[helix-dev-runner] npm install failed; sleeping 10s before supervisord retry"
      sleep 10
      exit 1
    }
  fi
  PORT=${HELIX_DEV_PORT:-5173}
  if [ "$WEB_DIR" = "apps/web" ]; then
    echo "[helix-dev-runner] starting vite via workspace apps/web on :$PORT"
    exec npm run dev --workspace apps/web -- --host 0.0.0.0 --port "$PORT"
  fi
  echo "[helix-dev-runner] starting vite on :$PORT"
  exec npm run dev -- --host 0.0.0.0 --port "$PORT"
fi

# 3. FastAPI only (no frontend)
if [ -n "$API_DIR" ]; then
  cd "$PROJECT_DIR/$API_DIR"
  if [ ! -f .venv/pyvenv.cfg ]; then
    echo "[helix-dev-runner] .venv missing in $API_DIR — running uv sync"
    uv sync 2>&1 | tail -20 || {
      echo "[helix-dev-runner] uv sync failed; sleeping 10s before supervisord retry"
      sleep 10
      exit 1
    }
  fi
  PORT=${HELIX_DEV_PORT:-8000}
  echo "[helix-dev-runner] starting uvicorn on :$PORT in $API_DIR"
  exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
fi

# Files appeared but neither stack matched — log + sleep so supervisord
# doesn't tight-loop. Likely a non-standard project; user can drop a
# `.helix-runner` file to override.
echo "[helix-dev-runner] project files detected but no recognized stack; sleeping 30s"
sleep 30
exit 1
