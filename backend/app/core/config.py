"""Runtime settings: bind address, paths, token TTLs.

Owns where the database and keys live and how the server binds. Does not own
domain defaults like retention or disk quota — those live on the Site row and
are per-tenant, not global.

The default bind is loopback-only. The box sits on a customer LAN and anyone
on that LAN can reach the port (SECURITY §2); a wider bind is an explicit,
logged decision, not a default.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


class Settings(BaseSettings):
    """Process-wide configuration, sourced from `CAMBRAIN_*` env vars.

    Env vars win over defaults. A `.env` file may supply values but is never
    committed; the file is optional so a bare environment still starts.
    """

    model_config = SettingsConfigDict(env_prefix="CAMBRAIN_", env_file=".env", extra="ignore")

    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    # Opt-in to 0.0.0.0; the startup path logs a WARN when this is True.
    bind_all: bool = False
    db_path: Path = Path(r"%LOCALAPPDATA%\CamBrain\cambrain.db")
    key_dir: Path | None = None
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    access_token_ttl_s: int = 43200
    refresh_token_ttl_s: int = 604800


settings = Settings()
