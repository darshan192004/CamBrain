"""Frozen engine entrypoint (packaged layout, D6-1 / plan T5).

The installer ships this as ``cambrian-engine.exe`` (PyInstaller onedir) and
the shell's supervisor spawns it with the resolved ``CAMBRAIN_*`` env,
mirroring the dev invocation ``python -m uvicorn app.main:app``. Frozen runs
need two things dev gets for free:

1. the schema: dev runs ``alembic upgrade head`` by hand (DATABASE.md); the
   packaged engine runs it on every start — no-op on a current schema,
   full creation on a fresh one. The migrations folder ships as data.
2. the model path: the repo-relative default is meaningless next to the exe,
   so the resolved tier's path is pointed at app data (D6-3) after config
   import — the same folder D6-4's bootstrap downloads into, and the same
   filename ``resolve_tier`` picks, so detector and bootstrap agree.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _script_location() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller onedir / onefile
        return Path(getattr(sys, "_MEIPASS", ".")) / "migrations"
    return Path(__file__).resolve().parents[1] / "migrations"


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    from app.core.config import settings

    cfg = Config()
    cfg.set_main_option("script_location", str(_script_location()))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")
    command.upgrade(cfg, "head")


_migrate()

# Point the detector at the resolved tier's asset under app data. Only the
# runtime reads ``settings.model_path`` afterwards (attribute, not env), so
# an assignment here re-scripts the packaged flow without touching dev.
if getattr(sys, "frozen", False):  # PyInstaller onedir / onefile
    from app.core.config import settings
    from app.services.inference.tiers import resolve_tier

    _tier, _model_path, _input_size = resolve_tier()
    settings.model_path = _model_path
    settings.model_input_size = _input_size

import uvicorn  # noqa: E402 - migrations run first

from app.main import app  # noqa: E402 - migrations run first

port = int(os.environ.get("CAMBRAIN_ENGINE_PORT", "8765"))
log_level = os.environ.get("CAMBRAIN_ENGINE_LOG_LEVEL", "info")

uvicorn.run(app, host="127.0.0.1", port=port, log_level=log_level)
