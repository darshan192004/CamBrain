"""CSRF and correlation-id middleware (API §1, SECURITY §4.5).

CamBrain's dashboard is a browser app on localhost talking to a LAN-bound API.
A cross-site form post cannot set `X-CambBrain-Client` or a JSON content-type,
so requiring both on mutating requests is a complete CSRF defence here — no
per-form tokens to mint or store.

Rejections are returned as the standard error envelope directly: exceptions
raised inside Starlette middleware bypass the app's exception handlers and
would surface as opaque 500s.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_CLIENT_HEADER = "x-cambbrain-client"


def _forbidden(message: str, request: Request) -> JSONResponse:
    """Build a 403 FORBIDDEN error envelope."""
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    return JSONResponse(
        status_code=403,
        content={
            "error": {
                "code": "FORBIDDEN",
                "message": message,
                "field": None,
                "correlation_id": correlation_id,
            }
        },
    )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Require the JSON content type and `X-CambBrain-Client` on writes.

    A bodyless mutating request (e.g. `POST /cameras/{id}/test`) cannot carry
    a form payload, so only the client header is required there; the JSON
    content type is enforced when a body is present.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _MUTATING:
            has_body = int(request.headers.get("content-length") or 0) > 0
            if has_body:
                content_type = request.headers.get("content-type", "")
                if not content_type.lower().startswith("application/json"):
                    return _forbidden(
                        "CSRF: mutating requests with a body require "
                        "Content-Type: application/json",
                        request,
                    )
            if _CLIENT_HEADER not in request.headers:
                return _forbidden(
                    "CSRF: mutating requests require the X-CambBrain-Client header",
                    request,
                )
        return await call_next(request)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a per-request id so an error envelope can be traced to a log line."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.correlation_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response
