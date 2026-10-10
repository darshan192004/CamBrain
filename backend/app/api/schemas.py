"""Pydantic request/response models for the API surface (auth portion first)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /auth/login body."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """POST /auth/refresh body."""

    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password body."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """Token pair returned by login and refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    """GET /auth/me: the caller's identity and tenancy."""

    user_id: int
    username: str
    role: str
    site_id: int


class OkResponse(BaseModel):
    """Generic acknowledgement body."""

    ok: bool = True
