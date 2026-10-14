"""The alert stage: one FrameSink that turns motion frames into fired alerts.

Detection and alerting stay separate concerns (spec A4.8): this stage never
filters classes before the engine and never persists — Phase 5 owns events,
clips, and notifiers. Cooldown state lives here, keyed (rule, track), because
the engine itself must stay pure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.alerts.rules import RuleConfig, RulesEngine, with_cooldown
from app.services.inference.tracker import Tracker
from app.services.inference.types import Detector
from app.services.stream.source import Frame


@dataclass(frozen=True, slots=True)
class Alert:
    """A fired rule, ready to persist, broadcast, and deliver (spec A5.6)."""

    rule_id: int
    rule_name: str
    severity: str
    track_id: int
    class_name: str
    confidence: float
    zone: str | None
    fired_at: datetime
    summary: str
    camera_id: int
    bbox: tuple[int, int, int, int]
    notify: bool


AlertSink = Callable[[Alert], Awaitable[None] | None]


class AlertStage:
    """Implement the FrameSink seam: detect, track, evaluate, fire."""

    def __init__(
        self,
        *,
        detector: Detector,
        rules: Sequence[RuleConfig],
        camera_id: int,
        on_alert: AlertSink,
        engine: RulesEngine | None = None,
        tracker: Tracker | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._detector = detector
        self._rules = list(rules)
        self._camera_id = camera_id
        self._on_alert = on_alert
        self._engine = engine or RulesEngine()
        self._tracker = tracker or Tracker()
        self._now = now_fn or (lambda: datetime.now(tz=ZoneInfo("UTC")))
        self._last_fired: dict[tuple[int, int], datetime] = {}

    async def __call__(self, frame: Frame) -> None:
        """Run one sampled frame through the whole chain (spec A4.8)."""
        now = self._now()
        detections = await self._detector.infer(frame)
        tracks = self._tracker.update(
            detections, frame_width=frame.width, frame_height=frame.height
        )
        for track in tracks:
            for config in self._rules:
                key = (config.rule_id, track.track_id)
                candidate = with_cooldown(config, self._last_fired.get(key))
                outcome = self._engine.evaluate(track, candidate, now)
                if not outcome.fired:
                    continue
                self._last_fired[key] = now
                zone = config.roi.name if config.roi else None
                where = zone or "frame"
                result = self._on_alert(
                    Alert(
                        rule_id=config.rule_id,
                        rule_name=config.name,
                        severity=config.severity,
                        track_id=track.track_id,
                        class_name=track.class_name,
                        confidence=track.confidence,
                        zone=zone,
                        fired_at=now,
                        summary=f"1 {track.class_name} in {where}",
                        camera_id=self._camera_id,
                        bbox=track.bbox,
                        notify=config.notify,
                    )
                )
                if result is not None:
                    await result
