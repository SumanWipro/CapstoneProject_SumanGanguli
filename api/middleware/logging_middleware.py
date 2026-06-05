"""
api/middleware/logging_middleware.py
=====================================
Starlette middleware for structured HTTP request/response logging.

Responsibilities:
- Log every incoming request: method, path, client IP
- Log every outgoing response: status code, latency in ms
- Attach a unique request_id to each request for log correlation

Design decision: Starlette BaseHTTPMiddleware is used rather than a
FastAPI dependency so logging fires for ALL requests including 404s
and validation errors, not just successfully routed handlers.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from utils.logger import get_logger

log = get_logger(__name__, component="logging_middleware")


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs each request and response with latency.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Intercept request, log it, call the next handler, log the response.

        Args:
            request:   Incoming Starlette request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            Response from the next handler, unchanged.
        """
        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        log.info(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else "unknown",
        )

        # TODO (Phase 7): bind request_id to structlog context vars
        response = await call_next(request)

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        log.info(
            "http_response",
            request_id=request_id,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        return response
