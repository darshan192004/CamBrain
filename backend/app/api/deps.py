"""FastAPI dependencies: DB session, bearer auth, and the role gate."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DbSession

from app.api.auth import AuthError, require_role, verify_access_token
from app.db.session import SessionLocal

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[DbSession]:
    """Yield a request-scoped session; closes on exit."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DbSessionDep = Annotated[DbSession, Depends(get_db)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def get_claims(
    credentials: CredentialsDep,
    db: DbSessionDep,
) -> dict[str, Any]:
    """Verify the bearer token and return its claims.

    Raises:
        AuthError: Missing, malformed, expired, or revoked credentials.
    """
    if credentials is None:
        raise AuthError("missing bearer token")
    return verify_access_token(db, credentials.credentials)


ClaimsDep = Annotated[dict[str, Any], Depends(get_claims)]


def require_role_dep(minimum: str) -> Any:
    """Build a FastAPI dependency enforcing a minimum role.

    Args:
        minimum: Required role ("viewer" or "admin").

    Returns:
        A dependency returning verified claims, or raising ForbiddenError.
    """
    checker = require_role(minimum)

    def _dep(claims: ClaimsDep) -> dict[str, Any]:
        return dict(checker(claims))

    return _dep
