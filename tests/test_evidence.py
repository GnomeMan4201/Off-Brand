"""Evidence sources, correlation, confidence levels and publication gating.

All feed data here is synthetic and uses reserved names (.test, example.com) so that no
fixture resembles a real accusation. No test touches a live feed (see conftest.py).
"""
import gzip
import io
import json
from urllib.error import HTTPError, URLError

import pytest

import evidence
import feeds
import publish_from_issue
from normalize import is_shared_host, normalize
from publish_from_issue import parse_kv_block

UUID = "01a1f8dd-b83d-7541-b503-42125f30510e"
SCAN = f"https://urlscan.io/result/{UUID}/"
PAGE = "https://login.bank-example.test/secure/verify.php?id=7"

PT_ROWS = [
    {"phish_id": 9001, "url": PAGE, "phish_detail_url": "javascript:alert(1)",
     "submission_time": "2026-11-20T10:00:00+00:00", "verified": "yes",
     "verification_time": "2026-11-20T11:00:00+00:00", "online": "yes", "target": "Example Bank"},
    {"phish_id": 9002, "url": "https://login.bank-example.test/other.html", "verified": "yes",
     "online": "yes", "target": "Other"},
    {"phish_id": 9003, "url": "https://sites.google.com/view/someone-else", "verified": "yes", "online": "yes"},
    {"phish_id": "not-a-number", "url": "https://x.test/", "verified": "yes"},
    {"phish_id": 9004, "url": "javascript:alert(1)", "verified": "yes"},
    "not an object",
]


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(body: bytes):
    seen = []

    def op(req, timeout=None):
        seen.append(req.full_url)
        return FakeResp(body)
    op.seen = seen
    return op


def opener_raising(exc):
    def op(req, timeout=None):
        raise exc
    return op


def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


def pt_snapshot(rows=PT_ROWS):
    return feeds.fetch_phishtank(opener=opener_returning(gz(rows)), app_key="")


def op_snapshot(lines):
    return feeds.fetch_openphish(opener=opener_returning("\n".join(lines).encode()))


def down(source, status="unavailable"):
    return feeds.Snapshot(source, status, "test outage", "2026-11-27T00:00:00Z")


# ---------------------------------------------------------------- normalization

def test_normalize_refangs_and_canonicalizes_without_changing_the_page():
    a = normalize("hxxps://LOGIN.Bank-Example[.]test:443/secure/verify.php?id=7#frag")
    b = normalize("http://login.bank-example.test/secure/verify.php?id=7")
    assert a["exact_key"] == b["exact_key"] == "login.bank-example.test/secure/verify.php?id=7"
    assert a["host_key"] == "login.bank-example.test"
    assert normalize("https://x.test")["exact_key"] == "x.test/"
    assert normalize("https://x.test./a")["host_key"] == "x.test"
    # The query is part of the page: different tokens are different pages.
    assert normalize("https://x.test/a?u=1")["exact_key"] != normalize("https://x.test/a?u=2")["exact_key"]


def test_normalize_uses_the_real_host_after_userinfo_and_handles_idn():
    assert normalize("https://bank.example.com@evil.test/login")["host_key"] == "evil.test"
    assert normalize("https://bücher.test/")["host_key"] == "xn--bcher-kva.test"
    assert normalize("https://x.test:8443/")["exact_key"] == "x.test:8443/"


@pytest.mark.parametrize("bad", [None, "", "javascript:alert(1)", "ftp://x.test/", "https://", "https://[::1]/", "https://a b/"])
def test_normalize_rejects_unusable_addresses(bad):
    assert normalize(bad) is None


def test_shared_hosts_are_known():
    assert is_shared_host("sites.google.com") and not is_shared_host("login.bank-example.test")


# ---------------------------------------------------------------- PhishTank adapter

def test_phishtank_parses_valid_rows_and_skips_malformed_ones():
    snap = pt_snapshot()
    assert snap.status == "ok" and len(snap.records) == 3 and snap.skipped == 3
    first = snap.records[0]
    # The record link is built from the numeric ID, never copied from the feed.
    assert first["record_url"] == "https://www.phishtank.com/phish_detail.php?phish_id=9001"
    assert first["verified"] and first["target"] == "Example Bank"
    assert first["verified_at"] == "2026-11-20T11:00:00Z"
    assert snap.records[1]["target"] is None  # "Other" means unknown


