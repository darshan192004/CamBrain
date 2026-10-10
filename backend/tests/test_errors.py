"""The error hierarchy must be catchable at three levels of specificity."""

from __future__ import annotations

import pytest

from app.core.errors import (
    CamBrainError,
    DetectionError,
    InferenceError,
    NotFoundError,
    StreamError,
)


def test_all_errors_subclass_base() -> None:
    """Catching CamBrainError must catch every domain error."""
    for error_type in (StreamError, InferenceError, DetectionError, NotFoundError):
        assert issubclass(error_type, CamBrainError)


def test_catch_by_specific_type() -> None:
    """A caller can branch on the narrow type where it matters."""
    with pytest.raises(StreamError) as excinfo:
        raise StreamError("RTSP handshake failed")
    assert "handshake" in str(excinfo.value)


def test_catch_by_family() -> None:
    """A caller handling all inference problems uses one except clause."""
    with pytest.raises(CamBrainError):
        raise InferenceError("model output shape mismatch")


def test_error_message_never_contains_url_credentials() -> None:
    """Raising with a URL must not leak credentials through the message."""
    from app.core.errors import safe_error

    message = safe_error("cannot reach rtsp://admin:hunter2@10.0.0.5:554/stream")
    assert "hunter2" not in message
    assert "10.0.0.5" in message


def test_cause_is_preserved() -> None:
    """`from exc` chaining must survive so tracebacks stay diagnosable."""
    original = ValueError("low level failure")
    with pytest.raises(StreamError) as excinfo:
        raise StreamError("container open failed") from original

    assert excinfo.value.__cause__ is original
