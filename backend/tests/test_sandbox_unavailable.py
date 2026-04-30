"""Sandbox-unavailable failure-mode tests.

The sandbox container can disappear mid-session (operator action, OOM-kill,
network blip). When that happens we expect:

  1. `_SafeSandboxClient.post` raises `SandboxUnavailableError` instead of
     httpx.ConnectError.
  2. The agent's `_invoke_tool_with_retries` short-circuits — no sleep, no
     burned retries, just a clean `ToolResult(success=False)`.
  3. The FastAPI handler returns 503 + `Retry-After`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.application.errors.exceptions import (
    SandboxUnavailableError,
    ServiceUnavailableError,
)
from app.domain.models.tool_result import ToolResult


# ---------------------------------------------------------------------------
# _SafeSandboxClient: connect failures must surface as SandboxUnavailableError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("Name or service not known"),
        httpx.ConnectTimeout("connect timed out"),
    ],
)
def test_safe_client_translates_connect_failures(exc: BaseException) -> None:
    from app.infrastructure.external.sandbox.docker_sandbox import _SafeSandboxClient

    class _StubClient:
        async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
            raise exc

        async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
            raise exc

        async def aclose(self) -> None:
            pass

    safe = _SafeSandboxClient(_StubClient(), sandbox_id="test")

    with pytest.raises(SandboxUnavailableError) as excinfo:
        asyncio.run(safe.post("http://nope/"))
    assert "test" in excinfo.value.msg
    assert excinfo.value.status_code == 503
    assert excinfo.value.retry_after >= 1
    # Original cause preserved for diagnostics.
    assert excinfo.value.__cause__ is exc


def test_safe_client_passes_through_other_exceptions() -> None:
    """Read timeouts, JSON errors, and HTTP 5xx bodies must NOT be classified
    as 'sandbox down' — those are different failure modes."""
    from app.infrastructure.external.sandbox.docker_sandbox import _SafeSandboxClient

    class _StubClient:
        async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ReadTimeout("slow sandbox")

        async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ReadTimeout("slow sandbox")

        async def aclose(self) -> None:
            pass

    safe = _SafeSandboxClient(_StubClient(), sandbox_id="test")
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(safe.post("http://nope/"))


# ---------------------------------------------------------------------------
# Agent loop: short-circuit on ServiceUnavailableError
# ---------------------------------------------------------------------------


def test_invoke_tool_short_circuits_on_service_unavailable() -> None:
    """No retries, no sleeps — return immediately as a failed ToolResult so
    LoopGuard can detect the streak and abort."""
    from app.domain.services.agents.base import BaseAgent

    class _StubTool:
        name = "stub"

        async def ainvoke(self, args: Any) -> ToolResult:
            raise SandboxUnavailableError("stub down")

    class _StubAgent(BaseAgent):
        def __init__(self) -> None:
            self.max_retries = 3
            self.retry_interval = 9999.0  # would explode if we burned retries

    agent = _StubAgent()
    tool = _StubTool()

    # If we burned retries with retry_interval=9999 the test would hang.
    result = asyncio.run(asyncio.wait_for(
        agent._invoke_tool_with_retries(tool, {}), timeout=2.0
    ))

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "Sandbox is unavailable" in (result.message or "")


# ---------------------------------------------------------------------------
# Type hierarchy sanity
# ---------------------------------------------------------------------------


def test_sandbox_unavailable_is_503_with_retry_after() -> None:
    err = SandboxUnavailableError("foo")
    assert isinstance(err, ServiceUnavailableError)
    assert err.status_code == 503
    assert err.retry_after >= 1
    assert "foo" in err.msg
