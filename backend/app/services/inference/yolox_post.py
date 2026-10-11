"""Anchor-free YOLOX decode: grid space -> frame pixels, then NMS.

Contract, verified empirically against yolox_s.onnx and yolox_nano.onnx
(release 0.1.1rc0): input `images` [1,3,S,S] float32 0..255 RGB where S is
the letterboxed input size (640 -> 8400 rows, 416 -> 3549); output `output`
[1,N,85] where columns 0..3 are raw grid-space (cx, cy, w, h) with xy as
cell offsets and wh stride-linear (NO exp), column 4 objectness and
5..84 class scores are already sigmoid'd. Grid: stride 8 -> (S/8)^2 rows,
16 -> (S/16)^2, 32 -> (S/32)^2 (spec A4.7 I/O signature; D17 swap contract
keeps this file YOLOX-only).
"""

from __future__ import annotations

import numpy as np

from app.core.errors import InferenceError
from app.services.inference.types import COCO_CLASSES, Detection, LetterboxMeta

_OUTPUT_COLS = 85
_STRIDES: tuple[int, ...] = (8, 16, 32)


def _build_grid(sides: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for stride, side in zip(_STRIDES, sides, strict=True):
        gy, gx = np.meshgrid(np.arange(side), np.arange(side), indexing="ij")
        grids.append(np.stack([gx, gy], -1).reshape(-1, 2))
        strides.append(np.full((side * side, 1), stride, dtype=np.float32))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides)


_GRID_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _grid_tables(input_size: int) -> tuple[np.ndarray, np.ndarray]:
    """Grid/stride tables for one input size; cached per size."""
    cached = _GRID_CACHE.get(input_size)
    if cached is not None:
        return cached
    if input_size % 32:
        raise InferenceError(f"input_size {input_size} is not a multiple of 32")
    tables = _build_grid(tuple(input_size // s for s in _STRIDES))
    _GRID_CACHE[input_size] = tables
    return tables


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


def _as_2d(output: np.ndarray, input_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate raw model output; return rows with grid/stride for its size."""
    arr = np.asarray(output, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2 or arr.shape[1] != _OUTPUT_COLS:
        raise InferenceError(f"expected model output (N, {_OUTPUT_COLS}), got {arr.shape}")
    if not np.isfinite(arr).all():
        raise InferenceError("model output contains NaN or inf")
    grid, stride = _grid_tables(input_size)
    if arr.shape[0] != grid.shape[0]:
        raise InferenceError(
            f"expected model output with {grid.shape[0]} rows for input_size "
            f"{input_size}, got {arr.shape[0]}"
        )
    return arr, grid, stride


def decode(
    output: np.ndarray,
    meta: LetterboxMeta,
    *,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> list[Detection]:
    """Turn one raw YOLOX output tensor into frame-pixel detections."""
    arr, grid, stride = _as_2d(output, meta.input_size)
    xy = (arr[:, :2] + grid) * stride
    wh = arr[:, 2:4] * stride
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
