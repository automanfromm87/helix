"""Defensive layer around the model loop.

Three categories, all in one module so the failure modes are easy to enumerate:

  Output-layer (model produced something pathological)
    * `is_truncated(payload)`     — `stop_reason == max_tokens`. Retry with
                                    bumped cap, then bail.
    * `is_refusal(payload)`       — `stop_reason == refusal`. Surface a
                                    clean error, don't try to JSON-parse.
    * `is_pause_turn(payload)`    — `stop_reason == pause_turn`. The model
                                    asked to be re-invoked with the same
                                    state; loop continues automatically.
    * `validate_tool_input(...)`  — required keys present before we invoke.
    * `truncate_tool_content(...)` — cap a tool_result before it goes back.
    * `LoopGuard`                 — detects same call / same error streaks.

  API-layer (Anthropic SDK threw)
    * `LLMError` hierarchy        — typed taxonomy of transport / status
                                    failures (rate-limit, overload, auth,
                                    bad-request, context-window, etc.).
    * `classify_api_exception()`  — turns an `anthropic.*Error` into one of
                                    those typed instances. Carries the
                                    `retry_after` hint for 429s/529s.
    * `should_retry(err, attempt)` — single source of truth on whether to
                                    retry, and how long to wait first.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)


# When the first call hits max_tokens, retry once with this cap before bailing.
TRUNCATION_RETRY_MAX_TOKENS = 32_000

# Cap on a single tool_result.content string before it goes back into memory.
# Tool calls like shell_exec, browser_view, or file_read can produce
# multi-MB outputs; injecting those into history balloons the next request
# past max_tokens almost immediately. We keep head + tail so the model still
# sees the start (usually the command echo) and end (usually the actual
# result or last error). 12K chars ≈ 3K tokens — enough to be useful, small
# enough to keep the cache hit rate high across turns.
MAX_TOOL_CONTENT_CHARS = 12_000


def truncate_tool_content(text: str, limit: int = MAX_TOOL_CONTENT_CHARS) -> str:
    """Trim a tool_result content string to `limit` chars, keeping head + tail."""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    omitted = len(text) - head - tail
    return (
        f"{text[:head]}\n"
        f"...\n[truncated {omitted} chars]\n...\n"
        f"{text[-tail:]}"
    )


class ModelOutputTruncatedError(RuntimeError):
    """Raised when the model output exceeds max_tokens twice in a row."""


class ModelRefusalError(RuntimeError):
    """Raised when the model returned `stop_reason == refusal`."""


# ---------------------------------------------------------------------------
# API-layer error taxonomy
# ---------------------------------------------------------------------------
#
# We classify every `anthropic.*Error` into one of these four buckets. The
# retry loop only needs the bucket — the concrete type is kept for logging
# and for selecting an appropriate user message.


class LLMError(RuntimeError):
    """Base class for any classified LLM-call failure."""

    retryable: bool = False
    # Suggested wait before retry, in seconds. Nonzero only for retryable.
    retry_after_seconds: float = 0.0

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.__cause__ = cause

    def with_retry_after(self, seconds: float) -> "LLMError":
        self.retry_after_seconds = seconds
        return self

    def user_message(self) -> str:
        """Operator-visible explanation. Subclasses override for context."""
        return f"Model call failed: {self}"


class LLMTransportError(LLMError):
    """Network / DNS / TLS / read timeout — usually transient."""
    retryable = True

    def user_message(self) -> str:
        return f"Network problem reaching the model: {self}"


class LLMSDKAssertionError(LLMTransportError):
    """The Anthropic SDK's stream parser hit an internal assertion on a
    response we received. Almost always retryable on the same prompt;
    distinct subclass so the user message can say so directly instead of
    blaming the network."""

    def user_message(self) -> str:
        return (
            "The model SDK choked on the streamed response. "
            f"Auto-retried but ran out of attempts. Detail: {self}"
        )


class LLMRateLimitError(LLMError):
    """HTTP 429 — exceeded RPM/TPM. Caller MUST honor `retry_after`."""
    retryable = True

    def user_message(self) -> str:
        return "Hit the model rate limit and exhausted retries. Wait a moment and resend."


class LLMOverloadedError(LLMError):
    """HTTP 529 (Anthropic-specific overload) — retry with longer backoff."""
    retryable = True

    def user_message(self) -> str:
        return "The model is currently overloaded. Please try again shortly."


class LLMServerError(LLMError):
    """HTTP 5xx — Anthropic-side issue, retry."""
    retryable = True

    def user_message(self) -> str:
        return f"The model service had a temporary problem: {self}"


class LLMBadRequestError(LLMError):
    """HTTP 400/422 — our request was malformed. Don't retry, fix the call."""
    retryable = False

    def user_message(self) -> str:
        return f"The request to the model was malformed: {self}"


