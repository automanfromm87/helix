"""`complete_stream` must surface a stalled SSE stream as a transport
error within `llm_stream_idle_timeout` seconds — not hang forever waiting
for an upstream that's keeping the TCP connection alive without sending
data.

These tests exercise the production module's iteration loop directly with
a fake stream context manager.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest

from app.domain.services.agents.protection import LLMTransportError
from app.infrastructure.external.llm import claude_client


class _StalledStreamIter:
    """Async iterator whose `__anext__` never returns. Models a server
    that has gone silent mid-stream."""

    def __aiter__(self) -> "_StalledStreamIter":
        return self

    async def __anext__(self) -> Any:
        await asyncio.sleep(3600)  # never resolves


class _StalledStreamCtx:
    """Async context manager wrapping a stalled iterator."""

    async def __aenter__(self) -> "_StalledStreamCtx":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def __aiter__(self) -> _StalledStreamIter:
        return _StalledStreamIter()

    async def get_final_message(self) -> Any:  # pragma: no cover — never reached
        await asyncio.sleep(3600)


def _stalled_stream_ctx(**_kwargs: Any) -> _StalledStreamCtx:
    return _StalledStreamCtx()


class _FakeAnthropicClient:
    """Stand-in for `anthropic.AsyncAnthropic`: only the surfaces
    `complete_stream` touches."""

    def __init__(self) -> None:
        # `client.messages.stream` and `client.beta.messages.stream` are
        # what `complete_stream` invokes depending on context_management.
        class _Messages:
            stream = staticmethod(_stalled_stream_ctx)

        class _Beta:
            messages = _Messages()

        self.messages = _Messages()
        self.beta = _Beta()


@pytest.mark.asyncio
async def test_streaming_idle_timeout_raises_transport_error() -> None:
    """Stalled stream must raise `LLMTransportError` close to the
    configured idle-timeout — not the SDK's much longer transport
    timeout. The error is retryable so the protection layer can
    recover the agent loop."""
    fake_settings = type("S", (), {
        "llm_stream_idle_timeout": 0.3,
        "llm_stream_first_byte_timeout": 5.0,  # high → idle fires first
        "llm_request_timeout": 300.0,
        "llm_stream_total_timeout": 300.0,
        "model_name": "claude-test",
        "max_tokens": 1024,
        "temperature": 0.7,
    })()

    with patch.object(claude_client, "get_settings", return_value=fake_settings), \
         patch.object(claude_client, "get_async_client", return_value=_FakeAnthropicClient()), \
         patch.object(claude_client, "_record_error", new=_async_noop):
        started = time.monotonic()
        with pytest.raises(LLMTransportError) as exc_info:
            async for _ in claude_client.complete_stream(messages=[{"role": "user", "content": "hi"}]):
                pass
        elapsed = time.monotonic() - started

    # Should fire within ~2x the idle timeout (slack for asyncio scheduling).
    assert elapsed < 1.5, f"timeout took {elapsed:.2f}s, idle_timeout=0.3s"
    assert "idle" in str(exc_info.value).lower()
    assert exc_info.value.retryable is True


async def _async_noop(*_args: Any, **_kwargs: Any) -> None:
    return None


class _StalledOpeningStreamCtx:
    """Stream context whose `__aenter__` never returns — models a server
    that accepts the TCP connection but never sends response headers /
    first byte (proxy queueing, big-cache compute, etc.)."""

    async def __aenter__(self) -> Any:
        await asyncio.sleep(3600)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _stalled_opening_stream_ctx(**_kwargs: Any) -> _StalledOpeningStreamCtx:
    return _StalledOpeningStreamCtx()


class _FakeOpeningStallClient:
    def __init__(self) -> None:
        class _Messages:
            stream = staticmethod(_stalled_opening_stream_ctx)

        class _Beta:
            messages = _Messages()

        self.messages = _Messages()
        self.beta = _Beta()


@pytest.mark.asyncio
async def test_streaming_first_byte_timeout_raises_transport_error() -> None:
    """Stream that never opens (server hangs before first byte) must
    raise within `first_byte_timeout` — not wait for the SDK's much
    longer connect/read timeout."""
    fake_settings = type("S", (), {
        "llm_stream_idle_timeout": 60.0,  # high → first_byte fires first
        "llm_stream_first_byte_timeout": 0.3,
        "llm_request_timeout": 300.0,
        "llm_stream_total_timeout": 300.0,
        "model_name": "claude-test",
        "max_tokens": 1024,
        "temperature": 0.7,
    })()

    with patch.object(claude_client, "get_settings", return_value=fake_settings), \
         patch.object(claude_client, "get_async_client", return_value=_FakeOpeningStallClient()), \
         patch.object(claude_client, "_record_error", new=_async_noop):
        started = time.monotonic()
        with pytest.raises(LLMTransportError) as exc_info:
            async for _ in claude_client.complete_stream(messages=[{"role": "user", "content": "hi"}]):
                pass
        elapsed = time.monotonic() - started

    assert elapsed < 1.5, f"timeout took {elapsed:.2f}s, first_byte=0.3s"
    assert "first-byte" in str(exc_info.value).lower()
    assert exc_info.value.retryable is True
