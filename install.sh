#!/usr/bin/env bash
# One-shot installer for AI Helix. Clones the repo, sets up .env,
# builds the sandbox image, and brings up the dev stack.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/automanfromm87/helix/main/install.sh | bash
# or, from an existing clone:
#   ./install.sh
#
# Optional overrides (if you need to route LLM traffic through a custom
# gateway / outbound HTTP proxy — e.g. a corporate egress setup):
#   LLM_API_KEY=sk-ant-...        # Anthropic key. Required unless your
#                                 # gateway injects auth (then any value).
#   LLM_GATEWAY_URL=https://...   # Override Anthropic's base URL.
#   HTTP_PROXY_ADDRESS=host:port  # Outbound HTTP proxy for LLM calls.
#   MODEL_NAME=claude-sonnet-4-5  # Override model name.
#
# Example (local clone, env vars on the same line):
#   LLM_API_KEY=sk-ant-xxx ./install.sh
#
# Example (curl pipe — note env vars must be on the `bash` side of the
# pipe, NOT the `curl` side, otherwise they're scoped to curl only):
#   curl -fsSL .../install.sh | LLM_API_KEY=sk-ant-xxx bash
#
# Or download first, then run with env vars:
#   curl -fsSL .../install.sh -o install.sh && \
#     LLM_API_KEY=sk-ant-xxx bash install.sh

set -Eeuo pipefail

readonly REPO_URL="https://github.com/automanfromm87/helix.git"
readonly REPO_DIR_DEFAULT="$HOME/helix"

readonly C_OK="\033[1;32m"
readonly C_WARN="\033[1;33m"
readonly C_ERR="\033[1;31m"
readonly C_DIM="\033[2m"
readonly C_RST="\033[0m"

step()   { printf "${C_OK}==>${C_RST} %s\n" "$1"; }
warn()   { printf "${C_WARN}!! ${C_RST} %s\n" "$1" >&2; }
fail()   { printf "${C_ERR}xx ${C_RST} %s\n" "$1" >&2; exit 1; }
detail() { printf "    ${C_DIM}%s${C_RST}\n" "$1"; }

# ----------------------------------------------------------------------
# 1. Pre-flight: tooling
# ----------------------------------------------------------------------
step "Checking prerequisites"

command -v docker >/dev/null 2>&1 \
  || fail "Docker not found. Install Docker Desktop (or Colima + Docker CLI) first."
docker info >/dev/null 2>&1 \
  || fail "Docker daemon not running. Start Docker Desktop and re-run."
docker compose version >/dev/null 2>&1 \
  || fail "Docker Compose v2 not available. Update Docker Desktop."
command -v git >/dev/null 2>&1 || fail "git not found."
command -v curl >/dev/null 2>&1 || fail "curl not found."

detail "docker $(docker --version | awk '{print $3}' | tr -d ',')"
detail "compose $(docker compose version --short)"

# Memory check (Docker Desktop default 4GB OOMs the sandbox).
mem_gb=$(docker info --format '{{.MemTotal}}' 2>/dev/null \
  | awk '{ printf "%.1f", $1/1024/1024/1024 }')
if [[ -n "$mem_gb" ]] && awk "BEGIN{exit !($mem_gb < 6)}"; then
  warn "Docker has only ${mem_gb}GB. Sandbox needs >=6GB to avoid OOM."
  warn "Bump in Docker Desktop → Settings → Resources, then re-run."
fi

# ----------------------------------------------------------------------
# 2. Repo: clone or use existing
# ----------------------------------------------------------------------
step "Locating repo"

if [[ -f "./docker-compose-development.yml" && -f "./sandbox/Dockerfile" ]]; then
  REPO_DIR="$(pwd)"
  detail "using current directory: $REPO_DIR"
elif [[ -d "$REPO_DIR_DEFAULT/.git" ]]; then
  REPO_DIR="$REPO_DIR_DEFAULT"
  detail "found existing clone at $REPO_DIR"
  cd "$REPO_DIR"
  git pull --ff-only || warn "git pull failed — continuing with current checkout"
else
  REPO_DIR="$REPO_DIR_DEFAULT"
  detail "cloning into $REPO_DIR"
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
fi

# ----------------------------------------------------------------------
# 3. .env bootstrap. Template ships with Anthropic defaults; we only
#    overwrite a key when the caller supplied it via env var.
# ----------------------------------------------------------------------
step "Configuring .env"

