"""ROI tests on normalised coordinates (DATABASE A4.5, spec A12).

Absolute pixels fail quietly on a resolution change; everything here works in
0..1 space so an ROI drawn at 1080p still means the same wall at 720p.
Containment is edge-inclusive: a centroid exactly on the boundary counts.
"""

from __future__ import annotations

from collections.abc import Sequence

_EPS = 1e-9


def _on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
    """True when (px, py) lies on segment a-b within EPS."""
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > _EPS:
        return False
    return (
        min(ax, bx) - _EPS <= px <= max(ax, bx) + _EPS
        and min(ay, by) - _EPS <= py <= max(ay, by) + _EPS
    )


def point_in_polygon(point: tuple[float, float], points: Sequence[tuple[float, float]]) -> bool:
    """Edge-inclusive containment by ray casting (spec A12)."""
    if len(points) < 3:
        return False
    px, py = point
    inside = False
    for i, (ax, ay) in enumerate(points):
        bx, by = points[(i + 1) % len(points)]
        if _on_segment(px, py, ax, ay, bx, by):
            return True
        if (ay > py) != (by > py):
            x_intersect = (bx - ax) * (py - ay) / (by - ay) + ax
            if px < x_intersect:
                inside = not inside
    return inside


def normalised_centroid(
    bbox: tuple[int, int, int, int], frame_width: int, frame_height: int
) -> tuple[float, float]:
    """Bbox midpoint in 0..1 frame coordinates."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2 / frame_width, (y1 + y2) / 2 / frame_height)
