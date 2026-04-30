"""Tests for the unified LLM error-handling layer in `agents.protection`.

Goal: every common Anthropic SDK failure mode maps to the right typed
domain error, with the right retry decision and the right `Retry-After`
behavior.
"""

from __future__ import annotations

from typing import Any

import anthropic
import httpx
import pytest

from app.domain.services.agents.protection import (
    LLMAuthError,
    LLMBadRequestError,
    LLMContextWindowError,
    LLMError,
    LLMNotFoundError,
    LLMOverloadedError,
    LLMRateLimitError,
    LLMServerError,
    LLMTransportError,
    ModelRefusalError,
    classify_api_exception,
    is_pause_turn,
    is_refusal,
    is_truncated,
    refusal_text,
    should_retry,
)


# ---------------------------------------------------------------------------
# Helpers — fabricate Anthropic SDK exceptions with a Retry-After header.
# ---------------------------------------------------------------------------


def _fake_response(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return httpx.Response(
        status_code=status,
        headers=headers,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def _make(cls: type[anthropic.APIStatusError], status: int, msg: str = "boom",
          retry_after: str | None = None) -> anthropic.APIStatusError:
    return cls(message=msg, response=_fake_response(status, retry_after), body=None)


# ---------------------------------------------------------------------------
# Classification: each Anthropic error → the right typed bucket
# ---------------------------------------------------------------------------


def test_rate_limit_classified_with_retry_after_from_header() -> None:
    err = classify_api_exception(_make(anthropic.RateLimitError, 429, retry_after="7"))
    assert isinstance(err, LLMRateLimitError)
    assert err.retryable is True
    assert err.retry_after_seconds == pytest.approx(7.0)


def test_rate_limit_falls_back_to_default_retry_after_when_missing() -> None:
    err = classify_api_exception(_make(anthropic.RateLimitError, 429))
    assert isinstance(err, LLMRateLimitError)
    assert err.retry_after_seconds >= 1.0  # default


def test_overloaded_529_uses_overloaded_class() -> None:
    err = classify_api_exception(_make(anthropic.APIStatusError, 529))
    assert isinstance(err, LLMOverloadedError)
    assert err.retryable is True


def test_5xx_classified_as_server_error() -> None:
    err = classify_api_exception(_make(anthropic.InternalServerError, 500))
    assert isinstance(err, LLMServerError)
    assert err.retryable is True


def test_authentication_is_fatal() -> None:
    err = classify_api_exception(_make(anthropic.AuthenticationError, 401))
    assert isinstance(err, LLMAuthError)
    assert err.retryable is False


def test_permission_denied_is_fatal() -> None:
    err = classify_api_exception(_make(anthropic.PermissionDeniedError, 403))
    assert isinstance(err, LLMAuthError)
    assert err.retryable is False


def test_not_found_is_fatal() -> None:
    err = classify_api_exception(_make(anthropic.NotFoundError, 404))
    assert isinstance(err, LLMNotFoundError)
    assert err.retryable is False


def test_bad_request_is_fatal() -> None:
    err = classify_api_exception(_make(anthropic.BadRequestError, 400))
    assert isinstance(err, LLMBadRequestError)
    assert err.retryable is False


def test_context_window_overflow_special_cased() -> None:
    """A 400 with the `prompt is too long` marker is a distinct fatal type
    so the agent loop can react (e.g. compact memory) rather than treat
    it as a generic bad-request bug."""
    err = classify_api_exception(
        _make(anthropic.BadRequestError, 400, msg="prompt is too long: 250000 tokens > 200000")
    )
    assert isinstance(err, LLMContextWindowError)
    assert err.retryable is False


def test_unprocessable_is_fatal() -> None:
    err = classify_api_exception(_make(anthropic.UnprocessableEntityError, 422))
    assert isinstance(err, LLMBadRequestError)
    assert err.retryable is False


def test_transport_error_is_retryable() -> None:
    inner = httpx.ConnectError("Name or service not known")
    err = classify_api_exception(
        anthropic.APIConnectionError(message="boom", request=httpx.Request("POST", "https://x/"))
    )
    assert isinstance(err, LLMTransportError)
    assert err.retryable is True


def test_unclassified_exception_treated_as_transport() -> None:
    err = classify_api_exception(RuntimeError("weird"))
    assert isinstance(err, LLMTransportError)
    assert err.retryable is True


def test_already_classified_passes_through() -> None:
    e = LLMRateLimitError("stop", cause=None)
    assert classify_api_exception(e) is e


def test_assertion_error_classified_as_short_retry_transport() -> None:
    """SDK stream parser sometimes asserts on edge-case payloads. Classify
    as transport (retryable) but with a small backoff so we don't burn a
    full 3-attempt budget on a transient hiccup."""
    err = classify_api_exception(AssertionError())
    assert isinstance(err, LLMTransportError)
    assert err.retryable is True
    assert err.retry_after_seconds <= 1.0  # short, not the 2s default


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


def test_should_retry_returns_none_for_fatal() -> None:
    assert should_retry(LLMAuthError("nope"), attempt=0, max_attempts=5) is None


def test_should_retry_returns_none_when_attempts_exhausted() -> None:
    err = LLMTransportError("net")
    err.retry_after_seconds = 1.0
    assert should_retry(err, attempt=5, max_attempts=5) is None


def test_should_retry_returns_jittered_wait_for_retryable() -> None:
    err = LLMRateLimitError("rl")
    err.retry_after_seconds = 2.0
    wait = should_retry(err, attempt=0, max_attempts=3)
    assert wait is not None
    assert 0.0 <= wait <= 2.0  # full jitter within suggested wait


def test_should_retry_uses_exp_backoff_when_no_retry_after() -> None:
    err = LLMServerError("svc")
    err.retry_after_seconds = 0.0
    # attempt=2 → base = max(0, 4.0); jitter ∈ [0, 4]
    wait = should_retry(err, attempt=2, max_attempts=5)
    assert wait is not None
    assert 0.0 <= wait <= 4.0


# ---------------------------------------------------------------------------
# Output-layer signals
# ---------------------------------------------------------------------------


def test_is_truncated() -> None:
    assert is_truncated({"stop_reason": "max_tokens"})
    assert not is_truncated({"stop_reason": "end_turn"})


def test_is_refusal_and_text_extraction() -> None:
    payload = {
        "stop_reason": "refusal",
        "content": [{"type": "refusal", "refusal": "I can't help with that."}],
    }
    assert is_refusal(payload)
    assert "can't help" in refusal_text(payload).lower()


def test_is_pause_turn() -> None:
    assert is_pause_turn({"stop_reason": "pause_turn"})
    assert not is_pause_turn({"stop_reason": "end_turn"})
