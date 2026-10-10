"""Fail the build if any dependency carries an AGPL obligation.

The product is sold closed-source. Any AGPL dependency reachable from the
shipped application obliges disclosure of the whole application's source,
which defeats the business model (spec §3).

Exporting AGPL weights to ONNX changes the file format. It does not change
the licence attached to the weights — that is exactly how copyleft gets
violated unknowingly. This gate is the last line of defence.

Usage:
    python backend/scripts/check_licences.py
Exit codes: 0 clean · 1 violation found · 2 could not determine
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_LOCK = REPO_ROOT / "frontend" / "package-lock.json"

DENIED_PACKAGES: frozenset[str] = frozenset(
    {
        "ultralytics",
        "ultralytics-thop",
    }
)

Record = tuple[str, str]


def _is_agpl(licence: str) -> bool:
    """Match AGPL specifically — never plain GPL or LGPL."""
    lowered = licence.lower()
    return "agpl" in lowered or "affero" in lowered


def find_agpl_violations(records: Iterable[Record]) -> list[str]:
    """Return one readable line per offending package."""
    violations: list[str] = []
    for name, licence in records:
        if not name:
            continue
        if name.lower() in DENIED_PACKAGES:
            violations.append(f"{name} ({licence or 'denied by name'})")
        elif _is_agpl(licence):
            violations.append(f"{name} ({licence})")
    return violations


def python_records() -> list[Record]:
    """Licence text for every installed distribution, from its own metadata."""
    records: list[Record] = []
    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        name = (meta.get("Name") or "").strip()
        expression = (meta.get("License-Expression") or "").strip()
        legacy = (meta.get("License") or "").strip()
        classifiers = " ".join(
            c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")
        )
        records.append((name, " ".join(x for x in (expression, legacy, classifiers) if x)))
    return records


def frontend_records(lock_path: Path = FRONTEND_LOCK) -> list[Record]:
    """Licence text for every locked npm package.

    A missing lock file while the manifest is present is a hard error, not an
    empty scan: silently scanning zero packages makes the gate a no-op and lets
    an AGPL dependency ship unnoticed. Exit code 2 = could not determine.
    """
    manifest = lock_path.parent / "package.json"
    if not lock_path.exists():
        if manifest.exists():
            print(
                f"ERROR: {manifest} exists but {lock_path} does not. "
                "Run `npm install --package-lock-only` in frontend/ and commit "
                "the lock file — without it the licence gate cannot see any "
                "npm dependency.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        return []
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    records: list[Record] = []
    for path, meta in data.get("packages", {}).items():
        if not path:
            continue
        name = path.split("node_modules/")[-1]
        licence = meta.get("license", "")
        if isinstance(licence, dict):
            licence = str(licence.get("type", ""))
        records.append((name, str(licence)))
    return records


def main() -> int:
    """Scan and report. Never warn — a warning nobody reads is not a gate."""
    records = python_records() + frontend_records()
    violations = find_agpl_violations(records)
    if violations:
        print("AGPL dependency detected — prohibited (spec §3):", file=sys.stderr)
        for line in violations:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"Licence scan clean ({len(records)} packages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
