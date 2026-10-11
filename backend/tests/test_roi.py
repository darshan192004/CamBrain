"""Normalised, edge-inclusive ROI geometry (spec A12: centroid on edge counts)."""

from __future__ import annotations

from app.services.alerts.roi import normalised_centroid, point_in_polygon

SQUARE = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]


def test_centroid_on_edge_counts_inside() -> None:
    """A detection exactly on the boundary must count — edge hysteresis is a
    false-negative factory for a loading-dock rule (A12)."""
    assert point_in_polygon((0.25, 0.5), SQUARE)
    assert point_in_polygon((0.5, 0.25), SQUARE)


def test_inside_and_outside() -> None:
    assert point_in_polygon((0.5, 0.5), SQUARE)
    assert not point_in_polygon((0.1, 0.5), SQUARE)
    assert not point_in_polygon((0.9, 0.9), SQUARE)


def test_convex_and_concave_polygons() -> None:
    # L-shape: (0,0)-(1,0)-(1,0.4)-(0.4,0.4)-(0.4,1)-(0,1)
    l_shape = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.4, 0.4), (0.4, 1.0), (0.0, 1.0)]
    assert point_in_polygon((0.2, 0.2), l_shape)
    assert not point_in_polygon((0.8, 0.8), l_shape)


def test_degenerate_polygon_rejects() -> None:
    assert not point_in_polygon((0.5, 0.5), [(0.5, 0.5), (0.6, 0.6)])


def test_centroid_normalises_against_frame_size() -> None:
    assert normalised_centroid((100, 200, 300, 400), 400, 800) == (0.5, 0.375)