def test_phishtank_uses_the_key_only_when_given_and_never_leaks_it():
    op = opener_returning(gz([]))
    feeds.fetch_phishtank(opener=op, app_key="")
    assert op.seen[-1] == feeds.PHISHTANK_DUMP
    key = "A" * 32
    feeds.fetch_phishtank(opener=op, app_key=key)
    assert op.seen[-1] == f"https://data.phishtank.com/data/{key}/online-valid.json.gz"
    failed = feeds.fetch_phishtank(opener=opener_raising(URLError(f"refused for {key}")), app_key=key)
    assert key not in failed.detail and failed.status == "unavailable"
    assert feeds.fetch_phishtank(opener=op, app_key="bad key!").status == "unavailable"


@pytest.mark.parametrize("code,status", [(509, "rate_limited"), (429, "rate_limited"),
                                         (403, "unavailable"), (500, "unavailable")])
def test_phishtank_http_failures_become_explicit_statuses(code, status):
    snap = feeds.fetch_phishtank(opener=opener_raising(HTTPError(feeds.PHISHTANK_DUMP, code, "x", {}, None)), app_key="")
    assert snap.status == status and not snap.ok and snap.records == []
    assert snap.lookup(PAGE) == ([], [])


@pytest.mark.parametrize("body", [b"not gzip", gzip.compress(b"{not json"), gzip.compress(b'{"a": 1}'),
                                  gz([1, 2])[:20]])
def test_phishtank_malformed_responses_are_reported_not_treated_as_empty(body):
    snap = feeds.fetch_phishtank(opener=opener_returning(body), app_key="")
    assert snap.status == "malformed" and not snap.ok


def test_phishtank_oversize_and_network_errors(monkeypatch):
    monkeypatch.setattr(feeds, "MAX_COMPRESSED", 10)
    assert feeds.fetch_phishtank(opener=opener_returning(gz(PT_ROWS)), app_key="").status == "too_large"
    assert feeds.fetch_phishtank(opener=opener_raising(TimeoutError("slow")), app_key="").status == "unavailable"


def test_openphish_feed_parsing_and_bad_responses():
    snap = op_snapshot(["https://a.test/x", "", "not a url", "https://b.test/"])
    assert snap.status == "ok" and len(snap.records) == 2 and snap.skipped == 1
    assert op_snapshot(["<html>blocked</html>"]).status == "malformed"
    assert feeds.fetch_openphish(opener=opener_returning(b"\xff\xfe")).status == "malformed"
    assert feeds.fetch_openphish(opener=opener_raising(HTTPError("u", 429, "x", {}, None))).status == "rate_limited"


def test_tests_cannot_reach_live_feeds():
    assert feeds.fetch_phishtank(app_key="").status == "unavailable"
    assert feeds.fetch_openphish().status == "unavailable"


# ---------------------------------------------------------------- correlation

def test_exact_and_same_host_matches_are_distinguished():
    exact, host = pt_snapshot().lookup("hxxp://login.bank-example[.]test/secure/verify.php?id=7")
    assert [r["phish_id"] for r in exact] == ["9001"]
    assert [r["phish_id"] for r in host] == ["9002"]
    exact, host = pt_snapshot().lookup("https://login.bank-example.test/never-reported")
    assert exact == [] and [r["phish_id"] for r in host] == ["9001", "9002"]


def test_shared_host_records_never_count_as_domain_matches():
    exact, host = pt_snapshot().lookup("https://sites.google.com/view/unrelated")
    assert exact == [] and host == []


# ---------------------------------------------------------------- confidence levels

def lead(src="phishtank", tags=()):
    return evidence.urlscan_record(SCAN, src, tags, "2026-11-20T12:00:00Z")


