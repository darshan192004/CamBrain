"""A normalised ROI survives a resolution change (plan 4.5, DATABASE §4.5).

A sub-stream switch rewrites `frame_width`/`frame_height`; the stored polygon
must not move. The same physical spot (centroid derived from each size's
pixels) therefore still evaluates `in_roi` the same through the rules engine
at both frame sizes, and coverage derives from the polygon alone.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.api.routers.rois import _coverage_pct
from app.db.models import Roi
from app.db.repositories.cameras import CameraRepository
from app.db.repositories.rois import RoiRepository
from app.services.alerts.rules import RoiConfig, RuleConfig, RulesEngine
from app.services.inference.tracker import Tracker
from app.services.inference.types import Detection

ENGINE = RulesEngine()
NOW = datetime(2026, 10, 6, 14, 32, tzinfo=ZoneInfo("Asia/Kolkata"))
SQUARE = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]


def _in_roi(
    roi: Roi,
    bbox: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
) -> bool:
    """Normalise a pixel bbox at this frame size, then ask the engine (A5.5)."""
    tracks = Tracker().update(
        [Detection(class_name="person", confidence=0.9, bbox=bbox)],
        frame_width=frame_width,
        frame_height=frame_height,
    )
    config = RuleConfig(
        rule_id=1,
        name="Dock rule",
        severity="warning",
        classes=("person",),
        confidence_threshold=0.55,
        cooldown_seconds=60,
        active_hours=None,
        roi=RoiConfig(name=roi.name, points=tuple(tuple(p) for p in roi.points)),
        last_fired_at=None,
    )
    outcome = ENGINE.evaluate(tracks[0], config, NOW)
    return next(c.passed for c in outcome.checks if c.condition == "in_roi")


def test_roi_survives_resolution_change(db_session: Session, seeded) -> None:
    site, _admin, _viewer = seeded
    cameras = CameraRepository(db_session, site_id=site.id)
    camera = cameras.create(
        name="dock",
        rtsp_url="rtsp://10.0.0.5:554/stream1",
        frame_width=640,
        frame_height=360,
    )
    roi = RoiRepository(db_session, site_id=site.id).create(
        camera_id=camera.id,
        name="Loading dock",
        points=SQUARE,
    )

    points_before = json.dumps(roi.points).encode()
    coverage_before = _coverage_pct(roi.points)

    # Sub-stream switch: dimensions change through the repository — the API's
    # CameraPatch deliberately excludes them, so nothing else may rewrite points.
    updated = cameras.update(camera.id, frame_width=320, frame_height=240)
    assert updated is not None and updated.frame_width == 320

    stored = db_session.get(Roi, roi.id)
    assert stored is not None
    assert json.dumps(stored.points).encode() == points_before
    assert _coverage_pct(stored.points) == coverage_before

    # Centre of the dock, as a pixel box at each size: still inside.
    assert _in_roi(stored, (260, 140, 380, 220), 640, 360) is True
    assert _in_roi(stored, (120, 80, 200, 160), 320, 240) is True
    # Far corner, as a pixel box at each size: still outside.
    assert _in_roi(stored, (0, 0, 80, 80), 640, 360) is False
    assert _in_roi(stored, (0, 0, 40, 40), 320, 240) is False
