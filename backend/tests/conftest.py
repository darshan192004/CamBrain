"""Fixtures shared by every backend test.

Clips are generated on demand and never committed (spec §11.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.make_fixtures import CLIP_NAMES, ensure_clip
from tests.rtsp.conftest import mediamtx_pause, mediamtx_url  # noqa: F401


@pytest.fixture
def clip_path() -> Path:
    """Path to the generated motion clip — the default input for stream tests."""
    return ensure_clip("motion")


@pytest.fixture
def clips() -> dict[str, Path]:
    """Every documented fixture clip, generated lazily on first access."""
    return {name: ensure_clip(name) for name in CLIP_NAMES}