class LLMAuthError(LLMError):
    """HTTP 401/403 — credentials/permissions. Don't retry, alert ops."""
    retryable = False

    def user_message(self) -> str:
        return f"The model API rejected our credentials — please contact the operator. ({self})"


class LLMNotFoundError(LLMError):
    """HTTP 404 — typically wrong model name. Don't retry."""
    retryable = False

    def user_message(self) -> str:
        return f"The configured model is unavailable. Check `MODEL_NAME`. ({self})"


class LLMContextWindowError(LLMBadRequestError):
    """Special-case 400: input exceeded the model's context window. Retrying
    won't help — the agent loop must compact memory or split the work.
    Detected by inspecting BadRequestError messages."""
    retryable = False

    def user_message(self) -> str:
        return (
            "The conversation grew past the model's context window. "
            "Start a new session or split the work into smaller steps."
        )


_CONTEXT_WINDOW_MARKERS = (
    "context window",
    "input is too long",
    "max_tokens_to_sample",
    "prompt is too long",
    "exceeds the maximum",
)


def classify_api_exception(exc: BaseException) -> LLMError:
    """Map an `anthropic.*Error` (or generic networking exception) to a
    typed `LLMError`. If the exception is already an `LLMError`, return it.
    """
    if isinstance(exc, LLMError):
        return exc

    # AssertionError raised inside the Anthropic SDK stream parser is
    # transient — the very same request usually succeeds on retry. We
    # classify as a retryable transport error but with the smallest backoff
    # so we don't burn three slow attempts on what's effectively a hiccup.
    if isinstance(exc, AssertionError):
        return LLMSDKAssertionError(
            f"SDK assertion: {exc!r}", cause=exc
        ).with_retry_after(0.5)

    msg = str(exc) or type(exc).__name__

    # APIStatusError holds the HTTP status_code; check its subclasses first
    # because they have richer types in the SDK.
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError(
            f"rate limited: {msg}",
            cause=exc,
        ).with_retry_after(_extract_retry_after(exc, default=10.0))

    if isinstance(exc, anthropic.AuthenticationError):
        return LLMAuthError(f"auth failed: {msg}", cause=exc)
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LLMAuthError(f"permission denied: {msg}", cause=exc)
    if isinstance(exc, anthropic.NotFoundError):
        return LLMNotFoundError(f"not found: {msg}", cause=exc)
    if isinstance(exc, anthropic.UnprocessableEntityError):
        return LLMBadRequestError(f"unprocessable: {msg}", cause=exc)
    if isinstance(exc, anthropic.BadRequestError):
        if _looks_like_context_window(msg):
            return LLMContextWindowError(
                f"input exceeds the model's context window: {msg}",
                cause=exc,
            )
        return LLMBadRequestError(f"bad request: {msg}", cause=exc)
    if isinstance(exc, anthropic.InternalServerError):
        return LLMServerError(f"server error: {msg}", cause=exc).with_retry_after(2.0)

    # APIStatusError without a specific subclass: read status_code.
    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", None)
        if status == 529:  # overloaded
            return LLMOverloadedError(
                f"overloaded: {msg}", cause=exc
            ).with_retry_after(_extract_retry_after(exc, default=15.0))
        if status and 500 <= status < 600:
            return LLMServerError(
                f"server error {status}: {msg}", cause=exc
            ).with_retry_after(2.0)
        if status and 400 <= status < 500:
            return LLMBadRequestError(f"http {status}: {msg}", cause=exc)
        return LLMServerError(f"http {status}: {msg}", cause=exc).with_retry_after(2.0)

    if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return LLMTransportError(f"transport error: {msg}", cause=exc).with_retry_after(2.0)

    if isinstance(exc, anthropic.APIError):
        # Generic catch-all for anything else from the SDK.
        return LLMServerError(f"api error: {msg}", cause=exc).with_retry_after(2.0)

    # Non-Anthropic exceptions (httpx / asyncio / etc.) — treat as transport.
    return LLMTransportError(f"unclassified: {msg}", cause=exc).with_retry_after(2.0)


