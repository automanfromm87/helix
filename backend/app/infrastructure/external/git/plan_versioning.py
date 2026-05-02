"""Plan-as-version git wrapper.

Each completed plan becomes one tagged commit on the session's project dir
(host bind-mount path). Operations run on the host filesystem from the
backend container — `/tmp/helix-sandboxes` is mirrored in via
docker-compose so the same path resolves on both sides.

Exposes:
    init_repo_if_needed   — idempotent `git init` + .gitignore + scaffold commit
    commit_plan           — stage + commit + tag (skips if no changes)
    diff_plan             — unified diff between a plan and its predecessor
    restore_to_plan       — `reset --hard` to a plan tag

Each function takes a project_path Path (already resolved against
session id by the caller) so this module never touches settings or the
session id directly. Failures are logged and swallowed — versioning is a
secondary feature, never block the agent on git issues.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# .gitignore matches the noise we'd never want to track in a Vite/Node
# scaffold; uv-fastapi adds .venv. Trimmed to common dev-server litter
# and OS junk — broad enough to fit any backend/frontend stack we ship
# scaffolders for, narrow enough not to silently hide source files.
_GITIGNORE = """\
# Dependency dirs
node_modules/
.venv/
__pycache__/
*.pyc

# Build / cache outputs
dist/
build/
.vite/
.next/
.turbo/
coverage/

# Local env / secrets
.env
.env.local
.env.*.local

