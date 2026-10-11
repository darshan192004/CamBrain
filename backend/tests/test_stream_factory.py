"""connect_url assembly (Phase 4 D9): credentials enter a URL exactly once.

The repository keeps credentials in dedicated columns so `rtsp_url` can be
logged and returned; this module is the single place they are joined, and
only at connection time.
"""

from __future__ import annotations

from app.db.models import Camera
from app.services.stream.factory import connect_url

_URL = "rtsp://10.0.0.5:554/Streaming/Channels/101"


def _camera(**overrides: object) -> Camera:
    fields: dict = {"rtsp_url": _URL}
    fields.update(overrides)
    return Camera(**fields)  # type: ignore[arg-type] - transient row, no session


def test_connect_url_embeds_credentials_encoded() -> None:
    camera = _camera(
        rtsp_username="ad min",
        rtsp_password_enc=b"tok",
    )
    url = connect_url(camera, decrypt=lambda _tok: "p@ss:w/rd")
    assert url == "rtsp://ad%20min:p%40ss%3Aw%2Frd@10.0.0.5:554/Streaming/Channels/101"
    # The stored URL is never mutated — it stays credential-free for logs/API.
    assert camera.rtsp_url == _URL
    assert "p@ss" not in camera.rtsp_url


def test_connect_url_without_username_is_unchanged() -> None:
    camera = _camera()
    assert connect_url(camera, decrypt=lambda _tok: "x") == _URL


def test_connect_url_username_only_has_no_colon() -> None:
    camera = _camera(rtsp_username="admin", rtsp_password_enc=None)
    url = connect_url(camera, decrypt=lambda _tok: "x")
    assert url == "rtsp://admin@10.0.0.5:554/Streaming/Channels/101"


def test_connect_url_decrypts_the_stored_token() -> None:
    seen: list[str] = []

    def _decrypt(token: str) -> str:
        seen.append(token)
        return "hunter2"

    camera = _camera(rtsp_username="admin", rtsp_password_enc=b"gAAAA-token")
    connect_url(camera, decrypt=_decrypt)
    assert seen == ["gAAAA-token"]
