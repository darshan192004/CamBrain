# Phase 3 — Inference + ROI + Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Controller note: this session executes inline (standing decision — no subagents; Conventional Commits; no `Co-Authored-By`).

**Goal:** A real YOLOX detector, an IoU tracker, and a pure rules engine turn a real clip into a real fired alert in under 2 seconds — hardware-free, licence-clean, fully testable.

**Architecture:** Pure, test-first layers: `inference/` (letterbox → ONNX → grid decode → NMS), `tracker/` (IoU identity across frames), `alerts/` (ROI geometry + a side-effect-free `RulesEngine` + an `AlertStage` that composes them behind the existing `FrameSink` seam). The `Detector` is a Protocol so the RT-DETR swap never touches the pipeline, the API, or the rules (spec §10.4).

**Tech Stack:** Python 3.13 · ONNX Runtime 1.31 (already locked in Phase 0) · NumPy 2.5 · opencv-python-headless 5.0 · pytest · ruff · mypy strict.

**Spec:** [`docs/superpowers/specs/spec.md`](../../specs/spec.md) — §1.5 (latency), §4.7 (tiers), §4.8 (detection ≠ alerting), §5.2 (`Detector`), §5.4 (`Tracker`), §5.5 (`RulesEngine`), §7.3 (rules test endpoint), §10.4 (detector decision), §11 (tests), §12 (verification matrix). Design: [`docs/superpowers/specs/2026-10-05-cambrain-mvp-design.md`](../../specs/2026-10-05-cambrain-mvp-design.md) D17. Living docs: [`API.md`](../../../API.md), [`tasks.md`](../../../tasks.md) (Phase 3 section mirrors this plan).

## Global Constraints

Copied verbatim from the master plan; this block wins over any phase file that differs.

**Licensing — hard constraint, CI-enforced:**
- No AGPL dependency in any form. `ultralytics` (YOLOv5, v8, v11, v26) is **prohibited**, including ONNX exports.
- Detector models must be Apache-2.0 or equivalent. Permitted family: **YOLOX** (default), **RT-DETR**, DAMO-YOLO, NanoDet.
- `models/*.onnx` is gitignored. Weights are fetched by script with SHA-256 verification.
- `models/LICENSE-MODEL-NOTICE` records provenance + licence for every shipped weight file. Apache-2.0 requires attribution — legal obligation.
- CI runs a licence scan and **fails the build on any AGPL identifier**.

**Language and stack:**
- Frontend is **JavaScript, not TypeScript**. JSDoc typedefs on every exported function and API boundary. ESLint enforces `jsdoc/require-jsdoc`.
- Frontend framework is **Vue 3**, never React.
- Python line length 100. Target Python 3.13.
- Type hints on every function signature. No `Any` outside tests and protocol boundaries.
- Google-style docstrings on every public function.

**Concurrency:**
- Single process. One thread per camera. **Not** process-per-camera.
- PyAV decode and ONNX Runtime `run()` both release the GIL.
- One `InferenceSession` per model tier, shared across cameras.
- `CameraPipeline` holds no shared mutable state; collaborators are constructor-injected; outward communication via injected sink. **This seam must not be eroded.**

**Backpressure — the single most important streaming rule:**
- Between source and every consumer sits a latest-frame slot (`asyncio.Queue(maxsize=1)`).
- **Full queue means replace the oldest frame.** Never block, never accumulate.
- Drop frames **before** resize, not after decode.

**Tenancy:**
- Every domain table carries `site_id`.
- `site_id` is taken from the **auth token**, never from a request body or query parameter.
- Cross-tenant access returns **404, never 403**.
- Every FK has an explicit `ON DELETE` behaviour.

**Secrets:** Fernet at rest · no credentials in `rtsp_url` · `REDACT_KEYS` structural redaction · URLs masked everywhere · secrets never in any `GET`.

**Conventions:**
- Components always `<script setup>`, order script → template → style, always `scoped`.
- Hardcoded hex colours in components: never. Design tokens as CSS variables only.
- A `watch` that only sets other state is forbidden — use `computed`.
- SQLAlchemy 2.0 `select()` style. No string-built SQL.
- Alembic only for migrations. Never edit a shipped migration.
- Conventional Commits. Scope is the module: `stream`, `inference`, `rules`, `ui`, `api`.
- Never commit: model weights, `.env`, `cambrain.db`, clips, `node_modules/`, build output, credentials.

## Phase 3 scope

**In:**
1. SHA-256-pinned fetch script for the three tier models + the real gate clip; `models/LICENSE-MODEL-NOTICE`.
2. `inference/`: `Detection`/`Detector` types, YOLOX letterbox + anchor-free decode + NMS, ONNX wrapper with output validation, bounded inference pool, hardware tier detection.
3. IoU `Tracker` producing stable `track_id`s and normalised centroids.
4. `alerts/roi.py`: edge-inclusive point-in-polygon on normalised coordinates.
5. `alerts/rules.py`: pure `RulesEngine` — class, confidence, ROI, active-hours (timezone, midnight wrap), cooldown — with per-condition `RuleCheck` details exactly as `API.md` documents them.
6. `alerts/stage.py`: `AlertStage` implementing `FrameSink` — detect → track → evaluate → fire injected `on_alert`.
7. Per-camera sinks on `StreamManager.add_camera` (backward compatible).
8. `POST /api/v1/rules/{id}/test` — real replay of the latest/explicit event's detections through the engine (replaces the 501-adjacent stub).
9. Gate: `test_motion_to_alert_under_2s` in `test_pipeline.py` (MockDetector) + the human-observed slow gate test running **real YOLOX on the real gate clip, asserting a real `person` alert under 2 s**.

**Out (explicit):**
- Live RTSP → alert wiring in the app runtime, event persistence, WS broadcast, clips, notifier — **Phase 5** (tasks.md).
- Dashboard, ROI editor UI — Phase 4.
- YOLOX-s vs RT-DETR benchmark on real footage — deferred by D17 (no cameras); recorded in deviations.
- `io_binding` / preallocated IO buffers — deferred optimisation; the bounded pool + one session per tier is the Phase 3 contract (recorded in deviations).

## Verification matrix rows this phase must prove

| Requirement | Proving test | Status |
|---|---|---|
| Hardware floor / graceful degradation | `test_tiers.py::test_tier_falls_back_on_low_capability` | new |
| Detection latency < 2s | `test_pipeline.py::test_motion_to_alert_under_2s` | new |
| Model output validated | `test_detector.py::test_rejects_malformed_output` | new |
| Rules correctness | `test_rules.py` — table-driven, every branch | new |
| ROI boundary logic | `test_roi.py::test_centroid_on_edge_counts_inside` | new |
| Real alert from a real clip, under 2s | `test_gate_inference.py::test_real_alert_from_real_clip_under_2s` (marker `slow`) | new — **phase gate** |
| Diagnostic endpoint matches API.md shape | `test_api_rules.py::test_rule_test_returns_api_shaped_checks` | new |
| Assets pinned by SHA-256 | `fetch_models.py --verify` + `test_fetch_models.py` | new |
| No dependency drift | `git diff requirements.lock.txt` at Task 3.12 shows only `+tzdata==…` | new |

## File structure

| File | Action | Responsibility |
|---|---|---|
| `models/manifest.json` | CREATE | SHA-256-pinned URLs for 3 tier models + gate clip (committed) |
| `models/LICENSE-MODEL-NOTICE` | CREATE | Provenance + licence for every downloaded asset (committed) |
| `backend/scripts/fetch_models.py` | CREATE | Download + verify against manifest; `--verify` check-only mode |
| `backend/tests/test_fetch_models.py` | CREATE | Hash mismatch rejected; verify-only never downloads |
| `backend/app/services/inference/__init__.py` | CREATE | Package exports |
| `backend/app/services/inference/types.py` | CREATE | `Detection`, `Detector`, `LetterboxMeta`, ordered `COCO_CLASSES` |
| `backend/app/services/inference/yolox_post.py` | CREATE | Grid decode, un-letterbox, confidence, NMS — pure NumPy |
| `backend/app/services/inference/pool.py` | CREATE | Bounded `ThreadPoolExecutor` runner |
| `backend/app/services/inference/detector.py` | CREATE | Letterbox, `OnnxYoloXDetector`, factory |
| `backend/app/services/inference/tiers.py` | CREATE | Capability probe + tier → model/input-size |
| `backend/app/services/inference/tracker.py` | CREATE | IoU tracker, `TrackedObject` |
| `backend/app/services/alerts/__init__.py` | CREATE | Package exports |
| `backend/app/services/alerts/roi.py` | CREATE | Edge-inclusive point-in-polygon, normalised centroids |
| `backend/app/services/alerts/rules.py` | CREATE | `RuleConfig`, `RuleCheck`, `RuleOutcome`, `RulesEngine` (pure) |
| `backend/app/services/alerts/stage.py` | CREATE | `AlertStage` (`FrameSink`), `Alert`, cooldown bookkeeping |
| `backend/app/services/alerts/replay.py` | CREATE | Project rule+ROI → `RuleConfig`; replay event detections through the engine |
| `backend/app/services/stream/stream_manager.py` | MODIFY | `add_camera(..., sink=None)` per-camera override |
| `backend/app/api/schemas.py` | MODIFY | `RuleTestRequest`, `RuleCheckOut`, `RuleTestOut` |
| `backend/app/api/routers/rules.py` | MODIFY | Real `test_rule` replay implementation |
| `docs/API.md` | MODIFY | Document `POST /rules/{id}/test` request body |
| `backend/tests/test_yolox_post.py` | CREATE | Decode, NMS, un-letterbox, malformed rejection |
| `backend/tests/test_detector.py` | CREATE | Malformed output rejected; real-model smoke (skip-if-absent) |
| `backend/tests/test_pool.py` | CREATE | Bounded runner orders and propagates errors |
| `backend/tests/test_tiers.py` | CREATE | Tier table + probe-failure fallback |
| `backend/tests/test_tracker.py` | CREATE | Id stability, IoU handoff, expiry |
| `backend/tests/test_roi.py` | CREATE | Edge-inclusive containment, normalisation |
| `backend/tests/test_rules.py` | CREATE | Table-driven, every branch, timezones, midnight wrap |
| `backend/tests/test_alert_stage.py` | CREATE | Fire/suppress/cooldown through the sink seam |
| `backend/tests/test_pipeline.py` | MODIFY | `test_motion_to_alert_under_2s` |
| `backend/tests/test_api_rules.py` | MODIFY | Replace the 501-era stub row with real replay rows |
| `backend/tests/conftest.py` | MODIFY | `gate_clip_path` fixture (visible skip when unfetched) |
| `backend/tests/test_api_rules.py` | MODIFY | Rules-test replay: shape, 404, 422 paths |
| `backend/tests/test_gate_inference.py` | CREATE | Real YOLOX + real clip alert under 2s (`slow`) |

**Dependency changes: one.** `onnxruntime==1.31.0`, `numpy==2.5.3`, `opencv-python-headless==5.0.0.93` are already in `requirements.lock.txt` from Phase 0. The single addition is `tzdata` (Apache-2.0): `zoneinfo` on Windows has no system IANA database, and active-hours would be untestable and unshippable without it (discovered executing Task 3.7; floor added to `requirements.txt`, lock regenerated by the Phase-0 `pip freeze` recipe). The gate verifies the lock diff is **exactly** that one line.

## Task overview

| # | Task | Deliverable | Commit scope |
|---|---|---|---|
| 3.1 | Asset manifest + fetch script + licence notice | `fetch_models.py --verify` green | `chore(infrastructure)` |
| 3.2 | Types + YOLOX decode/NMS | `yolox_post.py` pure decode proven | `feat(inference)` |
| 3.3 | Letterbox + ONNX detector + pool | `Detector.infer` returns `list[Detection]` | `feat(infrastructure)` |
| 3.4 | Hardware tiers | `tier_for`/`probe_capabilities` | `feat(inference)` |
| 3.5 | IoU tracker | stable ids + normalised centroid | `feat(inference)` |
| 3.6 | ROI geometry | edge-inclusive polygon containment | `feat(rules)` |
| 3.7 | Pure rules engine | table-driven every-branch green | `feat(rules)` |
| 3.8 | `AlertStage` + per-camera sinks | clip → fired alert in-process | `feat(rules)` + `feat(stream)` |
| 3.9 | Motion-to-alert latency test | `test_motion_to_alert_under_2s` | `test(stream)` |
| 3.10 | Rules test endpoint | real checks out of `POST /rules/{id}/test` | `feat(api)` |
| 3.11 | Real-clip gate | slow test fires `person` alert <2s | `test(inference)` |
| 3.12 | Full gate + ledger + living docs | every matrix row observed | `docs(phase3)` |

