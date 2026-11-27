"""Stage the public site deterministically, with no network or private inputs."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from build_reading_edition import build

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("index.html", "methodology.html", "teletext.html", "studio.html", "reading.html")


def stage(output: Path, revision: str, *, fixture_reviews: dict | None = None) -> Path:
    """Use an empty directory; fixture_reviews is for isolated browser tests only."""
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,40}", revision):
        raise ValueError("Invalid revision token")
    output = output.resolve()
    if output == ROOT or output in ROOT.parents or any(
        output == ROOT / name or ROOT / name in output.parents
        for name in ("site", "data", "scripts", ".git", ".github", "tests", "docs", "shelf", "archive")
    ):
        raise ValueError("Refusing to stage inside source or private directories")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output must be a new or empty directory")
    source = ROOT / "site"
    if any(p.is_symlink() for p in source.rglob("*")) or source.is_symlink():
        raise ValueError("Public site tree must not contain symlinks")
    reviews = ROOT / "data" / "reviews.json"
    if reviews.is_symlink() or reviews.parent.is_symlink():
        raise ValueError("Public review file must not be a symlink")
    raw = reviews.read_bytes() if fixture_reviews is None else json.dumps(fixture_reviews).encode("utf-8")
    reading = build(json.loads(raw))
    shutil.copytree(source, output, dirs_exist_ok=True)
    (output / "data").mkdir()
    (output / "data" / "reviews.json").write_bytes(raw)
    (output / "reading.html").write_text(reading, encoding="utf-8")
    for name in PAGES:
        path = output / name
        html = path.read_text(encoding="utf-8")
        if "__BUILD__" not in html:
            raise ValueError(f"Missing build token in {name}")
        path.write_text(html.replace("__BUILD__", revision), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    stage(args.output, args.revision)


if __name__ == "__main__":
    main()
