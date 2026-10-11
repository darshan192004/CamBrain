"""Bounded executor for ONNX runs.

Eight cameras must not mean eight simultaneous sessions submits: the pool caps
concurrent inference (spec A4.7, A1.5) while the GIL-releasing run() keeps
decode moving. One session per tier is shared; sessions are thread-safe.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class InferencePool:
    """Run blocking inference calls on a bounded thread pool."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="infer"
        )

    async def run(self, fn: Callable[..., T], /, *args: object) -> T:
        """Await fn(*args) on the pool thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args))

    def close(self) -> None:
        """Stop accepting work; never called from inside a pool task."""
        self._executor.shutdown(wait=False, cancel_futures=True)
