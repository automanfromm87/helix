"""Tests for `WorkspaceSurveyor` and the planner-prompt cache path.

The surveyor is the only thing pre-feeding code context to the planner, so
the contract is narrow but load-bearing: empty workspace must NOT trigger
an LLM call, a populated workspace must call complete_text exactly once,
and the cache check in `PlanActFlow._ensure_workspace_summary` must
distinguish "never generated" (NULL → regen) from "generated and empty"
(`""` → reuse).
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.constants import SANDBOX_PROJECT_DIR
from app.domain.external.llm import LLM
from app.domain.models.tool_result import ToolResult
from app.domain.services.workspace_surveyor import (
    SURVEYOR_SHELL_ID,
    WorkspaceSurveyor,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _StubSandbox:
    """Minimal Sandbox surface — only the calls the surveyor uses."""

    def __init__(self, output: Optional[str], success: bool = True) -> None:
        if output is None:
            self._result = ToolResult(success=success)
        else:
            self._result = ToolResult(success=success, data={"output": output})
        self.calls: list[tuple[str, str, str]] = []

    async def exec_command(
        self, session_id: str, exec_dir: str, command: str
    ) -> ToolResult:
        self.calls.append((session_id, exec_dir, command))
        return self._result


class _FakeLLM(LLM):
    """In-memory LLM stand-in. `complete_text_impl` lets each test
    inject the response (return value or raised exception)."""

    def __init__(self, complete_text_impl=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._impl = complete_text_impl

    async def complete_stream(self, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        if False:
            yield  # pragma: no cover - Protocol shape only
        raise NotImplementedError("complete_stream not used in surveyor tests")

    async def complete_text(self, prompt: str, **kwargs) -> str:
        self.calls.append((prompt, kwargs))
        if self._impl is None:
            return ""
        if isinstance(self._impl, BaseException):
            raise self._impl
        if callable(self._impl):
            return await self._impl(prompt, **kwargs) if hasattr(self._impl, "__await__") or _is_coro(self._impl) else self._impl(prompt, **kwargs)
        return self._impl


def _is_coro(fn):
    import inspect
    return inspect.iscoroutinefunction(fn)


# ---------------------------------------------------------------------------
# WorkspaceSurveyor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_workspace_returns_empty_string_no_llm_call() -> None:
    """find produces nothing → don't call the LLM at all."""
    sandbox = _StubSandbox(output="")
    llm = _FakeLLM(complete_text_impl=AssertionError("LLM must not be called"))
    surveyor = WorkspaceSurveyor(llm)

    result = await surveyor.summarize(sandbox)

    assert result == ""
    assert llm.calls == []
    # Sandbox was probed exactly once with the dedicated surveyor shell id.
    assert len(sandbox.calls) == 1
    assert sandbox.calls[0][0] == SURVEYOR_SHELL_ID
    assert SANDBOX_PROJECT_DIR in sandbox.calls[0][2]


@pytest.mark.asyncio
async def test_non_empty_workspace_calls_llm_once() -> None:
    sandbox = _StubSandbox(
        output="=== TREE ===\n/home/ubuntu/project\n/home/ubuntu/project/package.json\n"
    )
    llm = _FakeLLM(complete_text_impl="# Brief\n\n- src/ — code\n")
    surveyor = WorkspaceSurveyor(llm)

    result = await surveyor.summarize(sandbox)

    assert result == "# Brief\n\n- src/ — code"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_llm_failure_is_swallowed() -> None:
    """A summarizer failure must NOT propagate — planning still proceeds."""
    sandbox = _StubSandbox(output="some content")
    llm = _FakeLLM(complete_text_impl=RuntimeError("rate limited"))
    surveyor = WorkspaceSurveyor(llm)

    result = await surveyor.summarize(sandbox)

    assert result == ""


@pytest.mark.asyncio
async def test_exec_command_failure_is_swallowed() -> None:
    sandbox = MagicMock()
    sandbox.exec_command = AsyncMock(side_effect=RuntimeError("sandbox gone"))
    surveyor = WorkspaceSurveyor(_FakeLLM())

    result = await surveyor.summarize(sandbox)
    assert result == ""


@pytest.mark.asyncio
async def test_oversized_raw_is_truncated_before_llm() -> None:
    """Don't blow up the LLM payload on a megabyte of `find` output."""
    huge = "x" * 50_000
    sandbox = _StubSandbox(output=huge)
    llm = _FakeLLM(complete_text_impl="ok")
    surveyor = WorkspaceSurveyor(llm)

    await surveyor.summarize(sandbox)

    # Prompt body is well under the raw `huge` length — truncation kicked in.
    assert len(llm.calls) == 1
    prompt = llm.calls[0][0]
    assert "(truncated)" in prompt
    assert len(prompt) < 25_000


# ---------------------------------------------------------------------------
# PlanActFlow cache distinguishes NULL from "" — regenerated only when NULL.
# ---------------------------------------------------------------------------


def _bare_flow():
    """A PlanActFlow stripped of its heavy collaborators — only the bits
    `_ensure_workspace_summary` touches are wired up."""
    from app.domain.services.flows.plan_act import PlanActFlow

    flow = PlanActFlow.__new__(PlanActFlow)
    flow._session_id = "s1"
    flow._sandbox = MagicMock()
    flow._session_repository = MagicMock()
    flow._session_repository.update_workspace_summary = AsyncMock()
    flow._surveyor = MagicMock()
    return flow


@pytest.mark.asyncio
async def test_cache_reuses_empty_string_no_regeneration() -> None:
    """Workspace_summary == "" means "we surveyed and there's no code".
    Re-surveying every plan would defeat the cache for non-code chats."""
    flow = _bare_flow()
    flow._surveyor.summarize = AsyncMock(
        side_effect=AssertionError("Should not regenerate when cached")
    )

    result = await flow._ensure_workspace_summary("")

    assert result == ""
    flow._session_repository.update_workspace_summary.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_runs_surveyor_and_persists() -> None:
    flow = _bare_flow()
    flow._surveyor.summarize = AsyncMock(return_value="# brief")

    result = await flow._ensure_workspace_summary(None)

    assert result == "# brief"
    flow._surveyor.summarize.assert_awaited_once()
    flow._session_repository.update_workspace_summary.assert_awaited_once_with(
        "s1", "# brief"
    )


@pytest.mark.asyncio
async def test_cache_persists_empty_after_first_survey() -> None:
    """First survey returns "" → that empty value gets cached, not NULL,
    so subsequent plans don't re-survey."""
    flow = _bare_flow()
    flow._surveyor.summarize = AsyncMock(return_value="")

    result = await flow._ensure_workspace_summary(None)

    assert result == ""
    flow._session_repository.update_workspace_summary.assert_awaited_once_with(
        "s1", ""
    )
