"""Clip -> detect -> track -> rules -> one alert, through the sink seam."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np

from app.services.alerts.rules import ActiveHours, RuleConfig, Window
from app.services.alerts.stage import Alert, AlertStage
from app.services.inference.types import Detection
from app.services.stream.source import Frame


class FakeDetector:
    """Scripted detections: person visible from call `visible_from` onward."""

    def __init__(self, visible_from: int = 0) -> None:
        self.calls = 0
        self.visible_from = visible_from

    async def infer(self, _frame: Frame) -> list[Detection]:
        index = self.calls
        self.calls += 1
        if index < self.visible_from:
            return []
        return [Detection(class_name="person", confidence=0.8, bbox=(10, 10, 50, 120))]

    async def close(self) -> None:
        return None


def rule(**overrides: object) -> RuleConfig:
    defaults: dict[str, object] = {
        "rule_id": 7,
        "name": "Back door",
        "severity": "critical",
        "classes": ("person",),
        "confidence_threshold": 0.55,
        "cooldown_seconds": 60,
        "active_hours": None,
        "roi": None,
        "last_fired_at": None,
    }
    defaults.update(overrides)
    return RuleConfig(**defaults)  # type: ignore[arg-type]


def frame(index: int = 0) -> Frame:
    return Frame(
        data=np.zeros((432, 768, 3), dtype=np.uint8),
        timestamp=float(index) / 2.0,
        width=768,
        height=432,
    )


async def test_alert_fires_once_then_cooldown_silences() -> None:
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule()],
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    for _ in range(5):
        await stage(frame())
    assert len(alerts) == 1
    assert alerts[0].rule_id == 7
    assert alerts[0].class_name == "person"
    assert alerts[0].summary == "1 person in frame"


async def test_cooldown_rearms_on_a_later_pass() -> None:
    ticks = [
        datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 6, 12, 1, tzinfo=ZoneInfo("UTC")),
    ]
    it = iter(ticks)
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule()],
        on_alert=alerts.append,
        now_fn=lambda: next(it),
    )
    await stage(frame(0))
    await stage(frame(1))
    await stage(frame(2))
    assert len(alerts) == 2


async def test_non_matching_class_never_alerts() -> None:
    class CarDetector(FakeDetector):
        async def infer(self, _frame: Frame) -> list[Detection]:
            self.calls += 1
            return [Detection(class_name="car", confidence=0.9, bbox=(1, 1, 9, 9))]

    alerts: list[Alert] = []
    stage = AlertStage(detector=CarDetector(), rules=[rule()], on_alert=alerts.append)
    await stage(frame())
    assert alerts == []


async def test_disabled_hours_suppress() -> None:
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[
            rule(
                active_hours=ActiveHours(timezone="UTC", windows=(Window(time(22, 0), time(6, 0)),))
            )
        ],
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    await stage(frame())
    assert alerts == []


async def test_multiple_rules_each_get_their_own_cooldown() -> None:
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule(rule_id=1, severity="info"), rule(rule_id=2, severity="critical")],
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    await stage(frame())
    assert sorted(a.rule_id for a in alerts) == [1, 2]
    await stage(frame(1))
    assert len(alerts) == 2, "per-rule cooldowns are independent"
