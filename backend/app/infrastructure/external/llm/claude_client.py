"""Anthropic client wrapper (no langchain).

Exposes:

  * get_async_client()  — singleton AsyncAnthropic. Reads `llm_proxy_address`
                          and `agent_llm_base_url` from settings; both are
                          optional and default to direct upstream access.
  * complete()          — thin wrapper around messages.create that records
                          token / latency telemetry and returns the raw
                          Anthropic response payload as a dict.

Long-running properties enabled by default:
  * `betas=["context-management-2025-06-27"]` so the API can clear stale
    tool_use/tool_result blocks server-side.
  * Per-call `context_management` policy passed by callers (BaseAgent).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from functools import lru_cache
from typing import Any, AsyncGenerator, Dict, List, Optional

import anthropic
import httpx

from app.core.config import get_settings
from app.domain.services.agents.protection import LLMTransportError

logger = logging.getLogger(__name__)


CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"


def _build_async_http_client(
    proxy_address: str, timeout_seconds: float
) -> httpx.AsyncClient:
    """Build an httpx client honoring an optional outbound proxy. Empty
    `proxy_address` skips the proxy entirely (direct upstream)."""
    timeout = httpx.Timeout(timeout_seconds)
    if proxy_address:
        return httpx.AsyncClient(
            proxy=f"http://{proxy_address}", verify=False, timeout=timeout,
        )
    return httpx.AsyncClient(timeout=timeout)


@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    http_client = _build_async_http_client(
        settings.llm_proxy_address, settings.llm_request_timeout
    )
    headers = settings.extra_headers or {}
    kwargs: Dict[str, Any] = {
        "api_key": settings.llm_api_key or "missing",
        "default_headers": headers,
        "http_client": http_client,
    }
    if settings.agent_llm_base_url:
        kwargs["base_url"] = settings.agent_llm_base_url
    return anthropic.AsyncAnthropic(**kwargs)


def _model_rejects_temperature(model_name: str) -> bool:
    """Newer Claude models (opus 4.7+) 400 on `temperature`. Skip the param
    for those — defaults are fine."""
    name = (model_name or "").lower()
    return "opus-4-7" in name


async def complete(
    *,
    messages: List[Dict[str, Any]],
    system: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Dict[str, Any]] = None,
    context_management: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Single Messages API turn. Returns the response as a dict (model_dump).

    All long-running specifics — caching, context_management — are decided by
    the caller (BaseAgent). This wrapper just dispatches and records telemetry.
    """
    settings = get_settings()
    client = get_async_client()

    params: Dict[str, Any] = {
        "model": model or settings.model_name,
        "max_tokens": max_tokens or settings.max_tokens,
        "messages": messages,
    }
    if system:
        params["system"] = system
    if tools:
        params["tools"] = tools
    if tool_choice:
        params["tool_choice"] = tool_choice
    if context_management:
        params["context_management"] = context_management
        params["betas"] = [CONTEXT_MANAGEMENT_BETA]
        api_call = client.beta.messages.create
    else:
        api_call = client.messages.create
    if not _model_rejects_temperature(params["model"]):
        params["temperature"] = settings.temperature

    started = time.monotonic()
    try:
        resp = await api_call(**params)
    except Exception as exc:
        await _record_error(params["model"], started, exc)
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    payload = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    usage = payload.get("usage") or {}
    await _record_telemetry(
        model=params["model"],
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        latency_ms=latency_ms,
        error=None,
    )
    return payload


async def _record_telemetry(**kwargs: Any) -> None:
    # Lazy import to avoid hard dependency on the SQL session at import time.
    from app.infrastructure.external.llm.telemetry import record_llm_call

    await record_llm_call(**kwargs)


async def _record_error(model: str, started: float, exc: BaseException) -> None:
    """Record a failed LLM call. Shared by `complete()` and `complete_stream()`."""
    latency_ms = int((time.monotonic() - started) * 1000)
    await _record_telemetry(
        model=model,
        tokens_in=0,
        tokens_out=0,
        latency_ms=latency_ms,
        error=f"{type(exc).__name__}: {exc}"[:2000],
    )


