"""ASGI app factory: lifespan, CORS, routers, error envelope (API §1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.middleware import CorrelationIdMiddleware, CsrfMiddleware
from app.api.routers.auth import router as auth_router
from app.api.routers.cameras import router as cameras_router
from app.api.routers.rois import router as rois_router
from app.api.routers.rules import router as rules_router
from app.core.config import settings

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Build the CamBrain API application.

    Returns:
        A FastAPI instance with auth/camera routes, CSRF + correlation-id
        middleware, CORS allowlist, and the domain-error envelope installed.
    """
    app = FastAPI(
        title="CamBrain",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CambBrain-Client"],
    )
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    install_error_handlers(app)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(cameras_router, prefix=API_PREFIX)
    app.include_router(rois_router, prefix=API_PREFIX)
    app.include_router(rules_router, prefix=API_PREFIX)
    return app


app = create_app()
