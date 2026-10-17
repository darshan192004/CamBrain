"""Startup tier detection (spec A4.7). Never configured by hand.

Spec A4.7's rows overlap on the documented floor (4 cores + AVX2 + no VNNI
matches both the 'medium' and 'low' row); precedence resolves it so an Intel
N100 — the hardware floor itself — lands on `low` and gets YOLOX-nano.
Every probe failure degrades to the floor instead of raising: a box that
cannot identify its CPU must still run detection, slowly.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def models_dir() -> Path:
    """Where the resolved tier's weights live for this launch.

    Dev reads the repo's models tree; the frozen engine (plan T5) points at
    app data (D6-3), which is also where D6-4's bootstrap downloads land.
    """
    if getattr(sys, "frozen", False):  # PyInstaller onedir / onefile
        appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return appdata / "CamBrain" / "models"
    return REPO_ROOT / "models"


# Kept as an import-time alias for tests and callers that anchor the repo
# layout; resolve_tier uses models_dir() so packaging redirects cleanly.
MODELS_DIR = REPO_ROOT / "models"

# winnt.h processor-feature constants. An unknown constant returns 0 (False),
# which can only move a tier DOWN — the safe failure direction.
_PF_AVX = 39
_PF_AVX2 = 40
_PF_AVX512F = 41


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What the box can actually do, whatever the probe managed to read."""

    cores: int
    avx2: bool
    vnni: bool


TIER_SPECS: dict[str, tuple[str, int]] = {
    "high": ("yolox_m.onnx", 640),
    "medium": ("yolox_s.onnx", 640),
    "low": ("yolox_nano.onnx", 416),
}


def _read_feature_bits() -> tuple[bool, bool]:
    """Return (avx2, vnni_proxy) for this CPU; platform-specific."""
    if platform.system() == "Windows":
        # getattr: typeshed only defines ctypes.windll on win32.
        kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009
        avx2 = bool(kernel32.IsProcessorFeaturePresent(_PF_AVX2))
        # VNNI has no stable PF constant on every SDK; AVX512F is a safe
        # proxy that can only UNDER-report (N100 -> False -> low, correct).
        vnni = bool(kernel32.IsProcessorFeaturePresent(_PF_AVX512F))
        return avx2, vnni
    flags: set[str] = set()
    with Path("/proc/cpuinfo").open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("flags"):
                flags = set(line.split(":", 1)[1].split())
                break
    return "avx2" in flags, "avx512f" in flags


def probe_capabilities() -> Capabilities:
    """Read cores + features; any failure returns conservative capabilities."""
    cores = os.cpu_count() or 2
    try:
        avx2, vnni = _read_feature_bits()
    except OSError:
        return Capabilities(cores=cores, avx2=False, vnni=False)
    return Capabilities(cores=cores, avx2=avx2, vnni=vnni)


def tier_for(caps: Capabilities) -> str:
    """Map capabilities to a tier (A4.7), floor-first to resolve the row overlap."""
    if caps.cores >= 8 and caps.avx2 and caps.vnni:
        return "high"
    if caps.cores <= 4 and not caps.vnni:
        return "low"
    if caps.cores >= 4 and caps.avx2:
        return "medium"
    return "low"


def resolve_tier(caps: Capabilities | None = None) -> tuple[str, Path, int]:
    """Return (tier, absolute model path, input size) for this box."""
    resolved = tier_for(caps or probe_capabilities())
    model_file, input_size = TIER_SPECS[resolved]
    return resolved, models_dir() / model_file, input_size
