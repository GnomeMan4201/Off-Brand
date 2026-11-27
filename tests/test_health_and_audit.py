"""Source health check and historical audit: correct reporting, strictly read-only.

Fixture data only. Passing these tests says nothing about whether the live sources
respond; that is what the Source Health Check workflow is for.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

import re

import pytest

import audit_reviews
import evidence
import feeds
import source_health
from test_evidence import (PAGE, PT_ROWS, SCAN, UUID, FakeResp, down, gz, opener_raising,
                           opener_returning, pt_snapshot)

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- source health

def urlscan_opener(payload, headers=None):
    class Resp(FakeResp):
        pass

    def op(req, timeout=None):
        r = Resp(json.dumps(payload).encode())
        r.headers = headers or {}
        op.req = req
        return r
    return op


def test_urlscan_probe_reports_count_freshness_and_rate_limit():
    op = urlscan_opener({"results": [{"task": {"time": "2026-11-27T10:00:00.000Z"}}], "total": 812},
                        {"X-Rate-Limit-Remaining": "29", "X-Rate-Limit-Limit": "30", "X-Rate-Limit-Window": "minute"})
    snap = source_health.probe_urlscan(opener=op, api_key="k" * 36)
    assert snap.status == "ok" and snap.meta["record_count"] == 812
    assert snap.meta["rate_limit"]["X-Rate-Limit-Remaining"] == "29" and "29 search requests left" in snap.detail
    assert op.req.get_header("Api-key") == "k" * 36
    assert op.req.full_url.startswith("https://urlscan.io/api/v1/search/?") and "size=1" in op.req.full_url
    row = source_health.row(snap, {}, NOW)
    assert row["freshness"] == "fresh" and row["last_success"] == snap.fetched_at and row["format_valid"]


@pytest.mark.parametrize("body", [{"oops": 1}, {"results": "x"}, []])
def test_urlscan_probe_flags_unexpected_responses(body):
    assert source_health.probe_urlscan(opener=urlscan_opener(body), api_key="").status == "malformed"


def test_urlscan_rate_limit_is_reported_with_its_headers():
    err = HTTPError("u", 429, "Too Many", {"X-Rate-Limit-Reset-After": "41"}, None)
    snap = source_health.probe_urlscan(opener=opener_raising(err), api_key="")
    row = source_health.row(snap, {"urlscan.io": {"last_success": "2026-11-26T09:00:00Z"}}, NOW)
    assert row["status"] == "rate_limited" and row["rate_limited"] and row["http_status"] == 429
    assert row["rate_limit"] == {"X-Rate-Limit-Reset-After": "41"}
    assert row["last_success"] == "2026-11-26T09:00:00Z"  # carried from the previous report
    assert row["record_count"] is None and row["freshness"] == "unknown"


def test_freshness_thresholds():
    assert source_health.freshness("PhishTank", "2026-11-20T00:00:00Z", NOW) == "stale"
    assert source_health.freshness("PhishTank", "2026-11-26T00:00:00Z", NOW) == "fresh"
    assert source_health.freshness("OpenPhish", "Thu, 26 Nov 2026 20:00:00 GMT", NOW) == "fresh"
    assert source_health.freshness("OpenPhish", None, NOW) == "unknown"


def test_health_rows_for_feeds_and_markdown(monkeypatch):
    monkeypatch.setitem(source_health.CHECKS, "PhishTank", lambda: pt_snapshot())
    monkeypatch.setitem(source_health.CHECKS, "OpenPhish", lambda: down("OpenPhish", "rate_limited"))
    previous = {"sources": [{"source": "OpenPhish", "last_success": "2026-11-25T00:00:00Z"}]}
    report = source_health.run(["PhishTank", "OpenPhish"], previous, NOW)
    pt, op = report["sources"]
    assert pt["record_count"] == 3 and pt["skipped_records"] == 3 and pt["newest_data"] == "2026-11-20T11:00:00Z"
    assert pt["freshness"] == "stale"  # newest fixture entry is a week old
    assert op["status"] == "rate_limited" and op["last_success"] == "2026-11-25T00:00:00Z"
    assert report["not_checked"] == ["urlscan.io"]
    md = source_health.markdown(report)
    assert "| PhishTank | ok | 200 | valid | 3 |" in md and "Not checked this run" in md


def test_health_cli_writes_only_its_report_and_refuses_data(tmp_path, capsys):
    out = tmp_path / "r" / "health.json"
    assert source_health.main(["--out", str(out)]) == 0  # live feeds blocked in tests -> unavailable
    report = json.loads(out.read_text())
    assert {r["status"] for r in report["sources"]} == {"unavailable"}
    assert source_health.main(["--out", str(out), "--strict"]) == 1
    assert source_health.main(["--out", str(ROOT / "data" / "health.json")]) == 2
    assert not (ROOT / "data" / "health.json").exists()


def workflow_code(name):
    """The workflow without comment lines (comments may describe what it does not do)."""
    text = (ROOT / ".github" / "workflows" / name).read_text()
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("name", ["source-health.yml", "audit-reviews.yml"])
def test_read_only_workflows_cannot_write_or_publish(name):
    code = workflow_code(name)
    triggers = code.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert "workflow_dispatch" in triggers
    for other in ("schedule:", "push:", "pull_request", "issues:", "issue_comment", "workflow_run"):
        assert other not in triggers, other
    perms = code.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    lines = [ln.strip() for ln in perms.splitlines() if ln.strip()]
    assert lines and all(ln.endswith(": read") for ln in lines), lines
    assert code.count("permissions:") == 1  # no job-level override
    assert "write" not in code
    for forbidden in ("gh issue", "git push", "git commit", "publish", "workflow run", "> data/", "ingest.py",
                      "archive.py", "write_specimen", "SHELF_TOKEN", "secrets.GITHUB_TOKEN"):
        assert forbidden not in code, forbidden
    uses = {u.split("@")[0] for u in re.findall(r"uses:\s*(\S+)", code)}
    assert uses <= {"actions/checkout", "actions/setup-python", "actions/upload-artifact"}, uses


# ---------------------------------------------------------------- historical audit

def scan_json(source="phishtank", domain="login.bank-example.test"):
    return {"task": {"source": source, "tags": [], "url": PAGE}, "page": {"domain": domain}}


REVIEWS = {"items": [
    {"id": f"urlscan-{UUID}", "impersonated_brand": "Example Bank", "public_record_url": SCAN,
     "defanged_url": "hxxps://login[.]bank-example[.]test/secure/verify.php?id=7", "scanned_at": "2026-11-20T12:00:00Z"},
    {"id": "urlscan-11111111-1111-1111-1111-111111111111", "impersonated_brand": "Other Co",
     "public_record_url": "https://urlscan.io/result/11111111-1111-1111-1111-111111111111/",
     "defanged_url": "hxxps://login[.]bank-example[.]test/elsewhere", "scanned_at": "2026-11-21T00:00:00Z"},
    {"id": "urlscan-22222222-2222-2222-2222-222222222222", "impersonated_brand": "Quiet | Co",
     "public_record_url": "https://urlscan.io/result/22222222-2222-2222-2222-222222222222/",
     "defanged_url": "hxxps://quiet[.]test/", "scanned_at": "2026-11-22T00:00:00Z"},
]}


def test_audit_buckets(monkeypatch):
    fetched = []

    def fetch(uuid):
        fetched.append(uuid)
        return (scan_json("openphish", "accounts.example.com") if uuid == UUID else scan_json(None)), "ok"

    report = audit_reviews.run(REVIEWS, [pt_snapshot()], fetch)
    first, second, third = report["items"]
    assert first["level"] == "source-confirmed" and first["exact_feed_matches"] == ["PhishTank (verified)"]
    assert first["redirected"] is True
    assert second["level"] == "suspected" and second["buckets"]["domain_only"]
    assert third["level"] == "unverified" and third["buckets"]["missing_evidence"]
    assert report["counts"] == {"exact_corroboration": 0, "source_confirmed": 1, "suspected": 1,
                                "domain_only": 1, "missing_evidence": 1, "conflicting": 0,
                                "unavailable_sources": 0}
    assert len(fetched) == 3 and report["sources"]["urlscan.io"] == "scan records re-read: 3 ok"
    md = audit_reviews.report_markdown(report)
    assert "Quiet / Co" in md and "Read-only" in md


def test_audit_reports_unavailable_sources_and_stops_asking_when_rate_limited():
    calls = []

    def fetch(uuid):
        calls.append(uuid)
        return None, "rate_limited"

    report = audit_reviews.run(REVIEWS, [down("PhishTank", "rate_limited")], fetch)
    assert len(calls) == 1  # no further urlscan requests after a rate limit
    assert report["sources"]["urlscan.io"] == "scan records re-read: 3 rate_limited"
    assert report["counts"]["unavailable_sources"] == 3
    for item in report["items"]:
        assert "PhishTank" in item["unavailable_sources"] and "urlscan.io" in item["unavailable_sources"]
        assert item["level"] == "unverified" and "Could not check" in item["reason"]


def test_audit_public_view_hides_openphish_and_private_view_keeps_it():
    op = feeds.fetch_openphish(opener=opener_returning(PAGE.encode()))
    pub = audit_reviews.run(REVIEWS, [pt_snapshot(), op], None, public=True)
    assert "OpenPhish" not in json.dumps(pub)
    priv = audit_reviews.run(REVIEWS, [pt_snapshot(), op], None, public=False)
    assert "OpenPhish" in json.dumps(priv)


def test_audit_conflicting_evidence_bucket():
    conflict = {"source": "urlscan.io", "match": "exact", "stance": "contradicts", "strength": "label",
                "upstream": "editor", "detail": "genuine site", "record_url": SCAN}
    item = audit_reviews.audit_item(REVIEWS["items"][0], [pt_snapshot()], scan_json(), "ok", public=True)
    assert not item["buckets"]["conflicting"]
    ev = evidence.assess(PAGE, extra_records=[conflict], snapshots=[pt_snapshot()])
    assert ev["level"] == "disputed"  # the bucket is driven by the same classifier


def test_audit_cli_never_modifies_data(tmp_path):
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "data").glob("*.json")}
    assert audit_reviews.main(["--out-dir", str(tmp_path / "audit"), "--no-urlscan"]) == 0
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "data").glob("*.json")}
    assert before == after
    report = json.loads((tmp_path / "audit" / "audit.json").read_text())
    published = json.loads((ROOT / "data" / "reviews.json").read_text())["items"]
    assert report["review_count"] == len(published)
    assert report["counts"]["unavailable_sources"] == len(published)  # live PhishTank blocked in tests
    assert audit_reviews.main(["--out-dir", str(ROOT / "data")]) == 2
    assert audit_reviews.main(["--out-dir", str(ROOT / "data" / "sub")]) == 2


def test_audit_only_contacts_urlscan_for_scan_records():
    op = opener_returning(json.dumps(scan_json()).encode())
    data, status = audit_reviews.scan_record(UUID, opener=op)
    assert status == "ok" and op.seen == [f"https://urlscan.io/api/v1/result/{UUID}/"]
    assert audit_reviews.scan_record(UUID, opener=opener_returning(b"<html>"))[1] == "malformed"
