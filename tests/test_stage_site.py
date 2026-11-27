import hashlib
import json
from pathlib import Path

import pytest

from stage_site import PAGES, ROOT, stage


def test_public_staging_matches_inputs_and_all_pages(tmp_path):
    out = stage(tmp_path / "site", "abc1234")
    public = ROOT / "data" / "reviews.json"
    assert (out / "data" / "reviews.json").read_bytes() == public.read_bytes()
    assert list((out / "data").iterdir()) == [out / "data" / "reviews.json"]
    expected = {p.relative_to(ROOT / "site") for p in (ROOT / "site").rglob("*") if p.is_file()}
    actual = {p.relative_to(out) for p in out.rglob("*") if p.is_file()}
    assert actual == expected | {Path("reading.html"), Path("data/reviews.json")}
    for name in PAGES:
        page = (out / name).read_text()
        assert "__BUILD__" not in page
        assert "?v=abc1234" in page
    assert (out / "reading.html").read_text().count('<article id="review-') == len(json.loads(public.read_text())["items"])
    assert not any(p.is_symlink() for p in out.rglob("*"))


def test_build_is_repeatable(tmp_path):
    a = stage(tmp_path / "one", "abc1234")
    b = stage(tmp_path / "two", "abc1234")
    def digest(root):
        return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    assert digest(a) == digest(b)


def test_refuses_stale_and_source_output(tmp_path):
    (tmp_path / "stale.txt").write_text("do not overwrite")
    with pytest.raises(ValueError, match="new or empty"):
        stage(tmp_path, "abc1234")
    assert (tmp_path / "stale.txt").read_text() == "do not overwrite"
    with pytest.raises(ValueError):
        stage(ROOT / "data" / "staged", "abc1234")
    with pytest.raises(ValueError):
        stage(tmp_path / "bad", "../bad")


def test_fixture_input_never_changes_source(tmp_path):
    source = ROOT / "data" / "reviews.json"
    original = source.read_bytes()
    out = stage(tmp_path / "test-site", "test", fixture_reviews={"items": [], "rejected_log": []})
    assert json.loads((out / "data" / "reviews.json").read_text())["items"] == []
    assert source.read_bytes() == original


def test_ci_uses_single_dependency_manifest_and_keeps_gate():
    checks = (ROOT / ".github/workflows/checks.yml").read_text()
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
    requirements = (ROOT / "requirements-dev.txt").read_text()
    assert "pip install -r requirements-dev.txt" in checks
    assert "pip check" in checks
    assert "No tests executed" in checks and 'root.findall(".//skipped")' in checks
    assert "needs: checks" in deploy and "scripts/stage_site.py _site" in deploy
    assert {line.split("==")[0] for line in requirements.splitlines() if line and not line.startswith("#")} == {"pytest", "pillow", "playwright"}
