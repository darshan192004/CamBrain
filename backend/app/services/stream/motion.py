"""Cheap gate: is this frame worth inference? (spec §5.3)

MOG2 background subtraction on a 640x360 greyscale downscale costs a few
milliseconds against the detector's tens. That ratio is the entire reason
eight cameras fit on a 6-watt N100 (architecture §3).

Also owns the brightness-shift failure. A camera switching to IR at dusk
changes every pixel at once; without an explicit reset the background model
treats the transition as motion and fires a burst of false alerts at exactly
the hour the customer most needs to trust the product.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.stream.source import Frame


class MotionGate:
    """Decide whether a frame warrants running the detector.

    The gate breaks scenes into a cheap per-frame pipeline: downscale to a
    work size, grey, MOG2-diff, count. When the global brightness level
    jumps by ``reset_delta`` or more (an IR cut), the background model is
    reset and stays muted for ``cooldown_frames``: after a cut the model
    reports every pixel as foreground until it re-converges, and that output
    is exactly the false-burst a reset exists to prevent.
    """

    def __init__(
        self,
        *,
        width: int = 640,
        height: int = 360,
        min_area: int = 500,
        reset_delta: float = 40.0,
        cooldown_frames: int = 25,
    ) -> None:
        self._width = width
        self._height = height
        self._min_area = min_area
        self._reset_delta = reset_delta
        self._cooldown_frames = cooldown_frames
        self._cooldown = 0
        self._mog = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=16, detectShadows=False
        )
        self._mean: float = -1.0  # -1 = unprimed.

    def update(self, frame: Frame) -> bool:
        """Return True when the frame warrants inference.

        Args:
            frame: A frame, any resolution. Downscaled internally.

        Returns:
            True when the foreground change exceeds ``min_area`` pixels.
        """
        small = cv2.resize(frame.data, (self._width, self._height), interpolation=cv2.INTER_AREA)
        grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        mean_value = float(grey.mean())
        if self._mean >= 0.0 and abs(mean_value - self._mean) > self._reset_delta:
            self.reset()
            self._mean = mean_value
            return False
        self._mean = mean_value
        foreground = self._mog.apply(grey)  # always learn, even during cooldown
        if self._cooldown > 0:
            self._cooldown -= 1
            return False
        return int(np.count_nonzero(foreground)) >= self._min_area

    def reset(self) -> None:
        """Clear the background model and mute the gate while it re-converges."""
        self._mog.clear()
        self._cooldown = self._cooldown_frames
