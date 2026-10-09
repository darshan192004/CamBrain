"""Prove secrets cannot reach the log, regardless of caller discipline."""

from __future__ import annotations

import pytest

from app.core.logging import REDACTED, configure_logging, get_logger, mask_url

SECRET = "sup3rSecretValue123"


def _capture_logs(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_no_secret_in_log_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Every REDACT_KEY must be stripped from emitted log records."""
    configure_logging(level="DEBUG")

    logger = get_logger("test")
    logger.info(
        "camera config",
        rtsp_password=SECRET,
        password=SECRET,
        token=SECRET,
        bot_token=SECRET,
        api_key=SECRET,
        secret=SECRET,
        authorization=SECRET,
        camera_name="Back door",  # not a secret — must survive
    )

    output = _capture_logs(capsys)
    assert SECRET not in output, "a secret leaked into the log"
    assert "Back door" in output, "non-secret fields must not be redacted"
    assert REDACTED in output


def test_rtsp_url_userinfo_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    """An RTSP URL in a log must not carry credentials."""
    configure_logging(level="DEBUG")

    url = f"rtsp://admin:{SECRET}@10.0.0.5:554/Streaming/Channels/101"
    logger = get_logger("test")
    logger.warning("camera unreachable", rtsp_url=url, detail=url)

    output = _capture_logs(capsys)
    assert SECRET not in output
    assert "10.0.0.5" in output, "host is needed to diagnose"
    assert "Streaming/Channels/101" in output, "path is needed to diagnose"
    assert "***" in output


def test_redaction_is_case_insensitive() -> None:
    """A caller using RTSP_PASSWORD must still be redacted."""
    from app.core.logging import redact_event

    event = {"RTSP_PASSWORD": SECRET, "Bot_Token": SECRET, "safe": "keep-me"}
    redacted = redact_event(event)

    assert redacted["RTSP_PASSWORD"] == REDACTED
    assert redacted["Bot_Token"] == REDACTED
    assert redacted["safe"] == "keep-me"


def test_exception_messages_are_redacted() -> None:
    """A secret inside an exception message must not survive."""
    from app.core.logging import redact_value

    result = redact_value(f"failed to connect with password {SECRET}")
    assert SECRET not in str(result)


@pytest.mark.parametrize(
    ("raw", "expected_contains", "expected_excludes"),
    [
        ("rtsp://admin:pw@10.0.0.5:554/stream", "10.0.0.5", "admin"),
        ("rtsp://10.0.0.5:554/stream", "10.0.0.5", "@"),
        ("not a url at all", "not a url at all", "\0"),
    ],
)
def test_mask_url(
    raw: str, expected_contains: str, expected_excludes: str
) -> None:
    masked = mask_url(raw)
    assert expected_contains in masked
    assert expected_excludes not in masked
