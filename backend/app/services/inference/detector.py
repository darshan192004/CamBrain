"""ONNX Runtime implementation of the Detector protocol (spec A5.2, D17).

The factory `open_detector` is the single binding point: swapping to RT-DETR
means one new module + one new implementation here, nothing else changes.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from app.core.errors import InferenceError
from app.services.inference.pool import InferencePool
from app.services.inference.types import Detection, Detector, LetterboxMeta
from app.services.inference.yolox_post import decode
from app.services.stream.source import Frame

PAD_VALUE = 114


def letterbox(image: np.ndarray, input_size: int = 640) -> tuple[np.ndarray, LetterboxMeta]:
    """Aspect-preserving resize onto a square 114-padded canvas; RGB CHW float."""
    height, width = image.shape[:2]
    scale = min(input_size / width, input_size / height)
    new_w, new_h = int(width * scale), int(height * scale)
    resized = cv2.resize(image, (new_w, new_h))
    pad_x = (input_size - new_w) // 2
    pad_y = (input_size - new_h) // 2
    canvas = np.full((input_size, input_size, 3), PAD_VALUE, dtype=np.uint8)
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    tensor = canvas.transpose(2, 0, 1)[None].astype(np.float32)
    meta = LetterboxMeta(
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
        input_size=input_size,
        frame_width=width,
        frame_height=height,
    )
    return tensor, meta


class OnnxYoloXDetector:
    """One YOLOX ONNX session shared across camera pipelines."""

    def __init__(
        self,
        model_path: Path,
        *,
        input_size: int = 640,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        pool: InferencePool | None = None,
    ) -> None:
        self._model_path = model_path
        self._input_size = input_size
        self._conf_threshold = conf_threshold
        self._iou_threshold = iou_threshold
        self._pool = pool
        self._owns_pool = pool is None
        self._session: ort.InferenceSession | None = None

    def _get_session(self) -> ort.InferenceSession:
        if self._session is None:
            if not self._model_path.exists():
                raise InferenceError(
                    f"model weights missing: {self._model_path}"
                    " - run backend/scripts/fetch_models.py"
                )
            self._session = ort.InferenceSession(
                str(self._model_path), providers=["CPUExecutionProvider"]
            )
        return self._session

    def _run_tensor(self, tensor: np.ndarray) -> np.ndarray:
        session = self._get_session()
        input_name = session.get_inputs()[0].name
        raw: np.ndarray = session.run(None, {input_name: tensor})[0]
        return raw

    async def infer(self, frame: Frame) -> list[Detection]:
        """Letterbox, run, decode; malformed output raises InferenceError."""
        tensor, meta = letterbox(frame.data, self._input_size)
        pool = self._pool or self._ensure_pool()
        raw = await pool.run(self._run_tensor, tensor)
        return decode(
            raw, meta, conf_threshold=self._conf_threshold, iou_threshold=self._iou_threshold
        )

    def _ensure_pool(self) -> InferencePool:
        if self._pool is None:
            self._pool = InferencePool()
        return self._pool

    async def close(self) -> None:
        """Drop the session and, if we created it, the pool. Idempotent."""
        self._session = None
        if self._owns_pool and self._pool is not None:
            self._pool.close()
            self._pool = None


def open_detector(
    model_path: Path, *, input_size: int = 640, pool: InferencePool | None = None
) -> Detector:
    """Build a Detector, failing early when weights have not been fetched."""
    if not model_path.exists():
        raise InferenceError(
            f"model weights missing: {model_path} - run backend/scripts/fetch_models.py"
        )
    return OnnxYoloXDetector(model_path, input_size=input_size, pool=pool)
