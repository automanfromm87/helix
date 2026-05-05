#!/usr/bin/env bash
# Incremental updater for an existing Helix install.
#
# Pulls latest code, rebuilds the sandbox image (layer cache makes it cheap
# when nothing changed, correctness-critical when it did), and restarts
# the dev stack — picking up dropped/renamed services along the way.
#
# Use install.sh for a fresh install; use this for routine updates.
#
# Usage:
#   ./update.sh

set -Eeuo pipefail

readonly C_OK="\033[1;32m"
readonly C_WARN="\033[1;33m"
readonly C_ERR="\033[1;31m"
readonly C_DIM="\033[2m"
readonly C_RST="\033[0m"

step()   { printf "${C_OK}==>${C_RST} %s\n" "$1"; }
warn()   { printf "${C_WARN}!! ${C_RST} %s\n" "$1" >&2; }
fail()   { printf "${C_ERR}xx ${C_RST} %s\n" "$1" >&2; exit 1; }
detail() { printf "    ${C_DIM}%s${C_RST}\n" "$1"; }

# Must run inside a Helix clone
[[ -f docker-compose-development.yml && -f sandbox/Dockerfile ]] \
  || fail "Run this from the Helix repo root (no docker-compose-development.yml here)."

command -v docker >/dev/null 2>&1 || fail "Docker not found."
docker info >/dev/null 2>&1 || fail "Docker daemon not running. Start Docker Desktop and re-run."

# 1. Pull latest
step "Pulling latest from git"
if git pull --ff-only; then
  detail "git pull ok"
else
  warn "git pull --ff-only failed — continuing with current checkout"
fi

# 2. Always rebuild sandbox. Layer cache means it's near-instant when
#    Dockerfile + context didn't change; when they did, this is the
#    only place that re-baking matters (sandbox image is what backend
#    spawns per session).
step "Rebuilding sandbox image"
./dev.sh build sandbox

# 3. Restart stack. --remove-orphans cleans up services that were dropped
#    from compose (e.g. mockserver removal) so they don't linger.
step "Restarting dev stack"
./dev.sh up -d --remove-orphans

# 4. Quick health check
step "Verifying"
for i in {1..15}; do
  if curl -fs http://localhost:8000/openapi.json >/dev/null 2>&1; then
    detail "backend ready (port 8000)"
    break
  fi
  sleep 2
  if [[ $i -eq 15 ]]; then
    warn "Backend didn't respond in 30s. Check: ./dev.sh logs backend"
  fi
done

echo
printf "${C_OK}Helix updated.${C_RST}\n"
echo "  UI:        http://localhost:5174"
echo "  Logs:      ./dev.sh logs -f"
echo "  Stop:      ./dev.sh down"