**Working rules (from this repo's history):**
- TDD loop per step: failing test → watch it fail → implement → watch it pass → `ruff check backend && ruff format backend && ruff format --check backend && mypy backend/app` → commit → push.
- Prepend `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH` before any `git commit` (pre-commit runs mypy).
- Multi-line commit messages via a BOM-free file: `git commit -F .tmp\commit_msg.txt` written with `[IO.File]::WriteAllText` + `UTF8Encoding($false)`.
- Default suite: `pytest -m "not rtsp and not slow" --ignore=backend/tests/rtsp`. Never run pytest and mypy in parallel.
- `.tmp/` is untracked scratch — never `git add` it.
- FastAPI deps use `Annotated[...]` (ruff B008); tests keep `noqa` only where Phase 2 already established the pattern.

---

### Task 3.1: Asset manifest, fetch script, licence notice

**Files:**
- Create: `models/manifest.json`
- Create: `models/LICENSE-MODEL-NOTICE`
- Create: `backend/scripts/fetch_models.py`
- Create: `backend/tests/test_fetch_models.py`
- Modify: `.gitignore` (add `*.part`)

**Interfaces:**
- Produces: `Asset(name, url, sha256, dest, licence, source)`, `load_manifest() -> list[Asset]`, `sha256_of(path) -> str`, `verify(asset, dest) -> None` (raises `FetchError`), `fetch(asset, *, root, download) -> Path`, `main(argv) -> int`.

**Pinned assets (verified this session; digests are exact):**

| dest | sha256 |
|---|---|
| `models/yolox_s.onnx` | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` |
| `models/yolox_nano.onnx` | `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` |
| `models/yolox_m.onnx` | `21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f` |
| `backend/tests/fixtures/clips/gate.mp4` | `452b11b7e0efbd019f1d9570d0c790e90416ad4ad29eec6003872d08443140ef` |

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_fetch_models.py`:

```python
"""Fetch verification must reject tampered weights before they reach a session."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.fetch_models import Asset, FetchError, fetch, load_manifest, sha256_of, verify


def _asset(tmp_path: Path, body: bytes = b"clean-bytes") -> tuple[Asset, Path]:
    digest = hashlib.sha256(body).hexdigest()
    asset = Asset(
        name="fake.onnx",
        url="https://example.invalid/fake.onnx",
        sha256=digest,
        dest="models/fake.onnx",
        licence="Apache-2.0",
        source="test",
    )
    return asset, tmp_path / "models" / "fake.onnx"


def test_verify_accepts_matching_digest(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"clean-bytes")
    verify(asset, dest)


def test_verify_rejects_tampered_file(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"tampered")
    with pytest.raises(FetchError, match="sha256 mismatch"):
        verify(asset, dest)


def test_verify_rejects_missing_file(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    with pytest.raises(FetchError, match="missing"):
        verify(asset, dest)


def test_fetch_downloads_then_verifies(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    calls: list[str] = []

    def fake_download(url: str, target: Path) -> None:
        calls.append(url)
        target.write_bytes(b"clean-bytes")

    result = fetch(asset, root=tmp_path, download=fake_download)
    assert result == dest
    assert calls == [asset.url]
    assert dest.read_bytes() == b"clean-bytes"


def test_fetch_never_redownloads_a_present_asset(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"clean-bytes")

    def explode(url: str, target: Path) -> None:
        raise AssertionError("download must not run when the asset is present")

    fetch(asset, root=tmp_path, download=explode)


def test_fetch_rejects_a_poisoned_download(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)

    def fake_download(url: str, target: Path) -> None:
        target.write_bytes(b"wrong-bytes")

    with pytest.raises(FetchError, match="sha256 mismatch"):
        fetch(asset, root=tmp_path, download=fake_download)
    assert not dest.exists(), "a failed download must never be left at the final path"


def test_manifest_is_well_formed() -> None:
    assets = load_manifest()
    names = {a.name for a in assets}
    assert names == {"yolox_s.onnx", "yolox_nano.onnx", "yolox_m.onnx", "gate.mp4"}
    for asset in assets:
        assert len(asset.sha256) == 64
        assert asset.licence in {"Apache-2.0", "CC-BY-4.0"}


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abc")
    assert sha256_of(path) == hashlib.sha256(b"abc").hexdigest()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; pytest backend/tests/test_fetch_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.fetch_models'`

- [ ] **Step 3: Write the manifest, notice, fetch script, gitignore line**

`models/manifest.json`:

```json
{
  "assets": [
    {
      "name": "yolox_s.onnx",
      "url": "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
      "sha256": "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
      "dest": "models/yolox_s.onnx",
      "licence": "Apache-2.0",
      "source": "Megvii-BaseDetection/YOLOX release 0.1.1rc0"
    },
    {
      "name": "yolox_nano.onnx",
      "url": "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx",
      "sha256": "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d",
      "dest": "models/yolox_nano.onnx",
      "licence": "Apache-2.0",
      "source": "Megvii-BaseDetection/YOLOX release 0.1.1rc0"
    },
    {
      "name": "yolox_m.onnx",
      "url": "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_m.onnx",
      "sha256": "21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f",
      "dest": "models/yolox_m.onnx",
      "licence": "Apache-2.0",
      "source": "Megvii-BaseDetection/YOLOX release 0.1.1rc0"
    },
    {
      "name": "gate.mp4",
      "url": "https://github.com/intel-iot-devkit/sample-videos/raw/master/person-bicycle-car-detection.mp4",
      "sha256": "452b11b7e0efbd019f1d9570d0c790e90416ad4ad29eec6003872d08443140ef",
      "dest": "backend/tests/fixtures/clips/gate.mp4",
      "licence": "CC-BY-4.0",
      "source": "intel-iot-devkit/sample-videos (archived, CC-BY-4.0)"
    }
  ]
}
```

`models/LICENSE-MODEL-NOTICE`:

```text
CamBrain model asset notice
===========================

Weights are gitignored and fetched by backend/scripts/fetch_models.py.
Every entry below is pinned by SHA-256 in models/manifest.json.

yolox_s.onnx, yolox_nano.onnx, yolox_m.onnx
  Source:   https://github.com/Megvii-BaseDetection/YOLOX (release 0.1.1rc0)
  Licence:  Apache License 2.0
  Copyright (c) Megvii Imaging
  Note:     Apache-2.0 requires attribution; keep this file with any build
            that ships these weights. ultralytics exports are prohibited.

gate.mp4 (test asset, person-bicycle-car-detection.mp4)
  Source:   https://github.com/intel-iot-devkit/sample-videos
  Licence:  CC-BY-4.0
  Copyright (c) Intel Corporation
  Use:      Phase 3 gate only; never shipped to customers.

No model in this repository is AGPL, GPL, or network-copyleft in any form.
```

`backend/scripts/fetch_models.py`:

```python
"""Fetch and verify the assets pinned in models/manifest.json.

Weights are gitignored; the manifest pins URL + SHA-256 so a corrupted,
truncated, or swapped download fails loudly before an InferenceSession ever
opens it (spec A3, licensing hard constraint).

Usage:
    python backend/scripts/fetch_models.py           # download what is missing, verify all
    python backend/scripts/fetch_models.py --verify  # check-only, never touches the network
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.json"


class FetchError(RuntimeError):
    """An asset is missing or does not match its pinned digest."""


@dataclass(frozen=True, slots=True)
class Asset:
    """One downloadable, digest-pinned file."""

    name: str
    url: str
    sha256: str
    dest: str
    licence: str
    source: str


def load_manifest(path: Path = MANIFEST_PATH) -> list[Asset]:
    """Parse the manifest into Asset records."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Asset(**entry) for entry in raw["assets"]]


def sha256_of(path: Path) -> str:
    """Stream a file through SHA-256 and return the lowercase hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(asset: Asset, dest: Path) -> None:
    """Raise FetchError unless dest exists with exactly the pinned digest."""
    if not dest.exists():
        raise FetchError(f"{asset.name}: missing at {dest} - run fetch_models.py")
    actual = sha256_of(dest)
    if actual != asset.sha256:
        raise FetchError(f"{asset.name}: sha256 mismatch (got {actual}, pinned {asset.sha256})")


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp, dest.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)


def fetch(
    asset: Asset,
    *,
    root: Path = REPO_ROOT,
    download: Callable[[str, Path], None] | None = None,
) -> Path:
    """Ensure asset is at its dest with the pinned digest; return the path.

    Downloads to a .part sibling and renames, so an interrupted run never
    leaves a partial file at the final path.
    """
    dest = root / asset.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        partial = dest.with_name(dest.name + ".part")
        try:
            (download or _download)(asset.url, partial)
            verify(Asset(asset.name, asset.url, asset.sha256, asset.dest, asset.licence, asset.source), partial)
        except FetchError:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(dest)
    verify(asset, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    """Fetch (or only verify) every manifest asset; exit 1 on any failure."""
    parser = argparse.ArgumentParser(description="Fetch and verify CamBrain model assets")
    parser.add_argument("--verify", action="store_true", help="check local files only")
    args = parser.parse_args(argv)
    failures: list[str] = []
    for asset in load_manifest():
        try:
            if args.verify:
                verify(asset, REPO_ROOT / asset.dest)
            else:
                fetch(asset)
            print(f"ok   {asset.name}")
        except FetchError as exc:
            failures.append(str(exc))
    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Append to `.gitignore`:

```
*.part
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_fetch_models.py -v`
Expected: 8 passed

- [ ] **Step 5: Fetch the real assets and prove check-only mode**

Run: `python backend/scripts/fetch_models.py` (downloads ~142 MB once)
Run: `python backend/scripts/fetch_models.py --verify`
Expected: `ok` x 4, exit 0. Then delete `models/yolox_nano.onnx`, run `--verify` → exit 1 with `FAIL ... missing`, restore by re-running fetch.

- [ ] **Step 6: Static checks + commit**

Run: `ruff check backend; ruff format backend; ruff format --check backend; mypy backend/app`
Run: `git status` — assert no `.onnx`/`.mp4`/`.part` staged.
Commit: `chore(infrastructure): pin model weights and the gate clip by sha256`
Body: weights are code with a licence attached — a digest in git is the only way a silent upstream swap becomes a loud local failure; the gate clip is CC-BY-4.0 and test-only.

---

### Task 3.2: Detection types + YOLOX decode/NMS

**Files:**
- Create: `backend/app/services/inference/__init__.py`
- Create: `backend/app/services/inference/types.py`
- Create: `backend/app/services/inference/yolox_post.py`
- Test: `backend/tests/test_yolox_post.py`

**Interfaces:**
- Produces: `Detection(class_name, confidence, bbox)`, `Detector` Protocol (`async infer(Frame) -> list[Detection]`, `async close()`), `LetterboxMeta(scale, pad_x, pad_y, input_size, frame_width, frame_height)`, `COCO_CLASSES: tuple[str, ...]` (80, YOLOX order), `decode(output, meta, *, conf_threshold=0.25, iou_threshold=0.45) -> list[Detection]`, `nms(boxes, scores, iou_threshold, max_detections) -> np.ndarray`.
- Consumes: `InferenceError` from `app.core.errors` (already exists from Phase 0), `Frame` from `app.services.stream.source`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_yolox_post.py`:

```python
"""Decode contract: grid space -> frame pixels, names not indices, loud failures."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.errors import InferenceError
from app.services.inference.types import COCO_CLASSES, LetterboxMeta
from app.services.inference.yolox_post import decode, nms

META = LetterboxMeta(scale=0.5, pad_x=10, pad_y=20, input_size=640, frame_width=1280, frame_height=720)


def _blank() -> np.ndarray:
    return np.zeros((8400, 85), dtype=np.float32)


def _place(out: np.ndarray, cell: int, *, cx: float, cy: float, w: float, h: float,
           obj: float, cls_idx: int, cls_score: float) -> None:
    out[cell, 0:4] = [cx, cy, w, h]
    out[cell, 4] = obj
    out[cell, 5:] = 0.01
    out[cell, 5 + cls_idx] = cls_score


def test_confident_box_lands_in_frame_pixels() -> None:
    out = _blank()
    # Cell (10, 5) of the stride-8 level: grid index 5*80+10 = 410.
    # center = (pred + grid) * stride = (0.5+10, 0.5+5) * 8 = (84, 44);
    # wh = (1, 2) * 8 = (8, 16) -> input box (80, 36)-(88, 52).
    _place(out, 410, cx=0.5, cy=0.5, w=1.0, h=2.0, obj=0.9, cls_idx=0, cls_score=0.8)
    dets = decode(out, META, conf_threshold=0.3)
    assert len(dets) == 1
    det = dets[0]
    assert det.class_name == "person"
    assert det.confidence == pytest.approx(0.72)
    # un-letterbox: x1/y1 floor, x2/y2 ceil of (v - pad) / scale
    x1, y1, x2, y2 = det.bbox
    assert (x1, y1, x2, y2) == (140, 32, 156, 64)


def test_class_names_come_from_coco_order() -> None:
    out = _blank()
    _place(out, 410, cx=0.5, cy=0.5, w=1.0, h=1.0, obj=0.9, cls_idx=16, cls_score=0.9)
    dets = decode(out, META, conf_threshold=0.3)
    assert dets[0].class_name == "dog"
    assert COCO_CLASSES[0] == "person" and len(COCO_CLASSES) == 80


def test_nms_keeps_the_higher_box() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    keep = nms(boxes, scores, iou_threshold=0.5)
    assert keep.tolist() == [0, 2]


def test_low_confidence_is_dropped() -> None:
    out = _blank()
    _place(out, 0, cx=0.0, cy=0.0, w=1.0, h=1.0, obj=0.2, cls_idx=0, cls_score=0.5)
    assert decode(out, META, conf_threshold=0.3) == []


def test_rejects_wrong_shape() -> None:
    with pytest.raises(InferenceError, match="expected model output"):
        decode(np.zeros((7, 7, 3), dtype=np.float32), META)


def test_rejects_batched_shape_other_than_one() -> None:
    with pytest.raises(InferenceError, match="expected model output"):
        decode(np.zeros((2, 8400, 85), dtype=np.float32), META)


def test_rejects_nan_payload() -> None:
    out = _blank()
    out[0, 0] = np.nan
    with pytest.raises(InferenceError, match="NaN or inf"):
        decode(out, META)


def test_boxes_degenerate_after_unletterbox_are_dropped() -> None:
    out = _blank()
    # wh so small it rounds to an empty box after scaling by 0.5.
    _place(out, 0, cx=0.0, cy=0.0, w=0.4, h=0.4, obj=0.99, cls_idx=0, cls_score=0.99)
    assert decode(out, META, conf_threshold=0.3) == []


def test_coco_class_list_matches_the_api_validator() -> None:
    """Two deliberate copies (decode order vs API frozenset) must not drift."""
    from app.api.schemas import COCO_CLASSES as API_CLASSES
    from app.services.inference.types import COCO_CLASSES

    assert len(COCO_CLASSES) == 80
    assert set(COCO_CLASSES) == set(API_CLASSES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_yolox_post.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.inference'`

- [ ] **Step 3: Write the types and decoder**

`backend/app/services/inference/__init__.py`:

```python
"""Inference layer: Detector protocol, YOLOX decode, tiers, tracker (spec A5.2, A10.4)."""

from app.services.inference.types import COCO_CLASSES, Detection, Detector, LetterboxMeta

__all__ = [
    "COCO_CLASSES",
    "Detection",
    "Detector",
    "LetterboxMeta",
]
```

`backend/app/services/inference/types.py`:

```python
"""Detector-facing types (spec A5.2).

Classes are names, never indices: YOLOX and RT-DETR do not share output
ordering, so an index stored anywhere would silently repoint every rule when
the model changes (spec A6.4, D17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.stream.source import Frame

COCO_CLASSES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife",
    "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


@dataclass(frozen=True, slots=True)
class Detection:
    """One model output box, already in frame pixels."""

    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)


@dataclass(frozen=True, slots=True)
class LetterboxMeta:
    """Geometry needed to map network input space back to frame pixels."""

    scale: float
    pad_x: int
    pad_y: int
    input_size: int
    frame_width: int
    frame_height: int


class Detector(Protocol):
    """The licensing boundary (spec A5.2): one swap, no pipeline changes."""

    async def infer(self, frame: Frame) -> list[Detection]:
        """Return every detected object in frame pixels, all 80 COCO classes."""
        ...

    async def close(self) -> None:
        """Release the session; idempotent."""
        ...
```

`backend/app/services/inference/yolox_post.py`:

```python
"""Anchor-free YOLOX decode: grid space -> frame pixels, then NMS.

Contract, verified empirically against yolox_s.onnx (release 0.1.1rc0):
input `images` [1,3,640,640] float32 0..255 RGB; output `output` [1,8400,85]
where columns 0..3 are raw grid-space (cx, cy, w, h) with xy as cell offsets
and wh stride-linear (NO exp), column 4 objectness and 5..84 class scores are
already sigmoid'd. Grid: stride 8 -> 80x80, 16 -> 40x40, 32 -> 20x20
(spec A4.7 I/O signature; D17 swap contract keeps this file YOLOX-only).
"""

from __future__ import annotations

import numpy as np

from app.core.errors import InferenceError
from app.services.inference.types import COCO_CLASSES, Detection, LetterboxMeta

OUTPUT_SHAPE = (8400, 85)
_LEVELS: tuple[tuple[int, int], ...] = ((8, 80), (16, 40), (32, 20))


def _build_grid() -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for stride, side in _LEVELS:
        gy, gx = np.meshgrid(np.arange(side), np.arange(side), indexing="ij")
        grids.append(np.stack([gx, gy], -1).reshape(-1, 2))
        strides.append(np.full((side * side, 1), stride, dtype=np.float32))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides)


_GRID, _STRIDE = _build_grid()


def nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    *,
    iou_threshold: float = 0.45,
    max_detections: int = 100,
) -> np.ndarray:
    """Class-agnostic greedy NMS; returns kept indices in score order."""
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size and len(keep) < max_detections:
        best = int(order[0])
        keep.append(best)
        rest = order[1:]
        xx1 = np.maximum(boxes[best, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[best, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[best, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[best, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_a = (boxes[best, 2] - boxes[best, 0]) * (boxes[best, 3] - boxes[best, 1])
        area_b = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        iou = inter / (area_a + area_b - inter + 1e-9)
        order = rest[iou <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def _as_2d(output: np.ndarray) -> np.ndarray:
    """Validate raw model output and drop the batch axis."""
    arr = np.asarray(output, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.shape != OUTPUT_SHAPE:
        raise InferenceError(f"expected model output {OUTPUT_SHAPE}, got {arr.shape}")
    if not np.isfinite(arr).all():
        raise InferenceError("model output contains NaN or inf")
    return arr


def decode(
    output: np.ndarray,
    meta: LetterboxMeta,
    *,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> list[Detection]:
    """Turn one raw YOLOX output tensor into frame-pixel detections."""
    arr = _as_2d(output)
    xy = (arr[:, :2] + _GRID) * _STRIDE
    wh = arr[:, 2:4] * _STRIDE
    class_scores = arr[:, 5:] * arr[:, 4:5]
    class_idx = class_scores.argmax(axis=1)
    confidence = class_scores.max(axis=1)
    mask = confidence >= conf_threshold
    if not mask.any():
        return []
    cx, cy = xy[mask, 0], xy[mask, 1]
    half_w, half_h = wh[mask, 0] / 2.0, wh[mask, 1] / 2.0
    x1 = np.floor((cx - half_w - meta.pad_x) / meta.scale)
    y1 = np.floor((cy - half_h - meta.pad_y) / meta.scale)
    x2 = np.ceil((cx + half_w - meta.pad_x) / meta.scale)
    y2 = np.ceil((cy + half_h - meta.pad_y) / meta.scale)
    x1 = np.clip(x1, 0, meta.frame_width - 1)
    y1 = np.clip(y1, 0, meta.frame_height - 1)
    x2 = np.clip(x2, 0, meta.frame_width)
    y2 = np.clip(y2, 0, meta.frame_height)
    scores = confidence[mask]
    idx = np.nonzero((x2 - x1 >= 1) & (y2 - y1 >= 1))[0]
    if idx.size == 0:
        return []
    boxes = np.stack([x1[idx], y1[idx], x2[idx], y2[idx]], axis=1).astype(np.float32)
    keep = nms(boxes, scores[idx], iou_threshold=iou_threshold)
    kept = idx[keep]
    return [
        Detection(
            class_name=COCO_CLASSES[int(class_idx[mask][i])],
            confidence=float(confidence[mask][i]),
            bbox=(int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])),
        )
        for i in kept
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_yolox_post.py -v`
Expected: 9 passed. If `test_confident_box_lands_in_frame_pixels` disagrees on rounding, re-derive from the formula in the test comment — the empirical run in this plan pinned `floor`/`ceil` semantics.

> Import order note: `inference/__init__.py` may not import `tiers`/`tracker` (Tasks 3.4/3.5). Task 3.2 creates it with **only the `types` exports** shown above; Task 3.5 extends it with `TrackedObject`/`Tracker`. Tests import `app.services.inference.types`/`yolox_post` directly either way.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `feat(inference): decode YOLOX grid output into named frame detections`
Body: names not indices so a model swap cannot repoint rules; the grid/stride/linear-wh contract is pinned by test because it was measured against the shipped ONNX, not assumed.

---

### Task 3.3: Letterbox, ONNX detector, bounded pool

**Files:**
- Create: `backend/app/services/inference/pool.py`
- Create: `backend/app/services/inference/detector.py`
- Test: `backend/tests/test_pool.py`
- Test: `backend/tests/test_detector.py`

**Interfaces:**
- Consumes: `Detection`, `Detector`, `LetterboxMeta`, `decode` (Task 3.2); `InferenceError` (exists).
- Produces: `InferencePool(max_workers=2)` with `async run(fn, *args)` and `close()`; `letterbox(image, input_size=640) -> tuple[np.ndarray, LetterboxMeta]`; `OnnxYoloXDetector(model_path, *, input_size, conf_threshold, iou_threshold, pool)`; `open_detector(model_path, *, input_size=640, pool=None) -> Detector`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_pool.py`:

```python
"""The pool bounds executor threads and propagates failures untouched."""

from __future__ import annotations

import pytest

from app.services.inference.pool import InferencePool


async def test_run_returns_value() -> None:
    pool = InferencePool(max_workers=1)
    try:
        assert await pool.run(lambda a, b: a + b, 2, 3) == 5
    finally:
        pool.close()


async def test_run_propagates_errors() -> None:
    pool = InferencePool(max_workers=1)
    try:
        with pytest.raises(ValueError, match="boom"):
            await pool.run(_explode)
    finally:
        pool.close()


def _explode() -> None:
    raise ValueError("boom")
```

`backend/tests/test_detector.py`:

```python
"""Letterbox geometry, loud failures, and a real-model smoke test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.core.errors import InferenceError
from app.services.inference.detector import OnnxYoloXDetector, letterbox, open_detector
from app.services.stream.source import Frame

MODELS = Path(__file__).resolve().parents[2] / "models"
GATE = Path(__file__).parent / "fixtures" / "clips" / "gate.mp4"


def _frame(w: int = 768, h: int = 432) -> Frame:
    return Frame(data=np.zeros((h, w, 3), dtype=np.uint8), timestamp=0.0, width=w, height=h)


def test_letterbox_pads_to_square() -> None:
    tensor, meta = letterbox(np.zeros((432, 768, 3), dtype=np.uint8), 640)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert meta.scale == pytest.approx(640 / 768)
    assert meta.pad_x == 0
    assert meta.pad_y == (640 - int(432 * 640 / 768)) // 2
    assert (meta.frame_width, meta.frame_height) == (768, 432)


async def test_rejects_malformed_output() -> None:
    det = OnnxYoloXDetector(Path("unused.onnx"))

    def bad_run(_tensor: np.ndarray) -> np.ndarray:
        return np.zeros((3, 3, 3), dtype=np.float32)

    det._run_tensor = bad_run  # type: ignore[method-assign]
    with pytest.raises(InferenceError, match="expected model output"):
        await det.infer(_frame())


def test_open_detector_requires_weights(tmp_path: Path) -> None:
    with pytest.raises(InferenceError, match="missing"):
        open_detector(tmp_path / "nope.onnx")


@pytest.mark.skipif(
    not (MODELS / "yolox_s.onnx").exists() or not GATE.exists(),
    reason="run backend/scripts/fetch_models.py to enable the real-model smoke test",
)
async def test_real_model_detects_a_person_in_gate_clip() -> None:
    """Letterbox + decode + session, end to end, on the real clip (spec A11.1)."""
    import cv2

    cap = cv2.VideoCapture(str(GATE))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 60)
    ok, bgr = cap.read()
    cap.release()
    assert ok
    rgb = bgr[:, :, ::-1].copy()
    frame = Frame(data=rgb, timestamp=0.0, width=rgb.shape[1], height=rgb.shape[0])
    det = open_detector(MODELS / "yolox_s.onnx")
    try:
        found = await det.infer(frame)
    finally:
        await det.close()
    people = [d for d in found if d.class_name == "person" and d.confidence > 0.5]
    assert people, [(d.class_name, round(d.confidence, 3)) for d in found]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_pool.py backend/tests/test_detector.py -v`
Expected: FAIL — `No module named 'app.services.inference.pool'`

- [ ] **Step 3: Write the pool and detector**

`backend/app/services/inference/pool.py`:

```python
"""Bounded executor for ONNX runs.

Eight cameras must not mean eight simultaneous sessions submits: the pool caps
concurrent inference (spec A4.7, A1.5) while the GIL-releasing run() keeps
decode moving. One session per tier is shared; sessions are thread-safe.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class InferencePool:
    """Run blocking inference calls on a bounded thread pool."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="infer"
        )

    async def run(self, fn: Callable[..., T], /, *args: object) -> T:
        """Await fn(*args) on the pool thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args))

    def close(self) -> None:
        """Stop accepting work; never called from inside a pool task."""
        self._executor.shutdown(wait=False, cancel_futures=True)
