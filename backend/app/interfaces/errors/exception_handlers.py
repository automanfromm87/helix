from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
import logging
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.application.errors.exceptions import AppException, ServiceUnavailableError
from app.interfaces.schemas.base import APIResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers"""

    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(
        request: Request, exc: ServiceUnavailableError
    ) -> JSONResponse:
        """Surface 503 + Retry-After for backing-service outages.

        Logged at INFO: this is a known degraded state (sandbox stopped,
        upstream rebooting, etc.), not a bug worth a stack trace."""
        logger.info("ServiceUnavailable: %s", exc.msg)
        return JSONResponse(
            status_code=503,
            content=APIResponse(code=exc.code, msg=exc.msg, data=None).model_dump(),
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(AppException)
    async def api_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """Handle custom API exceptions"""
        logger.warning(f"APIException: {exc.msg}")
        return JSONResponse(
            status_code=exc.status_code,
            content=APIResponse(
                code=exc.code,
                msg=exc.msg,
                data=None
            ).model_dump(),
        )
    
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Handle HTTP exceptions"""
        logger.warning(f"HTTPException: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content=APIResponse(
                code=exc.status_code,
                msg=exc.detail,
                data=None
            ).model_dump(),
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle all uncaught exceptions"""
        logger.exception(f"Unhandled exception: {str(exc)}")
        return JSONResponse(
            status_code=500,
            content=APIResponse(
                code=500,
                msg="Internal server error",
                data=None
            ).model_dump(),
        ) 