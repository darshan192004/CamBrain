"""Table-driven rules: every branch, timezone edges, midnight wrap (spec A5.5).

Purity is the test surface: `now` is always injected, so 02:30 is a row in a
table instead of a flaky clock. This file is the false-positive battleground.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.services.alerts.rules import (
    ActiveHours,
    RoiConfig,
    RuleConfig,
    RuleOutcome,
    RulesEngine,
    Window,
    parse_active_hours,
)
from app.services.inference.tracker import TrackedObject

ENGINE = RulesEngine()
SQUARE_ROI = RoiConfig(
    name="Loading dock",
    points=((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)),
)


def track(
    cls: str = "person", conf: float = 0.7, centroid: tuple[float, float] = (0.5, 0.5)
) -> TrackedObject:
    return TrackedObject(
        track_id=1,
        class_name=cls,
        confidence=conf,
        bbox=(0, 0, 10, 10),
        centroid=centroid,
    )


def base_config(**overrides: object) -> RuleConfig:
    defaults: dict[str, object] = {
        "rule_id": 1,
        "name": "Back door",
        "severity": "warning",
        "classes": ("person",),
        "confidence_threshold": 0.55,
        "cooldown_seconds": 60,
        "active_hours": None,
        "roi": None,
        "last_fired_at": None,
    }
    defaults.update(overrides)
    return RuleConfig(**defaults)  # type: ignore[arg-type]


NOW = datetime(2026, 10, 6, 14, 32, tzinfo=ZoneInfo("Asia/Kolkata"))


def conditions(outcome: RuleOutcome) -> dict[str, bool]:
    return {c.condition: c.passed for c in outcome.checks}


def test_fires_when_everything_passes() -> None:
    outcome = ENGINE.evaluate(track(), base_config(), NOW)
    assert outcome.fired
    assert conditions(outcome) == {
        "class_in_allowlist": True,
        "confidence": True,
        "in_roi": True,
        "active_hours": True,
        "cooldown": True,
    }


def test_class_not_in_allowlist() -> None:
    outcome = ENGINE.evaluate(track(cls="car"), base_config(), NOW)
    assert not outcome.fired
    check = next(c for c in outcome.checks if c.condition == "class_in_allowlist")
    assert not check.passed
    assert check.detail == "'car' not in ['person']"


def test_confidence_detail_reads_like_the_api_example() -> None:
    outcome = ENGINE.evaluate(track(conf=0.71), base_config(confidence_threshold=0.55), NOW)
    check = next(c for c in outcome.checks if c.condition == "confidence")
    assert check.detail == "0.71 >= 0.55"
    failing = ENGINE.evaluate(track(conf=0.4), base_config(confidence_threshold=0.55), NOW)
    assert next(c for c in failing.checks if c.condition == "confidence").detail == "0.40 < 0.55"


def test_every_check_is_reported_even_when_one_fails() -> None:
    """API.md shows all five checks with mixed results — no short-circuit."""
    outcome = ENGINE.evaluate(track(centroid=(0.1, 0.1)), base_config(roi=SQUARE_ROI), NOW)
    assert not outcome.fired
    assert len(outcome.checks) == 5
    assert conditions(outcome)["in_roi"] is False
    assert conditions(outcome)["class_in_allowlist"] is True


def test_roi_detail_names_the_zone() -> None:
    inside = ENGINE.evaluate(track(), base_config(roi=SQUARE_ROI), NOW)
    assert "inside Loading dock" in next(c.detail for c in inside.checks if c.condition == "in_roi")
    outside = ENGINE.evaluate(track(centroid=(0.1, 0.62)), base_config(roi=SQUARE_ROI), NOW)
    assert "outside Loading dock" in next(
        c.detail for c in outside.checks if c.condition == "in_roi"
    )


def test_no_roi_means_whole_frame() -> None:
    check = next(
        c
        for c in ENGINE.evaluate(track(centroid=(0.01, 0.01)), base_config(), NOW).checks
        if c.condition == "in_roi"
    )
    assert check.passed and "whole frame" in check.detail


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 6, 23, 0, tzinfo=ZoneInfo("Asia/Kolkata")), True),
        (datetime(2026, 10, 6, 3, 0, tzinfo=ZoneInfo("Asia/Kolkata")), True),
        (datetime(2026, 10, 6, 14, 32, tzinfo=ZoneInfo("Asia/Kolkata")), False),
        # 18:00 UTC is 23:30 IST -> within; a UTC-naive engine would say False.
        (datetime(2026, 10, 6, 18, 0, tzinfo=ZoneInfo("UTC")), True),
    ],
)
def test_active_hours_wrap_and_timezones(now: datetime, expected: bool) -> None:
    hours = ActiveHours(timezone="Asia/Kolkata", windows=(Window(time(22, 0), time(6, 0)),))
    outcome = ENGINE.evaluate(track(), base_config(active_hours=hours), now)
    assert conditions(outcome)["active_hours"] is expected


def test_detail_reads_within_or_outside() -> None:
    hours = ActiveHours(timezone="UTC", windows=(Window(time(22, 0), time(6, 0)),))
    inside = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 10, 6, 23, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert "within" in next(c.detail for c in inside.checks if c.condition == "active_hours")
    outside = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert "outside" in next(c.detail for c in outside.checks if c.condition == "active_hours")


def test_utc_1630_is_2200_next_day_in_kolkata() -> None:
    """The shop closes at 22:00 IST, not 22:00 UTC (spec A12 timezone row)."""
    hours = ActiveHours(timezone="Asia/Kolkata", windows=(Window(time(22, 0), time(6, 0)),))
    now = datetime(2026, 10, 6, 16, 30, tzinfo=ZoneInfo("UTC"))
    outcome = ENGINE.evaluate(track(), base_config(active_hours=hours), now)
    assert conditions(outcome)["active_hours"] is True


def test_multiple_windows_any_one_counts() -> None:
    hours = ActiveHours(
        timezone="UTC",
        windows=(Window(time(6, 0), time(9, 0)), Window(time(17, 0), time(19, 0))),
    )
    morning = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC")),
    )
    midday = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert conditions(morning)["active_hours"]
    assert not conditions(midday)["active_hours"]


def test_cooldown_suppresses_a_recent_firing() -> None:
    config = base_config(last_fired_at=NOW.replace(minute=31, second=30))
    outcome = ENGINE.evaluate(track(), config, NOW)
    assert not outcome.fired
    check = next(c for c in outcome.checks if c.condition == "cooldown")
    assert not check.passed
    assert "cooldown 60s" in check.detail


def test_cooldown_rearms_after_the_window() -> None:
    config = base_config(last_fired_at=NOW.replace(minute=30))
    assert ENGINE.evaluate(track(), config, NOW).fired


def test_no_previous_firing_passes_cooldown() -> None:
    check = next(
        c for c in ENGINE.evaluate(track(), base_config(), NOW).checks if c.condition == "cooldown"
    )
    assert check.passed and "no recent trigger" in check.detail


def test_engine_never_reads_the_clock() -> None:
    """Purity guard: a naive (tz-less) datetime must not crash the engine."""
    outcome = ENGINE.evaluate(track(), base_config(), datetime(2026, 10, 6, 14, 32))
    assert isinstance(outcome.fired, bool)


def test_parse_active_hours_reads_db_json() -> None:
    raw = {"timezone": "Asia/Kolkata", "windows": [{"start": "22:00", "end": "06:00"}]}
    hours = parse_active_hours(raw)
    assert hours is not None
    assert hours.windows[0].start == time(22, 0)
    assert parse_active_hours(None) is None
    assert parse_active_hours({"timezone": "UTC", "windows": []}) is None