def test_same_upstream_is_not_independent_corroboration():
    ev = evidence.assess(PAGE, lead=lead("phishtank"), snapshots=[pt_snapshot(), op_snapshot([])])
    assert ev["level"] == "source-confirmed"
    assert "same feed" in ev["reason"]
    assert {r["upstream"] for r in ev["records"] if r["match"] == "exact"} == {"phishtank"}


def test_independent_credible_sources_corroborate():
    ev = evidence.assess(PAGE, lead=lead("phishtank"), snapshots=[pt_snapshot(), op_snapshot([PAGE])])
    assert ev["level"] == "corroborated"
    assert "OpenPhish" in ev["reason"] and "PhishTank" in ev["reason"]


def test_two_weak_labels_do_not_corroborate():
    extra = evidence.urlscan_record(SCAN, None, ["phishing"])
    ev = evidence.assess("https://new.test/", lead=lead("openphish"), extra_records=[extra],
                         snapshots=[pt_snapshot(), op_snapshot([])])
    assert ev["level"] == "suspected"


def test_feed_label_alone_is_suspected_and_says_nothing_verified():
    ev = evidence.assess("https://new.test/login", lead=lead("openphish"), snapshots=[pt_snapshot(), op_snapshot([])])
    assert ev["level"] == "suspected" and "no source verified" in ev["reason"]


def test_same_host_records_can_only_make_a_page_suspected():
    ev = evidence.assess("https://login.bank-example.test/new-page", snapshots=[pt_snapshot()])
    assert ev["level"] == "suspected"
    assert all(r["match"] == "same_host" for r in ev["records"])
    assert any("other pages on the same host" in x for x in ev["limitations"])


def test_no_record_in_checked_sources_is_unverified_with_the_sources_named():
    ev = evidence.assess("https://quiet.test/", snapshots=[pt_snapshot(), op_snapshot([])])
    assert ev["level"] == "unverified"
    assert "PhishTank" in ev["reason"] and "OpenPhish" in ev["reason"]
    assert any("does not mean the page was benign" in x for x in ev["limitations"])


def test_unavailable_sources_stay_unavailable_and_are_never_counted_as_checked():
    ev = evidence.assess(PAGE, lead=lead("openphish"),
                         snapshots=[down("PhishTank", "rate_limited"), down("OpenPhish")])
    assert ev["sources"]["PhishTank"]["status"] == "rate_limited"
    assert ev["sources"]["OpenPhish"]["status"] == "unavailable"
    # The PhishTank record for PAGE exists in the fixture, but the feed was not read here.
    assert not any(r["source"] == "PhishTank" for r in ev["records"])
    assert ev["level"] == "suspected" and "Could not check: OpenPhish, PhishTank" in ev["reason"]
    assert any("level may change" in x for x in ev["limitations"])
    nothing = evidence.assess(PAGE, snapshots=[down("PhishTank"), down("OpenPhish")])
    assert nothing["level"] == "unverified" and "No source could be checked" in nothing["reason"]


def test_conflicting_evidence_is_disputed():
    conflict = {"source": "urlscan.io", "match": "exact", "stance": "contradicts", "strength": "listed",
                "upstream": "editor", "detail": "the scan ended on the genuine login page",
                "record_url": SCAN, "observed_at": None}
    ev = evidence.assess(PAGE, lead=lead("phishtank"), extra_records=[conflict], snapshots=[pt_snapshot()])
    assert ev["level"] == "disputed" and "genuine login" in ev["reason"] and "support it" in ev["reason"]


def test_redirect_to_another_host_is_recorded_from_the_scan():
    ev = evidence.assess(PAGE, lead=lead(), final_host="accounts.example.com", snapshots=[])
    assert ev["specimen"]["redirected"] is True
    assert ev["specimen"]["defanged_final_host"] == "accounts[.]example[.]com"
    same = evidence.assess(PAGE, lead=lead(), final_host="login.bank-example.test", snapshots=[])
    assert same["specimen"]["redirected"] is False


def test_brand_claims_come_from_sources():
    ev = evidence.assess(PAGE, snapshots=[pt_snapshot()])
    assert ev["brand_claims"] == ["Example Bank"]


# ---------------------------------------------------------------- publication

