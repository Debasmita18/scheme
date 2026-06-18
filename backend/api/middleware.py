"""
Custom middleware for the MGNREGA Verification API.
====================================================

Provides:
- **RequestLoggingMiddleware** -- logs every request with method, path,
  status code, and elapsed time using loguru.
- **RateLimitMiddleware** -- simple in-memory sliding-window rate limiter
  keyed by client IP.
- **ErrorHandlingMiddleware** -- catches unhandled exceptions and returns
  a consistent JSON error envelope.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable, Dict, List, Tuple

from fastapi import FastAPI, Request, Response
from fastapi.responses import ORJSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


# ---------------------------------------------------------------------------
# Request logging
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing information."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"

        logger.info(
            "REQ  {} {} from {}",
            request.method,
            request.url.path,
            client_ip,
        )

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "RESP {} {} -> {} ({:.1f} ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
        return response


# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per-IP sliding window)
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter.

    Parameters
    ----------
    max_requests : int
        Maximum number of requests allowed in the window.
    window_seconds : int
        Length of the sliding window in seconds.
    """

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # ip -> list of request timestamps
        self._hits: Dict[str, List[float]] = defaultdict(list)

    def _prune(self, ip: str, now: float) -> None:
        """Remove timestamps outside the current window."""
        cutoff = now - self.window_seconds
        self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        self._prune(client_ip, now)

        if len(self._hits[client_ip]) >= self.max_requests:
            retry_after = int(
                self.window_seconds
                - (now - self._hits[client_ip][0])
            )
            logger.warning(
                "Rate limit exceeded for {} on {} {}",
                client_ip,
                request.method,
                request.url.path,
            )
            return ORJSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Too many requests. Limit is {self.max_requests} "
                        f"per {self.window_seconds}s. "
                        f"Retry after {max(retry_after, 1)}s."
                    ),
                    "retry_after_seconds": max(retry_after, 1),
                },
                headers={"Retry-After": str(max(retry_after, 1))},
            )

        self._hits[client_ip].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return a consistent JSON envelope."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            logger.exception(
                "Unhandled error on {} {}: {}",
                request.method,
                request.url.path,
                exc,
            )
            return ORJSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "An unexpected error occurred. Please try again later.",
                    "detail": str(exc) if __debug__ else None,
                },
            )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------
def register_middleware(app: FastAPI) -> None:
    """Add all custom middleware to the FastAPI application.

    Order matters: middleware are executed top-down for requests and
    bottom-up for responses.  We want error handling outermost, then
    rate limiting, then logging closest to the handler.
    """
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware, max_requests=200, window_seconds=60)
    app.add_middleware(ErrorHandlingMiddleware)
