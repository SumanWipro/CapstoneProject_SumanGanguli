"""
api/middleware/error_middleware.py
===================================
Global exception handlers for the FastAPI Loan Approval gateway.

Responsibilities:
- Catch Pydantic ValidationError and return HTTP 422 with ErrorResponse
- Catch unhandled exceptions and return HTTP 500 with ErrorResponse
- Ensure the API never returns a raw Python traceback to clients

Design decision: Exception handlers are registered on the app rather than
using middleware so FastAPI's automatic validation error formatting can be
overridden cleanly.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.models.response import ErrorResponse
from utils.logger import get_logger

log = get_logger(__name__, component="error_middleware")


def register_error_handlers(app: FastAPI) -> None:
    """
    Register all global exception handlers on the FastAPI app.

    Args:
        app: The FastAPI application instance.
    """

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Return HTTP 422 with a structured ErrorResponse for validation failures."""
        errors = exc.errors()
        first_error = errors[0] if errors else {}
        message = f"{first_error.get('loc', [''][-1])}: {first_error.get('msg', 'validation error')}"

        log.warning(
            "validation_error",
            path=request.url.path,
            errors=errors,
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error="VALIDATION_ERROR",
                message=message,
                detail=str(errors),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Return HTTP 500 with a structured ErrorResponse for unexpected errors."""
        log.error(
            "unhandled_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            error=str(exc),
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error="INTERNAL_ERROR",
                message="An unexpected error occurred. Please try again.",
                detail=type(exc).__name__,
            ).model_dump(),
        )
