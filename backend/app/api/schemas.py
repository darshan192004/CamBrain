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


# COCO 80-class names. Rules store names, not indices, because YOLOX and
# RT-DETR do not share an output ordering (spec 6.4).
COCO_CLASSES: frozenset[str] = frozenset(
    {
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "airplane",
        "bus",
        "train",
        "truck",
        "boat",
        "traffic light",
        "fire hydrant",
        "stop sign",
        "parking meter",
        "bench",
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
        "backpack",
        "umbrella",
        "handbag",
        "tie",
        "suitcase",
        "frisbee",
        "skis",
        "snowboard",
        "sports ball",
        "kite",
        "baseball bat",
        "baseball glove",
        "skateboard",
        "surfboard",
        "tennis racket",
        "bottle",
        "wine glass",
        "cup",
        "fork",
        "knife",
        "spoon",
        "bowl",
        "banana",
        "apple",
        "sandwich",
        "orange",
        "broccoli",
        "carrot",
        "hot dog",
        "pizza",
        "donut",
        "cake",
        "chair",
        "couch",
        "potted plant",
        "bed",
        "dining table",
        "toilet",
        "tv",
        "laptop",
        "mouse",
        "remote",
        "keyboard",
        "cell phone",
        "microwave",
        "oven",
        "toaster",
        "sink",
        "refrigerator",
        "book",
        "clock",
        "vase",
        "scissors",
        "teddy bear",
        "hair drier",
        "toothbrush",
    }
)


class RoiCreate(BaseModel):
    """POST /cameras/{id}/rois body. Points are normalised 0..1."""

    name: str = Field(min_length=1, max_length=128)
    points: list[list[float]] = Field(min_length=3)
    class_filter: list[str] | None = None
    active: bool = True

    @field_validator("points")
    @classmethod
    def _validate_points(cls, value: list[list[float]]) -> list[list[float]]:
        for point in value:
            if len(point) != 2:
                raise ValueError("each point must be [x, y]")
            x, y = point
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("coordinates must be normalised 0.0..1.0")
        return value

    @field_validator("class_filter")
    @classmethod
    def _validate_classes(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            for name in value:
                if name not in COCO_CLASSES:
                    raise ValueError(f"unknown COCO class: {name}")
        return value


class RoiPatch(BaseModel):
    """PATCH /rois/{id}. The full point list is required on every edit."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    points: list[list[float]] | None = Field(default=None, min_length=3)
    class_filter: list[str] | None = None
    active: bool | None = None

    @field_validator("points")
    @classmethod
    def _validate_points(cls, value: list[list[float]] | None) -> list[list[float]] | None:
        if value is None:
            return value
        for point in value:
            if len(point) != 2:
                raise ValueError("each point must be [x, y]")
            x, y = point
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("coordinates must be normalised 0.0..1.0")
        return value


class RoiOut(BaseModel):
    """ROI response. `coverage_pct` is polygon area / frame area, in percent."""

    id: int
    camera_id: int
    name: str
    points: list[list[float]]
    coverage_pct: float
    vertex_count: int
    class_filter: list[str] | None
    active: bool
    created_at: datetime


class ActiveHoursWindow(BaseModel):
    """One active window. `end < start` means the window wraps past midnight."""

    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class ActiveHours(BaseModel):
    """When a rule may fire. Windows may cross midnight (22:00 -> 06:00)."""

    timezone: str = Field(min_length=1, max_length=64)
    windows: list[ActiveHoursWindow] = Field(min_length=1, max_length=4)


class RuleCreate(BaseModel):
    """POST /cameras/{id}/rules body."""

    name: str = Field(min_length=1, max_length=128)
    roi_id: int | None = None
    enabled: bool = True
    classes: list[str] = Field(min_length=1)
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    cooldown_seconds: int = Field(default=60, ge=5, le=86400)
    active_hours: ActiveHours | None = None
    severity: Literal["info", "warning", "critical"] = "warning"
    notify: bool = True

    @field_validator("classes")
    @classmethod
    def _validate_classes(cls, value: list[str]) -> list[str]:
        for name in value:
            if name not in COCO_CLASSES:
                raise ValueError(f"unknown COCO class: {name}")
        return value


class RulePatch(BaseModel):
    """PATCH /rules/{id}. Soft-deleted rules cannot be resurrected."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    roi_id: int | None = None
    enabled: bool | None = None
    classes: list[str] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    cooldown_seconds: int | None = Field(default=None, ge=5, le=86400)
    active_hours: ActiveHours | None = None
    severity: Literal["info", "warning", "critical"] | None = None
    notify: bool | None = None

    @field_validator("classes")
    @classmethod
    def _validate_classes(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            for name in value:
                if name not in COCO_CLASSES:
                    raise ValueError(f"unknown COCO class: {name}")
        return value


class RuleOut(BaseModel):
    """Rule response. Soft-deleted rules are hidden from every read."""

    id: int
    camera_id: int
    roi_id: int | None
    name: str
    enabled: bool
    classes: list[str]
    confidence_threshold: float
    cooldown_seconds: int
    active_hours: dict[str, object] | None
    severity: str
    notify: bool
    created_at: datetime