# Editor / OS
.DS_Store
.idea/
.vscode/
*.swp
"""


@dataclass(frozen=True)
class CommitInfo:
    """Result of a successful `commit_plan` call."""

    sha: str
    short_sha: str
    files_changed: int


_GLOBAL_SAFE_DIR_INSTALLED = False


async def _ensure_global_safe_directory() -> None:
    """Add `safe.directory=*` to the backend container's global gitconfig.

    Per-command `-c safe.directory=*` only affects the calling git process;
    when the calling process spawns sub-processes to read another repo
    (notably `git fetch <local-path>`), those sub-processes inherit none
    of the -c flags and trip the dubious-ownership guard. A one-shot
    global config write fixes both cases. Idempotent — git just writes
    duplicate entries, no harm.

    Runs lazily on the first git op so it doesn't block startup if the
    binary is missing.
    """
    global _GLOBAL_SAFE_DIR_INSTALLED
    if _GLOBAL_SAFE_DIR_INSTALLED:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "config", "--global", "--add", "safe.directory", "*",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        _GLOBAL_SAFE_DIR_INSTALLED = True
    except Exception:
        logger.exception("Failed to install global safe.directory")


def _tag_for(plan_id: str) -> str:
    """Tag name convention. `helix/plan/<short>` keeps a clear namespace
    so the user's own tags don't collide and they can still `git tag -d`
    selectively. Short id (12 chars) avoids absurdly long tag names."""
    return f"helix/plan/{plan_id[:12]}"


async def _run_git(project_path: Path, *args: str, check: bool = True) -> tuple[int, str, str]:
    """Run a `git -C <path> <args...>` subprocess and return (rc, stdout, stderr).

    The bind-mounted project dir is owned by the sandbox container's `ubuntu`
    user (uid 1000), but the backend container runs as root — without
    `-c safe.directory=*` git refuses with "dubious ownership". Wildcard is
    fine here: this whole module only ever touches `<sandbox_data_host_root>`
    paths the backend itself created.

    Raises `RuntimeError` only if `check=True` and rc != 0.
    """
    await _ensure_global_safe_directory()
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "safe.directory=*",
        "-C",
        str(project_path),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    rc = proc.returncode if proc.returncode is not None else -1
    out = out_b.decode("utf-8", errors="replace").strip()
    err = err_b.decode("utf-8", errors="replace").strip()
    if check and rc != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (rc={rc}): {err or out}")
    return rc, out, err


async def _is_repo(project_path: Path) -> bool:
    if not (project_path / ".git").exists():
        return False
    rc, _, _ = await _run_git(
        project_path, "rev-parse", "--is-inside-work-tree", check=False
    )
    return rc == 0


async def init_repo_if_needed(project_path: Path) -> bool:
    """Idempotently turn `project_path` into a git repo with a baseline
    "scaffold" commit. Returns True if it was just initialized, False if
    it was already a repo.

    Safe to call before every `commit_plan` so the first plan in a
    session triggers init lazily — sandbox-create doesn't need to know.
    """
    if not project_path.exists():
        logger.warning("plan_versioning: project path %s does not exist yet", project_path)
        return False
    if await _is_repo(project_path):
        return False

    await _run_git(project_path, "init", "-b", "main")
    # Local-only identity. Avoids touching the user's global git config
    # and keeps Helix's commits clearly attributable in `git log`.
    await _run_git(project_path, "config", "user.email", "agent@helix.local")
    await _run_git(project_path, "config", "user.name", "Helix Agent")
    # Don't sign — local identity isn't trusted by anyone, signing would
    # only fail if user has commit.gpgsign=true in global config.
    await _run_git(project_path, "config", "commit.gpgsign", "false")

    gitignore = project_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE)

    await _run_git(project_path, "add", "-A")
    rc, _, _ = await _run_git(
        project_path, "diff", "--cached", "--quiet", check=False
    )
    if rc == 1:
        # rc==1 means there are staged changes (git diff --quiet inverts
        # exit codes). Make the scaffold commit.
        await _run_git(project_path, "commit", "-m", "scaffold", "--no-verify")
    logger.info("plan_versioning: initialized repo at %s", project_path)
    return True


async def commit_plan(
    project_path: Path, plan_id: str, plan_title: str
) -> Optional[CommitInfo]:
    """Stage everything, commit + tag if there are changes, otherwise
    return None. The tag name is `helix/plan/<short_plan_id>`.

    Caller is expected to update the Plan row's `commit_sha` from the
    return value (so the FE can show "v3 · abc123" + diff/restore).
    """
    try:
        await init_repo_if_needed(project_path)

        await _run_git(project_path, "add", "-A")
        rc, _, _ = await _run_git(
            project_path, "diff", "--cached", "--quiet", check=False
        )
        if rc == 0:
            # No staged changes — agent finished a plan without modifying
            # any tracked file (rare but possible: plans that only
            # inspect / answer questions). Skip the commit but don't
            # error.
            logger.info(
                "plan_versioning: plan %s completed with no changes — skipping commit",
                plan_id,
            )
            return None

        # Title may contain quotes / newlines; pass via stdin to avoid
        # shell escaping headaches.
        # Use --no-verify to skip user pre-commit hooks; agent's commit
        # is metadata, hooks are for the user's deliberate commits.
        msg = f"{plan_title}\n\nhelix-plan-id: {plan_id}\n"
        await _ensure_global_safe_directory()
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(project_path),
            "commit",
            "-F",
            "-",
            "--no-verify",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate(msg.encode())
        if proc.returncode != 0:
            raise RuntimeError(
                f"git commit failed: {err_b.decode('utf-8', errors='replace')}"
            )

        _, sha, _ = await _run_git(project_path, "rev-parse", "HEAD")
        # Force-overwrite tag — if the plan got re-committed for any
        # reason (manual re-run, retry of mark_completed), keep the tag
        # pointing at the latest commit.
        await _run_git(project_path, "tag", "-f", _tag_for(plan_id))
        _, files_str, _ = await _run_git(
            project_path, "diff-tree", "--no-commit-id", "--name-only", "-r", sha
        )
        files_changed = len([line for line in files_str.splitlines() if line.strip()])

        info = CommitInfo(sha=sha, short_sha=sha[:7], files_changed=files_changed)
        logger.info(
            "plan_versioning: committed plan %s as %s (%d files)",
            plan_id,
            info.short_sha,
            info.files_changed,
        )
        return info
    except Exception:
        logger.exception("plan_versioning: commit_plan failed for plan %s", plan_id)
        return None


async def diff_plan(project_path: Path, plan_id: str) -> str:
    """Unified diff for a plan's commit. Compares the plan tag against
    its first parent (the previous plan's commit, or the scaffold).
    Returns "" if the plan has no tag yet."""
    if not await _is_repo(project_path):
        return ""
    tag = _tag_for(plan_id)
    rc, _, _ = await _run_git(project_path, "rev-parse", "--verify", tag, check=False)
    if rc != 0:
        return ""
    # `git diff <tag>^!` is shorthand for `<tag>^..<tag>` — the diff
    # introduced by this commit. Works even when the tag is the very
    # first commit (no parent) by failing gracefully.
    rc, out, _ = await _run_git(
        project_path, "diff", f"{tag}^!", check=False
    )
    if rc != 0:
        # First commit has no parent; fall back to root diff.
        _, out, _ = await _run_git(
            project_path, "show", "--format=", tag
        )
    return out


# Directories never worth copying when forking — heavy build/runtime
# artifacts that the new sandbox will regenerate (or that the agent's
# `pnpm install` can rebuild from lockfile faster than we can copy).
_FORK_SKIP = {
    "node_modules",
    ".venv",
    "dist",
    "build",
    ".vite",
    ".next",
    ".turbo",
    "coverage",
}


def _fork_ignore(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n in _FORK_SKIP]


async def fork_project(
    src_path: Path, dst_path: Path, plan_id: str, fork_branch: str
) -> bool:
    """Clone `src_path` to `dst_path` and check out a new branch off
    the plan's tag. After this, the caller can spawn a sandbox bound to
    `dst_path` and the agent will see the project at the plan's snapshot
    on a fresh branch.

    Skips `node_modules` & friends — node_modules of a typical Vite app
    is ~200MB; the agent's first `pnpm install` rebuilds it from the
    lockfile in seconds, way faster than the copy.

    Sets up bidirectional remotes:
      - in dst: `upstream` → src's .git
      - in src: `<fork_branch>` → dst's .git
    so a future merge-back can `git fetch <fork_branch>` from the root
    session without manual remote setup.
    """
    try:
        if not (src_path / ".git").exists():
            logger.warning(
                "fork_project: source %s is not a git repo — cannot fork", src_path,
            )
            return False
        rc, _, _ = await _run_git(
            src_path, "rev-parse", "--verify", _tag_for(plan_id), check=False,
        )
        if rc != 0:
            logger.warning(
                "fork_project: tag %s missing in %s", _tag_for(plan_id), src_path,
            )
            return False

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists():
            # Don't silently nuke an existing dir — the caller is expected
            # to point at a fresh path. Surface as a clear error.
            raise RuntimeError(f"fork target {dst_path} already exists")

        # shutil.copytree handles symlinks, perms, modes; the ignore
        # callable prunes heavy dirs at recursion time so we don't read
        # node_modules off disk only to throw it away. dirs_exist_ok=False
        # is the default — defensive against the existence check above.
        await asyncio.to_thread(
            shutil.copytree, src_path, dst_path, ignore=_fork_ignore, symlinks=True,
        )

        # Detach from the source's HEAD and start a fresh branch from
        # the plan tag. Skipping `git reset` keeps the working tree at
        # whatever was on disk — same as src at this exact moment.
        await _run_git(dst_path, "checkout", "-B", fork_branch, _tag_for(plan_id))

        # Wire remotes both ways. Path is host-side; only the backend
        # ever talks to these, never the sandbox containers.
        src_dot_git = str(src_path / ".git")
        dst_dot_git = str(dst_path / ".git")
        # In dst: `upstream` points to source.
        await _run_git(
            dst_path, "remote", "remove", "upstream", check=False,
        )
        await _run_git(dst_path, "remote", "add", "upstream", src_dot_git)
        # In src: a remote named after the fork branch points at the new
        # session's repo. Lets the user later `git fetch <branch>` from
        # the parent session and merge back.
        await _run_git(
            src_path, "remote", "remove", fork_branch, check=False,
        )
        await _run_git(src_path, "remote", "add", fork_branch, dst_dot_git)

        logger.info(
            "fork_project: %s → %s (branch %s)", src_path, dst_path, fork_branch,
        )
        return True
    except Exception:
        logger.exception(
            "fork_project: failed src=%s dst=%s plan=%s", src_path, dst_path, plan_id,
        )
        # Roll back partial copy so a retry starts clean.
        if dst_path.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, dst_path)
            except Exception:
                logger.exception(
                    "fork_project: cleanup of %s failed", dst_path,
                )
        return False


async def restore_to_plan(project_path: Path, plan_id: str) -> bool:
    """`git reset --hard <plan-tag>`. Destructive — caller's responsible
    for confirming with the user. Returns True on success."""
    if not await _is_repo(project_path):
        return False
    tag = _tag_for(plan_id)
    rc, _, _ = await _run_git(project_path, "rev-parse", "--verify", tag, check=False)
    if rc != 0:
        logger.warning("plan_versioning: restore — tag %s not found", tag)
        return False
    try:
        await _run_git(project_path, "reset", "--hard", tag)
        logger.info("plan_versioning: restored %s to plan %s", project_path, plan_id)
        return True
    except Exception:
        logger.exception("plan_versioning: restore_to_plan failed for %s", plan_id)
        return False