def published_block(level="source-confirmed", **over):
    ev = evidence.assess(PAGE, lead=lead(), snapshots=[pt_snapshot()], now="2026-11-27T00:00:00Z")
    ev.update(level=level, **over)
    return ev


def test_sanitize_drops_unsafe_links_and_rejects_unknown_shapes():
    ev = published_block()
    ev["records"][0]["record_url"] = "javascript:alert(1)"
    clean = evidence.sanitize_evidence(ev)
    assert clean["records"][0]["record_url"] is None
    assert evidence.sanitize_evidence(published_block(level="confirmed")) is None
    bad = published_block()
    bad["sources"]["PhishTank"]["status"] = "fine"
    assert evidence.sanitize_evidence(bad) is None
    assert evidence.sanitize_evidence({"version": 99}) is None
    assert evidence.sanitize_evidence("nope") is None


def test_issue_section_round_trips_through_the_issue_parser():
    ev = published_block()
    body = "id: urlscan-x\n\n" + "\n".join(evidence.issue_lines(ev))
    meta = parse_kv_block(body)
    assert json.loads(meta["evidence_json"])["level"] == "source-confirmed"
    assert "### Evidence level: Source-confirmed" in body
    assert "phish_id=9001" in body
    assert "evidence_ack" not in body
    assert "evidence_ack" in "\n".join(evidence.issue_lines(published_block(level="unverified")))


def meta_with(ev):
    return {"evidence_json": json.dumps(ev)}


def test_publication_gate():
    assert publish_from_issue.evidence_for({}, {}) == (None, None)  # issue predates evidence levels
    ok, err = publish_from_issue.evidence_for(meta_with(published_block()), {})
    assert err is None and ok["level"] == "source-confirmed"
    _, err = publish_from_issue.evidence_for({"evidence_json": "{broken"}, {})
    assert "malformed" in err
    for level in ("unverified", "disputed"):
        _, err = publish_from_issue.evidence_for(meta_with(published_block(level=level)), {})
        assert "evidence_ack" in err
        ok, err = publish_from_issue.evidence_for(meta_with(published_block(level=level)),
                                                  {"evidence_ack": "Shows a common redirect trick"})
        assert err is None and ok["editor_ack"] == "Shows a common redirect trick"


REVIEW = "\n".join([
    "brand: Example Bank", "aisle: Banking", "verdict: Bargain Bin", "rating: 2/10",
    "tells: The address is not the bank's | The form wants a card PIN",
    "critic_note: A bank login on a host the bank has never heard of.",
])


def run_publish(tmp_path, monkeypatch, issue_body, review):
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps({"items": [], "rejected_log": []}))
    monkeypatch.setattr(publish_from_issue, "REVIEWS_PATH", reviews)
    monkeypatch.setenv("ISSUE_BODY", issue_body)
    monkeypatch.setenv("REVIEW_COMMENT", review)
    code = publish_from_issue.main()
    return code, json.loads(reviews.read_text())["items"]


def issue_body(ev=None):
    lines = [f"id: urlscan-{UUID}", "source: urlscan.io (source: phishtank)",
             f"public_record_url: {SCAN}", "defanged_url: hxxps://login.bank-example[.]test/secure/verify.php?id=7"]
    return "\n".join(lines + (evidence.issue_lines(ev) if ev else []))


def test_published_entry_carries_validated_evidence(tmp_path, monkeypatch):
    code, items = run_publish(tmp_path, monkeypatch, issue_body(published_block()), REVIEW)
    assert code == 0 and items[0]["evidence"]["level"] == "source-confirmed"
    assert items[0]["evidence"]["records"][0]["record_url"].startswith("https://")


def test_unverified_needs_an_ack_and_publishes_nothing_without_one(tmp_path, monkeypatch):
    code, items = run_publish(tmp_path, monkeypatch, issue_body(published_block(level="unverified")), REVIEW)
    assert code == 1 and items == []
    code, items = run_publish(tmp_path, monkeypatch, issue_body(published_block(level="unverified")),
                              REVIEW + "\nevidence_ack: Worth showing for the redirect trick")
    assert code == 0 and items[0]["evidence"]["editor_ack"].startswith("Worth showing")


