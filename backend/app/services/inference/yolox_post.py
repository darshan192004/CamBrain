"""Anchor-free YOLOX decode: grid space -> frame pixels, then NMS.

Contract, verified empirically against yolox_s.onnx (release 0.1.1rc0):
input `images` [1,3,640,640] float32 0..255 RGB; output `output` [1,8400,85]
where columns 0..3 are raw grid-space (cx, cy, w, h) with xy as cell offsets
and wh stride-linear (NO exp), column 4 objectness and 5..84 class scores are
already sigmoid'd. Grid: stride 8 -> 80x80, 16 -> 40x40, 32 -> 20x20
(spec A4.7 I/O signature; D17 swap contract keeps this file YOLOX-only).
"""

from __future__ import annotations

import numpy as np

from app.core.errors import InferenceError
from app.services.inference.types import COCO_CLASSES, Detection, LetterboxMeta

OUTPUT_SHAPE = (8400, 85)
_LEVELS: tuple[tuple[int, int], ...] = ((8, 80), (16, 40), (32, 20))


def _build_grid() -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for stride, side in _LEVELS:
        gy, gx = np.meshgrid(np.arange(side), np.arange(side), indexing="ij")
        grids.append(np.stack([gx, gy], -1).reshape(-1, 2))
        strides.append(np.full((side * side, 1), stride, dtype=np.float32))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides)


_GRID, _STRIDE = _build_grid()


def nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    *,
    iou_threshold: float = 0.45,
    max_detections: int = 100,
) -> np.ndarray:
    """Class-agnostic greedy NMS; returns kept indices in score order."""
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size and len(keep) < max_detections:
        best = int(order[0])
        keep.append(best)
        rest = order[1:]
        xx1 = np.maximum(boxes[best, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[best, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[best, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[best, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_a = (boxes[best, 2] - boxes[best, 0]) * (boxes[best, 3] - boxes[best, 1])
        area_b = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        iou = inter / (area_a + area_b - inter + 1e-9)
        order = rest[iou <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def _as_2d(output: np.ndarray) -> np.ndarray:
    """Validate raw model output and drop the batch axis."""
    arr = np.asarray(output, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.shape != OUTPUT_SHAPE:
        raise InferenceError(f"expected model output {OUTPUT_SHAPE}, got {arr.shape}")
    if not np.isfinite(arr).all():
        raise InferenceError("model output contains NaN or inf")
    return arr


def decode(
    output: np.ndarray,
    meta: LetterboxMeta,
    *,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> list[Detection]:
    """Turn one raw YOLOX output tensor into frame-pixel detections."""
    arr = _as_2d(output)
    xy = (arr[:, :2] + _GRID) * _STRIDE
    wh = arr[:, 2:4] * _STRIDE
    class_scores = arr[:, 5:] * arr[:, 4:5]
    class_idx = class_scores.argmax(axis=1)
    confidence = class_scores.max(axis=1)
    mask = confidence >= conf_threshold
    if not mask.any():
        return []
    cx, cy = xy[mask, 0], xy[mask, 1]
    half_w, half_h = wh[mask, 0] / 2.0, wh[mask, 1] / 2.0
    x1 = np.floor((cx - half_w - meta.pad_x) / meta.scale)
    y1 = np.floor((cy - half_h - meta.pad_y) / meta.scale)
    x2 = np.ceil((cx + half_w - meta.pad_x) / meta.scale)
    y2 = np.ceil((cy + half_h - meta.pad_y) / meta.scale)
    x1 = np.clip(x1, 0, meta.frame_width - 1)
    y1 = np.clip(y1, 0, meta.frame_height - 1)
    x2 = np.clip(x2, 0, meta.frame_width)
    y2 = np.clip(y2, 0, meta.frame_height)
    scores = confidence[mask]
    idx = np.nonzero((x2 - x1 >= 1) & (y2 - y1 >= 1))[0]
    if idx.size == 0:
        return []
    boxes = np.stack([x1[idx], y1[idx], x2[idx], y2[idx]], axis=1).astype(np.float32)
    keep = nms(boxes, scores[idx], iou_threshold=iou_threshold)
    kept = idx[keep]
    return [
        Detection(
            class_name=COCO_CLASSES[int(class_idx[mask][i])],
            confidence=float(confidence[mask][i]),
            bbox=(int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])),
        )
        for i in kept
    ]
