"""Detector-facing types (spec A5.2).

Classes are names, never indices: YOLOX and RT-DETR do not share output
ordering, so an index stored anywhere would silently repoint every rule when
the model changes (spec A6.4, D17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.stream.source import Frame

COCO_CLASSES: tuple[str, ...] = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
)


@dataclass(frozen=True, slots=True)
class Detection:
    """One model output box, already in frame pixels."""

    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)


@dataclass(frozen=True, slots=True)
class LetterboxMeta:
    """Geometry needed to map network input space back to frame pixels."""

    scale: float
    pad_x: int
    pad_y: int
    input_size: int
    frame_width: int
    frame_height: int


class Detector(Protocol):
    """The licensing boundary (spec A5.2): one swap, no pipeline changes."""

    async def infer(self, frame: Frame) -> list[Detection]:
        """Return every detected object in frame pixels, all 80 COCO classes."""
        ...

    async def close(self) -> None:
        """Release the session; idempotent."""
        ...
