"""Motion gate behaviour against the synthetic fixtures (spec §5.3).

The brightness-shift test is the one that matters: a camera switching to IR
at dusk changes every pixel at once. Without an explicit reset the
background model fires a burst of false alerts at the wrong hour.
"""

from __future__ import annotations

from pathlib import Path

import av

from app.services.stream.motion import MotionGate
from app.services.stream.source import Frame

# MOG2 needs ~30 samples to build a background model; the gate samples every
# 4th frame, so 30 samples span 120 input frames.
WARMUP = 120


def _to_frame(raw) -> Frame:  # type: ignore[no-untyped-def]
    return Frame(
        data=raw.to_ndarray(format="rgb24").copy(),
        timestamp=0.0,
        width=raw.width,
        height=raw.height,
    )


def _gate_on_clip(clip: Path) -> list[bool]:
    gate = MotionGate()
    decisions: list[bool] = []

    with av.open(str(clip)) as container:
        stream = container.streams.video[0]
        for raw in container.decode(stream):
            frame = Frame(
                data=raw.to_ndarray(format="rgb24").copy(),
                timestamp=0.0,
                width=raw.width,
                height=raw.height,
            )
            decisions.append(gate.update(frame))
    return decisions


def test_static_stays_closed(clips: dict[str, Path]) -> None:
    """A still scene must never open the gate — that would be a false alarm."""
    decisions = _gate_on_clip(clips["static"])
    assert not any(decisions[WARMUP:])


def test_motion_opens(clips: dict[str, Path]) -> None:
    """A translating object must open the gate on (nearly) every frame."""
    decisions = _gate_on_clip(clips["motion"])
    assert sum(decisions[WARMUP:]) / len(decisions[WARMUP:]) > 0.9


def test_brightness_shift_resets_instead_of_bursting(
    clips: dict[str, Path],
) -> None:
    """A day/night cut must reset the model, not fire a burst."""
    decisions = _gate_on_clip(clips["brightness_shift"])
    # A burst would be ~150 consecutive opens at the cut. A reset is < 5.
    assert sum(decisions) < 5
    assert not any(decisions[-50:])  # steady-state after the shift stays closed


def test_reset_clears_the_model(clips: dict[str, Path]) -> None:
    """reset() must make the very next frame *not* count as motion."""
    gate = MotionGate()
    with av.open(str(clips["static"])) as container:
        stream = container.streams.video[0]
        frames = [f for _, f in zip(range(60), container.decode(stream), strict=False)]
        for raw in frames[:30]:
            gate.update(_to_frame(raw))
        gate.reset()
        next_decision = gate.update(_to_frame(frames[30]))
        assert next_decision is False


def test_low_light_gate_runs(clips: dict[str, Path]) -> None:
    """The night path must produce decisions without raising (Phase 3 uses it)."""
    decisions = _gate_on_clip(clips["low_light"])
    assert all(isinstance(d, bool) for d in decisions)
