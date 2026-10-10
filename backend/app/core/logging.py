"""Structured logging with structural secret redaction.

Owns: log formatting and the guarantee that secrets never reach a log sink.
Does not own: what gets logged (callers decide that) or where logs go.

Redaction lives in the structlog processor chain rather than at call sites.
That placement is the whole point: a developer cannot leak a credential by
forgetting to mask it, because every event passes through this processor.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

REDACTED = "••••••••"

# Keys whose values are secret regardless of context.
# Matching is case-insensitive and substring-based, so `RTSP_PASSWORD` and
# `telegram_bot_token_enc` are both caught by the entries below.
REDACT_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "bot_token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "private_key",
        "session_token",
        "jwt_secret",
        "master_key",
        "signature",
        "salt",
    }
)

# Encrypted-at-rest columns: the ciphertext is not a secret, but logging it
# is pointless noise and invites confusion during debugging.
_REDACT_SUFFIXES = ("_enc", "_encrypted", "_ciphertext")

# rtsp://user:password@host:port/path  ->  rtsp://***:***@host:port/path
# Whitespace-bounded and greedy so the credentials stretch to the LAST '@' in
# the token; a password may legitimately contain '@' or '/'. A URL that has an
# '@' in its path but no userinfo is intentionally over-redacted: security over
# precision.
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<creds>[^\s]+)@")

# A secret pasted into free text ("failed with password hunter2").
# Catches keyword-prefixed values without over-matching ordinary prose.
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)"
    r"(?:=|:|\s+)"
    r"(?P<value>[^\s,;'\"}]{3,})"
)


def mask_url(url: str) -> str:
    """Strip credentials from a URL, preserving host, port, and path.

    Preserving the host and path matters: an installer reading a log needs to
    know *which* camera and *which* channel failed. Only userinfo is removed.

    Args:
        url: Any string. Non-URLs pass through with inline secrets masked.

    Returns:
        The URL with userinfo replaced by `***:***`.

    Examples:
        >>> mask_url("rtsp://admin:pw@10.0.0.5:554/stream")
        'rtsp://***:***@10.0.0.5:554/stream'
    """
    masked = _URL_CREDENTIALS.sub(r"\g<scheme>***:***@", url)
    return _INLINE_SECRET.sub(_replace_inline_secret, masked)


def _replace_inline_secret(match: re.Match[str]) -> str:
    keyword = match.group(1)
    return f"{keyword}={REDACTED}"


def _is_secret_key(key: str) -> bool:
    """Return True when a field name indicates the value must not be logged.

    Matching is case-insensitive and substring-based so aliases such as
    `RTSP_PASSWORD` and `telegram_bot_token_enc` are caught even when they do
    not match a `REDACT_KEYS` entry exactly. `_REDACT_SUFFIXES` catches
    encrypted-at-rest columns whose base name carries no secret keyword.
    """
    normalised = key.lower().replace("-", "_")
    if any(secret in normalised for secret in REDACT_KEYS):
        return True
    return any(normalised.endswith(suffix) for suffix in _REDACT_SUFFIXES)


def redact_value(value: Any) -> Any:
    """Recursively redact a single value.

    Strings get URL userinfo and inline-secret masking. Mappings and sequences
    are walked so a secret nested inside an exception dict is still caught.
    """
    if isinstance(value, str):
        return mask_url(value)
    if isinstance(value, dict):
        return redact_event(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def redact_event(event_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Redact secrets from an event dict.

    Pure, single-argument so it is directly testable. The structlog processor
    chain calls `_redact_processor`, which adapts the structlog signature.

    Non-string keys (int port numbers, enum members) are passed through
    untouched: `mask_url` and `_is_secret_key` both assume `str`, and a
    `TypeError` raised inside a log processor would crash the log call itself.
    """
    return {
        (mask_url(key) if isinstance(key, str) else key): (
            REDACTED if isinstance(key, str) and _is_secret_key(key) else redact_value(value)
        )
        for key, value in event_dict.items()
    }


def _redact_processor(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """structlog processor adapter for `redact_event`."""
    return redact_event(event_dict)


def redact_exc_info(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """structlog processor: scrub secret URLs from exception text.

    An exception message is the single most common leak vector, because it
    is often built by string interpolation at the raise site rather than
    passed as a structured field.

    `format_exc_info` runs earlier and *pops* `exc_info`, leaving only the
    formatted `exception` string, so we guard on that alone.
    """
    if event_dict.get("exception"):
        event_dict["exception"] = mask_url(str(event_dict["exception"]))
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool | None = None) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: Standard logging level name.
        json_output: Force JSON (`logs/`) or console (`--dev`) format. `None`
            means JSON when not in a TTY, which is the production default.
    """
    if json_output is None:
        json_output = not sys.stdout.isatty()

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )
    # uvicorn and httpx are chatty at INFO and we have nothing to learn from them.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    renderer = (
        # Default ensure_ascii=True escapes non-ASCII safely; a non-UTF-8 sink
        # would otherwise raise UnicodeEncodeError inside StreamHandler, which
        # swallows the whole record and can drop security lines entirely.
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[
            # Order matters. Context is bound first so request/camera ids are
            # available; redaction runs last so nothing reaches a sink.
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redact_processor,
            redact_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Redaction runs here too, for records that arrive from *stdlib*
        # loggers (uvicorn, httpx, or any `logging.getLogger(name)` module
        # such as crypto.py) rather than through the structlog chain above.
        # Without this, a secret in a third-party log line reaches the sink
        # unmasked — the exact leak the redaction chain exists to prevent.
        foreign_pre_chain=[_redact_processor, redact_exc_info],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    logging.getLogger().handlers[0].setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger.

    Args:
        name: Usually `__name__`.

    Returns:
        A logger that has already passed through the redaction chain.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