```

`backend/app/services/inference/detector.py`:

```python
"""ONNX Runtime implementation of the Detector protocol (spec A5.2, D17).

The factory `open_detector` is the single binding point: swapping to RT-DETR
means one new module + one new implementation here, nothing else changes.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from app.core.errors import InferenceError
from app.services.inference.pool import InferencePool
from app.services.inference.types import Detection, Detector, LetterboxMeta
from app.services.inference.yolox_post import decode
from app.services.stream.source import Frame

PAD_VALUE = 114


def letterbox(image: np.ndarray, input_size: int = 640) -> tuple[np.ndarray, LetterboxMeta]:
    """Aspect-preserving resize onto a square 114-padded canvas; RGB CHW float."""
    height, width = image.shape[:2]
    scale = min(input_size / width, input_size / height)
    new_w, new_h = int(width * scale), int(height * scale)
    resized = cv2.resize(image, (new_w, new_h))
    pad_x = (input_size - new_w) // 2
    pad_y = (input_size - new_h) // 2
    canvas = np.full((input_size, input_size, 3), PAD_VALUE, dtype=np.uint8)
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    tensor = canvas.transpose(2, 0, 1)[None].astype(np.float32)
    meta = LetterboxMeta(
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
        input_size=input_size,
        frame_width=width,
        frame_height=height,
    )
    return tensor, meta


class OnnxYoloXDetector:
    """One YOLOX ONNX session shared across camera pipelines."""

    def __init__(
        self,
        model_path: Path,
        *,
        input_size: int = 640,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        pool: InferencePool | None = None,
    ) -> None:
        self._model_path = model_path
        self._input_size = input_size
        self._conf_threshold = conf_threshold
        self._iou_threshold = iou_threshold
        self._pool = pool
        self._owns_pool = pool is None
        self._session: ort.InferenceSession | None = None

    def _get_session(self) -> ort.InferenceSession:
        if self._session is None:
            if not self._model_path.exists():
                raise InferenceError(
                    f"model weights missing: {self._model_path} - run backend/scripts/fetch_models.py"
                )
            self._session = ort.InferenceSession(
                str(self._model_path), providers=["CPUExecutionProvider"]
            )
        return self._session

    def _run_tensor(self, tensor: np.ndarray) -> np.ndarray:
        session = self._get_session()
        input_name = session.get_inputs()[0].name
        return session.run(None, {input_name: tensor})[0]

    async def infer(self, frame: Frame) -> list[Detection]:
        """Letterbox, run, decode; malformed output raises InferenceError."""
        tensor, meta = letterbox(frame.data, self._input_size)
        pool = self._pool or self._ensure_pool()
        raw = await pool.run(self._run_tensor, tensor)
        return decode(
            raw, meta, conf_threshold=self._conf_threshold, iou_threshold=self._iou_threshold
        )

    def _ensure_pool(self) -> InferencePool:
        if self._pool is None:
            self._pool = InferencePool()
        return self._pool

    async def close(self) -> None:
        """Drop the session and, if we created it, the pool. Idempotent."""
        self._session = None
        if self._owns_pool and self._pool is not None:
            self._pool.close()
            self._pool = None


def open_detector(
    model_path: Path, *, input_size: int = 640, pool: InferencePool | None = None
) -> Detector:
    """Build a Detector, failing early when weights have not been fetched."""
    if not model_path.exists():
        raise InferenceError(
            f"model weights missing: {model_path} - run backend/scripts/fetch_models.py"
        )
    return OnnxYoloXDetector(model_path, input_size=input_size, pool=pool)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_pool.py backend/tests/test_detector.py -v`
Expected: `test_real_model_detects_a_person_in_gate_clip` PASSES if assets were fetched in 3.1 (it should: frame 60 measured confidence 0.907), others pass; suite green.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `feat(infrastructure): letterboxed onnx detector behind a bounded pool`
Body: one session per tier shared across cameras, bounded submits so eight cameras cannot oversubscribe the box; malformed output raises before any rule sees it.

---

### Task 3.4: Hardware tier detection

**Files:**
- Create: `backend/app/services/inference/tiers.py`
- Test: `backend/tests/test_tiers.py`

**Interfaces:**
- Produces: `Capabilities(cores, avx2, vnni)`, `probe_capabilities() -> Capabilities` (never raises; degrades to conservative), `tier_for(caps) -> str` in `{"high", "medium", "low"}`, `TIER_SPECS` mapping tier → `(model_file, input_size)`, `resolve_tier(caps=None) -> tuple[str, Path, int]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tiers.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_tiers.py -v`
Expected: FAIL — `No module named 'app.services.inference.tiers'`

- [ ] **Step 3: Write the module**

`backend/app/services/inference/tiers.py`:

```python
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
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
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
    return resolved, MODELS_DIR / model_file, input_size
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_tiers.py -v`
Expected: 9 passed

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `feat(inference): detect hardware tier at startup and degrade to the floor`
Body: the N100 must land on nano without anyone configuring it; probe failure degrades instead of crashing because an unidentified CPU still has to run detection.

---

### Task 3.5: IoU tracker

**Files:**
- Create: `backend/app/services/inference/tracker.py`
- Test: `backend/tests/test_tracker.py`

**Interfaces:**
- Consumes: `Detection` (Task 3.2).
- Produces: `TrackedObject(track_id, class_name, confidence, bbox, centroid)` where `centroid: tuple[float, float]` is **normalised 0..1**; `Tracker(iou_threshold=0.3, max_misses=5)` with `update(detections, *, frame_width, frame_height) -> list[TrackedObject]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tracker.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_tracker.py -v`
Expected: FAIL — `No module named 'app.services.inference.tracker'`

- [ ] **Step 3: Write the tracker**

`backend/app/services/inference/tracker.py`:

```python
"""Greedy IoU tracker, written for this project (spec A5.4).

