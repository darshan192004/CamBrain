"""Prove the things we must never commit are blocked structurally."""

from __future__ import annotations

from scripts.check_forbidden_files import find_forbidden


def test_blocks_model_weights() -> None:
    assert find_forbidden(["models/yolox_s.onnx"])
    assert find_forbidden(["models/yolox_nano.onnx"])


def test_blocks_env_and_key_material() -> None:
    assert find_forbidden([".env"])
    assert find_forbidden(["backend/.env.local"])
    assert find_forbidden(["master.key"])


def test_blocks_database_and_its_wal_sidecars() -> None:
    """A committed WAL can contain production secrets."""
    assert find_forbidden(["cambrain.db"])
    assert find_forbidden(["backend/cambrain.db-wal"])


def test_blocks_generated_media() -> None:
    assert find_forbidden(["backend/tests/fixtures/clips/motion.mp4"])


def test_blocks_frontend_build_output() -> None:
    assert find_forbidden(["frontend/node_modules/vue/index.js"])
    assert find_forbidden(["frontend/dist/index.html"])


def test_permits_the_model_licence_notice() -> None:
    """Apache-2.0 attribution is a legal obligation, not repo tidiness."""
    assert find_forbidden(["models/LICENSE-MODEL-NOTICE"]) == []


def test_permits_gitkeep_and_source() -> None:
    assert find_forbidden(["models/.gitkeep"]) == []
    assert find_forbidden(["backend/app/core/crypto.py"]) == []
    assert find_forbidden([".github/workflows/ci.yml"]) == []


def test_permits_a_clips_directory_without_media_in_it() -> None:
    """The directory is fine; the footage inside it is not."""
    assert find_forbidden(["backend/tests/fixtures/clips/"]) == []


def test_reports_every_path_not_just_the_first() -> None:
    hits = find_forbidden(["models/a.onnx", "ok.py", "cambrain.db"])
    assert len(hits) == 2


def test_normalises_windows_separators() -> None:
    """Git reports POSIX paths; a dev may pass Windows ones."""
    assert find_forbidden(["models\\yolox_s.onnx"])
