"""User routes: admin-only CRUD with last-admin protection (API §Users).

A user cannot demote or delete the last remaining admin — 409. Locking
yourself out of your own box is a support call, and it is preventable.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select

from app.api.auth import hash_password
from app.api.deps import DbSessionDep, require_role_dep
from app.api.schemas import UserCreate, UserOut, UserPatch
from app.core.errors import ConflictError, NotFoundError
from app.db.models.user import User

router = APIRouter(tags=["users"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]


def _to_out(user: User) -> UserOut:
    """Map a User row to its public response (no password hash)."""
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _admin_count(db: Any, site_id: int) -> int:
    """Count active admins in the site."""
    return int(
        db.execute(
            select(func.count())
            .select_from(User)
            .where(User.site_id == site_id, User.role == "admin", User.is_active.is_(True))
        ).scalar_one()
    )


def _last_admin_check(db: Any, claims: dict[str, Any], user: User) -> None:
    """Raise 409 if the action would remove the last active admin."""
    if user.role == "admin" and user.is_active and _admin_count(db, int(claims["site_id"])) <= 1:
        raise ConflictError("cannot demote or delete the last remaining admin")


def _get_or_404(db: Any, claims: dict[str, Any], user_id: int) -> User:
    """Fetch a user scoped to the caller's site."""
    user: User | None = db.get(User, user_id)
    if user is None or user.site_id != int(claims["site_id"]):
        raise NotFoundError("user not found")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(claims: AdminDep, db: DbSessionDep) -> list[UserOut]:
    """List every user in the caller's site."""
    rows = db.execute(
        select(User).where(User.site_id == int(claims["site_id"])).order_by(User.id)
    ).scalars()
    return [_to_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, claims: AdminDep, db: DbSessionDep) -> UserOut:
    """Create a user in the caller's site. Admin only."""
    user = User(
        site_id=int(claims["site_id"]),
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_out(user)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, claims: AdminDep, db: DbSessionDep) -> UserOut:
    """Fetch one user. Cross-tenant id is a 404."""
    return _to_out(_get_or_404(db, claims, user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: UserPatch, claims: AdminDep, db: DbSessionDep) -> UserOut:
    """Update a user. Demoting the last admin is a 409."""
    user = _get_or_404(db, claims, user_id)
    updates = body.model_dump(exclude_unset=True)
    if "role" in updates and updates["role"] != user.role:
        _last_admin_check(db, claims, user)
    if updates.get("is_active") is False:
        _last_admin_check(db, claims, user)
    if "password" in updates and updates["password"] is not None:
        user.password_hash = hash_password(updates["password"])
        del updates["password"]
    for key, value in updates.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return _to_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, claims: AdminDep, db: DbSessionDep) -> Response:
    """Delete a user. Deleting the last admin is a 409."""
    user = _get_or_404(db, claims, user_id)
    _last_admin_check(db, claims, user)
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
