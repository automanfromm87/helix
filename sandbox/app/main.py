from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
import sys

from app.core.config import settings
from app.api.router import api_router
from app.core.exceptions import (
    AppException, 
    app_exception_handler, 
    http_exception_handler, 
    validation_exception_handler,
    general_exception_handler
)
from app.core.middleware import auto_extend_timeout_middleware

import json
from datetime import datetime, timezone


class _SandboxJsonFormatter(logging.Formatter):
    """Same JSON shape as backend's logger so logs aggregate cleanly."""

    _RESERVED = frozenset(
        {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message", "module",
            "msecs", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName", "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": "sandbox",
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging():
    """JSON logging to stdout, matching backend format for unified ingestion."""
    log_level = getattr(logging, settings.LOG_LEVEL)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_SandboxJsonFormatter())
    handler.setLevel(log_level)
    root_logger.addHandler(handler)
    root_logger.info("Sandbox logging system initialized")

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    version="1.0.0",
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("Sandbox API server starting")

# Register middleware
app.middleware("http")(auto_extend_timeout_middleware)

# Register exception handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Register routes
app.include_router(api_router, prefix="/api/v1")

logger.info("Sandbox API routes registered and server ready")