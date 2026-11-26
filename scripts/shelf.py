"""Where the private specimen shelf lives, and the guard that keeps it private.

Screenshots, thumbnails, the catalog, progress state and draft notes live in a
separate PRIVATE repository (the "shelf"), checked out at OFFBRAND_SHELF_DIR
(default: ./shelf). Nothing from it may be written to this public repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def shelf_dir() -> Path:
    return Path(os.environ.get("OFFBRAND_SHELF_DIR") or ROOT / "shelf")


class Shelf:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.shots = self.base / "archive" / "shots"
        self.thumbs = self.base / "archive" / "thumbs"
        self.index = self.base / "data" / "archive.json"
        self.state = self.base / "data" / "archive_state.json"
        self.drafts = self.base / "data" / "archive_drafts.json"
        self.inspections = self.base / "data" / "archive_inspections.json"


def assert_private(repo: str, runner=None) -> None:
    """Exit unless `repo` ("owner/name") is reachable and private. Uses `gh api`."""
    if not repo or repo.count("/") != 1:
        raise SystemExit("Shelf repo is not configured: set the SHELF_REPO variable to owner/name.")
    run = runner or (lambda args: subprocess.run(args, capture_output=True, text=True))
    res = run(["gh", "api", f"repos/{repo}", "--jq", ".private"])
    if res.returncode != 0:
        raise SystemExit(f"Cannot read shelf repo {repo} (missing or token lacks access): "
                         f"{(res.stderr or '').strip()[:200]}")
    if (res.stdout or "").strip() != "true":
        raise SystemExit(f"Refusing to continue: shelf repo {repo} is NOT private.")


def assert_separate_checkout(base: Path, public_root: Path = ROOT) -> None:
    """The shelf must be its own git checkout, never a folder of the public repo."""
    base = Path(base).resolve()
    if not (base / ".git").exists():
        raise SystemExit(f"{base} is not a separate git checkout of the private shelf repo.")
    if base == Path(public_root).resolve():
        raise SystemExit("Shelf directory is the public repository; refusing.")


if __name__ == "__main__":
    if sys.argv[1:] == ["check-private"]:
        assert_private(os.environ.get("SHELF_REPO", ""))
        print("Shelf repo is private.")
    else:
        raise SystemExit("usage: shelf.py check-private")
