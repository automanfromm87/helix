import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator

from app.core.config import get_settings

_session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Standard LogRecord attrs — anything not in this set on a record gets emitted
# as a top-level JSON field so callers can pass `logger.info("msg", extra={...})`.
_RESERVED_LOGRECORD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
        # Context fields handled explicitly above; skip here so None values
        # don't leak into the extras loop.
        "session_id", "user_id", "request_id",
    }
)


class ContextFilter(logging.Filter):
    """Inject contextvar-bound session_id / user_id / request_id onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = _session_id_var.get()
        record.user_id = _user_id_var.get()
        record.request_id = _request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Single-line JSON per record so logs are machine-greppable."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for ctx_field in ("session_id", "user_id", "request_id"):
            value = getattr(record, ctx_field, None)
            if value is not None:
                payload[ctx_field] = value
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_ATTRS or key in payload:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Root logger: JSON to stdout, context-aware, level from HELIX env."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    handler.setLevel(log_level)
    root_logger.addHandler(handler)

    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)

    root_logger.info("Logging system initialized")


@contextmanager
def bind_log_context(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
) -> Iterator[None]:
    """Bind session/user/request context to subsequent log records.

    Propagates across `await` and `asyncio.create_task()` via ContextVar, but
    NOT across threads or process boundaries.
    """
    tokens: list[tuple[ContextVar[str | None], Any]] = []
    if session_id is not None:
        tokens.append((_session_id_var, _session_id_var.set(session_id)))
    if user_id is not None:
        tokens.append((_user_id_var, _user_id_var.set(user_id)))
    if request_id is not None:
        tokens.append((_request_id_var, _request_id_var.set(request_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            try:
                var.reset(token)
            except (LookupError, ValueError):
                pass


def current_session_id() -> str | None:
    return _session_id_var.get()
