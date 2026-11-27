"""Collection authenticity, replay prevention, and fail-closed publication."""
import json
from types import SimpleNamespace
import pytest

import provenance
import publish_from_issue
from test_evidence import issue_body, published_block, REVIEW

KEY = bytes.fromhex("a1" * 32)
REPO = "owner/project"
ISSUE = 42


def test_attestation_round_trip_and_github_newline_normalization():
    body = "id: example\nsource: test\nevidence_json: {}"
    signed = provenance.attest(body, REPO, ISSUE, KEY)
    assert provenance.verify(signed, REPO.upper(), ISSUE, KEY) == body
    assert provenance.verify(signed.replace("\n", "\r\n") + "\r\n", REPO, ISSUE, KEY) == body


@pytest.mark.parametrize("mutate", [
    lambda s: s.replace("example", "other"),
    lambda s: s.replace("evidence_json: {}", 'evidence_json: {"level":"source-confirmed"}'),
    lambda s: s.replace("source: test", "source: PhishTank"),
    lambda s: s + "\nadditional: data",
    lambda s: s.replace("evidence_attestation: v1:", "evidence_attestation: v2:"),
])
def test_mutated_issue_body_is_rejected(mutate):
    signed = provenance.attest("id: example\nsource: test\nevidence_json: {}", REPO, ISSUE, KEY)
    with pytest.raises(ValueError):
        provenance.verify(mutate(signed), REPO, ISSUE, KEY)


@pytest.mark.parametrize("repo,issue,key", [
    ("owner/other", ISSUE, KEY), (REPO, ISSUE + 1, KEY), (REPO, ISSUE, b"b" * 32),
])
def test_attestation_cannot_be_replayed(repo, issue, key):
    signed = provenance.attest("id: example", REPO, ISSUE, KEY)
    with pytest.raises(ValueError):
        provenance.verify(signed, repo, issue, key)


def test_missing_key_and_preexisting_marker_are_refused(monkeypatch):
    monkeypatch.delenv(provenance.KEY_ENV, raising=False)
    with pytest.raises(ValueError):
        provenance.signing_key()
    with pytest.raises(ValueError):
        provenance.attest("evidence_attestation: v1:bad", REPO, ISSUE, KEY)


def test_issue_creation_attests_only_original_body(monkeypatch):
    monkeypatch.setenv(provenance.KEY_ENV, KEY.hex())
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="https://github.com/owner/project/issues/42\n")
    body = "id: example"
    result = provenance.create_attested_issue(REPO, "Title", body, runner=runner)
    assert result["number"] == ISSUE and len(calls) == 2
    assert calls[0][calls[0].index("--body") + 1] == body
    signed = calls[1][calls[1].index("--body") + 1]
    assert provenance.verify(signed, REPO, ISSUE, KEY) == body
    assert KEY.hex() not in str(calls)


def test_untrusted_issue_cannot_publish_even_with_valid_looking_evidence(tmp_path, monkeypatch):
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps({"items": [], "rejected_log": []}))
    monkeypatch.setattr(publish_from_issue, "REVIEWS_PATH", reviews)
    monkeypatch.setenv(provenance.KEY_ENV, KEY.hex())
    monkeypatch.setenv("REVIEW_COMMENT", REVIEW)
    body = issue_body(published_block())
    signed = provenance.attest(body, REPO, ISSUE, KEY)
    for forged in (body, signed.replace("source: urlscan.io", "source: forged")):
        monkeypatch.setenv("ISSUE_BODY", forged)
        assert publish_from_issue.main(repo=REPO, issue_number=ISSUE) == 1
        assert json.loads(reviews.read_text())["items"] == []
    monkeypatch.setenv("ISSUE_BODY", signed)
    assert publish_from_issue.main(repo=REPO, issue_number=ISSUE) == 0


def test_workflow_signing_and_verification_use_secret_only_on_owner_main():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name in ("ingest.yml", "write-specimen.yml", "publish.yml", "publish-shelf.yml"):
        code = (root / ".github/workflows" / name).read_text()
        assert "github.ref == 'refs/heads/main'" in code
        assert "github.triggering_actor == github.repository_owner" in code
        assert "OFFBRAND_PROVENANCE_KEY: ${{ secrets.OFFBRAND_PROVENANCE_KEY }}" in code


def test_defanged_identity_is_preserved_or_rejected():
    from sanitize import defang_url
    from normalize import normalize
    for url in ("https://example.test/Ａ?x=１", "https://example.test?x=a.b", "https://example.test/#/a"):
        safe = defang_url(url)
        assert safe is not None
        assert normalize(safe)["exact_key"] == normalize(url)["exact_key"]
    assert defang_url("https://example.test/a\u200bb") is None
    assert defang_url("https://example.test/" + "a" * 600) is None
    assert defang_url("https://user:pass@example.test/") is None


def test_issue_creation_failure_does_not_log_body(monkeypatch):
    import subprocess
    monkeypatch.setenv(provenance.KEY_ENV, KEY.hex())
    def runner(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)
    with pytest.raises(ValueError, match="creation failed") as err:
        provenance.create_attested_issue(REPO, "title", "private body", runner=runner)
    assert "private body" not in str(err.value)
