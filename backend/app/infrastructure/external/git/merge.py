"""Cross-session git merge — pulls one fork's branch into another session's
working tree, auto-resolves conflicts via Claude, and commits the result.

Pairs with `plan_versioning.py`: forks set up two-way remotes when created,
so this module never has to set up new remotes — just `git fetch` + `git
merge` + (on conflict) ask the LLM to resolve.

The bind-mount paths live on the host; backend container has the same root
mounted in via docker-compose, so all subprocess calls run from the
backend's perspective.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from app.infrastructure.external.git.plan_versioning import _run_git, _tag_for

logger = logging.getLogger(__name__)


@dataclass
class MergeResult:
    """Outcome of a merge attempt.

    `status`:
      - "merged"  : clean merge, `commit_sha` set
      - "resolved": had conflicts, LLM resolved them all, `commit_sha` set
      - "conflict": had conflicts the LLM couldn't fully resolve;
                    `unresolved_files` lists which files still have markers
      - "noop"    : already up-to-date, nothing to merge
      - "failed"  : git itself errored before merge (fetch failure, etc.)
    """

    status: str
    commit_sha: Optional[str] = None
    conflicted_files: List[str] = field(default_factory=list)
    resolved_files: List[str] = field(default_factory=list)
    unresolved_files: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _fork_remote_name(session_id: str) -> str:
    """Convention used by fork_project: `fork/<short_id>` is the remote
    name in the parent's repo pointing at the fork's `.git`."""
    return f"fork/{session_id[:12]}"


async def _current_branch(path: Path) -> str:
    _, out, _ = await _run_git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip()


async def _has_uncommitted(path: Path) -> bool:
    """True if there are tracked changes (staged or unstaged) — does NOT
    include untracked files; those won't conflict with a merge."""
    rc, _, _ = await _run_git(path, "diff", "--quiet", check=False)
    if rc != 0:
        return True
    rc, _, _ = await _run_git(path, "diff", "--cached", "--quiet", check=False)
    return rc != 0


async def _stash_save(path: Path) -> bool:
    """Auto-commit any uncommitted changes so they don't collide with the
    merge. Better than `git stash` because the commit becomes a real
    versioned snapshot the user can restore from. Returns True if a
    save commit landed."""
    if not await _has_uncommitted(path):
        return False
    await _run_git(path, "add", "-A")
    rc, _, _ = await _run_git(path, "diff", "--cached", "--quiet", check=False)
    if rc == 0:
        return False
    await _run_git(
        path, "commit", "-m", "pre-merge auto-save", "--no-verify",
    )
    return True


CONFLICT_BEGIN_RE = re.compile(r"^<<<<<<< ")
CONFLICT_END_RE = re.compile(r"^>>>>>>> ")


def _has_conflict_markers(text: str) -> bool:
    """Quick sanity check — any line starting with merge markers means
    the LLM didn't fully resolve."""
    for line in text.splitlines():
        if CONFLICT_BEGIN_RE.match(line) or CONFLICT_END_RE.match(line):
            return True
    return False


async def attempt_merge(
    target_path: Path,
    source_session_id: str,
    source_branch: str,
) -> MergeResult:
    """Run `git fetch <fork-remote> && git merge`. Does NOT resolve
    conflicts — caller decides whether to invoke the LLM resolver and
    re-attempt the commit step.
    """
    try:
        await _stash_save(target_path)

        remote = _fork_remote_name(source_session_id)
        rc, _, err = await _run_git(target_path, "fetch", remote, check=False)
        if rc != 0:
            return MergeResult(status="failed", error=f"git fetch failed: {err}")

        rc, out, err = await _run_git(
            target_path,
            "merge",
            "--no-edit",
            "--no-ff",
            f"{remote}/{source_branch}",
            check=False,
        )
        if rc == 0:
            if "Already up to date" in out or "Already up-to-date" in out:
                return MergeResult(status="noop")
            _, sha, _ = await _run_git(target_path, "rev-parse", "HEAD")
            return MergeResult(status="merged", commit_sha=sha)

        # rc != 0 — could be conflicts. Collect them.
        rc2, files_str, _ = await _run_git(
            target_path,
            "diff",
            "--name-only",
            "--diff-filter=U",
            check=False,
        )
        conflicted = [
            line for line in files_str.splitlines() if line.strip()
        ] if rc2 == 0 else []
        if conflicted:
            return MergeResult(status="conflict", conflicted_files=conflicted)
        # No conflicts but merge still failed — surface the error.
        return MergeResult(status="failed", error=err or out)
    except Exception as e:
        logger.exception("attempt_merge failed")
        return MergeResult(status="failed", error=str(e))


_RESOLVE_SYSTEM_PROMPT = """\
You are resolving a git merge conflict. The user's file below contains \
standard `<<<<<<< / ======= / >>>>>>>` conflict markers. Your job is to \
output the FULL resolved file contents — no markers, no commentary, no \
markdown fences. Integrate both intents whenever that makes semantic \
sense; only drop one side if they're truly mutually exclusive. \
Preserve indentation, trailing newlines, and surrounding code unchanged.
"""