No BYTETracker copy — the licensing chain stays clean and the dependency
count stays zero. Identity exists to suppress duplicate alerts: the cooldown
key is (rule, track), so ids must be stable but do not need to survive a
process restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.inference.types import Detection


@dataclass(frozen=True, slots=True)
class TrackedObject:
    """One live track handed to the rules engine."""

    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]  # normalised 0..1 against the frame


@dataclass(slots=True)
class _Track:
    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]
    misses: int = 0


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter) if inter else 0.0


class Tracker:
    """Assign stable track ids by greedy same-class IoU matching."""

    def __init__(self, *, iou_threshold: float = 0.3, max_misses: int = 5) -> None:
        self._iou_threshold = iou_threshold
        self._max_misses = max_misses
        self._tracks: list[_Track] = []
        self._next_id = 1

    def update(
        self, detections: list[Detection], *, frame_width: int, frame_height: int
    ) -> list[TrackedObject]:
        """Match detections to live tracks; return tracks seen this frame."""
        unmatched = list(detections)
        matched_tracks: list[_Track] = []
        for track in list(self._tracks):
            best: Detection | None = None
            best_iou = self._iou_threshold
            for candidate in unmatched:
                if candidate.class_name != track.class_name:
                    continue
                score = _iou(track.bbox, candidate.bbox)
                if score >= best_iou:
                    best, best_iou = candidate, score
            if best is not None:
                unmatched.remove(best)
                track.bbox = best.bbox
                track.confidence = best.confidence
                track.misses = 0
                matched_tracks.append(track)
            else:
                track.misses += 1
        self._tracks = [t for t in self._tracks if t.misses < self._max_misses]
        for candidate in unmatched:
            track = _Track(
                track_id=self._next_id,
                class_name=candidate.class_name,
                confidence=candidate.confidence,
                bbox=candidate.bbox,
            )
            self._next_id += 1
            self._tracks.append(track)
            matched_tracks.append(track)
        live = {id(t) for t in matched_tracks}
        return [
            TrackedObject(
                track_id=t.track_id,
                class_name=t.class_name,
                confidence=t.confidence,
                bbox=t.bbox,
                centroid=_centroid(t.bbox, frame_width, frame_height),
            )
            for t in self._tracks
            if id(t) in live
        ]


def _centroid(
    bbox: tuple[int, int, int, int], frame_width: int, frame_height: int
) -> tuple[float, float]:
    """Normalised bbox midpoint — resolution-independent for ROI checks."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2 / frame_width, (y1 + y2) / 2 / frame_height)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_tracker.py -v`
Expected: 6 passed. (If `test_two_boxes_get_distinct_ids` ordering matters, sort ids before asserting.)

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `feat(inference): iou tracker with stable ids for cooldown keys`
Body: cooldown is per rule per track — without identity every frame looks like a first sighting and a shop owner gets spammed; written here rather than copied so the licence chain stays clean.

---

### Task 3.6: ROI geometry

**Files:**
- Create: `backend/app/services/alerts/__init__.py`
- Create: `backend/app/services/alerts/roi.py`
- Test: `backend/tests/test_roi.py`

**Interfaces:**
- Produces: `point_in_polygon(point, points) -> bool` (edge-inclusive), `normalised_centroid(bbox, frame_width, frame_height) -> tuple[float, float]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_roi.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_roi.py -v`
Expected: FAIL — `No module named 'app.services.alerts'`

- [ ] **Step 3: Write the module**

`backend/app/services/alerts/__init__.py`:

```python
"""Alert-side logic: ROI geometry, the pure rules engine, the alert stage."""

from __future__ import annotations

from app.services.alerts.roi import normalised_centroid, point_in_polygon
from app.services.alerts.rules import (
    ActiveHours,
    RoiConfig,
    RuleCheck,
    RuleConfig,
    RuleOutcome,
    RulesEngine,
    Window,
    parse_active_hours,
)
from app.services.alerts.stage import Alert, AlertStage

__all__ = [
    "ActiveHours",
    "Alert",
    "AlertStage",
    "RoiConfig",
    "RuleCheck",
    "RuleConfig",
    "RuleOutcome",
    "RulesEngine",
    "Window",
    "normalised_centroid",
    "parse_active_hours",
    "point_in_polygon",
]
```

> Import order note: `alerts/__init__.py` imports `stage`, which does not exist until Task 3.8. Create the `__init__.py` in Task 3.6 with **only the roi import** (`from app.services.alerts.roi import normalised_centroid, point_in_polygon` and `__all__` limited to those two), then extend it in Task 3.8 with the rules/stage exports shown above. Tests import `app.services.alerts.roi` directly either way.

`backend/app/services/alerts/roi.py`:

```python
"""ROI tests on normalised coordinates (DATABASE A4.5, spec A12).

