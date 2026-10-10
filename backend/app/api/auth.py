"""Argon2 password hashing, HS256 JWTs, and revocable server-side sessions.

Owns: credential verification, token issuance/rotation, session revocation.
Does not own: HTTP concerns (routers), FastAPI wiring (deps), rate-limit
policy beyond the login tracker.

A stateless JWT cannot be revoked before `exp`; for a security product that
matters, so every access token carries a `jti` backed by a `sessions` row —
"sign out everywhere" is a single UPDATE, not a wait for expiry (SECURITY 4.2).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.errors import AuthError as CoreAuthError
from app.db.models.site import _utcnow
from app.db.models.user import Session as SessionRow
from app.db.models.user import User


def _now() -> datetime:
    """Naive UTC now — the convention for every DateTime column (see repositories)."""
    return _utcnow().replace(tzinfo=None)


class AuthError(CoreAuthError):
    """Bad credentials or an invalid/revoked token. Maps to 401."""


class AccountLockedError(CoreAuthError):
    """Too many failed logins; the account is locked. Maps to 423."""


class ForbiddenError(CoreAuthError):
    """Authenticated but the role is insufficient. Maps to 403."""


# SECURITY 4.1: Argon2id at m=64MB t=3 p=4. Tests pass weaker parameters
# explicitly; production call sites rely on these defaults.
_HASH_TIME_COST = 3
_HASH_MEMORY_COST = 64 * 1024  # KiB
_HASH_PARALLELISM = 4

_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_S = 300

_ROLE_RANK: Mapping[str, int] = {"viewer": 1, "admin": 2}

# Precomputed dummy hash so an unknown username burns the same verify time
# as a wrong password (user-enumeration resistance).
_DUMMY_HASH = (
    "$argon2id$v=19$m=8,t=1,p=1$Q7MWRHh+vDCVHhPvcpnXMg$/nH/3sHDLwUhnWY5Qd4JDmUbRXUTmoug5BYoLUVEi10"
)


@dataclass(frozen=True)
class TokenPair:
    """An access/refresh pair as returned to the client."""

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class _AttemptBucket:
    """Consecutive-failure counter for one username."""

    __slots__ = ("failures", "locked_until")

    def __init__(self) -> None:
        self.failures = 0
        self.locked_until: float | None = None


class LoginAttemptTracker:
    """Per-username login-failure counter with a lockout window.

    In-memory and per-process: a single-box product (spec 2), so a shared
    store would be over-engineering. Resets on successful login.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _AttemptBucket] = {}

    def reset(self) -> None:
        """Forget every bucket (test helper)."""
        self._buckets.clear()

    def check_and_record(self, username: str, ok: bool) -> None:
        """Record an attempt; raise if this attempt or the account is locked.

        Args:
            username: The login name attempted.
            ok: Whether the credentials verified.

        Raises:
            AccountLockedError: The account is inside a lockout window.
            AuthError: The credentials were wrong (and may arm a lockout).
        """
        now = time.monotonic()
        bucket = self._buckets.setdefault(username, _AttemptBucket())
        if bucket.locked_until is not None:
            if now < bucket.locked_until:
                raise AccountLockedError("423 account locked: too many failed logins")
            bucket.failures = 0
            bucket.locked_until = None
        if ok:
            bucket.failures = 0
            return
        bucket.failures += 1
        if bucket.failures >= _MAX_LOGIN_ATTEMPTS:
            bucket.locked_until = now + _LOCKOUT_S
        raise AuthError("invalid credentials")


tracker = LoginAttemptTracker()


def hash_password(
    password: str,
    *,
    time_cost: int = _HASH_TIME_COST,
    memory_cost: int = _HASH_MEMORY_COST,
    parallelism: int = _HASH_PARALLELISM,
) -> str:
    """Hash a password with Argon2id at the configured cost.

    Args:
        password: Plaintext password.
        time_cost: Argon2 time cost (production: 3).
        memory_cost: Argon2 memory in KiB (production: 65536 = 64MB).
        parallelism: Argon2 lanes (production: 4).

    Returns:
        The encoded Argon2id hash, safe to store in a TEXT column.
    """
    return PasswordHasher(
        time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
    ).hash(password)


def _verify_password(password: str, encoded: str) -> bool:
    """Verify a password against an Argon2id hash without raising."""
    try:
        return PasswordHasher().verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _jwt_secret() -> bytes:
    """Resolve the HS256 signing key: env, settings, or the master key."""
    env = os.environ.get("CAMBRAIN_JWT_SECRET")
    if env:
        return env.encode()
    if settings.jwt_secret is not None:
        return settings.jwt_secret.get_secret_value().encode()
    # No explicit secret: derive a stable HS256 key from the installation's
    # master key so tokens survive restarts without a second secret to manage.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    from app.core.crypto import get_master_key_material

    master = get_master_key_material(settings.key_dir)
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"cambrain-jwt", info=b"jwt-hs256"
    ).derive(master)


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign_jwt(claims: Mapping[str, object]) -> str:
    """Sign claims as an HS256 JWT (hand-rolled; PyJWT is not in the lock)."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(dict(claims), separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}"
    signature = hmac.new(_jwt_secret(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _decode_jwt(token: str) -> dict[str, object]:
    """Verify signature and expiry, then return the claims."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise AuthError("malformed token") from exc
    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(_jwt_secret(), signing_input.encode(), hashlib.sha256).digest()
    actual = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, actual):
        raise AuthError("invalid token signature")
    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except (ValueError, UnicodeError) as exc:
        raise AuthError("malformed token payload") from exc
    if not isinstance(claims, dict):
        raise AuthError("malformed token payload")
    if int(claims.get("exp", 0)) < int(time.time()):
        raise AuthError("token expired")
    return claims