async def _llm_resolve_one_file(
    file_path: Path,
    target_summary: str,
    source_summary: str,
) -> Tuple[bool, Optional[str]]:
    """Send one conflicted file to Claude. Returns (ok, error_msg).
    On success the file's been rewritten in place to the resolved content."""
    from app.infrastructure.external.llm.claude_client import complete

    try:
        original = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"read failed: {e}"

    user_msg = (
        f"Target branch's recent intent:\n{target_summary}\n\n"
        f"Source branch's recent intent:\n{source_summary}\n\n"
        f"File: {file_path.name}\n\n"
        f"Conflicted content:\n```\n{original}\n```"
    )

    try:
        resp = await complete(
            messages=[{"role": "user", "content": user_msg}],
            system=[{"type": "text", "text": _RESOLVE_SYSTEM_PROMPT}],
            max_tokens=8000,
        )
    except Exception as e:
        return False, f"LLM call failed: {e}"

    # Pull plain text from the response. complete() returns model_dump
    # of the Anthropic Message; content is a list of blocks.
    content_blocks = resp.get("content", [])
    text = "".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    ).strip()
    if not text:
        return False, "LLM returned empty response"

    # Strip a stray markdown fence if the model included one despite
    # the system prompt. Defensive — matches ```lang\n ... ``` or ```\n ... ```.
    fence = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*)\n```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    if _has_conflict_markers(text):
        return False, "LLM left conflict markers in the output"

    try:
        file_path.write_text(text, encoding="utf-8")
    except Exception as e:
        return False, f"write failed: {e}"
    return True, None


async def resolve_conflicts_with_llm(
    target_path: Path,
    conflicted_files: List[str],
    target_summary: str = "",
    source_summary: str = "",
) -> Tuple[List[str], List[str]]:
    """Resolve each conflicted file via Claude. Stages successful ones
    via `git add`. Returns (resolved, unresolved) — caller commits if
    everything resolved.
    """
    resolved: List[str] = []
    unresolved: List[str] = []
    for rel in conflicted_files:
        abs_path = target_path / rel
        ok, err = await _llm_resolve_one_file(
            abs_path, target_summary, source_summary,
        )
        if ok:
            await _run_git(target_path, "add", "--", rel)
            resolved.append(rel)
            logger.info("LLM resolved merge conflict in %s", rel)
        else:
            unresolved.append(rel)
            logger.warning("LLM could not resolve %s: %s", rel, err)
    return resolved, unresolved


async def finalize_merge_commit(
    target_path: Path, message: str
) -> Optional[str]:
    """After conflicts are resolved + staged, finalize the merge commit.
    Returns the commit SHA on success, None on failure."""
    try:
        await _run_git(
            target_path, "commit", "-m", message, "--no-verify",
        )
        _, sha, _ = await _run_git(target_path, "rev-parse", "HEAD")
        return sha
    except Exception:
        logger.exception("finalize_merge_commit failed")
        return None


async def merge_session_with_resolve(
    target_path: Path,
    source_session_id: str,
    source_branch: str,
    target_summary: str = "",
    source_summary: str = "",
    plan_id_for_tag: Optional[str] = None,
) -> MergeResult:
    """End-to-end: try merge, if conflicts → LLM resolve → commit. If
    LLM can't resolve everything, leaves the working tree in conflict
    state (tells the caller via `unresolved_files`) so the user can
    finish manually inside the agent's shell.

    `plan_id_for_tag`, when provided, tags the resulting commit as
    `helix/plan/<short>` so the FE's PlanVersionBar treats it as a
    normal versioned snapshot.
    """
    result = await attempt_merge(target_path, source_session_id, source_branch)
    if result.status in ("merged", "noop", "failed"):
        if result.status == "merged" and plan_id_for_tag and result.commit_sha:
            try:
                await _run_git(
                    target_path, "tag", "-f", _tag_for(plan_id_for_tag),
                )
            except Exception:
                logger.exception("tag write for merge commit failed")
        return result

    # status == "conflict" — try LLM
    resolved, unresolved = await resolve_conflicts_with_llm(
        target_path, result.conflicted_files,
        target_summary=target_summary, source_summary=source_summary,
    )
    result.resolved_files = resolved
    result.unresolved_files = unresolved

    if unresolved:
        # Bail out — caller should surface the file list to the user.
        # We DON'T abort the merge, leaving the working tree mid-merge so
        # the user/agent can finish in shell. They'd see `git status`
        # showing the remaining conflicts.
        result.status = "conflict"
        return result

    sha = await finalize_merge_commit(
        target_path, f"Merge fork ({source_session_id[:8]}) with AI resolution",
    )
    if not sha:
        result.status = "failed"
        result.error = "commit failed after LLM resolve"
        return result
    if plan_id_for_tag:
        try:
            await _run_git(target_path, "tag", "-f", _tag_for(plan_id_for_tag))
        except Exception:
            logger.exception("tag write for merge commit failed")
    result.status = "resolved"
    result.commit_sha = sha
    return result


async def detect_branch(path: Path) -> str:
    return await _current_branch(path)
