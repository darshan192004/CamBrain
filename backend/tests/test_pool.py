"""The pool bounds executor threads and propagates failures untouched."""

from __future__ import annotations

import pytest

from app.services.inference.pool import InferencePool


async def test_run_returns_value() -> None:
    pool = InferencePool(max_workers=1)
    try:
        assert await pool.run(lambda a, b: a + b, 2, 3) == 5
    finally:
        pool.close()


async def test_run_propagates_errors() -> None:
    pool = InferencePool(max_workers=1)
    try:
        with pytest.raises(ValueError, match="boom"):
            await pool.run(_explode)
    finally:
        pool.close()


def _explode() -> None:
    raise ValueError("boom")