def should_retry(err: LLMError, attempt: int, max_attempts: int) -> Optional[float]:
    """Return the seconds to sleep before the next attempt, or `None` if no
    retry is warranted. Adds full jitter to whatever the error suggested so
    callers stampeding on the same outage spread out automatically."""
    if not err.retryable:
        return None
    if attempt >= max_attempts:
        return None
    base = max(err.retry_after_seconds, _exp_backoff(attempt))
    return random.uniform(0.0, base)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _exp_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Capped exponential backoff: 1, 2, 4, 8, ... up to `cap`."""
    return min(base * (2 ** attempt), cap)


def _extract_retry_after(exc: BaseException, *, default: float) -> float:
    """Pull `Retry-After` header off an Anthropic API error, falling back to
    `default` when the header is missing or malformed."""
    response = getattr(exc, "response", None)
    if response is None:
        return default
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return default


def _looks_like_context_window(msg: str) -> bool:
    lower = msg.lower()
    return any(marker in lower for marker in _CONTEXT_WINDOW_MARKERS)




def is_truncated(payload: Dict[str, Any]) -> bool:
    return payload.get("stop_reason") == "max_tokens"


def is_refusal(payload: Dict[str, Any]) -> bool:
    """`stop_reason == refusal` means the safety system blocked the response.

    The body usually contains a refusal text block; trying to parse it as
    JSON or as a tool call yields garbage. Treat as a fatal, surface to the
    user untouched."""
    return payload.get("stop_reason") == "refusal"


def is_pause_turn(payload: Dict[str, Any]) -> bool:
    """`stop_reason == pause_turn` is the model asking for another invocation
    to keep working — common in long agent loops when Anthropic's
    server-side context editing reshuffles the conversation. The caller
    should re-invoke `complete_stream` with the same memory; the assistant
    turn goes into history as-is.
    """
    return payload.get("stop_reason") == "pause_turn"


def refusal_text(payload: Dict[str, Any]) -> str:
    """Pull out the human-readable reason from a refusal payload, if any."""
    parts: List[str] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("text", "refusal"):
            parts.append(block.get("text", "") or block.get("refusal", ""))
    return " ".join(p for p in parts if p) or "model refused without explanation"


def validate_tool_input(input_schema: Dict[str, Any], args: Any) -> Optional[str]:
    """Lightweight pre-flight check for tool args.

    We only enforce the `required` list — a real JSON Schema validator is
    overkill here. Anthropic's truncation is what bites us in practice
    (`input` ends up `{}` for a tool that requires `file` and `content`),
    and a missing-required error message is exactly what we want to feed
    back to the model so it retries with a smaller payload.
    """
    if not isinstance(args, dict):
        return f"Tool input must be a JSON object, got {type(args).__name__}"
    required = input_schema.get("required") or []
    missing = [key for key in required if key not in args]
    if missing:
        return (
            f"Missing required argument(s): {', '.join(missing)}. "
            "Likely caused by output exceeding max_tokens — split the "
            "operation into smaller steps."
        )
    return None


class LoopGuard:
    """Bounded memory of recent calls + recent errors.

    Triggers:
      * `max_repeated_calls` consecutive calls with identical (name, args).
      * `max_repeated_failures` consecutive failures with the same error
        message (regardless of which tool produced them).

    Each guard returns a non-empty string to abort, or None to continue.
    """

    def __init__(
        self,
        *,
        max_repeated_calls: int = 5,
        max_repeated_failures: int = 3,
    ) -> None:
        self._max_repeated_calls = max_repeated_calls
        self._max_repeated_failures = max_repeated_failures
        self._recent_signatures: List[str] = []
        self._last_error: Optional[str] = None
        self._error_streak: int = 0

    @staticmethod
    def _signature(name: str, args: Any) -> str:
        try:
            payload = json.dumps(args, sort_keys=True, default=str)
        except Exception:
            payload = repr(args)
        return f"{name}::{hashlib.sha1(payload.encode()).hexdigest()[:12]}"

    def record_call(self, name: str, args: Any) -> Optional[str]:
        sig = self._signature(name, args)
        self._recent_signatures.append(sig)
        self._recent_signatures = self._recent_signatures[-self._max_repeated_calls:]
        if (
            len(self._recent_signatures) >= self._max_repeated_calls
            and len(set(self._recent_signatures)) == 1
        ):
            return (
                f"Tool '{name}' called {self._max_repeated_calls} times with "
                "identical arguments without progress — aborting to avoid a "
                "runaway loop."
            )
        return None

    def record_failure(self, message: str) -> Optional[str]:
        message = (message or "").strip()
        if not message:
            return None
        if message == self._last_error:
            self._error_streak += 1
        else:
            self._last_error = message
            self._error_streak = 1
        if self._error_streak >= self._max_repeated_failures:
            return (
                f"Same tool error repeated {self._error_streak} times — "
                f"aborting. Last error: {message}"
            )
        return None

    def record_success(self) -> None:
        self._last_error = None
        self._error_streak = 0
