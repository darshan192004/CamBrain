"""Pydantic request/response models for the API surface (auth portion first)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class CameraCreate(BaseModel):
    """POST /cameras body. `site_id` is never accepted — it comes from the token."""

    name: str = Field(min_length=1, max_length=128)
    rtsp_url: str = Field(min_length=1, max_length=512)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=128)
    enabled: bool = True
    sample_fps: float = Field(default=2.0, ge=0.1, le=10)
    motion_threshold: float = Field(default=0.02, ge=0.0, le=1.0)

    @field_validator("rtsp_url")
    @classmethod
    def _must_be_rtsp(cls, value: str) -> str:
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("rtsp_url must start with rtsp:// or rtsps://")
        return value

    @field_validator("password")
    @classmethod
    def _no_empty_password(cls, value: str | None) -> str | None:
        # "" is rejected: an empty password on a camera is almost always a
        # mistake, not an intent (API §Cameras).
        if value == "":
            raise ValueError("password must not be empty; use null to clear")
        return value


class CameraPatch(BaseModel):
    """PATCH /cameras/{id}. Omit `password` = unchanged, `null` = clear, `""` = 422."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    rtsp_url: str | None = Field(default=None, min_length=1, max_length=512)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    sample_fps: float | None = Field(default=None, ge=0.1, le=10)
    motion_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("rtsp_url")
    @classmethod
    def _must_be_rtsp(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("rtsp_url must start with rtsp:// or rtsps://")
        return value

    @field_validator("password")
    @classmethod
    def _no_empty_password(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("password must not be empty; use null to clear")
        return value


class CameraOut(BaseModel):
    """Camera response. Never contains `username` or the real password."""

    id: int
    name: str
    rtsp_url: str
    has_password: bool
    password: str | None = None  # masked "••••••••" when set, else null
    enabled: bool
    sample_fps: float
    motion_threshold: float
    frame_width: int | None
    frame_height: int | None
    status: Literal["starting", "live", "offline", "error"]
    last_error: str | None
    created_at: datetime


class CameraTestResult(BaseModel):
    """POST /cameras/{id}/test. Always 200 — a failed probe is data, not an error."""

    ok: bool
    message: str
    latency_ms: int | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    fps: float | None = None
    error_code: str | None = None