def test_issue_without_evidence_still_publishes_like_before(tmp_path, monkeypatch):
    code, items = run_publish(tmp_path, monkeypatch, issue_body(), REVIEW)
    assert code == 0 and "evidence" not in items[0]


# ---------------------------------------------------------------- pipeline integration

def test_ingest_attaches_evidence_and_marks_unread_sources(monkeypatch):
    import ingest
    cands = [{"id": f"urlscan-{UUID}", "public_record_url": SCAN + "report/",
              "defanged_url": "hxxps://login.bank-example[.]test/secure/verify.php?id=7",
              "defanged_domain": "accounts[.]example[.]com", "scanned_at": "2026-11-20T12:00:00Z",
              "urlscan_source": "phishtank", "urlscan_tags": []},
             {"id": "openphish-abc", "lead": "openphish", "defanged_url": "hxxps://new[.]test/",
              "defanged_domain": "new[.]test", "scanned_at": None}]
    ingest.attach_evidence(cands, [pt_snapshot(), down("OpenPhish", "rate_limited")])
    assert cands[0]["evidence"]["level"] == "source-confirmed"
    assert cands[0]["evidence"]["specimen"]["redirected"] is True
    assert cands[0]["evidence"]["sources"]["OpenPhish"]["status"] == "rate_limited"
    assert cands[1]["evidence"]["level"] == "suspected"
    assert cands[1]["evidence"]["specimen"]["redirected"] is None  # a feed listing has no scan
    json.dumps(cands)  # serializable without private index fields


def test_openphish_candidates_keep_the_original_address():
    import ingest
    snap = op_snapshot(["https://Mixed.Case.test/Path?Q=1"])
    cand = ingest.fetch_openphish_candidates(snapshot=snap)[0]
    assert cand["defanged_url"] == "hxxps://Mixed[.]Case[.]test/Path?Q=1"
    assert ingest.fetch_openphish_candidates(snapshot=down("OpenPhish")) == []


def test_shelf_assessment_never_replaces_findings_during_an_outage():
    import archive
    spec = {"id": f"urlscan-{UUID}", "defanged_url": "hxxps://login.bank-example[.]test/secure/verify.php?id=7",
            "defanged_domain": "login[.]bank-example[.]test", "source_record_url": SCAN + "report/",
            "captured_at": "2026-11-20T12:00:00Z", "classification": {"source": "phishtank", "tags": []}}
    index = {"specimens": [spec]}
    first = archive.assess_specimens(index, [down("PhishTank", "rate_limited"), op_snapshot([])])
    assert first["assessed"] == 1 and spec["evidence"]["level"] == "suspected"
    outage = archive.assess_specimens(index, [down("PhishTank"), down("OpenPhish")])
    assert outage == {"assessed": 0, "kept": 1} and spec["evidence"]["level"] == "suspected"
    later = archive.assess_specimens(index, [pt_snapshot(), op_snapshot([])])
    assert later["assessed"] == 1 and spec["evidence"]["level"] == "source-confirmed"
    assert archive.assess_specimens(index, [pt_snapshot(), op_snapshot([])])["assessed"] == 0


def test_shelf_draft_issue_includes_the_evidence_section():
    import write_specimen
    spec = {"id": f"urlscan-{UUID}", "source_record_url": SCAN, "defanged_url": "hxxps://a[.]test/",
            "captured_at": "2026-11-20T12:00:00Z", "image": {"path": "archive/shots/x.png", "sha256": "0" * 64},
            "evidence": published_block()}
    body = write_specimen.build_body(spec, [], "o/shelf")
    assert "### Evidence level: Source-confirmed" in body
    assert json.loads(parse_kv_block(body)["evidence_json"])["version"] == 1
    del spec["evidence"]
    assert "### Evidence level: not assessed" in write_specimen.build_body(spec, [], "o/shelf")


def test_existing_published_reviews_are_untouched_and_still_valid():
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "data" / "reviews.json").read_text())
    for item in data["items"]:
        if "evidence" in item:
            assert evidence.sanitize_evidence(item["evidence"]) is not None, item["id"]
