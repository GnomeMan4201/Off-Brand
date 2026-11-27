"""Publication must use the exact owner-approved comment and fail closed."""
import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import approval
import publish_from_issue

REPO = "owner/project"
BODY = "brand: Example\naisle: Banking\nverdict: Suspected phishing\nrating: Unconfirmed\ncritic_note: A review."
ISSUE = {"number": 12, "state": "open", "body": "metadata", "labels": [{"name": "triage"}, {"name": "approved"}]}
COMMENT = {"id": 42, "issue_url": "https://api.github.com/repos/owner/project/issues/12", "user": {"login": "owner"}, "body": BODY}


def select(issue=None, comment=None, actor="owner", comment_id=42):
    return approval.select_review(REPO, 12, comment_id, "owner", actor,
                                  copy.deepcopy(ISSUE if issue is None else issue),
                                  copy.deepcopy(COMMENT if comment is None else comment))


def test_explicit_comment_not_latest(monkeypatch):
    calls = []
    def fetch(path):
        calls.append(path)
        return ISSUE if path.endswith("/12") else COMMENT
    monkeypatch.setattr(approval, "fetch_json", fetch)
    assert approval.fetch_approved_review(REPO, 12, 42, "owner", "owner") == ("metadata", BODY)
    assert calls == ["repos/owner/project/issues/12", "repos/owner/project/issues/comments/42"]


@pytest.mark.parametrize("overrides", [
    {"id": 43}, {"user": {"login": "stranger"}}, {"user": None},
    {"issue_url": "https://api.github.com/repos/owner/project/issues/99"},
    {"issue_url": "https://api.github.com/repos/owner/other/issues/12"},
    {"performed_via_github_app": {"id": 1}}, {"body": ""},
])
def test_reject_untrusted_comment(overrides):
    with pytest.raises(SystemExit):
        select(comment={**COMMENT, **overrides})


@pytest.mark.parametrize("overrides", [
    {"state": "closed"}, {"number": 13}, {"labels": [{"name": "triage"}]},
    {"labels": [{"name": "approved"}]}, {"pull_request": {"url": "example"}},
])
def test_issue_must_be_open_and_approved(overrides):
    with pytest.raises(SystemExit):
        select(issue={**ISSUE, **overrides})


def test_nonowner_cannot_authorize():
    with pytest.raises(SystemExit):
        select(actor="stranger")


@pytest.mark.parametrize("extra", ["\ncontinued text", "\nbrand: duplicate", "\nunknown: value", "\nedge: "])
def test_malformed_review_rejected(extra):
    with pytest.raises(ValueError):
        publish_from_issue.parse_review_block(BODY + extra)


def test_fenced_review_and_withheld_record():
    assert publish_from_issue.parse_review_block("```\n" + BODY + "\n```")["brand"] == "Example"
    old = "urlscan-example"
    digest = "withheld-" + hashlib.sha256(old.encode()).hexdigest()
    assert publish_from_issue.is_excluded({"rejected_log": [{"id": digest}]}, old)
    assert publish_from_issue.is_excluded({"rejected_log": [{"id": old}]}, old)
    assert not publish_from_issue.is_excluded({"rejected_log": [{"id": digest}]}, "other")


def test_publication_workflows_share_guard_and_gate():
    root = Path(__file__).resolve().parents[1]
    for name in ("publish.yml", "publish-shelf.yml"):
        text = (root / ".github/workflows" / name).read_text()
        assert "workflow_dispatch:" in text and "comment_id:" in text
        assert "github.actor == github.repository_owner" in text
        assert "scripts/publish_approved.py" in text
        assert "comments[-1]" not in text
    deploy = (root / ".github/workflows/deploy.yml").read_text()
    assert "needs: checks" in deploy and "./.github/workflows/checks.yml" in deploy


def test_private_exclusions_have_no_public_pointer():
    import json
    data = json.loads((Path(__file__).resolve().parents[1] / "data/reviews.json").read_text())
    private = [r for r in data["rejected_log"] if r["id"].startswith("withheld-")]
    assert len(private) >= 2
    assert all(r["defanged_domain"] == "Withheld for privacy" and not r.get("public_record_url") for r in private)
