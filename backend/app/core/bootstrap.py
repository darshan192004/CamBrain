"""First-run bootstrap: the resolved tier's weights self-heal from the manifest.

Decision D6-4 of phase-6-packaging.md: on lifespan start the engine makes sure
the resolved tier's asset exists and matches its pinned SHA-256, reusing
scripts/fetch_models.py (download only when missing; atomic .part rename). A
corrupted file is deleted and re-downloaded exactly once; a second failure
leaves the weights absent and returns a reason string instead of raising past
the lifespan — the API and dashboard stay up, the runtime starts degraded
(the detector path already handles missing weights), and /system/status
surfaces the reason through `last_reason`.

The LICENSE-MODEL-NOTICE file is hand-maintained legal text (Apache-2.0
attribution), so bootstrap *verifies* it names every fetched asset rather
than mutating it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from app.services.inference.tiers import resolve_tier
from scripts.fetch_models import Asset, FetchError, fetch, load_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.json"


def data_root() -> Path:
    """Where model downloads live for THIS launch (D6-4 dest side).

    Dev keeps the repo layout (E:\\...\\models). The frozen engine (plan T5)
    resolves against app data (D6-3, `%LOCALAPPDATA%\\CamBrain`): the bundle
    is read-only, so downloads land under that folder.
    """
    if getattr(sys, "frozen", False):  # PyInstaller onedir / onefile
        return (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            / "CamBrain"
        )
    return REPO_ROOT


def bundle_root() -> Path:
    """Where the pinned manifest + legal notice ship (read-only assets).

    Dev: the repo models tree. Frozen (onedir): `_MEIPASS` is the `_internal`
    folder next to the exe, mirroring the bundler's resource layout (see
    engine.spec datas).
    """
    if getattr(sys, "frozen", False):  # PyInstaller onedir / onefile
        return Path(getattr(sys, "_MEIPASS", "."))
    return REPO_ROOT


def resolve_manifest() -> Path:
    """The pinned manifest for this launch."""
    return bundle_root() / "models" / "manifest.json"


# Set by ensure_resolved_model; read by the /system/status router so the
# dashboard can explain a degraded runtime. Module-level because status does
# not otherwise reach app.state.
last_reason: str | None = None


def ensure_resolved_model(
    root: Path = REPO_ROOT,
    *,
    download: Callable[[str, Path], None] | None = None,
) -> str | None:
    """Bootstrap the resolved tier's weights; return a degradation reason or None.

    The reason, when set, is mirrored into `last_reason` for /system/status.
    """
    global last_reason
    _tier, model_path, _input_size = resolve_tier()
    manifest = resolve_manifest()
    last_reason = ensure_model(
        root=root,
        model_name=model_path.name,
        manifest_path=manifest,
        notice_path=manifest.parent / "LICENSE-MODEL-NOTICE",
        download=download,
    )
    return last_reason


def ensure_model(
    *,
    root: Path = REPO_ROOT,
    model_name: str,
    manifest_path: Path | None = None,
    notice_path: Path | None = None,
    download: Callable[[str, Path], None] | None = None,
    retries: int = 1,
) -> str | None:
    """Ensure one asset exists with its pinned digest; return a reason or None.

    `retries` is the number of re-download attempts after the first failure
    (`1` matches D6-4: corrupt file -> one re-download -> degrade).
    """
    manifest = manifest_path or MANIFEST_PATH
    notice = notice_path or root / "models" / "LICENSE-MODEL-NOTICE"
    try:
        assets = _asset_map(manifest)
    except OSError as exc:
        return f"{model_name}: pinned manifest unreadable ({exc})"
    asset = assets.get(model_name)
    if asset is None:
        return f"{model_name}: not listed in the pinned manifest ({manifest.name})"

    dest = root / asset.dest
    error = ""
    for _attempt in range(1 + max(retries, 0)):
        try:
            fetch(asset, root=root, download=download)
            _assert_notice(notice, asset.name)
            return None
        except (FetchError, OSError) as exc:
            error = str(exc)
            # A corrupt or stale file must not linger blocking the next
            # attempt (or an InferenceSession open on bad bytes).
            dest.unlink(missing_ok=True)
    return f"{model_name}: {error}"


def _asset_map(manifest_path: Path) -> dict[str, Asset]:
    """Manifest assets keyed by file name."""
    return {asset.name: asset for asset in load_manifest(manifest_path)}


def _assert_notice(notice: Path, name: str) -> None:
    """Fail loudly unless the hand-maintained notice names this asset (D6-4)."""
    try:
        text = notice.read_text(encoding="utf-8")
    except OSError as exc:
        raise FetchError(f"LICENSE-MODEL-NOTICE unreadable: {exc}") from exc
    if name not in text:
        raise FetchError(
            f"LICENSE-MODEL-NOTICE does not mention {name}; "
            "Apache-2.0 attribution must ship with the weights"
        )