def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(
    db: DbSession, user: User, *, ip: str | None, user_agent: str | None
) -> tuple[str, str, SessionRow]:
    """Create a session row and the (jti, refresh) pair for it."""
    jti = uuid.uuid4().hex
    refresh = secrets.token_urlsafe(32)
    row = SessionRow(
        id=jti,
        user_id=user.id,
        site_id=user.site_id,
        refresh_token_hash=_hash_refresh(refresh),
        expires_at=_now() + timedelta(seconds=settings.refresh_token_ttl_s),
        ip=ip,
        user_agent=user_agent,
    )
    db.add(row)
    return jti, refresh, row


def issue_tokens(
    db: DbSession,
    user: User,
    password: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> TokenPair:
    """Verify credentials, open a session, and issue a token pair.

    Args:
        db: Open database session.
        user: The user row being logged in.
        password: Plaintext password presented.
        ip: Client address for the session record.
        user_agent: Client user-agent for the session record.

    Returns:
        Access JWT + opaque refresh token + access TTL in seconds.

    Raises:
        AuthError: The password did not verify.
    """
    if not user.is_active or not _verify_password(password, user.password_hash):
        raise AuthError("invalid credentials")
    jti, refresh, _row = _new_session(db, user, ip=ip, user_agent=user_agent)
    user.last_login_at = _now()
    claims: dict[str, object] = {
        "sub": str(user.id),
        "site_id": user.site_id,
        "role": user.role,
        "jti": jti,
        "exp": int(time.time()) + settings.access_token_ttl_s,
    }
    db.commit()
    return TokenPair(
        access_token=_sign_jwt(claims),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_s,
    )


def verify_access_token(db: DbSession, token: str) -> dict[str, object]:
    """Decode an access token and confirm its session is still live.

    Args:
        db: Open database session.
        token: The JWT from the Authorization header.

    Returns:
        The verified claims.

    Raises:
        AuthError: Signature, expiry, or revocation check failed.
    """
    claims = _decode_jwt(token)
    jti = claims.get("jti")
    if not isinstance(jti, str):
        raise AuthError("token missing jti")
    row = db.get(SessionRow, jti)
    if row is None or row.revoked_at is not None:
        raise AuthError("session revoked")
    return claims


def _revoke_family(db: DbSession, user_id: int) -> None:
    """Revoke every live session for a user (refresh-reuse response)."""
    now = _now()
    rows = db.scalars(
        select(SessionRow).where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
    )
    for row in rows:
        row.revoked_at = now
    db.commit()


def verify_refresh_token(db: DbSession, refresh_token: str) -> SessionRow:
    """Look up a refresh token; reuse of a rotated token revokes the family.

    Args:
        db: Open database session.
        refresh_token: The opaque refresh token.

    Returns:
        The still-valid session row.

    Raises:
        AuthError: Unknown, expired, or already-rotated token. Presenting a
            rotated token is treated as theft and revokes every session the
            user owns.
    """
    row = db.scalar(
        select(SessionRow).where(SessionRow.refresh_token_hash == _hash_refresh(refresh_token))
    )
    if row is None:
        raise AuthError("invalid refresh token")
    if row.revoked_at is not None:
        _revoke_family(db, row.user_id)
        raise AuthError("refresh token reuse detected; sessions revoked")
    if row.expires_at < _now():
        raise AuthError("refresh token expired")
    return row


def rotate_refresh_token(
    db: DbSession,
    refresh_token: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> TokenPair:
    """Consume a refresh token and issue a fresh pair for the same user.

    Args:
        db: Open database session.
        refresh_token: The opaque refresh token to rotate.
        ip: Client address for the new session row.
        user_agent: Client user-agent for the new session row.

    Returns:
        A new access/refresh pair; the old refresh is dead.

    Raises:
        AuthError: The refresh token was invalid (see verify_refresh_token).
    """
    old = verify_refresh_token(db, refresh_token)
    user = db.get(User, old.user_id)
    if user is None or not user.is_active:
        raise AuthError("account disabled")
    old.revoked_at = _now()
    jti, refresh, _row = _new_session(db, user, ip=ip, user_agent=user_agent)
    claims: dict[str, object] = {
        "sub": str(user.id),
        "site_id": user.site_id,
        "role": user.role,
        "jti": jti,
        "exp": int(time.time()) + settings.access_token_ttl_s,
    }
    db.commit()
    return TokenPair(
        access_token=_sign_jwt(claims),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_s,
    )


def revoke_session(db: DbSession, access_token: str) -> None:
    """Revoke the session behind an access token (logout).

    Args:
        db: Open database session.
        access_token: The JWT to revoke.

    Raises:
        AuthError: The token itself is malformed or expired.
    """
    claims = _decode_jwt(access_token)
    jti = claims.get("jti")
    if not isinstance(jti, str):
        raise AuthError("token missing jti")
    row = db.get(SessionRow, jti)
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()


def revoke_all_sessions(db: DbSession, user_id: int) -> None:
    """Revoke every live session for a user (password change)."""
    _revoke_family(db, user_id)


def require_role(minimum: str) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    """Build a checker that enforces a minimum role on verified claims.

    Args:
        minimum: The required role ("viewer" or "admin").

    Returns:
        A callable taking claims and returning them, or raising ForbiddenError.
    """
    needed = _ROLE_RANK.get(minimum, 99)

    def _check(claims: Mapping[str, object]) -> Mapping[str, object]:
        role = claims.get("role")
        if not isinstance(role, str) or _ROLE_RANK.get(role, 0) < needed:
            raise ForbiddenError(f"403 forbidden: role must be at least {minimum}")
        return claims

    return _check
