"""Records every Claude API call to `llm_calls`.

The previous langchain callback handler is gone — telemetry is now a single
async function the client wrapper calls directly after each request.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.infrastructure.logging import _session_id_var, _user_id_var
from app.infrastructure.models.sql import LLMCallRow

logger = logging.getLogger(__name__)


async def record_llm_call(
    *,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    error: Optional[str],
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    session_id = _session_id_var.get()
    user_id = _user_id_var.get()
    # Anthropic's `input_tokens` is freshly-billed input only; `cache_read`
    # and `cache_creation` are reported separately. The total input the
    # model actually saw is the sum of all three.
    total_in = tokens_in + cache_read_tokens + cache_creation_tokens
    cache_hit_pct = (
        round(100.0 * cache_read_tokens / total_in, 1) if total_in else 0.0
    )
    log_payload = {
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_read": cache_read_tokens,
        "cache_creation": cache_creation_tokens,
        "cache_hit_pct": cache_hit_pct,
        "latency_ms": latency_ms,
        "error": error,
    }
    if error:
        logger.warning("llm_call", extra=log_payload)
    else:
        logger.info("llm_call", extra=log_payload)

    # Telemetry is observational — never let DB issues kill the LLM call.
    try:
        from app.infrastructure.storage.postgres import get_postgres

        async with get_postgres().session_factory() as db:
            db.add(
                LLMCallRow(
                    session_id=session_id,
                    user_id=user_id,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    latency_ms=latency_ms,
                    error=error,
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to persist LLM telemetry row")
