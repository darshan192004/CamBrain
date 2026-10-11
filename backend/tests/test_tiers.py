"""Tier table per spec A4.7, with the probe failing toward the floor."""

from __future__ import annotations

import os

import pytest

from app.services.inference import tiers


def test_high_tier_needs_cores_avx2_and_vnni() -> None:
    assert tiers.tier_for(tiers.Capabilities(cores=8, avx2=True, vnni=True)) == "high"


def test_eight_cores_without_vnni_is_medium() -> None:
    assert tiers.tier_for(tiers.Capabilities(cores=8, avx2=True, vnni=False)) == "medium"


def test_n100_shape_is_low() -> None:
    """4 cores, AVX2, no VNNI is the documented hardware floor -> nano (A4.7)."""
    assert tiers.tier_for(tiers.Capabilities(cores=4, avx2=True, vnni=False)) == "low"


def test_two_cores_is_low() -> None:
    assert tiers.tier_for(tiers.Capabilities(cores=2, avx2=True, vnni=True)) == "low"


def test_no_avx2_is_low() -> None:
    assert tiers.tier_for(tiers.Capabilities(cores=16, avx2=False, vnni=False)) == "low"


def test_tier_falls_back_on_low_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe failure must degrade to the floor, never crash startup (A12)."""

    def explode() -> bool:
        raise OSError("cpuinfo unavailable")

    monkeypatch.setattr(tiers, "_read_feature_bits", explode)
    caps = tiers.probe_capabilities()
    assert caps.avx2 is False and caps.vnni is False
    assert caps.cores == (os.cpu_count() or 2)
    assert tiers.tier_for(caps) == "low"


def test_specs_pick_the_right_model_and_input() -> None:
    assert tiers.TIER_SPECS["high"] == ("yolox_m.onnx", 640)
    assert tiers.TIER_SPECS["medium"] == ("yolox_s.onnx", 640)
    assert tiers.TIER_SPECS["low"] == ("yolox_nano.onnx", 416)


def test_probe_on_this_machine_is_sane() -> None:
    caps = tiers.probe_capabilities()
    assert caps.cores >= 1
    assert tiers.tier_for(caps) in {"high", "medium", "low"}


def test_resolve_tier_points_at_the_repo_models_dir() -> None:
    tier, path, size = tiers.resolve_tier(tiers.Capabilities(cores=2, avx2=True, vnni=True))
    assert tier == "low"
    assert path == tiers.MODELS_DIR / "yolox_nano.onnx"
    assert tiers.MODELS_DIR.is_dir(), "models/ lives at the repo root, not backend/models/"
    assert size == 416
