"""Regression checks for the commercial-break feature and the page shell.

These run with the rest of the suite (pytest) and need no network.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
MANIFEST = SITE / "commercials" / "manifest.json"
INDEX = (SITE / "index.html").read_text(encoding="utf-8")

NAME = r"[a-z0-9][a-z0-9-]{0,63}"
SRC_RE = re.compile(rf"^commercials/{NAME}\.mp4$")
POSTER_RE = re.compile(rf"^commercials/{NAME}\.(?:jpg|png|webp)$")
MAX_VIDEO_BYTES = 25 * 1024 * 1024  # keep GitHub Pages light; GitHub refuses files over 100 MB

REQUESTED_BUMPERS = [
    "Unfortunately, we’ll be right back.",
    "The following advertisement is more trustworthy than our regularly scheduled programming.",
    "No credentials were harvested during the making of this commercial.",
    "Paid for by absolutely nobody.",
    "Broadcasting from somewhere we probably shouldn’t be.",
]


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_entries_are_well_formed(manifest):
    items = manifest["commercials"]
    assert items, "manifest lists no commercials"
    ids = [c["id"] for c in items]
    assert len(ids) == len(set(ids)), "duplicate commercial ids"
    for c in items:
        assert re.fullmatch(NAME, c["id"]), c["id"]
        assert c["title"].strip(), c["id"]
        assert SRC_RE.fullmatch(c["src"]), c["src"]
        if c.get("poster"):
            assert POSTER_RE.fullmatch(c["poster"]), c["poster"]
        assert 0 < c["runtime_seconds"] <= 600


def test_every_manifest_file_exists_and_is_small(manifest):
    for c in manifest["commercials"]:
        video = SITE / c["src"]
        assert video.is_file(), f"missing {c['src']}"
        assert video.stat().st_size <= MAX_VIDEO_BYTES, f"{c['src']} is too large for Pages"
        if c.get("poster"):
            assert (SITE / c["poster"]).is_file(), f"missing {c['poster']}"


def test_no_orphan_videos_ship(manifest):
    listed = {c["src"] for c in manifest["commercials"]}
    on_disk = {f"commercials/{p.name}" for p in (SITE / "commercials").glob("*.mp4")}
    assert on_disk <= listed, f"videos not in the manifest: {sorted(on_disk - listed)}"


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_runtimes_and_codecs_match_the_files(manifest):
    for c in manifest["commercials"]:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name",
             "-of", "json", str(SITE / c["src"])],
            capture_output=True, text=True, check=True,
        )
        info = json.loads(out.stdout)
        duration = float(info["format"]["duration"])
        assert abs(duration - c["runtime_seconds"]) <= 1, f"{c['id']}: file runs {duration:.1f}s"
        codecs = {s["codec_name"] for s in info["streams"]}
        # H.264 + AAC plays in every current browser, including iPhone Safari.
        assert "h264" in codecs, f"{c['id']}: video must be H.264"
        assert codecs <= {"h264", "aac"}, f"{c['id']}: unexpected streams {codecs}"


def test_bumpers_include_the_requested_lines_and_do_not_repeat(manifest):
    bumpers = manifest["bumpers"]
    assert len(bumpers) == len(set(bumpers))
    for line in REQUESTED_BUMPERS:
        assert line in bumpers


def test_csp_stays_strict():
    csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', INDEX).group(1)
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";") if d.strip())
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert directives["media-src"] == "'self'"
    assert directives["img-src"] == "'self' https://urlscan.io"
    assert "frame-src" not in directives and "child-src" not in directives
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_page_shell_keeps_tagline_favicon_and_scripts():
    assert "The internet’s knockoff aisle. Real phishing sites reviewed by me GnomeMan4201" in INDEX
    for href in ("favicon.svg", "favicon-32.png", "apple-touch-icon.png"):
        assert f'href="{href}"' in INDEX
        assert (SITE / href).is_file()
    # breaks.js must load before app.js, both cache-busted by deploy.yml
    assert INDEX.index('src="breaks.js?v=__BUILD__"') < INDEX.index('src="app.js?v=__BUILD__"')
    assert "<style" not in INDEX and " style=" not in INDEX  # CSP forbids inline styles


def test_app_never_injects_html():
    for name in ("app.js", "breaks.js"):
        src = (SITE / name).read_text(encoding="utf-8")
        assert "innerHTML" not in src and "insertAdjacentHTML" not in src, name
        # Breaks start muted from script; nothing may set the autoplay attribute.
        assert not re.search(r"\.autoplay\s*=|setAttribute\(\s*[\"']autoplay", src), name


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_break_logic_unit_tests():
    tests = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
    result = subprocess.run(["node", "--test", *tests], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
