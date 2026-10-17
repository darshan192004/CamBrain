"""Telegram transport: sendVideo > sendPhoto > sendMessage, token never logged.

The bot token appears inside Telegram's URL, so every httpx failure is caught
and re-raised as TelegramError with the reason only — a token in an error
string is a token in a log file (SECURITY A3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.db.models import Event

DEFAULT_CAPTION_LIMIT = 1024


class TelegramError(Exception):
    """A Telegram delivery failed; the message is credential-free."""


class TelegramNotifier:
    """Notifier for a single bot token + chat id (spec A5.6)."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        media_root: Path | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._base_url = (base_url or settings.telegram_api_base).rstrip("/")
        self._media_root = media_root or settings.media_root

    async def send(self, event: Event) -> None:
        """Deliver the event as video, photo, or text — best media first."""
        caption = f"{event.severity.upper()}: {event.summary or 'CamBrain alert'}"
        caption = caption[:DEFAULT_CAPTION_LIMIT]
        clip = self._resolve(event.clip_path)
        still = self._resolve(event.thumbnail_path)
        if clip is not None and clip.is_file():
            await self._call(
                "sendVideo",
                data={"chat_id": self._chat_id, "caption": caption},
                files={"video": (clip.name, clip.read_bytes(), "video/mp4")},
            )
        elif still is not None and still.is_file():
            await self._call(
                "sendPhoto",
                data={"chat_id": self._chat_id, "caption": caption},
                files={"photo": (still.name, still.read_bytes(), "image/jpeg")},
            )
        else:
            await self._call(
                "sendMessage",
                data={"chat_id": self._chat_id, "text": caption},
            )

    async def test_message(self) -> dict[str, Any]:
        """POST /notifiers/test: a real ping, Telegram's response verbatim."""
        return await self._call(
            "sendMessage",
            data={"chat_id": self._chat_id, "text": "CamBrain test message"},
        )

    def _resolve(self, relative: str | None) -> Path | None:
        return (self._media_root / relative) if relative else None

    async def _call(
        self,
        method: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        """POST one Bot API method; failures raise credential-free errors.

        The URL embeds the bot token, so httpx exception text (which can
        echo the URL) is never included — only the exception class name.
        """
        url = f"{self._base_url}/bot{self._token}/{method}"
        try:
            response = await self._client.post(url, data=data, files=files)
            payload: Any = response.json()
        except httpx.HTTPError as exc:
            raise TelegramError(f"telegram {method} failed: {type(exc).__name__}") from None
        except ValueError as exc:
            raise TelegramError(
                f"telegram {method} returned invalid JSON: {type(exc).__name__}"
            ) from None
        if not isinstance(payload, dict):
            raise TelegramError(f"telegram {method} rejected: unexpected response shape")
        if not payload.get("ok"):
            raise TelegramError(
                f"telegram {method} rejected: {payload.get('description', 'unknown error')}"
            )
        return dict(payload)