async def complete_stream(
    *,
    messages: List[Dict[str, Any]],
    system: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Dict[str, Any]] = None,
    context_management: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Streaming Messages API turn.

    Yields:
      * `{"type": "text_delta", "text": <chunk>, "accumulated": <so far>}`
      * `{"type": "final", "payload": <full message dict>}`

    Telemetry is recorded once on stream completion (or on error). Tool
    use blocks aren't surfaced as deltas — they only matter complete, and
    the final payload carries them.
    """
    settings = get_settings()
    client = get_async_client()

    params: Dict[str, Any] = {
        "model": model or settings.model_name,
        "max_tokens": max_tokens or settings.max_tokens,
        "messages": messages,
    }
    if system:
        params["system"] = system
    if tools:
        params["tools"] = tools
    if tool_choice:
        params["tool_choice"] = tool_choice
    if context_management:
        params["context_management"] = context_management
        params["betas"] = [CONTEXT_MANAGEMENT_BETA]
        stream_ctx = client.beta.messages.stream
    else:
        stream_ctx = client.messages.stream
    if not _model_rejects_temperature(params["model"]):
        params["temperature"] = settings.temperature

    started = time.monotonic()
    idle_timeout = settings.llm_stream_idle_timeout
    first_byte_timeout = settings.llm_stream_first_byte_timeout
    # Don't repeatedly join the chunk list — quadratic on large outputs.
    # Consumers that need the prefix can compute it themselves; emitting the
    # incremental chunk is enough for streamed UI rendering.
    #
    # Two timeouts cover the two stall modes Anthropic streams can hit:
    #   * `first_byte_timeout` — `__aenter__()` hung: server hasn't even
    #     accepted the request yet (proxy issue, queueing, big-cache key
    #     compute, etc.).
    #   * `idle_timeout` — stream open but server gone silent mid-response.
    # `AsyncExitStack` ensures the stream is properly closed if either
    # timeout fires, so we don't leak the underlying httpx connection.
    try:
        async with AsyncExitStack() as stack:
            try:
                stream = await asyncio.wait_for(
                    stack.enter_async_context(stream_ctx(**params)),
                    timeout=first_byte_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise LLMTransportError(
                    f"first-byte idle for >{first_byte_timeout:.0f}s",
                    cause=exc,
                ).with_retry_after(2.0)

            stream_iter = stream.__aiter__()
            while True:
                try:
                    event = await asyncio.wait_for(
                        stream_iter.__anext__(), timeout=idle_timeout,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise LLMTransportError(
                        f"streaming idle for >{idle_timeout:.0f}s",
                        cause=exc,
                    ).with_retry_after(2.0)
                if getattr(event, "type", None) != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                if delta is None or getattr(delta, "type", None) != "text_delta":
                    continue
                chunk = getattr(delta, "text", "") or ""
                if chunk:
                    yield {"type": "text_delta", "text": chunk}
            try:
                final_msg = await asyncio.wait_for(
                    stream.get_final_message(), timeout=idle_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise LLMTransportError(
                    f"final-message idle for >{idle_timeout:.0f}s",
                    cause=exc,
                ).with_retry_after(2.0)
        payload = (
            final_msg.model_dump() if hasattr(final_msg, "model_dump") else dict(final_msg)
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        # SDK stream-parser asserts on rare unexpected payloads; log the
        # full traceback so it's diagnosable, but still flow into the
        # standard telemetry-and-raise path. Upstream classifier treats it
        # as a short-retry transport hiccup.
        if isinstance(exc, AssertionError):
            logger.exception(
                "complete_stream AssertionError after %dms (model=%s)",
                latency_ms, params["model"],
            )
        await _record_error(params["model"], started, exc)
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    usage = payload.get("usage") or {}
    await _record_telemetry(
        model=params["model"],
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        latency_ms=latency_ms,
        error=None,
    )
    yield {"type": "final", "payload": payload}


async def complete_text(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> str:
    """One-shot text completion helper used outside the agent loop
    (e.g. browser content extraction). No tools, no caching."""
    sys_blocks = [{"type": "text", "text": system}] if system else None
    payload = await complete(
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        system=sys_blocks,
        max_tokens=max_tokens,
        model=model,
    )
    return "".join(
        b.get("text", "")
        for b in (payload.get("content") or [])
        if b.get("type") == "text"
    )