if [[ ! -f .env ]]; then
  cp .env.example .env
  detail ".env created from template"
fi

# Helper: replace `^KEY=...` line in .env, or append if missing.
set_env_var() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    # Use a delimiter that's unlikely to appear in URLs.
    sed -i.bak "s|^${key}=.*|${key}=${value}|" .env
  else
    # If the file doesn't end in a newline, our appended KEY=value would
    # glue onto the previous line (e.g. LOG_LEVEL=INFOSANDBOX_IMAGE=...).
    # .env.example happens to ship without a trailing newline, so guard
    # before every append.
    if [[ -s .env ]] && [[ "$(tail -c1 .env)" != "" ]]; then
      printf '\n' >> .env
    fi
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

# Always pin the sandbox image name so backend uses the locally built one
# instead of pulling from Docker Hub (where it may not exist).
set_env_var "SANDBOX_IMAGE" "helix-sandbox"

# Optional overrides — only written if the caller supplied them.
if [[ -n "${LLM_API_KEY:-}" ]]; then
  set_env_var "LLM_API_KEY" "$LLM_API_KEY"
  detail "LLM_API_KEY        → set"
fi
if [[ -n "${LLM_GATEWAY_URL:-}" ]]; then
  set_env_var "AGENT_LLM_BASE_URL" "$LLM_GATEWAY_URL"
  detail "AGENT_LLM_BASE_URL → $LLM_GATEWAY_URL"
fi
if [[ -n "${HTTP_PROXY_ADDRESS:-}" ]]; then
  set_env_var "LLM_PROXY_ADDRESS" "$HTTP_PROXY_ADDRESS"
  detail "LLM_PROXY_ADDRESS  → $HTTP_PROXY_ADDRESS"
fi
if [[ -n "${MODEL_NAME:-}" ]]; then
  set_env_var "MODEL_NAME" "$MODEL_NAME"
  detail "MODEL_NAME         → $MODEL_NAME"
fi

rm -f .env.bak

# Sanity: warn if LLM_API_KEY is still empty (chat will 401).
if ! grep -qE "^LLM_API_KEY=.+$" .env; then
  warn "LLM_API_KEY is not set in .env — chat will fail until you fix it."
  warn "Two ways to fix:"
  warn "  1) Edit .env directly:  $(pwd)/.env  (set LLM_API_KEY=...)"
  warn "  2) Re-run install with env vars on the right side of the pipe:"
  warn "     curl ... | LLM_API_KEY=sk-... bash"
  warn "After fixing, run: ./dev.sh restart backend"
fi

# ----------------------------------------------------------------------
# 4. Build sandbox image (heavy — ~3GB, ~5-10min first time)
# ----------------------------------------------------------------------
step "Building sandbox image (5-10 min first time, cached after)"

./dev.sh build sandbox

# ----------------------------------------------------------------------
# 5. Bring up the dev stack
# ----------------------------------------------------------------------
step "Starting Helix dev stack"

./dev.sh up -d

# ----------------------------------------------------------------------
# 6. Health check
# ----------------------------------------------------------------------
step "Waiting for backend"

for i in {1..30}; do
  if curl -fs http://localhost:8000/openapi.json >/dev/null 2>&1; then
    detail "backend ready (port 8000)"
    break
  fi
  sleep 2
  if [[ $i -eq 30 ]]; then
    warn "Backend didn't respond in 60s. Check: ./dev.sh logs backend"
  fi
done

for i in {1..15}; do
  if curl -fs http://localhost:5174 >/dev/null 2>&1; then
    detail "frontend ready (port 5174)"
    break
  fi
  sleep 2
done

# ----------------------------------------------------------------------
# 7. Done
# ----------------------------------------------------------------------
echo
printf "${C_OK}Helix is up.${C_RST}\n"
echo "  UI:        http://localhost:5174"
echo "  Backend:   http://localhost:8000/docs"
echo "  Logs:      cd $REPO_DIR && ./dev.sh logs -f"
echo "  Stop:      cd $REPO_DIR && ./dev.sh down"
echo
echo "First chat: open http://localhost:5174 and send a message."
echo "If chat fails with 'Sandbox unavailable: ImageNotFound', re-run:"
echo "  ./dev.sh build sandbox"
