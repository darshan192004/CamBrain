"""Matrix row 3: a real alert fires from a real clip, under 2s (spec 11).

Marked slow: it runs YOLOX-nano over every frame. The latency asserted is
per frame (feed -> alert), because the budget that can blow past 2s on an
N100 is one inference pass; the motion->alert plumbing budget without
inference is test_pipeline.py::test_motion_to_alert_under_2s.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.services.alerts.rules import RuleConfig
from app.services.alerts.stage import Alert, AlertStage
from app.services.inference.detector import open_detector
from app.services.stream.file_source import FileSource

pytestmark = pytest.mark.slow

MODEL = Path(__file__).resolve().parents[2] / "models" / "yolox_nano.onnx"


@pytest.mark.skipif(not MODEL.exists(), reason="yolox_nano.onnx missing - run fetch_models.py")
async def test_real_alert_from_real_clip_under_2s(gate_clip_path: Path) -> None:
    alerts: list[Alert] = []

    async def record(alert: Alert) -> None:
        alerts.append(alert)

    detector = open_detector(MODEL, input_size=416)
    stage = AlertStage(
        detector=detector,
        rules=[
            RuleConfig(
                rule_id=1,
                name="gate",
                severity="warning",
                classes=("person",),
                confidence_threshold=0.55,
                cooldown_seconds=0,
                active_hours=None,
                roi=None,
                last_fired_at=None,
            )
        ],
        camera_id=1,
        on_alert=record,
    )
    source = FileSource(gate_clip_path, loop=False)
    worst = 0.0
    try:
        async for frame in source.frames():
            started = time.monotonic()
            await stage(frame)
            worst = max(worst, time.monotonic() - started)
            if alerts:
                break
    finally:
        await source.close()
        await detector.close()

    assert alerts, "no person alert from the gate clip (person is visible frames 15-75)"
    assert alerts[0].class_name == "person"
    assert alerts[0].summary.startswith("1 person")
    assert worst < 2.0, f"slowest detect+rules pass took {worst:.2f}s (budget 2s)"
