"""Telemetry: cache_hit_pct formula + structured log payload."""

from __future__ import annotations

import logging

import pytest

from app.infrastructure.external.llm.telemetry import record_llm_call


@pytest.mark.asyncio
async def test_cache_hit_pct_uses_total_input(caplog) -> None:
    """tokens_in is FRESHLY-billed input only — Anthropic reports
    cache_read and cache_creation separately. Hit rate must be relative
    to the model's total seen prompt: tokens_in + cache_read + cache_creation."""
    caplog.set_level(logging.INFO, logger="app.infrastructure.external.llm.telemetry")

    # Simulate a typical cached-prefix call: 4441 fresh + 5968 cache_read.
    # Old broken formula would give 100*5968/4441 = 134.4%. New formula:
    # 100*5968/(4441+5968+0) = 57.3%.
    await record_llm_call(
        model="claude-opus-4-7",
        tokens_in=4441,
        tokens_out=200,
        cache_read_tokens=5968,
        cache_creation_tokens=0,
        latency_ms=10,
        error=None,
    )

    payload = next(
        rec for rec in caplog.records if getattr(rec, "msg", None) == "llm_call"
    )
    assert hasattr(payload, "cache_hit_pct")
    assert payload.cache_hit_pct == pytest.approx(57.3, rel=0.01)
    assert payload.cache_hit_pct <= 100.0


@pytest.mark.asyncio
async def test_cache_hit_pct_zero_when_no_cache(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.infrastructure.external.llm.telemetry")
    await record_llm_call(
        model="claude-opus-4-7",
        tokens_in=1000,
        tokens_out=50,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        latency_ms=5,
        error=None,
    )
    payload = next(
        rec for rec in caplog.records if getattr(rec, "msg", None) == "llm_call"
    )
    assert payload.cache_hit_pct == 0.0


@pytest.mark.asyncio
async def test_cache_hit_pct_zero_when_no_input(caplog) -> None:
    """Guard against divide-by-zero when the call errored before any tokens
    came back."""
    caplog.set_level(logging.WARNING, logger="app.infrastructure.external.llm.telemetry")
    await record_llm_call(
        model="claude-opus-4-7",
        tokens_in=0,
        tokens_out=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        latency_ms=1,
        error="boom",
    )
    payload = next(
        rec for rec in caplog.records if getattr(rec, "msg", None) == "llm_call"
    )
    assert payload.cache_hit_pct == 0.0
