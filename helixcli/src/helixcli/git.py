"""Tiny git wrapper. Generators auto-commit so plan-versioning's diff
view shows only the agent's customisations on top of a known
baseline."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from helixcli.errors import GeneratorFailed


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command, raising on non-zero. On failure, surface
    git's stderr through GeneratorFailed — bare CalledProcessError
    swallows the message and Typer prints a useless traceback.

    Force `safe.directory` via env so git accepts the cwd no matter who
    owns it. The sandbox bind-mount makes /home/ubuntu/project owned by
    `ubuntu` while shell sessions run as root — git's "dubious
    ownership" guard would otherwise abort every generator. Setting via
    GIT_CONFIG_COUNT/KEY/VALUE leaves the user's real ~/.gitconfig
    untouched (vs. `git config --global` which would).
    """
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "safe.directory"
    env["GIT_CONFIG_VALUE_0"] = "*"
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise GeneratorFailed(f"git {' '.join(args)}", detail)
    return proc


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _has_identity(root: Path) -> bool:
    """True if `git commit` would be able to find user.email + user.name
    via any config layer (local / global / system).

    Reuses `run()` so safe.directory is set the same way — without it
    git refuses to read config in a "dubious-ownership" repo.
    """
    for key in ("user.email", "user.name"):
        try:
            proc = run(["config", "--get", key], cwd=root)
        except GeneratorFailed:
            return False
        if not proc.stdout.strip():
            return False
    return True


def init_if_needed(root: Path) -> bool:
    """Initialise a git repo at `root` if there's no .git there yet.
    Returns True if a fresh repo was created.

    Identity (user.email / user.name) is only set if no layer of git
    config provides it — that way we don't override the developer's
    real identity when running on a host machine, and we still produce
    a working setup on a fresh sandbox where no global identity exists.
    """
    if is_repo(root):
        return False
    run(["init", "--quiet", "--initial-branch=main"], cwd=root)
    if not _has_identity(root):
        run(["config", "user.email", "helixcli@helix.local"], cwd=root)
        run(["config", "user.name", "helixcli"], cwd=root)
    return True


def commit_all(root: Path, message: str) -> str:
    """Stage everything and create a commit. Returns the new SHA."""
    run(["add", "-A"], cwd=root)
    # Allow empty so a generator that produced no file changes (rare
    # but possible — e.g. reconciling a manifest) still records a
    # commit boundary.
    run(["commit", "--quiet", "--allow-empty", "-m", message], cwd=root)
    sha = run(["rev-parse", "HEAD"], cwd=root).stdout.strip()
    return sha


def reset_hard(root: Path) -> None:
    """Used by the atomic-failure path: undo any half-applied changes."""
    run(["reset", "--hard", "HEAD"], cwd=root)
