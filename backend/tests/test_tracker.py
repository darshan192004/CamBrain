"""Stable ids across frames; class never switches mid-track (spec A5.4)."""

from __future__ import annotations

from app.services.inference.tracker import Tracker
from app.services.inference.types import Detection


def det(x1: int, y1: int, x2: int, y2: int, cls: str = "person", conf: float = 0.9) -> Detection:
    return Detection(class_name=cls, confidence=conf, bbox=(x1, y1, x2, y2))


def test_first_sighting_gets_id_one() -> None:
    tr = Tracker()
    tracks = tr.update([det(10, 10, 50, 80)], frame_width=100, frame_height=100)
    assert len(tracks) == 1
    assert tracks[0].track_id == 1
    assert tracks[0].centroid == (0.3, 0.45)


def test_same_box_keeps_its_id() -> None:
    tr = Tracker()
    first = tr.update([det(10, 10, 50, 80)], frame_width=100, frame_height=100)
    second = tr.update([det(12, 11, 52, 81)], frame_width=100, frame_height=100)
    assert second[0].track_id == first[0].track_id == 1


def test_two_boxes_get_distinct_ids() -> None:
    tr = Tracker()
    tracks = tr.update([det(0, 0, 20, 20), det(60, 60, 90, 90)], frame_width=100, frame_height=100)
    assert {t.track_id for t in tracks} == {1, 2}


def test_class_mismatch_never_reuses_an_id() -> None:
    tr = Tracker()
    tr.update([det(0, 0, 20, 20, cls="person")], frame_width=100, frame_height=100)
    tracks = tr.update([det(0, 0, 20, 20, cls="car")], frame_width=100, frame_height=100)
    assert tracks[0].class_name == "car"
    assert tracks[0].track_id == 2


def test_track_expires_after_max_misses() -> None:
    tr = Tracker(max_misses=2)
    tr.update([det(0, 0, 20, 20)], frame_width=100, frame_height=100)
    assert tr.update([], frame_width=100, frame_height=100) == []
    assert tr.update([], frame_width=100, frame_height=100) == []
    # Two misses reach max_misses=2 -> track is gone; the sighting gets a NEW id.
    tracks = tr.update([det(0, 0, 20, 20)], frame_width=100, frame_height=100)
    assert tracks[0].track_id == 2


def test_expired_track_is_not_returned_while_missed() -> None:
    tr = Tracker()
    tr.update([det(0, 0, 20, 20)], frame_width=100, frame_height=100)
    assert tr.update([], frame_width=100, frame_height=100) == []
