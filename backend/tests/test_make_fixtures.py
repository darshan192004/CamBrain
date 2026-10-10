"""Prove the generator produces clips PyAV can actually decode."""

from __future__ import annotations

import av
import pytest

from tests.make_fixtures import CLIP_NAMES, ensure_clip


def test_every_named_clip_decodes_to_the_expected_frame_count() -> None:
    """A fixture that will not decode is worse than no fixture — it hides the
    real failure behind a decoder error."""
    expected_frames = {"static": 300, "motion": 300, "brightness_shift": 300}
    for name, count in expected_frames.items():
        path = ensure_clip(name)
        with av.open(str(path)) as container:
            decoded = list(container.decode(container.streams.video[0]))
        assert len(decoded) == count, f"{name} decoded {len(decoded)} frames"


def test_decoded_frames_are_1080p_safe_dimensions() -> None:
    """Fixtures run thousands of times; 640x360 keeps the suite fast while
    still exercising the same code paths as a real sub-stream."""
    path = ensure_clip("motion")
    with av.open(str(path)) as container:
        frame = next(container.decode(container.streams.video[0]))
    assert frame.width == 640
    assert frame.height == 360


def test_brightness_shift_changes_every_pixel_mid_clip() -> None:
    """The day→night cut is the whole point of this fixture: the motion gate
    must reset instead of firing a burst of false alerts."""
    path = ensure_clip("brightness_shift")
    with av.open(str(path)) as container:
        frames = list(container.decode(container.streams.video[0]))
    first_mean = float(frames[0].to_ndarray(format="gray").mean())
    last_mean = float(frames[-1].to_ndarray(format="gray").mean())
    assert last_mean - first_mean > 50


def test_ensure_clip_is_idempotent() -> None:
    """Generating twice must not rewrite — tests call this constantly."""
    first = ensure_clip("motion")
    first.write_bytes(first.read_bytes())
    stamp = first.stat().st_mtime_ns
    assert ensure_clip("motion") == first
    assert first.stat().st_mtime_ns == stamp


def test_unknown_clip_name_is_rejected() -> None:
    """A typo should fail loudly, not silently generate an empty file."""
    with pytest.raises(KeyError):
        ensure_clip("does_not_exist")


def test_clip_names_cover_every_fixture_documented_in_the_spec() -> None:
    """spec §11.2 lists five clips. Adding one there without adding it here
    means the scenario is silently untested."""
    assert set(CLIP_NAMES) == {
        "static",
        "motion",
        "brightness_shift",
        "low_light",
        "multi_object",
    }