Absolute pixels fail quietly on a resolution change; everything here works in
0..1 space so an ROI drawn at 1080p still means the same wall at 720p.
Containment is edge-inclusive: a centroid exactly on the boundary counts.
"""

from __future__ import annotations

from collections.abc import Sequence

_EPS = 1e-9


def _on_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> bool:
    """True when (px, py) lies on segment a-b within EPS."""
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > _EPS:
        return False
    return (
        min(ax, bx) - _EPS <= px <= max(ax, bx) + _EPS
        and min(ay, by) - _EPS <= py <= max(ay, by) + _EPS
    )


def point_in_polygon(
    point: tuple[float, float], points: Sequence[tuple[float, float]]
) -> bool:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_roi.py -v`
Expected: 5 passed

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `feat(rules): edge-inclusive roi geometry in normalised coordinates`
Body: on-edge counts as inside because the alternative turns a correctly drawn loading-dock ROI into a stream of misses; normalised so a resolution change cannot move the wall.

---

### Task 3.7: The pure rules engine

**Files:**
- Create: `backend/app/services/alerts/rules.py`
- Test: `backend/tests/test_rules.py`

**Interfaces:**
- Consumes: `TrackedObject` (Task 3.5), `point_in_polygon` (Task 3.6).
- Produces: `RuleConfig(rule_id, name, severity, classes, confidence_threshold, cooldown_seconds, active_hours, roi, last_fired_at)`, `ActiveHours(timezone, windows)`, `Window(start, end)`, `RoiConfig(name, points)`, `RuleCheck(condition, passed, detail)`, `RuleOutcome(fired, checks)`, `RulesEngine.evaluate(track, config, now) -> RuleOutcome` (**pure**), `parse_active_hours(raw)`, `with_cooldown(config, last_fired_at)`.
- Condition names, fixed by `API.md`: `class_in_allowlist`, `confidence`, `in_roi`, `active_hours`, `cooldown`.

- [ ] **Step 1: Write the failing table-driven tests**

`backend/tests/test_rules.py`:

```python
"""Table-driven rules: every branch, timezone edges, midnight wrap (spec A5.5).

Purity is the test surface: `now` is always injected, so 02:30 is a row in a
table instead of a flaky clock. This file is the false-positive battleground.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.services.alerts.rules import (
    ActiveHours,
    RoiConfig,
    RuleConfig,
    RulesEngine,
    Window,
    parse_active_hours,
)
from app.services.inference.tracker import TrackedObject

ENGINE = RulesEngine()
SQUARE_ROI = RoiConfig(
    name="Loading dock",
    points=((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)),
)


def track(
    cls: str = "person", conf: float = 0.7, centroid: tuple[float, float] = (0.5, 0.5)
) -> TrackedObject:
    return TrackedObject(
        track_id=1,
        class_name=cls,
        confidence=conf,
        bbox=(0, 0, 10, 10),
        centroid=centroid,
    )


def base_config(**overrides: object) -> RuleConfig:
    defaults: dict[str, object] = {
        "rule_id": 1,
        "name": "Back door",
        "severity": "warning",
        "classes": ("person",),
        "confidence_threshold": 0.55,
        "cooldown_seconds": 60,
        "active_hours": None,
        "roi": None,
        "last_fired_at": None,
    }
    defaults.update(overrides)
    return RuleConfig(**defaults)  # type: ignore[arg-type]


NOW = datetime(2026, 10, 6, 14, 32, tzinfo=ZoneInfo("Asia/Kolkata"))


def conditions(outcome) -> dict[str, bool]:
    return {c.condition: c.passed for c in outcome.checks}


def test_fires_when_everything_passes() -> None:
    outcome = ENGINE.evaluate(track(), base_config(), NOW)
    assert outcome.fired
    assert conditions(outcome) == {
        "class_in_allowlist": True,
        "confidence": True,
        "in_roi": True,
        "active_hours": True,
        "cooldown": True,
    }


def test_class_not_in_allowlist() -> None:
    outcome = ENGINE.evaluate(track(cls="car"), base_config(), NOW)
    assert not outcome.fired
    check = next(c for c in outcome.checks if c.condition == "class_in_allowlist")
    assert not check.passed
    assert check.detail == "'car' not in ['person']"


def test_confidence_detail_reads_like_the_api_example() -> None:
    outcome = ENGINE.evaluate(
        track(conf=0.71), base_config(confidence_threshold=0.55), NOW
    )
    check = next(c for c in outcome.checks if c.condition == "confidence")
    assert check.detail == "0.71 >= 0.55"
    failing = ENGINE.evaluate(
        track(conf=0.4), base_config(confidence_threshold=0.55), NOW
    )
    assert (
        next(c for c in failing.checks if c.condition == "confidence").detail
        == "0.40 < 0.55"
    )


def test_every_check_is_reported_even_when_one_fails() -> None:
    """API.md shows all five checks with mixed results — no short-circuit."""
    outcome = ENGINE.evaluate(
        track(centroid=(0.1, 0.1)), base_config(roi=SQUARE_ROI), NOW
    )
    assert not outcome.fired
    assert len(outcome.checks) == 5
    assert conditions(outcome)["in_roi"] is False
    assert conditions(outcome)["class_in_allowlist"] is True


def test_roi_detail_names_the_zone() -> None:
    inside = ENGINE.evaluate(track(), base_config(roi=SQUARE_ROI), NOW)
    assert "inside Loading dock" in next(
        c.detail for c in inside.checks if c.condition == "in_roi"
    )
    outside = ENGINE.evaluate(
        track(centroid=(0.1, 0.62)), base_config(roi=SQUARE_ROI), NOW
    )
    assert "outside Loading dock" in next(
        c.detail for c in outside.checks if c.condition == "in_roi"
    )


def test_no_roi_means_whole_frame() -> None:
    check = next(
        c
        for c in ENGINE.evaluate(track(centroid=(0.01, 0.01)), base_config(), NOW).checks
        if c.condition == "in_roi"
    )
    assert check.passed and "whole frame" in check.detail


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 6, 23, 0, tzinfo=ZoneInfo("Asia/Kolkata")), True),
        (datetime(2026, 10, 6, 3, 0, tzinfo=ZoneInfo("Asia/Kolkata")), True),
        (datetime(2026, 10, 6, 14, 32, tzinfo=ZoneInfo("Asia/Kolkata")), False),
        # 18:00 UTC is 23:30 IST -> within; a UTC-naive engine would say False.
        (datetime(2026, 10, 6, 18, 0, tzinfo=ZoneInfo("UTC")), True),
    ],
)
def test_active_hours_wrap_and_timezones(now, expected) -> None:
    hours = ActiveHours(timezone="Asia/Kolkata", windows=(Window(time(22, 0), time(6, 0)),))
    outcome = ENGINE.evaluate(track(), base_config(active_hours=hours), now)
    assert conditions(outcome)["active_hours"] is expected


def test_detail_reads_within_or_outside() -> None:
    hours = ActiveHours(timezone="UTC", windows=(Window(time(22, 0), time(6, 0)),))
    inside = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 10, 6, 23, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert "within" in next(
        c.detail for c in inside.checks if c.condition == "active_hours"
    )
    outside = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert "outside" in next(
        c.detail for c in outside.checks if c.condition == "active_hours"
    )


def test_utc_1630_is_2200_next_day_in_kolkata() -> None:
    """The shop closes at 22:00 IST, not 22:00 UTC (spec A12 timezone row)."""
    hours = ActiveHours(timezone="Asia/Kolkata", windows=(Window(time(22, 0), time(6, 0)),))
    now = datetime(2026, 10, 6, 16, 30, tzinfo=ZoneInfo("UTC"))
    outcome = ENGINE.evaluate(track(), base_config(active_hours=hours), now)
    assert conditions(outcome)["active_hours"] is True


