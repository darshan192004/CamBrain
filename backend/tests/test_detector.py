"""Letterbox geometry, loud failures, and a real-model smoke test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.core.errors import InferenceError
from app.services.inference.detector import OnnxYoloXDetector, letterbox, open_detector
from app.services.stream.source import Frame

MODELS = Path(__file__).resolve().parents[2] / "models"
GATE = Path(__file__).parent / "fixtures" / "clips" / "gate.mp4"


def _frame(w: int = 768, h: int = 432) -> Frame:
    return Frame(data=np.zeros((h, w, 3), dtype=np.uint8), timestamp=0.0, width=w, height=h)


def test_letterbox_pads_to_square() -> None:
    tensor, meta = letterbox(np.zeros((432, 768, 3), dtype=np.uint8), 640)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert meta.scale == pytest.approx(640 / 768)
    assert meta.pad_x == 0
    assert meta.pad_y == (640 - int(432 * 640 / 768)) // 2
    assert (meta.frame_width, meta.frame_height) == (768, 432)


async def test_rejects_malformed_output() -> None:
    det = OnnxYoloXDetector(Path("unused.onnx"))

    def bad_run(_tensor: np.ndarray) -> np.ndarray:
        return np.zeros((3, 3, 3), dtype=np.float32)

    det._run_tensor = bad_run  # type: ignore[method-assign]
    with pytest.raises(InferenceError, match="expected model output"):
        await det.infer(_frame())


def test_open_detector_requires_weights(tmp_path: Path) -> None:
    with pytest.raises(InferenceError, match="missing"):
        open_detector(tmp_path / "nope.onnx")


@pytest.mark.skipif(
    not (MODELS / "yolox_s.onnx").exists() or not GATE.exists(),
    reason="run backend/scripts/fetch_models.py to enable the real-model smoke test",
)
async def test_real_model_detects_a_person_in_gate_clip() -> None:
    """Letterbox + decode + session, end to end, on the real clip (spec A11.1)."""
    import cv2

    cap = cv2.VideoCapture(str(GATE))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 60)
    ok, bgr = cap.read()
    cap.release()
    assert ok
    rgb = bgr[:, :, ::-1].copy()
    frame = Frame(data=rgb, timestamp=0.0, width=rgb.shape[1], height=rgb.shape[0])
    det = open_detector(MODELS / "yolox_s.onnx")
    try:
        found = await det.infer(frame)
    finally:
        await det.close()
    people = [d for d in found if d.class_name == "person" and d.confidence > 0.5]
    assert people, [(d.class_name, round(d.confidence, 3)) for d in found]
