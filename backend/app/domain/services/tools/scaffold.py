"""Helix scaffold toolkit — exposes `helixcli` as the agent's first move.

The agent should call this BEFORE reaching for `file_write` on any
greenfield project request. helixcli ships baked into the sandbox image
and emits byte-stable scaffolds; this tool is the deterministic baseline
on top of which the agent adds custom code.

Lifecycle helpers (`install`, `up`, `down`) are intentionally excluded —
in production sandboxes supervisord owns dev-server lifecycle, and
`helixcli install` would race against the auto-runner.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import uuid
from typing import Any, Literal, Optional

from app.domain.constants import SANDBOX_PROJECT_DIR
from app.domain.external.sandbox import Sandbox
from app.domain.models.tool_result import ToolResult
from app.domain.services.tools.base import BaseToolkit, tool

logger = logging.getLogger(__name__)


SCAFFOLD_TOOLKIT_NAME = "helix_scaffold"

# Whitelist — install/up/down are supervisord's job, not the agent's.
_ALLOWED_ACTIONS = {
    "init",       # scaffold the monorepo
    "page",       # routed React page + test + <Route> wiring
    "endpoint",   # FastAPI handler + Pydantic schemas + httpx test
    "migration",  # alembic revision --autogenerate
    "component",  # React component (no routing)
    "hook",       # React custom hook
    "model",      # SQLAlchemy ORM model
}

# Marker the wrapper command echoes around helixcli's JSON line so we can
# extract it cleanly from the shell session's interleaved output (prompt,
# command echo, etc.). UUID-suffixed so we never collide with user text.
_BEGIN_MARKER = "__HELIX_SCAFFOLD_BEGIN__"
_END_MARKER = "__HELIX_SCAFFOLD_END__"


class ScaffoldToolkit(BaseToolkit):
    """Deterministic scaffolder. Wraps the `helixcli` binary."""

    name: str = SCAFFOLD_TOOLKIT_NAME

    def __init__(self, sandbox: Sandbox) -> None:
        super().__init__()
        self.sandbox = sandbox
        # Per-toolkit lock to serialise helixcli invocations. The CLI's
        # generators each touch `.git/index` (git add + commit) — running
        # two in parallel collides on `.git/index.lock`. Anthropic emits
        # parallel tool_use blocks freely, so we MUST serialise here even
        # though the agent's coroutine model is single-threaded.
        self._lock = asyncio.Lock()

    @tool
    async def helix_scaffold(
        self,
        action: Literal[
            "init", "page", "endpoint", "migration",
            "component", "hook", "model",
        ],
        args: Optional[Any] = None,
    ) -> ToolResult:
        """Run the deterministic project scaffolder. Prefer this over
        `file_write` for any of the seven supported actions — generators
        emit byte-stable templates, update `.helix/manifest.json`, and
        auto-commit, which keeps the diff view clean.

        Actions and their args (positional, in order):
          - init [--frontend-only|--backend-only] [--db postgres|sqlite]
            Scaffold the monorepo. Call this first on any greenfield task.
            Pass NO project name — init runs in cwd.
          - page <PascalName>
            Add a frontend page + Vitest + router wiring (best-effort).
            Use this for top-level routed pages (Login, Dashboard, etc.).
          - component <PascalName>
            Add a presentational React component + test under components/.
            Use this for non-routed UI (PostCard, Modal, NavBar, etc.).
          - hook <PascalName>
            Add a custom React hook + test. The generator prepends 'use':
            pass 'Posts' to get usePosts.ts. Use for stateful logic
            shared across components.
          - endpoint <METHOD> <path> [--auth required|public]
            Add a FastAPI handler + Pydantic schemas + pytest. METHOD is
            GET/POST/PATCH/DELETE; path like /api/v1/auth/login.
          - model <PascalName>
            Add a SQLAlchemy ORM model. File path is snake_case (User →
            user.py); table is plural snake_case (users). Auto-registered
            in models/__init__.py so Alembic autogenerate picks it up.
          - migration <snake_case_name>
            Run alembic revision --autogenerate. Call AFTER model changes.

        Returns the CLI's parsed stdout JSON (paths created + manifest).
        On generator failure (exit 64–70) returns success=False with the
        CLI's error JSON in `data` and the exit_code in `code`.

        Args:
            action: One of init / page / component / hook / endpoint /
              model / migration.
            args: Positional args + flags for the action, as a list of
              strings (e.g. ["POST", "/api/v1/auth/login", "--auth", "public"]).
        """
        if action not in _ALLOWED_ACTIONS:
            return ToolResult(
                success=False,
                message=f"Unknown action {action!r}. Allowed: {sorted(_ALLOWED_ACTIONS)}",
                code="invalid_action",
            )

        # Some LLMs serialise list-typed tool args as a JSON string instead
        # of a real list. Accept either shape so the agent's first scaffold
        # call doesn't burn a turn on a parse error.
        normalised: list[str]
        if args is None:
            normalised = []
        elif isinstance(args, list):
            normalised = [str(a) for a in args]
        elif isinstance(args, str):
            stripped = args.strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    normalised = [str(a) for a in parsed]
                else:
                    normalised = shlex.split(stripped)
            else:
                normalised = shlex.split(stripped)
        else:
            return ToolResult(
                success=False,
                message=f"args must be a list or string, got {type(args).__name__}",
                code="invalid_args",
            )

        # Hard guard: helixcli init's optional NAME arg creates a subdirectory
        # like /home/ubuntu/project/<name>/, which the supervisord dev-runner
        # can't see (it watches /home/ubuntu/project/ for package.json).
        # Models routinely ignore the skill's "args=[]" instruction and pass
        # their app name anyway. Strip non-flag positionals before exec — the
        # right behaviour every time on this sandbox.
        if action == "init" and normalised:
            stripped_names = [a for a in normalised if not a.startswith("-")]
            if stripped_names:
                logger.info(
                    "helix_scaffold init: dropping positional name(s) %r — "
                    "init must run in cwd /home/ubuntu/project/, not a subdir",
                    stripped_names,
                )
                normalised = [a for a in normalised if a.startswith("-")]

        argv = [shlex.quote(str(a)) for a in normalised]
        helixcli_cmd = " ".join(["helixcli", action, *argv])
        # Wrap so we can recover the JSON line + exit code unambiguously
        # from the shell session's free-form output.
        wrapped = (
            f"echo {_BEGIN_MARKER}; "
            f"{helixcli_cmd}; "
            f"_rc=$?; "
            f"echo {_END_MARKER}EXIT=$_rc"
        )

        # Serialise concurrent invocations — Anthropic dispatches parallel
        # tool_use blocks freely and helixcli generators each `git add +
        # commit`, which collides on `.git/index.lock`. The lock is
        # per-toolkit-instance which is per-session via the flow, so two
        # different sessions still get to scaffold concurrently.
        async with self._lock:
            session_id = f"helix-scaffold-{uuid.uuid4().hex[:8]}"
            exec_result = await self.sandbox.exec_command(
                session_id=session_id,
                exec_dir=SANDBOX_PROJECT_DIR,
                command=wrapped,
            )

            if not exec_result.success:
                return ToolResult(
                    success=False,
                    message=f"helixcli exec failed: {exec_result.message or 'unknown'}",
                    code=exec_result.code or "exec_failed",
                )

            output = _extract_output_text(exec_result.data)
            payload, exit_code = _parse_wrapped_output(output)

            # `migration` (and a cold `init`) shell out to uv / alembic,
            # which can exceed the sandbox's exec_command poll window —
            # exec_result then carries status="running" with no end marker
            # yet. Re-view the shell session until the marker arrives (or
            # we hit the bound). Held under the lock so a concurrent call
            # can't start git work while we're still polling.
            if exit_code is None:
                for _ in range(30):  # 30 × 1s ≈ 30s ceiling
                    await asyncio.sleep(1)
                    view = await self.sandbox.view_shell(session_id)
                    if view and view.success and view.data:
                        output = view.data.get("output") or output
                        payload, exit_code = _parse_wrapped_output(output)
                        if exit_code is not None:
                            break

            if exit_code is None:
                return ToolResult(
                    success=False,
                    message=(
                        "Could not parse helixcli output (no end marker). "
                        "Raw output truncated below.\n" + output[-500:]
                    ),
                    code="parse_failed",
                )

            if payload is None:
                return ToolResult(
                    success=False,
                    message=(
                        f"helixcli exited {exit_code} but produced no JSON. "
                        "Raw output:\n" + output[-500:]
                    ),
                    code=f"exit_{exit_code}",
                )

            if exit_code != 0:
                return ToolResult(
                    success=False,
                    message=payload.get("message")
                    or payload.get("error")
                    or f"helixcli {action} failed (exit {exit_code})",
                    data=payload,
                    code=f"exit_{exit_code}",
                )

            return ToolResult(success=True, data=payload)


def _extract_output_text(data: Any) -> str:
    """Pull the console output text out of `exec_command`'s ToolResult.data."""
    if data is None:
        return ""
    if isinstance(data, dict):
        return data.get("output") or ""
    output = getattr(data, "output", None)
    return output or ""


def _parse_wrapped_output(output: str) -> tuple[Optional[dict], Optional[int]]:
    """Find the JSON payload + exit code between our markers.

    Returns (payload_or_None, exit_code_or_None). exit_code is None when
    we couldn't locate the end marker at all (likely means the command
    timed out or the shell got disrupted).
    """
    end_match = re.search(rf"{re.escape(_END_MARKER)}EXIT=(\d+)", output)
    if not end_match:
        return None, None
    exit_code = int(end_match.group(1))

    begin_idx = output.rfind(_BEGIN_MARKER)
    if begin_idx == -1:
        between = output[: end_match.start()]
    else:
        between = output[begin_idx + len(_BEGIN_MARKER) : end_match.start()]

    # helixcli emits exactly one JSON object on stdout — find the last
    # line that parses as JSON (ignoring command echoes / prompts).
    payload: Optional[dict] = None
    for line in reversed(between.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break
    return payload, exit_code
