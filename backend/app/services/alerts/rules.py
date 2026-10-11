"""Pure rules engine (spec A5.5) — the highest-value test surface.

No IO, no clock reads, no side effects: `now` is injected so every false
positive class (hours boundaries, timezones, cooldown, ROI edges) is a table
row. `checks` exists because "rule did not fire" is unactionable —
POST /api/v1/rules/{id}/test returns them verbatim (API.md).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import cast
from zoneinfo import ZoneInfo

from app.services.alerts.roi import point_in_polygon
from app.services.inference.tracker import TrackedObject


@dataclass(frozen=True, slots=True)
class Window:
    """One active-hours window; end < start wraps past midnight."""

    start: time
    end: time


@dataclass(frozen=True, slots=True)
class ActiveHours:
    """When a rule is allowed to fire, in the camera's own timezone."""

    timezone: str
    windows: tuple[Window, ...]


@dataclass(frozen=True, slots=True)
class RoiConfig:
    """A named normalised polygon; None ROI means the whole frame."""

    name: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Everything evaluate() needs, projected from the rules row."""

    rule_id: int
    name: str
    severity: str
    classes: tuple[str, ...]
    confidence_threshold: float
    cooldown_seconds: int
    active_hours: ActiveHours | None
    roi: RoiConfig | None
    last_fired_at: datetime | None


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """One condition's verdict, ready for the debug endpoint."""

    condition: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """The verdict plus every per-condition reason (API.md A7.3)."""

    fired: bool
    checks: tuple[RuleCheck, ...]


def _parse_hhmm(raw: str) -> time:
    """Parse an HH:MM window edge; raises on malformed input at the edge."""
    hour_s, _, minute_s = raw.partition(":")
    return time(int(hour_s), int(minute_s))


def parse_active_hours(raw: dict[str, object] | None) -> ActiveHours | None:
    """Build ActiveHours from the rules.active_hours JSON column."""
    if not raw:
        return None
    timezone = str(raw.get("timezone") or "UTC")
    ZoneInfo(timezone)  # raises on a bad zone — validate at the edge
    entries = cast("list[dict[str, str]]", raw.get("windows") or [])
    windows = tuple(
        Window(start=_parse_hhmm(w["start"]), end=_parse_hhmm(w["end"])) for w in entries
    )
    if not windows:
        return None
    return ActiveHours(timezone=timezone, windows=windows)


def _in_window(now_local: time, window: Window) -> bool:
    if window.start <= window.end:
        return window.start <= now_local < window.end
    return now_local >= window.start or now_local < window.end


def _check_class(track: TrackedObject, config: RuleConfig) -> RuleCheck:
    passed = track.class_name in config.classes
    listing = list(config.classes)
    detail = (
        f"{track.class_name!r} in {listing!r}"
        if passed
        else f"{track.class_name!r} not in {listing!r}"
    )
    return RuleCheck("class_in_allowlist", passed, detail)


def _check_confidence(track: TrackedObject, config: RuleConfig) -> RuleCheck:
    passed = track.confidence >= config.confidence_threshold
    op = ">=" if passed else "<"
    detail = f"{track.confidence:.2f} {op} {config.confidence_threshold:.2f}"
    return RuleCheck("confidence", passed, detail)


def _check_roi(track: TrackedObject, config: RuleConfig) -> RuleCheck:
    if config.roi is None:
        return RuleCheck("in_roi", True, "no ROI configured - whole frame")
    cx, cy = track.centroid
    passed = point_in_polygon((cx, cy), config.roi.points)
    where = "inside" if passed else "outside"
    detail = f"centroid ({cx:.2f},{cy:.2f}) {where} {config.roi.name}"
    return RuleCheck("in_roi", passed, detail)


def _check_active_hours(now: datetime, config: RuleConfig) -> RuleCheck:
    if config.active_hours is None:
        return RuleCheck("active_hours", True, "no active hours configured")
    local = now.astimezone(ZoneInfo(config.active_hours.timezone))
    now_local = local.time()
    for window in config.active_hours.windows:
        if _in_window(now_local, window):
            detail = f"{now_local:%H:%M} within {window.start:%H:%M}-{window.end:%H:%M}"
            return RuleCheck("active_hours", True, detail)
    listed = ", ".join(f"{w.start:%H:%M}-{w.end:%H:%M}" for w in config.active_hours.windows)
    return RuleCheck("active_hours", False, f"{now_local:%H:%M} is outside {listed}")


def _check_cooldown(now: datetime, config: RuleConfig) -> RuleCheck:
    if config.last_fired_at is None:
        return RuleCheck("cooldown", True, "no recent trigger on this track")
    elapsed = (now - config.last_fired_at).total_seconds()
    if elapsed > config.cooldown_seconds:
        return RuleCheck("cooldown", True, "cooldown expired")
    return RuleCheck(
        "cooldown",
        False,
        f"last trigger {int(elapsed)}s ago, cooldown {config.cooldown_seconds}s",
    )


class RulesEngine:
    """Evaluate one track against one rule. Pure (spec A5.5)."""

    def evaluate(self, track: TrackedObject, config: RuleConfig, now: datetime) -> RuleOutcome:
        """Return every condition's verdict; fired iff all pass.

        Args:
            track: The tracked object under test.
            config: Projected rule, including caller-held cooldown state.
            now: Injected awareness — the engine never reads the clock.

        Returns:
            RuleOutcome with five checks in API.md's documented order.
        """
        checks = (
            _check_class(track, config),
            _check_confidence(track, config),
            _check_roi(track, config),
            _check_active_hours(now, config),
            _check_cooldown(now, config),
        )
        return RuleOutcome(fired=all(c.passed for c in checks), checks=checks)


def with_cooldown(config: RuleConfig, last_fired_at: datetime | None) -> RuleConfig:
    """Copy config with fresh cooldown state (callers hold the map)."""
    return replace(config, last_fired_at=last_fired_at)
