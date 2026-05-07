#!/bin/bash

# Pick the container runtime. Default sandbox_vendor is podman, so prefer
# `podman compose` when available; fall through to docker only if podman
# is missing. HELIX_COMPOSE override lets operators force a specific
# command (e.g. HELIX_COMPOSE="docker compose").
if [[ -n "${HELIX_COMPOSE:-}" ]]; then
    COMPOSE="$HELIX_COMPOSE"
elif command -v podman &> /dev/null && podman compose version &> /dev/null; then
    COMPOSE="podman compose"
    # Resolve the host-side podman socket path so the backend container's
    # bind-mount lands on a socket the rootless podman user can access.
    # Rootful /run/podman/podman.sock is owned by root and unreachable
    # from a rootless-spawned container.
    if [[ -z "${HELIX_HOST_RUNTIME_SOCKET:-}" ]]; then
        # Anchor on the same socket as podman's default connection so the
        # backend container's image store matches what `podman compose
        # build` populated. Mismatching rootful vs rootless stores is
        # invisible until first sandbox spawn, when the SDK reports the
        # image as missing even though `podman images` shows it.
        default_uri=$(podman system connection list --format '{{.Default}} {{.URI}}' 2>/dev/null \
            | awk '$1=="true"{print $2; exit}')
        if [[ -n "$default_uri" ]]; then
            # Strip "ssh://user@host:port" to leave the in-VM socket path.
            export HELIX_HOST_RUNTIME_SOCKET="${default_uri##*[0-9]}"
        elif podman machine list --format '{{.Running}}' 2>/dev/null | grep -qi true; then
            # No default connection (rare). Fallback for podman-machine.
            machine_uid=$(podman machine ssh "id -u core" 2>/dev/null | tr -d '\r ' || true)
            export HELIX_HOST_RUNTIME_SOCKET="/run/user/${machine_uid:-501}/podman/podman.sock"
        elif [[ -S "/run/user/$(id -u)/podman/podman.sock" ]]; then
            export HELIX_HOST_RUNTIME_SOCKET="/run/user/$(id -u)/podman/podman.sock"
        else
            export HELIX_HOST_RUNTIME_SOCKET="/run/podman/podman.sock"
        fi
    fi
elif command -v docker &> /dev/null && docker compose version &> /dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE="docker-compose"
else
    echo "Error: No container runtime found (need podman, docker compose, or docker-compose)" >&2
    exit 1
fi


# Execute compose command
$COMPOSE -f docker-compose-development.yml "$@"
