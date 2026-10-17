"""Fixed-window rate limiter per API A6 (phase-4 debt, D9).

In-memory: one process, one box, no Redis (architecture A8). Windows reset
on a monotonic clock; the table drives matching so a new route is a row.

Bucket key is (client IP, route parent) — `/api/v1/cameras/3/test` and
`/api/v1/cameras/4/test` share one bucket: the probe cap protects the
camera hardware, so it is per-IP across all cameras. Installed inside
CORS (main.py) so 429s still carry CORS headers and a correlation id.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

WINDOW_S = 60.0
DEFAULT_LIMIT = 120


def _limit_for(method: str, path: str) -> int | None:
    """Bucket limit for a route, or None when excluded entirely (D9).

    Exclusions: `/auth/login` (the lockout owns it), `/system/health`
    (liveness must never be throttled), `/cameras/*/stream` (the slot cap
    owns it), `/ws/*` (the socket handshake is rate-limit enough), and
    anything outside the API prefix.
    """
    if not path.startswith("/api/v1/"):
        return None
    if path.startswith(("/api/v1/auth/login", "/api/v1/system/health", "/api/v1/ws/")):
        return None
    if "/cameras/" in path and path.endswith("/stream"):
        return None
    if method == "POST":
        if path.startswith("/api/v1/auth/refresh"):
            return 30
        # Hardware probes: the draft form and the saved-camera form.
        if "/cameras/" in path and path.endswith("/test"):
            return 10
    return DEFAULT_LIMIT


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Count requests per (IP, route-bucket, window); 429 past the row."""

    def __init__(self, app: ASGIApp, *, now: Callable[[], float] = time.monotonic) -> None:
        super().__init__(app)
        self._now = now
        self._hits: dict[tuple[str, str], tuple[int, float]] = {}

    def _check(self, key: tuple[str, str], limit: int) -> int | None:
        """Count one hit; seconds remaining in the window when limited."""
        now = self._now()
        count, start = self._hits.get(key, (0, 0.0))
        if now - start >= WINDOW_S:
            count, start = 0, now
        count += 1
        self._hits[key] = (count, start)
        if count > limit:
            return max(1, int(WINDOW_S - (now - start)))
        return None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        limit = _limit_for(request.method, request.url.path)
        if limit is None:
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        bucket = request.url.path.rsplit("/", 1)[0]
        retry = self._check((ip, bucket), limit)
        if retry is not None:
            correlation_id = getattr(request.state, "correlation_id", "unknown")
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry)},
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"rate limit exceeded; retry in {retry}s",
                        "field": None,
                        "correlation_id": correlation_id,
                    }
                },
            )
        return await call_next(request)
