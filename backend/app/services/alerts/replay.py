"""Replay recorded detections through the pure rules engine (spec A7.3).

Two callers share this module: the event path replays what the pipeline
already recorded, and the still path (image_b64) evaluates detections from
an injected detector — neither owns inference, so evaluation stays pure,
deterministic, and free of weights in API tests. Pixel bboxes are normalised
against a frame size — the camera's stored dimensions for an event, the
image's own for a still — because without it a normalised ROI cannot be
interpreted, which is a 422, not a silent pass.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.errors import ValidationError
from app.db.models import Camera, Event, EventDetection, Roi, Rule
from app.services.alerts.roi import normalised_centroid
from app.services.alerts.rules import (
    RoiConfig,
    RuleConfig,
    RuleOutcome,
    RulesEngine,
    parse_active_hours,
)
from app.services.inference.tracker import TrackedObject
from app.services.inference.types import Detection


def rule_config(rule: Rule, roi: Roi | None) -> RuleConfig:
    """Project a rules row (+ joined ROI) into the engine's config."""
    return RuleConfig(
        rule_id=rule.id,
        name=rule.name,
        severity=rule.severity,
        classes=tuple(rule.classes),
        confidence_threshold=rule.confidence_threshold,
        cooldown_seconds=rule.cooldown_seconds,
        active_hours=parse_active_hours(rule.active_hours),
        roi=(
            RoiConfig(name=roi.name, points=tuple((p[0], p[1]) for p in roi.points))
            if roi
            else None
        ),
        last_fired_at=None,
        notify=rule.notify,
    )


def detections_to_tracked(
    detections: Sequence[EventDetection | Detection], width: int, height: int
) -> list[TrackedObject]:
    """Project stored rows — or a fresh still's detections — into engine inputs.

    A stored row keeps its recorded track id; a still has no history, so it
    gets a synthetic one (its position in the detection list).
    """
    tracks: list[TrackedObject] = []
    for index, det in enumerate(detections, start=1):
        bbox = (int(det.bbox[0]), int(det.bbox[1]), int(det.bbox[2]), int(det.bbox[3]))
        track_id = det.track_id if isinstance(det, EventDetection) else index
        tracks.append(
            TrackedObject(
                track_id=track_id or index,
                class_name=det.class_name,
                confidence=det.confidence,
                bbox=bbox,
                centroid=normalised_centroid(bbox, width, height),
            )
        )
    return tracks


def evaluate_detections(
    engine: RulesEngine,
    config: RuleConfig,
    tracked: Sequence[TrackedObject],
    when: datetime,
) -> RuleOutcome:
    """Evaluate tracked objects; the strongest candidate's checks win.

    Most conditions passed wins; confidence breaks ties; fired (all five)
    is always the maximum, so `fired` and the returned checks agree.
    """
    if not tracked:
        raise ValidationError("no detections to replay")
    outcomes = [(track.confidence, engine.evaluate(track, config, when)) for track in tracked]
    _, best = max(outcomes, key=lambda pair: (sum(c.passed for c in pair[1].checks), pair[0]))
    return best


def replay(
    engine: RulesEngine,
    config: RuleConfig,
    camera: Camera,
    detections: list[EventDetection],
    event: Event,
) -> RuleOutcome:
    """Evaluate every stored detection; return the strongest candidate's checks.

    Raises:
        ValidationError: When the camera has no frame size (422) or the event
            carries no detections. Phase 2's envelope keeps `field` null, so
            the condition is named in the message instead.
    """
    width, height = camera.frame_width, camera.frame_height
    if width is None or height is None:
        raise ValidationError(
            "camera has no known frame size; run the camera once before testing rules"
        )
    if not detections:
        raise ValidationError("event has no detections to replay")
    when = event.started_at if event.started_at.tzinfo else event.started_at.replace(tzinfo=UTC)
    return evaluate_detections(
        engine, config, detections_to_tracked(detections, width, height), when
    )
