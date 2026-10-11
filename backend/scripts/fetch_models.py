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
            verify(asset, partial)
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
