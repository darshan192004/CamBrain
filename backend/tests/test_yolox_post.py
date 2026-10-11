"""Decode contract: grid space -> frame pixels, names not indices, loud failures."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.errors import InferenceError
from app.services.inference.types import COCO_CLASSES, LetterboxMeta
from app.services.inference.yolox_post import decode, nms

META = LetterboxMeta(
    scale=0.5, pad_x=10, pad_y=20, input_size=640, frame_width=1280, frame_height=720
)


def _blank() -> np.ndarray:
    return np.zeros((8400, 85), dtype=np.float32)


def _place(
    out: np.ndarray,
    cell: int,
    *,
    cx: float,
    cy: float,
    w: float,
    h: float,
    obj: float,
    cls_idx: int,
    cls_score: float,
) -> None:
    out[cell, 0:4] = [cx, cy, w, h]
    out[cell, 4] = obj
    out[cell, 5:] = 0.01
    out[cell, 5 + cls_idx] = cls_score


def test_confident_box_lands_in_frame_pixels() -> None:
    out = _blank()
    # Cell (10, 5) of the stride-8 level: grid index 5*80+10 = 410.
    # center = (pred + grid) * stride = (0.5+10, 0.5+5) * 8 = (84, 44);
    # wh = (1, 2) * 8 = (8, 16) -> input box (80, 36)-(88, 52).
    _place(out, 410, cx=0.5, cy=0.5, w=1.0, h=2.0, obj=0.9, cls_idx=0, cls_score=0.8)
    dets = decode(out, META, conf_threshold=0.3)
    assert len(dets) == 1
    det = dets[0]
    assert det.class_name == "person"
    assert det.confidence == pytest.approx(0.72)
    # un-letterbox: x1/y1 floor, x2/y2 ceil of (v - pad) / scale
    x1, y1, x2, y2 = det.bbox
    assert (x1, y1, x2, y2) == (140, 32, 156, 64)


def test_class_names_come_from_coco_order() -> None:
    out = _blank()
    _place(out, 410, cx=0.5, cy=0.5, w=1.0, h=1.0, obj=0.9, cls_idx=16, cls_score=0.9)
    dets = decode(out, META, conf_threshold=0.3)
    assert dets[0].class_name == "dog"
    assert COCO_CLASSES[0] == "person" and len(COCO_CLASSES) == 80


def test_nms_keeps_the_higher_box() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    keep = nms(boxes, scores, iou_threshold=0.5)
    assert keep.tolist() == [0, 2]


def test_low_confidence_is_dropped() -> None:
    out = _blank()
    _place(out, 0, cx=0.0, cy=0.0, w=1.0, h=1.0, obj=0.2, cls_idx=0, cls_score=0.5)
    assert decode(out, META, conf_threshold=0.3) == []


def test_rejects_wrong_shape() -> None:
    with pytest.raises(InferenceError, match="expected model output"):
        decode(np.zeros((7, 7, 3), dtype=np.float32), META)


def test_rejects_batched_shape_other_than_one() -> None:
    with pytest.raises(InferenceError, match="expected model output"):
        decode(np.zeros((2, 8400, 85), dtype=np.float32), META)


def test_rejects_nan_payload() -> None:
    out = _blank()
    out[0, 0] = np.nan
    with pytest.raises(InferenceError, match="NaN or inf"):
        decode(out, META)


def test_boxes_degenerate_after_unletterbox_are_dropped() -> None:
    out = _blank()
    # wh so small it rounds to an empty box after scaling by 0.5.
    _place(out, 0, cx=0.0, cy=0.0, w=0.4, h=0.4, obj=0.99, cls_idx=0, cls_score=0.99)
    assert decode(out, META, conf_threshold=0.3) == []


def test_coco_class_list_matches_the_api_validator() -> None:
    """Two deliberate copies (decode order vs API frozenset) must not drift."""
    from app.api.schemas import COCO_CLASSES as API_CLASSES
    from app.services.inference.types import COCO_CLASSES

    assert len(COCO_CLASSES) == 80
    assert set(COCO_CLASSES) == set(API_CLASSES)
