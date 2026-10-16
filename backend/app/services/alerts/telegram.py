"""Telegram transport behind the `Notifier` protocol (spec §5.6).

Owns: `sendPhoto` against the Bot API. Does not own: config storage or
retry — the token arrives decrypted from the caller, and `deliver_event`
in `notifier.py` decides what a failure means.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.crypto import decrypt
from app.core.errors import NotificationError
from app.core.logging import mask_url

_SEND_TIMEOUT_S = 30.0
_MASK = "••••••••"
# Plaintext keys are never stored: create/patch seal these to `{key}_enc`.
SECRET_KEYS = ("bot_token", "api_key", "api_token", "token", "secret")


def seal_config(config: dict[str, Any]) -> dict[str, Any]:
    """Encrypt secret values into `{key}_enc` entries, dropping plaintext.

    Mirrors the cameras table (`rtsp_password_enc`): the stored dict is
    safe to select and export, and only the `_enc` columns need the key.
    """
    from app.core.crypto import encrypt

    sealed = dict(config)
    for key in SECRET_KEYS:
        value = sealed.get(key)
        if isinstance(value, str) and value and value != _MASK:
            sealed[f"{key}_enc"] = encrypt(value)
            sealed.pop(key, None)
    return sealed


def public_config(entry: dict[str, Any]) -> dict[str, Any]:
    """GET-safe view: raw non-secrets plus masked placeholders, no ciphertext."""
    raw = entry.get("config", {})
    config = dict(raw) if isinstance(raw, dict) else {}
    out: dict[str, Any] = {k: v for k, v in config.items() if not k.endswith("_enc")}
    for key in SECRET_KEYS:
        if f"{key}_enc" in config:
            out[key] = _MASK
    return out


def notifiers_from_entries(entries: list[dict[str, Any]]) -> list[TelegramNotifier]:
    """Build enabled telegram senders, decrypting tokens. Plaintext falls back
    for rows written before sealing — they reseal on the next patch."""
    notifiers: list[TelegramNotifier] = []
    for entry in entries:
        if entry.get("kind", "telegram") != "telegram" or not entry.get("enabled", True):
            continue
        config = entry.get("config", {})
        if not isinstance(config, dict):
            continue
        token = None
        enc = config.get("bot_token_enc")
        if isinstance(enc, str) and enc:
            token = decrypt(enc)
        elif isinstance(config.get("bot_token"), str) and config["bot_token"]:
            token = str(config["bot_token"])
        chat = config.get("chat_id")
        if token and chat:
            notifiers.append(TelegramNotifier(token, str(chat)))
    return notifiers


class TelegramNotifier:
    """Send a photo + caption via `sendPhoto`. Free, instant, no verification."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        """Take the decrypted token; never log or store it here."""
        self._token = bot_token
        self._chat_id = chat_id

    async def send(self, *, photo: bytes, caption: str) -> None:
        """POST one photo message. Raises `NotificationError`, token-masked."""
        body = await self._post("sendPhoto", data={"caption": caption}, photo=photo)
        if not body.get("ok", False):
            raise NotificationError(f"telegram rejected the photo: {mask_url(str(body))}"[:500])

    async def send_text(self, text: str) -> dict[str, Any]:
        """POST a text message; return Telegram's response verbatim.

        The `/notifiers/test` endpoint proves a config actually delivers —
        a config that never delivered is not a working notifier (API §System).
        """
        body = await self._post("sendMessage", data={"text": text})
        if not body.get("ok", False):
            raise NotificationError(f"telegram rejected the text: {mask_url(str(body))}"[:500])
        return body

    async def _post(
        self, method: str, *, data: dict[str, str], photo: bytes | None = None
    ) -> dict[str, Any]:
        """POST one Bot API call. Transport errors become masked `NotificationError`."""
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        payload = {"chat_id": self._chat_id, **data}
        try:
            async with httpx.AsyncClient(timeout=_SEND_TIMEOUT_S) as client:
                if photo is None:
                    resp = await client.post(url, json=payload)
                else:
                    resp = await client.post(url, data=payload, files={"photo": photo})
                body = resp.json()
        except Exception as exc:
            raise NotificationError(f"telegram send failed: {mask_url(str(exc))}") from exc
        if resp.status_code != 200:
            raise NotificationError(f"telegram errored: {mask_url(str(body))}"[:500])
        return dict(body)
