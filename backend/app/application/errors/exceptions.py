"""Re-export shim for backward compatibility.

The exception classes themselves now live in `app.domain.errors.exceptions`
so the domain layer can raise them without a reverse import. Existing
code that imports from `app.application.errors.exceptions` keeps working
unchanged.
"""

from app.domain.errors.exceptions import (
    AppException,
    BadRequestError,
    NotFoundError,
    SandboxUnavailableError,
    ServerError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)

__all__ = [
    "AppException",
    "BadRequestError",
    "NotFoundError",
    "SandboxUnavailableError",
    "ServerError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
]
