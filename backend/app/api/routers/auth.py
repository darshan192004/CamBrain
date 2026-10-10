"""Auth routes: login, refresh, logout, me, change-password (API §Auth)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.auth import (
    AuthError,
    hash_password,
    issue_tokens,
    revoke_all_sessions,
    revoke_session,
    rotate_refresh_token,
    tracker,
)
from app.api.auth import _verify_password as verify_password
from app.api.deps import ClaimsDep, DbSessionDep
from app.api.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    OkResponse,
    RefreshRequest,
    TokenResponse,
)
from app.db.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract (ip, user-agent) for the session record."""
    return request.client.host if request.client else None, request.headers.get("user-agent")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: DbSessionDep) -> TokenResponse:
    """Exchange credentials for a token pair. 5 failures lock the username for 5 min."""
    user = db.scalar(select(User).where(User.username == body.username, User.is_active.is_(True)))
    ok = user is not None and verify_password(body.password, user.password_hash)
    tracker.check_and_record(body.username, ok)
    if user is None:
        raise AuthError("invalid credentials")
    ip, user_agent = _client_meta(request)
    tokens = issue_tokens(db, user, body.password, ip=ip, user_agent=user_agent)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request, db: DbSessionDep) -> TokenResponse:
    """Rotate the refresh token and return a new pair."""
    ip, user_agent = _client_meta(request)
    tokens = rotate_refresh_token(db, body.refresh_token, ip=ip, user_agent=user_agent)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", response_model=OkResponse)
def logout(request: Request, db: DbSessionDep) -> OkResponse:
    """Revoke the caller's current session."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    revoke_session(db, header.removeprefix("bearer ").removeprefix("Bearer "))
    return OkResponse()


@router.get("/me", response_model=MeResponse)
def me(claims: ClaimsDep, db: DbSessionDep) -> MeResponse:
    """Return the caller's identity, role, and site."""
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise AuthError("unknown user")
    return MeResponse(user_id=user.id, username=user.username, role=user.role, site_id=user.site_id)


@router.post("/change-password", response_model=OkResponse)
def change_password(body: ChangePasswordRequest, claims: ClaimsDep, db: DbSessionDep) -> OkResponse:
    """Rotate the caller's password and revoke every session."""
    user = db.get(User, int(claims["sub"]))
    if user is None or not verify_password(body.current_password, user.password_hash):
        raise AuthError("invalid current password")
    user.password_hash = hash_password(body.new_password)
    revoke_all_sessions(db, user.id)
    return OkResponse()
