"""Refuse to commit model weights, credentials, databases, or footage.

These are the Global Constraints of every commit, enforced rather than
remembered. Redaction in `app.core.logging` follows the same reasoning:
a rule that depends on discipline is a rule that will be broken at 3am.

Usage:
    python backend/scripts/check_forbidden_files.py [paths...]
With no arguments it reads `git diff --cached --name-only`.
Exit codes: 0 clean · 1 violation found
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from re import Pattern

FORBIDDEN: tuple[Pattern[str], ...] = (
    re.compile(r"\.onnx$", re.IGNORECASE),
    re.compile(r"\.(pt|pth|weights|engine)$", re.IGNORECASE),
    re.compile(r"(^|/)\.env(\.[^/]+)?$", re.IGNORECASE),
    re.compile(r"(^|/)master\.key$", re.IGNORECASE),
    re.compile(r"(^|/)cambrain\.db", re.IGNORECASE),
    re.compile(r"(^|/)node_modules/", re.IGNORECASE),
    re.compile(r"^frontend/dist/", re.IGNORECASE),
    re.compile(r"(^|/)clips/.+\.(mp4|mkv|avi|jpg|jpeg|png)$", re.IGNORECASE),
)

ALLOWED: tuple[Pattern[str], ...] = (
    re.compile(r"LICENSE-MODEL-NOTICE$"),
    re.compile(r"\.gitkeep$"),
)


def find_forbidden(paths: Iterable[str]) -> list[str]:
    """Return every path that must not be committed, one per line."""
    hits: list[str] = []
    for raw in paths:
        path = raw.replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        if not path:
            continue
        if any(allowed.search(path) for allowed in ALLOWED):
            continue
        if any(forbidden.search(path) for forbidden in FORBIDDEN):
            hits.append(path)
    return hits


def _staged_paths() -> list[str]:
    """Paths currently staged, as git reports them."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    """Check and report. Every hit, not just the first."""
    paths = argv[1:] or _staged_paths()
    hits = find_forbidden(paths)
    if not hits:
        return 0
    print("Refusing to commit files that must never be committed:", file=sys.stderr)
    for hit in hits:
        print(f"  - {hit}", file=sys.stderr)
    print(
        "\nWeights are fetched by scripts/fetch_model.py; clips and fixtures are "
        "generated; .env and master.key are machine-local.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
