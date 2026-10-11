"""Alert-side logic: ROI geometry, the pure rules engine, the alert stage."""

from __future__ import annotations

from app.services.alerts.roi import normalised_centroid, point_in_polygon

__all__ = [
    "normalised_centroid",
    "point_in_polygon",
]
