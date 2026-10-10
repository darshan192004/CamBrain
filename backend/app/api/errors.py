"""Map domain errors to the single API error envelope (API §4).

Envelope shape: {"error": {"code", "message", "field", "correlation_id"}}.
One shape for every failure so the Tauri shell can render errors without
parsing per-endpoint quirks.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import (
    AuthError as CoreAuthError,
)
from app.core.errors import (
    CamBrainError,
    NotFoundError,
    StorageError,
    ValidationError,
)


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def _envelope(
    code: str, message: str, request: Request, field: str | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "field": field,
            "correlation_id": _correlation_id(request),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register domain-exception handlers producing the error envelope."""

    from app.api.auth import AccountLockedError, AuthError, ForbiddenError

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401, content=_envelope("UNAUTHENTICATED", str(exc), request)
        )

    @app.exception_handler(AccountLockedError)
    async def _locked(request: Request, exc: AccountLockedError) -> JSONResponse:
        return JSONResponse(status_code=423, content=_envelope("ACCOUNT_LOCKED", str(exc), request))

    @app.exception_handler(ForbiddenError)
    async def _forbidden(request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content=_envelope("FORBIDDEN", str(exc), request))

    @app.exception_handler(CoreAuthError)
    async def _core_auth(request: Request, exc: CoreAuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401, content=_envelope("UNAUTHENTICATED", str(exc), request)
        )

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=_envelope("NOT_FOUND", str(exc), request))

    @app.exception_handler(ValidationError)
    async def _validation(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=_envelope("VALIDATION_ERROR", str(exc), request)
        )

    @app.exception_handler(StorageError)
    async def _storage(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=500, content=_envelope("INTERNAL", str(exc), request))

    @app.exception_handler(CamBrainError)
    async def _domain(request: Request, exc: CamBrainError) -> JSONResponse:
        return JSONResponse(status_code=500, content=_envelope("INTERNAL", str(exc), request))
