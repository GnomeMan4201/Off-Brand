"""Legacy recovery must rebuild from trusted private collection, never old issues."""
import copy
import hashlib

import pytest

import provenance
import write_specimen
from shelf import Shelf
from test_archive import result, uid

REPO = "owner/shelf"
UUID = uid(1)
SID = "urlscan-" + UUID
KEY = bytes.fromhex("a1" * 32)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setenv(provenance.KEY_ENV, KEY.hex())
    raw = result(1, 1)
    raw["task"].update(uuid=UUID, visibility="public")
    spec = write_specimen.parse_result(raw)
    shelf = Shelf(tmp_path / "shelf")
    shelf.shots.mkdir(parents=True)
    shot = shelf.shots / "fixture.png"
    shot.write_bytes(b"synthetic archived image")
    spec["image"] = {"path": "archive/shots/fixture.png",
                     "sha256": hashlib.sha256(shot.read_bytes()).hexdigest()}
    drafts = {SID: 12}
    issues = [{"number": 12, "body": "id: " + SID + "\nsource: FORGED", "state": "OPEN"}]
    calls = []
    def create(title, body):
        calls.append(body)
        signed = provenance.attest(body, REPO, 13, KEY)
        issues.append({"number": 13, "body": signed, "state": "OPEN"})
        return {"number": 13, "url": "https://github.com/owner/shelf/issues/13"}
    return raw, spec, shelf, drafts, issues, calls, create


def replace(sample, dry=True, fetch=None, number=12):
    raw, spec, shelf, drafts, issues, calls, create = sample
    return write_specimen.replace_legacy(SID, number, {"specimens": [spec]}, drafts, {}, REPO, shelf,
                                          lambda: issues, create, fetch or (lambda _: (raw, "ok")), dry)


def test_dry_run_does_not_create_or_change_mapping(sample):
    assert replace(sample)["action"] == "would_replace"
    assert sample[3] == {SID: 12}
    assert sample[5] == []


def test_fresh_draft_does_not_copy_legacy_body_or_approval(sample):
    assert replace(sample, dry=False)["action"] == "replacement_created"
    assert sample[3] == {SID: 13}
    assert "FORGED" not in sample[5][0]
    assert "Evidence level: Suspected" in sample[5][0]
    assert sample[4][0]["body"].endswith("FORGED")
    # Regular workflow follows trusted map instead of finding the older issue.
    r = write_specimen.write_specimen(SID, {"specimens": [sample[1]]}, sample[3], {}, REPO,
                                       lambda: sample[4], sample[6])
    assert r["number"] == 13 and len(sample[5]) == 1


def test_replacement_is_reused_after_interrupted_mapping_update(sample):
    replace(sample, dry=False)
    sample[3][SID] = 12
    assert replace(sample, dry=False)["action"] == "replacement_exists"
    assert len(sample[5]) == 1 and sample[3][SID] == 13


@pytest.mark.parametrize("change", ["url", "uuid", "visibility", "time", "image", "disputed"])
def test_identity_conflict_or_missing_evidence_fails_closed(sample, change):
    raw, spec, shelf, *_ = sample
    if change == "url":
        raw["task"]["url"] = "https://different.test/"
    elif change == "uuid":
        raw["task"]["uuid"] = uid(2)
    elif change == "visibility":
        raw["task"]["visibility"] = "unlisted"
    elif change == "time":
        raw["task"]["time"] = "2026-11-01T00:00:00Z"
    elif change == "image":
        (shelf.shots / "fixture.png").write_bytes(b"changed")
    else:
        spec["evidence"] = {"level": "disputed"}
    with pytest.raises(ValueError):
        replace(sample, dry=False)
    assert sample[5] == []


def test_source_outage_and_wrong_mapping_do_not_sign(sample):
    with pytest.raises(ValueError):
        replace(sample, dry=False, fetch=lambda _: (None, "unavailable"))
    with pytest.raises(ValueError):
        replace(sample, dry=False, number=99)
    assert sample[5] == []


def test_existing_valid_attestation_is_not_replaced(sample):
    sample[4][0]["body"] = provenance.attest("id: " + SID, REPO, 12, KEY)
    with pytest.raises(ValueError, match="already has a valid"):
        replace(sample, dry=False)
