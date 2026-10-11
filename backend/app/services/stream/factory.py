"""Injectable FrameSource construction for API routes (spec 11.1 / plan D9).

Probe, snapshot, and MJPEG all obtain their source through this seam: the
production factory opens RTSP with decrypted credentials, tests override
`get_source_factory` with a `FileSource` (or a fake), and no route ever
opens a connection its own way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from app.db.models.camera import Camera
from app.services.stream.rtsp_source import RtspSource
from app.services.stream.source import FrameSource

SourceFactory = Callable[[Camera], FrameSource]


class DecryptFn(Protocol):
    """Decrypt a stored Fernet token (matches app.core.crypto.decrypt)."""

    def __call__(self, token: str, key_dir: object = ...) -> str: ...


def connect_url(camera: Camera, *, decrypt: Callable[[str], str]) -> str:
    """Build a credentials-bearing RTSP URL from the dedicated columns.

    Credentials live in `rtsp_username` / `rtsp_password_enc` (DATABASE §4.4)
    so `rtsp_url` stays safe to log and return; this is the single place
    they enter a URL, and that URL never leaves the process.
    """
    parts = urlsplit(camera.rtsp_url)
    if camera.rtsp_username:
        userinfo = quote(camera.rtsp_username, safe="")
        if camera.rtsp_password_enc is not None:
            password = decrypt(camera.rtsp_password_enc.decode("ascii"))
            userinfo += ":" + quote(password, safe="")
        netloc = f"{userinfo}@{parts.netloc}"
    else:
        netloc = parts.netloc
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def default_source_factory(camera: Camera) -> FrameSource:
    """Production factory: a fresh RTSP source for this request's consumer."""
    from app.core.crypto import decrypt  # noqa: PLC0415 - DPAPI touch only when used

    def _decrypt(token: str) -> str:
        return decrypt(token)

    return RtspSource(connect_url(camera, decrypt=_decrypt))


def get_source_factory() -> SourceFactory:
    """FastAPI dependency: the frame-source seam routes depend on."""
    return default_source_factory
