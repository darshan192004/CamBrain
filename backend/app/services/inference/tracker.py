"""Greedy IoU tracker, written for this project (spec A5.4).

No BYTETracker copy — the licensing chain stays clean and the dependency
count stays zero. Identity exists to suppress duplicate alerts: the cooldown
key is (rule, track), so ids must be stable but do not need to survive a
process restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.inference.types import Detection


@dataclass(frozen=True, slots=True)
class TrackedObject:
    """One live track handed to the rules engine."""

    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]  # normalised 0..1 against the frame


@dataclass(slots=True)
class _Track:
    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]
    misses: int = 0


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter) if inter else 0.0


class Tracker:
    """Assign stable track ids by greedy same-class IoU matching."""

    def __init__(self, *, iou_threshold: float = 0.3, max_misses: int = 5) -> None:
        self._iou_threshold = iou_threshold
        self._max_misses = max_misses
        self._tracks: list[_Track] = []
        self._next_id = 1

    def update(
        self, detections: list[Detection], *, frame_width: int, frame_height: int
    ) -> list[TrackedObject]:
        """Match detections to live tracks; return tracks seen this frame."""
        unmatched = list(detections)
        matched_tracks: list[_Track] = []
        for track in list(self._tracks):
            best: Detection | None = None
            best_iou = self._iou_threshold
            for candidate in unmatched:
                if candidate.class_name != track.class_name:
                    continue
                score = _iou(track.bbox, candidate.bbox)
                if score >= best_iou:
                    best, best_iou = candidate, score
            if best is not None:
                unmatched.remove(best)
                track.bbox = best.bbox
                track.confidence = best.confidence
                track.misses = 0
                matched_tracks.append(track)
            else:
                track.misses += 1
        self._tracks = [t for t in self._tracks if t.misses < self._max_misses]
        for candidate in unmatched:
            track = _Track(
                track_id=self._next_id,
                class_name=candidate.class_name,
                confidence=candidate.confidence,
                bbox=candidate.bbox,
            )
            self._next_id += 1
            self._tracks.append(track)
            matched_tracks.append(track)
        live = {id(t) for t in matched_tracks}
        return [
            TrackedObject(
                track_id=t.track_id,
                class_name=t.class_name,
                confidence=t.confidence,
                bbox=t.bbox,
                centroid=_centroid(t.bbox, frame_width, frame_height),
            )
            for t in self._tracks
            if id(t) in live
        ]


def _centroid(
    bbox: tuple[int, int, int, int], frame_width: int, frame_height: int
) -> tuple[float, float]:
    """Normalised bbox midpoint — resolution-independent for ROI checks."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2 / frame_width, (y1 + y2) / 2 / frame_height)
