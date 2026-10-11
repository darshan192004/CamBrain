"""Replay stored detections through the pure rules engine (spec A7.3).

The endpoint must never run a detector: a diagnostic uses what was already
recorded, so it stays fast, deterministic, and free of weights in API tests.
Pixel bboxes are normalised with the camera's stored frame size — without it
a normalised ROI cannot be interpreted, which is a 422, not a silent pass.
"""

from __future__ import annotations

from datetime import UTC

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
    )


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
    outcomes: list[tuple[float, RuleOutcome]] = []
    for index, det in enumerate(detections, start=1):
        bbox = (int(det.bbox[0]), int(det.bbox[1]), int(det.bbox[2]), int(det.bbox[3]))
        track = TrackedObject(
            track_id=det.track_id or index,
            class_name=det.class_name,
            confidence=det.confidence,
            bbox=bbox,
            centroid=normalised_centroid(bbox, width, height),
        )
        outcomes.append((det.confidence, engine.evaluate(track, config, when)))
    # Most conditions passed wins; confidence breaks ties; fired (all five)
    # is always the maximum, so `fired` and the returned checks agree.
    _, best = max(outcomes, key=lambda pair: (sum(c.passed for c in pair[1].checks), pair[0]))
    return best