def test_multiple_windows_any_one_counts() -> None:
    hours = ActiveHours(
        timezone="UTC",
        windows=(Window(time(6, 0), time(9, 0)), Window(time(17, 0), time(19, 0))),
    )
    morning = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC")),
    )
    midday = ENGINE.evaluate(
        track(),
        base_config(active_hours=hours),
        datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert conditions(morning)["active_hours"]
    assert not conditions(midday)["active_hours"]


def test_cooldown_suppresses_a_recent_firing() -> None:
    config = base_config(last_fired_at=NOW.replace(minute=31))
    outcome = ENGINE.evaluate(track(), config, NOW)
    assert not outcome.fired
    check = next(c for c in outcome.checks if c.condition == "cooldown")
    assert not check.passed
    assert "cooldown 60s" in check.detail


def test_cooldown_rearms_after_the_window() -> None:
    config = base_config(last_fired_at=NOW.replace(minute=30))
    assert ENGINE.evaluate(track(), config, NOW).fired


def test_no_previous_firing_passes_cooldown() -> None:
    check = next(
        c
        for c in ENGINE.evaluate(track(), base_config(), NOW).checks
        if c.condition == "cooldown"
    )
    assert check.passed and "no recent trigger" in check.detail


def test_engine_never_reads_the_clock() -> None:
    """Purity guard: a naive (tz-less) datetime must not crash the engine."""
    outcome = ENGINE.evaluate(track(), base_config(), datetime(2026, 10, 6, 14, 32))
    assert isinstance(outcome.fired, bool)


def test_parse_active_hours_reads_db_json() -> None:
    raw = {"timezone": "Asia/Kolkata", "windows": [{"start": "22:00", "end": "06:00"}]}
    hours = parse_active_hours(raw)
    assert hours is not None
    assert hours.windows[0].start == time(22, 0)
    assert parse_active_hours(None) is None
    assert parse_active_hours({"timezone": "UTC", "windows": []}) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_rules.py -v`
Expected: FAIL — `No module named 'app.services.alerts.rules'`

- [ ] **Step 3: Write the engine**

`backend/app/services/alerts/rules.py`:

```python
"""Pure rules engine (spec A5.5) — the highest-value test surface.

No IO, no clock reads, no side effects: `now` is injected so every false
positive class (hours boundaries, timezones, cooldown, ROI edges) is a table
row. `checks` exists because "rule did not fire" is unactionable —
POST /api/v1/rules/{id}/test returns them verbatim (API.md).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import cast
from zoneinfo import ZoneInfo

from app.services.alerts.roi import point_in_polygon
from app.services.inference.tracker import TrackedObject


@dataclass(frozen=True, slots=True)
class Window:
    """One active-hours window; end < start wraps past midnight."""

    start: time
    end: time


@dataclass(frozen=True, slots=True)
class ActiveHours:
    """When a rule is allowed to fire, in the camera's own timezone."""

    timezone: str
    windows: tuple[Window, ...]


@dataclass(frozen=True, slots=True)
class RoiConfig:
    """A named normalised polygon; None ROI means the whole frame."""

    name: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Everything evaluate() needs, projected from the rules row."""

    rule_id: int
    name: str
    severity: str
    classes: tuple[str, ...]
    confidence_threshold: float
    cooldown_seconds: int
    active_hours: ActiveHours | None
    roi: RoiConfig | None
    last_fired_at: datetime | None


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """One condition's verdict, ready for the debug endpoint."""

    condition: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """The verdict plus every per-condition reason (API.md A7.3)."""

    fired: bool
    checks: tuple[RuleCheck, ...]


def _parse_hhmm(raw: str) -> time:
    """Parse an HH:MM window edge; raises on malformed input at the edge."""
    hour_s, _, minute_s = raw.partition(":")
    return time(int(hour_s), int(minute_s))


def parse_active_hours(raw: dict[str, object] | None) -> ActiveHours | None:
    """Build ActiveHours from the rules.active_hours JSON column."""
    if not raw:
        return None
    timezone = str(raw.get("timezone") or "UTC")
    ZoneInfo(timezone)  # raises on a bad zone — validate at the edge
    entries = cast("list[dict[str, str]]", raw.get("windows") or [])
    windows = tuple(
        Window(start=_parse_hhmm(w["start"]), end=_parse_hhmm(w["end"])) for w in entries
    )
    if not windows:
        return None
    return ActiveHours(timezone=timezone, windows=windows)


def _in_window(now_local: time, window: Window) -> bool:
    if window.start <= window.end:
        return window.start <= now_local < window.end
    return now_local >= window.start or now_local < window.end


def _check_class(track: TrackedObject, config: RuleConfig) -> RuleCheck:
    passed = track.class_name in config.classes
    listing = list(config.classes)
    detail = (
        f"{track.class_name!r} in {listing!r}"
        if passed
        else f"{track.class_name!r} not in {listing!r}"
    )
    return RuleCheck("class_in_allowlist", passed, detail)


def _check_confidence(track: TrackedObject, config: RuleConfig) -> RuleCheck:
    passed = track.confidence >= config.confidence_threshold
    op = ">=" if passed else "<"
    detail = f"{track.confidence:.2f} {op} {config.confidence_threshold:.2f}"
    return RuleCheck("confidence", passed, detail)


def _check_roi(track: TrackedObject, config: RuleConfig) -> RuleCheck:
    if config.roi is None:
        return RuleCheck("in_roi", True, "no ROI configured - whole frame")
    cx, cy = track.centroid
    passed = point_in_polygon((cx, cy), config.roi.points)
    where = "inside" if passed else "outside"
    detail = f"centroid ({cx:.2f},{cy:.2f}) {where} {config.roi.name}"
    return RuleCheck("in_roi", passed, detail)


def _check_active_hours(now: datetime, config: RuleConfig) -> RuleCheck:
    if config.active_hours is None:
        return RuleCheck("active_hours", True, "no active hours configured")
    local = now.astimezone(ZoneInfo(config.active_hours.timezone))
    now_local = local.time()
    for window in config.active_hours.windows:
        if _in_window(now_local, window):
            detail = f"{now_local:%H:%M} within {window.start:%H:%M}-{window.end:%H:%M}"
            return RuleCheck("active_hours", True, detail)
    listed = ", ".join(
        f"{w.start:%H:%M}-{w.end:%H:%M}" for w in config.active_hours.windows
    )
    return RuleCheck("active_hours", False, f"{now_local:%H:%M} is outside {listed}")


def _check_cooldown(now: datetime, config: RuleConfig) -> RuleCheck:
    if config.last_fired_at is None:
        return RuleCheck("cooldown", True, "no recent trigger on this track")
    elapsed = (now - config.last_fired_at).total_seconds()
    if elapsed > config.cooldown_seconds:
        return RuleCheck("cooldown", True, "cooldown expired")
    return RuleCheck(
        "cooldown",
        False,
        f"last trigger {int(elapsed)}s ago, cooldown {config.cooldown_seconds}s",
    )


class RulesEngine:
    """Evaluate one track against one rule. Pure (spec A5.5)."""

    def evaluate(
        self, track: TrackedObject, config: RuleConfig, now: datetime
    ) -> RuleOutcome:
        """Return every condition's verdict; fired iff all pass.

        Args:
            track: The tracked object under test.
            config: Projected rule, including caller-held cooldown state.
            now: Injected awareness — the engine never reads the clock.

        Returns:
            RuleOutcome with five checks in API.md's documented order.
        """
        checks = (
            _check_class(track, config),
            _check_confidence(track, config),
            _check_roi(track, config),
            _check_active_hours(now, config),
            _check_cooldown(now, config),
        )
        return RuleOutcome(fired=all(c.passed for c in checks), checks=checks)


def with_cooldown(config: RuleConfig, last_fired_at: datetime | None) -> RuleConfig:
    """Copy config with fresh cooldown state (callers hold the map)."""
    return replace(config, last_fired_at=last_fired_at)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_rules.py -v`
Expected: all passed. `test_engine_never_reads_the_clock` uses the no-hours path, so no tz conversion happens with a naive datetime.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `feat(rules): pure rules engine with per-condition debug checks`
Body: purity is what makes 02:30, IST, and the midnight wrap testable rows instead of timing flukes; every check is reported because a bare "didn't fire" cannot tell a shop owner whether to widen the ROI or accept the hour.

---

### Task 3.8: AlertStage + per-camera sinks

**Files:**
- Create: `backend/app/services/alerts/stage.py`
- Modify: `backend/app/services/stream/stream_manager.py` (`add_camera` gains `sink=None`)
- Test: `backend/tests/test_alert_stage.py`
- Test: `backend/tests/test_stream_manager.py` (one new row)

**Interfaces:**
- Consumes: `Detector` (3.3), `Tracker` (3.5), `RulesEngine`/`RuleConfig`/`with_cooldown` (3.7), `FrameSink` from `pipeline.py`.
- Produces: `Alert(rule_id, rule_name, severity, track_id, class_name, confidence, zone, fired_at, summary)`, `AlertSink = Callable[[Alert], Awaitable[None]]`, `AlertStage(detector, rules, on_alert, ...)` implementing `async __call__(frame: Frame) -> None`; `StreamManager.add_camera(config, *, sink: FrameSink | None = None)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_alert_stage.py`:

```python
"""Clip -> detect -> track -> rules -> one alert, through the sink seam."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np

from app.services.alerts.rules import ActiveHours, RuleConfig, Window
from app.services.alerts.stage import Alert, AlertStage
from app.services.inference.types import Detection
from app.services.stream.source import Frame


class FakeDetector:
    """Scripted detections: person visible from call `visible_from` onward."""

    def __init__(self, visible_from: int = 0) -> None:
        self.calls = 0
        self.visible_from = visible_from

    async def infer(self, frame: Frame) -> list[Detection]:
        index = self.calls
        self.calls += 1
        if index < self.visible_from:
            return []
        return [Detection(class_name="person", confidence=0.8, bbox=(10, 10, 50, 120))]

    async def close(self) -> None:
        return None


def rule(**overrides) -> RuleConfig:
    defaults = dict(
        rule_id=7,
        name="Back door",
        severity="critical",
        classes=("person",),
        confidence_threshold=0.55,
        cooldown_seconds=60,
        active_hours=None,
        roi=None,
        last_fired_at=None,
    )
    defaults.update(overrides)
    return RuleConfig(**defaults)  # type: ignore[arg-type]


def frame(index: int = 0) -> Frame:
    return Frame(
        data=np.zeros((432, 768, 3), dtype=np.uint8),
        timestamp=float(index) / 2.0,
        width=768,
        height=432,
    )


async def test_alert_fires_once_then_cooldown_silences() -> None:
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule()],
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    for _ in range(5):
        await stage(frame())
    assert len(alerts) == 1
    assert alerts[0].rule_id == 7
    assert alerts[0].class_name == "person"
    assert alerts[0].summary == "1 person in frame"


async def test_cooldown_rearms_on_a_later_pass() -> None:
    ticks = [
        datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 6, 12, 1, tzinfo=ZoneInfo("UTC")),
    ]
    it = iter(ticks)
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule()],
        on_alert=alerts.append,
        now_fn=lambda: next(it),
    )
    await stage(frame(0))
    await stage(frame(1))
    await stage(frame(2))
    assert len(alerts) == 2


async def test_non_matching_class_never_alerts() -> None:
    class CarDetector(FakeDetector):
        async def infer(self, frame: Frame) -> list[Detection]:
            self.calls += 1
            return [Detection(class_name="car", confidence=0.9, bbox=(1, 1, 9, 9))]

    alerts: list[Alert] = []
    stage = AlertStage(detector=CarDetector(), rules=[rule()], on_alert=alerts.append)
    await stage(frame())
    assert alerts == []


async def test_disabled_hours_suppress() -> None:
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[
            rule(
                active_hours=ActiveHours(
                    timezone="UTC", windows=(Window(time(22, 0), time(6, 0)),)
                )
            )
        ],
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    await stage(frame())
    assert alerts == []


async def test_multiple_rules_each_get_their_own_cooldown() -> None:
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule(rule_id=1, severity="info"), rule(rule_id=2, severity="critical")],
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    await stage(frame())
    assert sorted(a.rule_id for a in alerts) == [1, 2]
    await stage(frame(1))
    assert len(alerts) == 2, "per-rule cooldowns are independent"
```

New row in `backend/tests/test_stream_manager.py`, modelled on `test_add_remove_status_all`'s local factory (uses imports the file already has: `time`, `threading`, `Path`, `FileSource`, `CameraConfig`, `FrameSource`, `Frame`, `StreamManager`):

```python
def test_per_camera_sink_overrides_the_default(clip_path: Path) -> None:
    """Phase 3 attaches one AlertStage per camera without eroding the seam."""
    default_hits = threading.Event()
    special_hits = threading.Event()

    def make_source(_config: CameraConfig) -> FrameSource:
        return FileSource(clip_path, loop=True)

    async def default_sink(_frame: Frame) -> None:
        default_hits.set()

    async def special_sink(_frame: Frame) -> None:
        special_hits.set()

    manager = StreamManager(make_source, default_sink)
    try:
        manager.add_camera(CameraConfig("a", "A", "file://one.mp4", sample_fps=5.0))
        manager.add_camera(
            CameraConfig("b", "B", "file://two.mp4", sample_fps=5.0), sink=special_sink
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not special_hits.is_set():
            time.sleep(0.05)
        assert special_hits.is_set(), "the override sink must receive frames"
    finally:
        manager.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_alert_stage.py backend/tests/test_stream_manager.py -v`
Expected: FAIL — `No module named 'app.services.alerts.stage'`; stream row fails because `add_camera` does not accept `sink`.

- [ ] **Step 3: Write the stage and the manager change**

`backend/app/services/alerts/stage.py`:

```python
"""The alert stage: one FrameSink that turns motion frames into fired alerts.

Detection and alerting stay separate concerns (spec A4.8): this stage never
filters classes before the engine and never persists — Phase 5 owns events,
clips, and notifiers. Cooldown state lives here, keyed (rule, track), because
the engine itself must stay pure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.alerts.rules import RuleConfig, RulesEngine, with_cooldown
from app.services.inference.tracker import Tracker
from app.services.inference.types import Detector
from app.services.stream.source import Frame


@dataclass(frozen=True, slots=True)
class Alert:
    """A fired rule, ready for Phase 5 to persist and deliver."""

    rule_id: int
    rule_name: str
    severity: str
    track_id: int
    class_name: str
    confidence: float
    zone: str | None
    fired_at: datetime
    summary: str


AlertSink = Callable[[Alert], Awaitable[None]]


class AlertStage:
    """Implement the FrameSink seam: detect, track, evaluate, fire."""

    def __init__(
        self,
        *,
        detector: Detector,
        rules: Sequence[RuleConfig],
        on_alert: AlertSink,
        engine: RulesEngine | None = None,
        tracker: Tracker | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._detector = detector
        self._rules = list(rules)
        self._on_alert = on_alert
        self._engine = engine or RulesEngine()
        self._tracker = tracker or Tracker()
        self._now = now_fn or (lambda: datetime.now(tz=ZoneInfo("UTC")))
        self._last_fired: dict[tuple[int, int], datetime] = {}

    async def __call__(self, frame: Frame) -> None:
        """Run one sampled frame through the whole chain (spec A4.8)."""
        now = self._now()
        detections = await self._detector.infer(frame)
        tracks = self._tracker.update(
            detections, frame_width=frame.width, frame_height=frame.height
        )
        for track in tracks:
            for config in self._rules:
                key = (config.rule_id, track.track_id)
                candidate = with_cooldown(config, self._last_fired.get(key))
                outcome = self._engine.evaluate(track, candidate, now)
                if not outcome.fired:
                    continue
                self._last_fired[key] = now
                zone = config.roi.name if config.roi else None
                where = zone or "frame"
                await self._on_alert(
                    Alert(
                        rule_id=config.rule_id,
                        rule_name=config.name,
                        severity=config.severity,
                        track_id=track.track_id,
                        class_name=track.class_name,
                        confidence=track.confidence,
                        zone=zone,
                        fired_at=now,
                        summary=f"1 {track.class_name} in {where}",
                    )
                )
```

`backend/app/services/stream/stream_manager.py` — change `add_camera`:

```python
    def add_camera(self, config: CameraConfig, *, sink: FrameSink | None = None) -> None:
        """Start a pipeline for ``config`` on a fresh thread+loop.

        Args:
            config: Camera settings for the new pipeline.
            sink: Per-camera override; falls back to the manager-wide sink.
                Phase 3 passes one AlertStage per camera through this slot.

        Raises:
            ValueError: If the camera is already running.
        """
        with self._lock:
            if config.camera_id in self._workers:
                raise ValueError(f"camera {config.camera_id} is already running")
            worker = _CameraWorker(config.camera_id)
            source = self._factory(config)
            worker.pipeline = CameraPipeline(config, source, sink or self._sink)
            worker.thread.start()
            worker.future = asyncio.run_coroutine_threadsafe(
                worker.pipeline.run(), worker.loop
            )
            worker.future.add_done_callback(
                lambda fut: self._on_done(config.camera_id, worker, fut)
            )
            self._workers[config.camera_id] = worker
```

(Match the file's existing docstring/structure exactly — this snippet shows the one-line behaviour change: `sink or self._sink`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_alert_stage.py backend/tests/test_stream_manager.py -v`
Expected: all passed. `test_stream_manager.py` includes rtsp canaries — run `-m "not rtsp"` if MediaMTX is not running; never let them silently pass.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit 1: `feat(rules): alert stage composes detector, tracker, and engine behind FrameSink`
Body: one sink keeps CameraPipeline untouched (spec A4 seam); cooldown state lives in the stage so the engine stays pure.
Commit 2: `feat(stream): per-camera sink override on add_camera`
Body: eight cameras need eight rule sets without turning StreamManager into a rules loader — the override is the smallest seam that delivers it.

---

### Task 3.9: Motion-to-alert latency test

**Files:**
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `CameraPipeline`, `MotionGate`, `FileSource` (Phase 1), `AlertStage` + `RuleConfig` (Task 3.8), `clip_path` fixture.
- Produces: `test_pipeline.py::test_motion_to_alert_under_2s` — the exact name the spec binds to its `<2s` matrix row (spec §11: `test_pipeline.py::test_motion_to_alert_under_2s | 3`).

- [ ] **Step 1: Write the failing test**

Add to `test_pipeline.py`'s top-level import block: `from app.services.alerts.rules import RuleConfig`, `from app.services.alerts.stage import Alert, AlertStage`, `from app.services.inference.types import Detection` (everything else — `asyncio`, `time`, `Path`, `FileSource`, `Frame`, `CameraConfig`, `CameraPipeline` — is already imported).

Append:

```python
async def test_motion_to_alert_under_2s(clip_path: Path) -> None:
    """Motion clip -> gate -> sample -> detect -> rules -> alert, under 2s.

    The plumbing leg of the spec §11 latency row: a scripted detector stands
    in for inference (its cost is proven separately by the slow real-clip
    gate), so this measures motion gate + sampling + stage + engine as one
    number that runs in the default suite.
    """

    class InstantDetector:
        async def infer(self, frame: Frame) -> list[Detection]:
            return [Detection(class_name="person", confidence=0.9, bbox=(10, 10, 60, 140))]

        async def close(self) -> None:
            return None

    alerts: list[Alert] = []
    fired_at: list[float] = []

    async def record(alert: Alert) -> None:
        alerts.append(alert)
        fired_at.append(time.monotonic())

    stage = AlertStage(
        detector=InstantDetector(),
        rules=[
            RuleConfig(
                rule_id=1,
                name="anything",
                severity="warning",
                classes=("person",),
                confidence_threshold=0.55,
                cooldown_seconds=0,
                active_hours=None,
                roi=None,
                last_fired_at=None,
            )
        ],
        on_alert=record,
    )
    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", str(clip_path), sample_fps=5.0),
        FileSource(clip_path),
        stage,
    )
    started = time.monotonic()
    task = asyncio.create_task(pipeline.run())
    deadline = started + 3.0
    while not alerts and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert alerts, "no alert fired from a clip full of motion"
    latency = fired_at[0] - started
    assert latency < 2.0, f"first alert took {latency:.2f}s (budget 2s)"
```

Notes: `FileSource` decodes unpaced, so the whole clip can land inside the first sample window — the first gate-passing frame sends immediately (`_last_send_at` starts at `0.0`), which is why a 2s budget holds even on a loaded machine. `cooldown_seconds=0` lets every qualifying sample fire; only the first timestamp matters.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_pipeline.py::test_motion_to_alert_under_2s -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.alerts'` (written in sequence after 3.6–3.8, so it may instead be red-on-assert; either way it must go green only through the real chain).

- [ ] **Step 3: Watch it fail for the right reason, then pass**

Run again after confirming the failure is import/assert (not a typo): same command → green.
If it fails on latency, check that the MotionGate opens (first motion frame sends immediately because `_last_send_at` starts at `0.0`).

- [ ] **Step 4: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `test(stream): motion-to-alert latency budget under two seconds`
Body: the spec pins this row to test_pipeline.py by name; scripted detection isolates the plumbing budget so the slow real-clip gate can own the inference budget.

---

### Task 3.10: Rules test endpoint (event replay)

**Files:**
- Create: `backend/app/services/alerts/replay.py`
- Modify: `backend/app/api/schemas.py` (`RuleCheckOut`, `RuleTestOut`, `RuleTestRequest`)
- Modify: `backend/app/api/routers/rules.py` (replace the `RuleOut` stub)
- Modify: `docs/API.md` (request body + frame-size note under `POST /api/v1/rules/{id}/test`)
- Test: `backend/tests/test_api_rules.py` (replace `test_test_endpoint_returns_rule`, add rows)

**Interfaces:**
- Consumes: `EventRepository.list/.get/.detections` (exists), `RoiRepository`, `CameraRepository`, `RulesEngine`/`parse_active_hours`/`RoiConfig` (Task 3.7), `normalised_centroid` (Task 3.6), `TrackedObject` (Task 3.5), `ValidationError`/`NotFoundError` (exists).
- Produces: `RuleTestRequest(event_id: int | None)`, `RuleCheckOut(condition, passed, detail)`, `RuleTestOut(rule_id, fired, checks)` (exactly API.md's documented response), `POST /api/v1/rules/{id}/test` → 200 `RuleTestOut`.
- Replay semantics: body `event_id` selects a specific event; omitted → most recent event on the rule's camera. Each `EventDetection` becomes a `TrackedObject` (bbox pixels → normalised centroid via camera `frame_width/height`). Engine runs once per detection with `now = event.started_at` (UTC); the returned `checks` are those of the candidate with the most passing checks, tie-broken by confidence; `fired` is true iff that candidate passed all five. `cooldown` evaluates as "no recent trigger" (replay has no firing history). Disabled rules still replay — this is a diagnostic, not a firing path.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api_rules.py`: add `Camera`, `Event`, `EventDetection` to the existing `from app.db.models import Rule, Site` line, then **replace** `test_test_endpoint_returns_rule` (lines 235–242) with the helper + rows below.

```python
def _seed_detection_event(
    db: Session, site_id: int, camera_id: int, *, confidence: float = 0.71
) -> Event:
    """Event + one person detection at a known pixel bbox (no create API until Phase 4)."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC, as _seed_event does
    event = Event(
        site_id=site_id,
        camera_id=camera_id,
        triggered_by="rule",
        started_at=now,
        severity="critical",
        summary="1 person in Loading dock",
    )
    db.add(event)
    db.flush()
    db.add(
        EventDetection(
            event_id=event.id,
            camera_id=camera_id,
            class_name="person",
            confidence=confidence,
            bbox=[100, 200, 300, 400],
            track_id=1,
            detected_at=now,
        )
    )
    db.commit()
    db.refresh(event)
    return event


def _set_frame_size(db: Session, camera_id: int) -> None:
    """Pixel bboxes need a frame size before they can be normalised."""
    camera = db.get(Camera, camera_id)
    assert camera is not None
    camera.frame_width, camera.frame_height = 768, 432
    db.commit()


def test_rule_test_returns_api_shaped_checks(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """API.md's documented response, down to the condition order."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _set_frame_size(db_session, cid)
    _seed_detection_event(db_session, site.id, cid)

    resp = client.post(f"/api/v1/rules/{rule['id']}/test", json={}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rule_id"] == rule["id"]
    assert body["fired"] is True
    assert [c["condition"] for c in body["checks"]] == [
        "class_in_allowlist",
        "confidence",
        "in_roi",
        "active_hours",
        "cooldown",
    ]
    assert all(isinstance(c["passed"], bool) and c["detail"] for c in body["checks"])
    # person 0.71 >= 0.55, no ROI -> whole frame, no hours, no cooldown history.
    roi_check = next(c for c in body["checks"] if c["condition"] == "in_roi")
    assert "whole frame" in roi_check["detail"]


def test_rule_test_replays_a_supplied_event_id(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _set_frame_size(db_session, cid)
    event = _seed_detection_event(db_session, site.id, cid)

    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test",
        json={"event_id": event.id},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fired"] is True


def test_rule_test_unknown_event_id_is_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test", json={"event_id": 999999}, headers=admin_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_rule_test_event_on_another_camera_is_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """A replayed event must belong to the rule's own camera."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    other_cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    event = _seed_detection_event(db_session, site.id, other_cid)

    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test",
        json={"event_id": event.id},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_rule_test_404s_with_no_event_to_replay(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    resp = client.post(f"/api/v1/rules/{rule['id']}/test", json={}, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_rule_test_422_when_frame_size_unknown(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """No frame size means no ROI interpretation — a loud 422, not a pass."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _seed_detection_event(db_session, site.id, cid)  # camera dims intentionally NULL

    resp = client.post(f"/api/v1/rules/{rule['id']}/test", json={}, headers=admin_headers)
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "frame size" in body["message"]


def test_rule_test_cross_tenant_event_is_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _set_frame_size(db_session, cid)
    event = _seed_detection_event(db_session, site.id, cid)
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    event.site_id = other.id
    db_session.commit()
    db_session.expire_all()

    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test",
        json={"event_id": event.id},
        headers=admin_headers,
    )
    assert resp.status_code == 404
```

Notes: `seeded` returns `tuple[Site, User, User]`; the `client` fixture shares `db_session`, so direct row edits are visible to API calls after `expire_all()` (mirror `test_cross_tenant_returns_404`). The envelope's `field` slot is always `null` in Phase 2's handler — assert on `message`, not `field` (populating `field` is a future error-handler change, out of scope here).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_api_rules.py -v -k test_rule_test or test_test_endpoint`
Expected: FAIL — response shape still `RuleOut` (no `checks`), 404/422 rows fail.

- [ ] **Step 3: Write schemas, replay service, and the route**

`backend/app/api/schemas.py` (next to `RuleOut`):

```python
class RuleCheckOut(BaseModel):
    """One condition verdict (API.md APOST /rules/{id}/test)."""

    condition: str
    passed: bool
    detail: str


class RuleTestOut(BaseModel):
    """Diagnostic replay response (API.md, spec A7.3)."""

    rule_id: int
    fired: bool
    checks: list[RuleCheckOut]


class RuleTestRequest(BaseModel):
    """Optional event selection; omit for the camera's most recent event."""

    event_id: int | None = None
```

`backend/app/services/alerts/replay.py`:

```python
"""Replay stored detections through the pure rules engine (spec A7.3).

The endpoint must never run a detector: a diagnostic uses what was already
recorded, so it stays fast, deterministic, and free of weights in API tests.
Pixel bboxes are normalised with the camera's stored frame size — without it
a normalised ROI cannot be interpreted, which is a 422, not a silent pass.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from app.core.errors import ValidationError
from app.db.models import Camera, Event, EventDetection, Roi, Rule
from app.services.alerts.roi import normalised_centroid
from app.services.alerts.rules import RoiConfig, RuleConfig, RulesEngine, parse_active_hours
from app.services.alerts.rules import RuleOutcome
from app.services.inference.tracker import TrackedObject


def rule_config(rule: Rule, roi: Roi | None) -> RuleConfig:
    """Project a rules row (+ joined ROI) into the engine's config."""
    return RuleConfig(
        rule_id=rule.id,
        name=rule.name,
        severity=rule.severity,
        classes=tuple(rule.classes),
        confidence_threshold=rule.confidence_threshold,
        cooldown_seconds=rule.cooldown_seconds,
        active_hours=parse_active_hours(rule.active_hours),
        roi=RoiConfig(name=roi.name, points=tuple((p[0], p[1]) for p in roi.points)) if roi else None,
        last_fired_at=None,
    )


def replay(
    engine: RulesEngine,
    config: RuleConfig,
    camera: Camera,
    detections: list[EventDetection],
    event: Event,
) -> RuleOutcome:
    """Evaluate every stored detection; return the strongest candidate's checks.

    Raises:
        ValidationError: When the camera has no frame size (422, field=camera)
            or the event carries no detections.
    """
    if camera.frame_width is None or camera.frame_height is None:
        raise ValidationError(
            "camera has no known frame size; run the camera once before testing rules",
            field="camera",
        )
    if not detections:
        raise ValidationError("event has no detections to replay", field="event_id")
    when = event.started_at if event.started_at.tzinfo else event.started_at.replace(tzinfo=UTC)
    outcomes: list[tuple[float, RuleOutcome]] = []
    for index, det in enumerate(detections, start=1):
        centroid = normalised_centroid(
            (int(det.bbox[0]), int(det.bbox[1]), int(det.bbox[2]), int(det.bbox[3])),
            camera.frame_width,
            camera.frame_height,
        )
        track = TrackedObject(
            track_id=det.track_id or index,
            class_name=det.class_name,
            confidence=det.confidence,
            bbox=(int(det.bbox[0]), int(det.bbox[1]), int(det.bbox[2]), int(det.bbox[3])),
            centroid=centroid,
        )
        outcomes.append((det.confidence, engine.evaluate(track, config, when)))
    # Most conditions passed wins; confidence breaks ties; fired (all five)
    # is always the maximum, so `fired` and the returned checks agree.
    _, best = max(outcomes, key=lambda pair: (sum(c.passed for c in pair[1].checks), pair[0]))
    return best
```

> Type note: `ValidationError` must accept a `field=` kwarg — verify the constructor in `app/core/errors.py`; if it does not, pass the field through whatever mechanism `ValidationError` already uses (the 422 envelope documents `field`), do not change the error class.

`backend/app/api/routers/rules.py` — replace the stub:

```python
@router.post("/rules/{rule_id}/test", response_model=RuleTestOut)
async def test_rule(
    rule_id: int,
    claims: AdminDep,
    db: DbSessionDep,
    body: RuleTestRequest | None = None,
) -> RuleTestOut:
    """Replay detections through the engine and return every condition."""
    rule = _repo(db, claims).get(rule_id)
    if rule is None:
        raise NotFoundError("rule not found")
    events = EventRepository(db, site_id=int(claims["site_id"]))
    event_id = body.event_id if body else None
    if event_id is not None:
        event = events.get(event_id)
        if event is None or event.camera_id != rule.camera_id:
            raise NotFoundError("event not found")
    else:
        found, _total = events.list(camera_id=rule.camera_id, limit=1)
        if not found:
            raise NotFoundError("no event to replay yet")
        event = found[0]
    camera = CameraRepository(db, site_id=int(claims["site_id"])).get(rule.camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    roi = RoiRepository(db, site_id=int(claims["site_id"])).get(rule.roi_id) if rule.roi_id else None
    outcome = replay(
        RulesEngine(),
        rule_config(rule, roi),
        camera,
        events.detections(event.id),
        event,
    )
    return RuleTestOut(
        rule_id=rule.id,
        fired=outcome.fired,
        checks=[
            RuleCheckOut(condition=c.condition, passed=c.passed, detail=c.detail)
            for c in outcome.checks
        ],
    )
```

Imports to add: `EventRepository`, `RuleCheckOut`, `RuleTestOut`, `RuleTestRequest`, `replay`, `rule_config`, `RulesEngine` (`CameraRepository`, `RoiRepository` are already imported). The defaulted `body` parameter goes last so the signature stays valid Python; FastAPI's DI order is unaffected.

`docs/API.md` — under `POST /api/v1/rules/{id}/test`, add the request body:

```json
{
  "event_id": 812
}
```

and the notes: omit `event_id` to replay the camera's most recent event; `404` when there is nothing to replay; `422 VALIDATION_ERROR` whose message names the frame size when the camera has never produced one (the envelope's `field` slot stays null — Phase 2's handler never populates it); evaluation runs at the event's `started_at` in UTC; cooldown always reports "no recent trigger" because replay carries no firing history; **still-image upload is not implemented in Phase 3** (JSON-only mutation rule blocks multipart; a base64 still would drag model weights into API tests) — tracked as a deviation for Phase 5.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_api_rules.py -v`
Expected: all passed, including the untouched CRUD rows (response model change touches one route).

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app; pytest backend/tests/test_api_system.py::test_openapi_matches_spec -v` (paths-only comparison — response model change must not trip it)
Commit: `feat(api): real rule diagnostics from stored event detections`
Body: the debug endpoint is the reason checks exist at all; replaying recorded detections keeps it deterministic and keeps model weights out of the API layer.

---

### Task 3.11: Real-clip gate (slow, real weights)

**Files:**
- Modify: `backend/tests/conftest.py` (add `gate_clip_path` fixture)
- Create: `backend/tests/test_gate_inference.py`

**Interfaces:**
- Consumes: `yolox_nano` weights + `gate.mp4` (Task 3.1 assets), `open_detector` (3.3), `AlertStage` (3.8), `FileSource`.
- Produces: `pytest.mark.slow` test proving matrix row 3 end-to-end: a real alert fires from a real clip, per-frame inference→alert under 2s.

- [ ] **Step 1: Write the failing test**

`backend/tests/conftest.py`:

```python
@pytest.fixture
def gate_clip_path() -> Path:
    """The real surveillance clip; skipped visibly when not fetched."""
    path = CLIPS_DIR / "gate.mp4"
    if not path.exists():
        pytest.skip("gate.mp4 missing - run backend/scripts/fetch_models.py --verify")
    return path
```

`backend/tests/test_gate_inference.py`:

```python
"""Matrix row 3: a real alert fires from a real clip, under 2s (spec A11).

Marked slow: it runs YOLOX-nano over every frame. The latency asserted is
per frame (feed -> alert), because the budget that can blow past 2s on an
N100 is one inference pass; the motion->alert plumbing budget without
inference is test_pipeline.py::test_motion_to_alert_under_2s.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.services.alerts.rules import RuleConfig
from app.services.alerts.stage import Alert, AlertStage
from app.services.inference.detector import open_detector
from app.services.stream.file_source import FileSource

pytestmark = pytest.mark.slow

MODEL = Path(__file__).resolve().parents[2] / "models" / "yolox_nano.onnx"


@pytest.mark.skipif(not MODEL.exists(), reason="yolox_nano.onnx missing - run fetch_models.py")
async def test_real_alert_from_real_clip_under_2s(gate_clip_path: Path) -> None:
    alerts: list[Alert] = []

    async def record(alert: Alert) -> None:
        alerts.append(alert)

    detector = open_detector(MODEL, input_size=416)
    stage = AlertStage(
        detector=detector,
        rules=[
            RuleConfig(
                rule_id=1,
                name="gate",
                severity="warning",
                classes=("person",),
                confidence_threshold=0.55,
                cooldown_seconds=0,
                active_hours=None,
                roi=None,
                last_fired_at=None,
            )
        ],
        on_alert=record,
    )
    source = FileSource(gate_clip_path, loop=False)
    worst = 0.0
    try:
        async for frame in source.frames():
            started = time.monotonic()
            await stage(frame)
            worst = max(worst, time.monotonic() - started)
            if alerts:
                break
    finally:
        await source.close()
        await detector.close()

    assert alerts, "no person alert from the gate clip (person is visible frames 15-75)"
    assert alerts[0].class_name == "person"
    assert alerts[0].summary.startswith("1 person")
    assert worst < 2.0, f"slowest detect+rules pass took {worst:.2f}s (budget 2s)"
```

Budget note: `worst` measures only the frames actually fed (up to and including the first alert), so a slow first decode cannot be mistaken for inference latency.

- [ ] **Step 2: Watch it fail**

Run: `pytest backend/tests/test_gate_inference.py -v -m slow --no-header -rs`
Expected: SKIP rows are fine if assets are not yet fetched — **fetch first** (Task 3.1 `python backend/scripts/fetch_models.py --verify`), then FAIL on red test (module absent) until 3.1–3.8 are done. When run in sequence this task comes last, so expected: **passed** with `worst < 2.0` printed via assertion only on breach.

- [ ] **Step 3: Verify green with visible skip path**

Temporarily rename `models/yolox_nano.onnx` → run → expect visible `skipreason`; restore. Never let the gate pass silently without weights.

- [ ] **Step 4: Static checks + commit**

Run: `ruff check backend; ruff format backend; mypy backend/app`
Commit: `test(inference): real-clip gate proves yolo alert under the 2s budget`
Body: the only test that touches all four layers with real weights; skip is loud because a silently skipped gate is a lie.

---

### Task 3.12: Full gate, ledger, living docs

**Files:**
- Modify: `docs/tasks.md` (tick Phase 3)
- Modify: `docs/API.md` (if any response/request drift remains from 3.10)
- Modify: `docs/superpowers/plans/phase-3-inference-rules.md` (execution ledger — record actual test counts and commits)

- [ ] **Step 1: Full local gate (one command at a time, never in parallel)**

1. `ruff check backend` → 0 findings
2. `ruff format --check backend` → clean
3. `mypy backend/app` → 0 errors
4. `python backend/scripts/fetch_models.py --verify` → green (manifest hashes match)
5. `git diff requirements.lock.txt` → exactly one added line, `tzdata==…` (Phase 3's only dependency, needed for `zoneinfo` on Windows)
6. `pytest -m "not rtsp and not slow" --ignore=backend/tests/rtsp` → all green; record count
7. `pytest -m slow` → gate test green; record `worst` value from a `-s` run if available
8. `pytest -m rtsp` (only if Docker/MediaMTX is up) → canaries pass or are visibly skipped with `-rs`
9. `git status --porcelain` → only intended files; `.tmp/` never staged

- [ ] **Step 2: Update living docs**

- `docs/tasks.md`: tick every Phase 3 checkbox that this plan delivered; leave Phase 5 items unticked.
- `docs/API.md`: confirm the `POST /rules/{id}/test` section matches the shipped contract (from 3.10).
- Execution ledger at the bottom of this plan: actual commit SHAs, test counts per suite, any deviation hit during execution.

- [ ] **Step 3: Commit the docs**

Commit: `docs(phase3): record gate evidence and tick phase 3 tasks`
Body: every matrix row has a named test; counts recorded so the next phase's gate has a baseline.

---

## Deviations (locked during planning)

| # | Deviation | Reason | Where |
|---|---|---|---|
| D1 | `POST /rules/{id}/test` replays **events only**; still-image upload not implemented | JSON-only mutation header blocks multipart; a base64 still drags weights into API tests; event detections carry everything the engine needs | API.md documents the event body + the deferral; Phase 5 candidate |
| D2 | `422 VALIDATION_ERROR` (message names the frame size) when `frame_width/height` is NULL | Nothing writes frame dims yet (Phase 5's stream→db bridge); silently guessing would misplace every ROI check. The envelope's `field` slot is always null in Phase 2's handler, so the tests assert on `message` | `replay.py` |
| D3 | YOLOX-vs-RT-DETR accuracy benchmark deferred (design D17 swap contract untouched) | Out of Phase 3 scope; nano/s/m weights are fetched so the benchmark can run later without rework | design D17 |
| D4 | `io_binding` session optimisation deferred | Correctness first; the bounded pool already caps concurrency; measurable before optimisable | Task 3.3 |
| D5 | Spec §4.7 tier rows overlap on the documented floor (4 cores + AVX2 + no VNNI); precedence resolves low < medium < high | The floor hardware (N100) must land on nano; overlap is in the spec text, so precedence is documented in `tiers.py` and here | Task 3.4 |
| D6 | `test_motion_to_alert_under_2s` uses a scripted detector; the real-weights leg is the slow gate | Keeps the spec-named row in the default suite; inference budget proven separately where weights are legal | Task 3.9 / 3.11 |

---

## Execution ledger (filled during Task 3.12)

| Gate step | Evidence | Result |
|---|---|---|
| `ruff check backend` / `ruff format --check backend` | command output | |
| `mypy backend/app` | command output | |
| `fetch_models.py --verify` | `ok` x 4 | |
| `requirements.lock.txt` diff is `+tzdata` only | `git diff requirements.lock.txt` | |
| default suite | `pytest -m "not rtsp and not slow" --ignore=backend/tests/rtsp` (count) | |
| slow gate | `pytest -m slow` (`worst` seconds) | |
| rtsp canaries | `pytest -m rtsp -rs` | |
| commits | task → SHA list | |
