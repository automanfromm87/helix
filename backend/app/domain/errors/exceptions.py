"""Domain-layer exceptions.

These were originally hosted under `app.application.errors.exceptions`,
which created a domain → application reverse import every time a domain
service raised one. Moving them down here keeps the dependency direction
clean (domain knows nothing about application).

The HTTP `code` / `status_code` attributes are kept on the exception
type because they're inherent to the error's identity ("a NotFoundError
maps to 404 wherever it surfaces"), not specific to any one transport.
The interfaces layer reads them off the exception in its handler — that
direction (interfaces → domain) is allowed.

`app.application.errors.exceptions` re-exports these for backward
compatibility; new code should import from here.
"""


class AppException(RuntimeError):
    def __init__(
        self,
        code: int,
        msg: str,
        status_code: int = 400,
    ):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.status_code = status_code


class NotFoundError(AppException):
    def __init__(self, msg: str = "Resource not found"):
        super().__init__(code=404, msg=msg, status_code=404)


class BadRequestError(AppException):
    def __init__(self, msg: str = "Bad request parameters"):
        super().__init__(code=400, msg=msg, status_code=400)


class ValidationError(AppException):
    def __init__(self, msg: str = "Validation error"):
        super().__init__(code=422, msg=msg, status_code=422)


class ServerError(AppException):
    def __init__(self, msg: str = "Internal server error"):
        super().__init__(code=500, msg=msg, status_code=500)


class UnauthorizedError(AppException):
    def __init__(self, msg: str = "Authentication required"):
        super().__init__(code=401, msg=msg, status_code=401)


class ServiceUnavailableError(AppException):
    """Backing service is reachable as a concept but currently down.

    Carries a `retry_after` hint (seconds) the HTTP layer surfaces as a
    standard `Retry-After` header so the frontend can back off intelligently
    instead of hammering the endpoint."""

    def __init__(self, msg: str = "Service temporarily unavailable", retry_after: int = 5):
        super().__init__(code=503, msg=msg, status_code=503)
        self.retry_after = retry_after


class SandboxUnavailableError(ServiceUnavailableError):
    """Specialization of ServiceUnavailableError for the sandbox container."""

    def __init__(self, detail: str = ""):
        msg = "Sandbox is unavailable"
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(msg=msg, retry_after=5)
