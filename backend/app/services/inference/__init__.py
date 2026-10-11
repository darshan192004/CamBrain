"""Inference layer: Detector protocol, YOLOX decode, tiers, tracker (spec A5.2, A10.4)."""

from app.services.inference.types import COCO_CLASSES, Detection, Detector, LetterboxMeta

__all__ = [
    "COCO_CLASSES",
    "Detection",
    "Detector",
    "LetterboxMeta",
]
