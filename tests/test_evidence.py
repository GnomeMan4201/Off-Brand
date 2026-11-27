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

def test_normalize_only_applies_changes_a_server_cannot_see():
    a = normalize("hxxps://LOGIN.Bank-Example[.]test:443/secure/verify.php?id=7")
    b = normalize("https://login.bank-example.test/secure/verify.php?id=7")
    assert a["exact_key"] == b["exact_key"] == "//login.bank-example.test/secure/verify.php?id=7"
    assert a["host_key"] == "login.bank-example.test"
    assert normalize("https://x.test")["exact_key"] == "//x.test/"
    assert normalize("https://x.test./a")["host_key"] == "x.test"
    assert normalize("https://x.test:8443/")["exact_key"] == "//x.test:8443/"


@pytest.mark.parametrize("a,b", [
    ("https://x.test/a?u=1", "https://x.test/a?u=2"),           # query values
    ("https://x.test/a?u=1&v=2", "https://x.test/a?v=2&u=1"),   # query order
    ("https://x.test/a", "https://x.test/a?"),                  # empty query
    ("https://x.test/Login", "https://x.test/login"),           # path case
    ("https://x.test/a%2Fb", "https://x.test/a/b"),             # no percent-decoding
    ("https://x.test/a%2fb", "https://x.test/a%2Fb"),           # no escape re-casing
    ("https://x.test/a", "https://x.test/a/"),                  # trailing slash
    ("https://x.test/#/login", "https://x.test/#/signup"),      # hash-routed kit pages
    ("https://x.test/\uff41", "https://x.test/a"),               # no NFKC folding (fullwidth a)
    ("https://x.test/a\u200bb", "https://x.test/ab"),            # zero-width chars are not stripped
    ("https://bank.example.com@x.test/a", "https://x.test/a"),  # userinfo is part of the address
    ("https://x.test/p[.]q", "https://x.test/p.q"),             # refanging never touches the path
])
def test_distinct_pages_are_never_merged(a, b):
    na, nb = normalize(a), normalize(b)
    assert na and nb and na["exact_key"] != nb["exact_key"]


def test_normalize_uses_the_real_host_after_userinfo_and_handles_idn():
    assert normalize("https://bank.example.com@evil.test/login")["host_key"] == "evil.test"
    assert normalize("https://b\u00fccher.test/")["host_key"] == "xn--bcher-kva.test"


@pytest.mark.parametrize("bad", [None, "", "javascript:alert(1)", "ftp://x.test/", "https://", "https://[::1]/",
                                 "https://a b/", "https://x.test/a b", "https://x.test/\x00", "//x.test/",
                                 "https://x.test:99999999999x/"])
def test_normalize_rejects_unusable_addresses(bad):
    assert normalize(bad) is None


def test_shared_hosts_are_known():
    assert is_shared_host("sites.google.com") and not is_shared_host("login.bank-example.test")


OTHER = ["https://unrelated.test/x"]  # a non-empty feed that does not list the test page


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
    assert snap.meta["newest_record_at"] == "2026-11-20T11:00:00Z" and snap.meta["http_status"] == 200


def test_phishtank_uses_the_key_only_when_given_and_never_leaks_it():
    op = opener_returning(gz(PT_ROWS))
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
def test_http_failures_become_explicit_statuses(code, status):
    err = HTTPError(feeds.PHISHTANK_DUMP, code, "x", {"Retry-After": "120"}, None)
    snap = feeds.fetch_phishtank(opener=opener_raising(err), app_key="")
    assert snap.status == status and not snap.ok and snap.records == []
    assert snap.meta["http_status"] == code and snap.meta["rate_limit"] == {"Retry-After": "120"}
    assert snap.lookup(PAGE) == ([], [])


@pytest.mark.parametrize("body", [b"not gzip", gzip.compress(b"{not json"), gzip.compress(b'{"a": 1}'),
                                  gz([1, 2])[:20], gz([]), gz(["junk", {"phish_id": 1}])])
def test_phishtank_malformed_or_empty_responses_are_not_treated_as_no_record(body):
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
    assert op_snapshot([]).status == "malformed"  # an empty feed is a fault, not "nothing listed"
    assert feeds.fetch_openphish(opener=opener_returning(b"\xff\xfe")).status == "malformed"
    assert feeds.fetch_openphish(opener=opener_raising(HTTPError("u", 429, "x", {}, None))).status == "rate_limited"


def test_tests_cannot_reach_live_feeds():
    assert feeds.fetch_phishtank(app_key="").status == "unavailable"
    assert feeds.fetch_openphish().status == "unavailable"


def test_only_feed_hosts_can_be_fetched_or_redirected_to():
    assert feeds.allowed_feed_host("https://data.phishtank.com/data/x")
    assert feeds.allowed_feed_host("https://urlscan.io/api/v1/search/")
    for bad in ("http://data.phishtank.com/x", "https://phishtank.com.evil.test/", "https://evil.test/",
                "https://notopenphish.com/feed.txt"):
        assert not feeds.allowed_feed_host(bad), bad
    with pytest.raises(URLError):
        feeds.FeedHostOnly().redirect_request(None, None, 302, "Found", {}, "https://evil.test/feed")
    # Live-observed redirects (2026-11-27) are allowed, and nothing broader.
    assert feeds.allowed_redirect("https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt")
    assert feeds.allowed_redirect("https://cdn.phishtank.com/datadumps/verified_online.json.gz")
    assert not feeds.allowed_redirect("https://raw.githubusercontent.com/someone/else/feed.txt")
    assert not feeds.allowed_redirect("http://raw.githubusercontent.com/openphish/public_feed/x")


# ---------------------------------------------------------------- correlation

def test_exact_and_same_host_matches_are_distinguished():
    exact, host = pt_snapshot().lookup("hxxps://login.bank-example[.]test/secure/verify.php?id=7")
    assert [r["phish_id"] for r in exact] == ["9001"]
    assert [r["phish_id"] for r in host] == ["9002"]
    exact, host = pt_snapshot().lookup("https://login.bank-example.test/never-reported")
    assert exact == [] and [r["phish_id"] for r in host] == ["9001", "9002"]
    # A scheme-only difference is the same page, and the record says so.
    exact, _ = pt_snapshot().lookup("http://login.bank-example.test/secure/verify.php?id=7")
    assert [r["phish_id"] for r in exact] == ["9001"]
    ev = evidence.assess("http://login.bank-example.test/secure/verify.php?id=7", snapshots=[pt_snapshot()])
    assert ev["level"] == "source-confirmed"
    assert "recorded as https://, scanned as http://" in ev["records"][0]["detail"]


def test_live_observed_phishtank_shapes_match():
    # Shapes observed in the live dump on 2026-11-27 (hosts replaced with reserved names):
    # no trailing slash, a scheme different from the scan, and two entries for one page.
    rows = [{"phish_id": 1, "url": "https://shop.example.test", "verified": "yes", "online": "yes",
             "submission_time": "2026-11-27T02:26:31+00:00", "verification_time": "2026-11-27T02:31:42+00:00",
             "target": "Other", "details": [{"ip_address": "192.0.2.1"}], "phish_detail_url": "x"},
            {"phish_id": 2, "url": "https://shop.example.test/", "verified": "yes", "online": "yes",
             "target": "Example"},
            {"phish_id": 3, "url": "http://deep.example.test/logowanie/48819", "verified": "yes", "online": "yes"}]
    snap = pt_snapshot(rows)
    exact, _ = snap.lookup("hxxps://shop[.]example[.]test/")
    assert sorted(r["phish_id"] for r in exact) == ["1", "2"]
    exact, _ = snap.lookup("hxxps://deep[.]example[.]test/logowanie/48819")
    assert [r["phish_id"] for r in exact] == ["3"]
    assert snap.lookup("hxxps://deep[.]example[.]test/logowanie/48818")[0] == []


def test_shared_host_records_never_count_as_domain_matches():
    exact, host = pt_snapshot().lookup("https://sites.google.com/view/unrelated")
    assert exact == [] and host == []


# ---------------------------------------------------------------- confidence levels

def lead(src="phishtank", tags=()):
    return evidence.urlscan_record(SCAN, src, tags, "2026-11-20T12:00:00Z")


def test_same_upstream_is_not_independent_corroboration():
    ev = evidence.assess(PAGE, lead=lead("phishtank"), snapshots=[pt_snapshot(), op_snapshot(OTHER)])
    assert ev["level"] == "source-confirmed"
    assert "same feed" in ev["reason"]
    assert {r["upstream"] for r in ev["records"] if r["match"] == "exact"} == {"phishtank"}


def test_independent_credible_sources_corroborate_but_the_public_view_drops_openphish():
    ev = evidence.assess(PAGE, lead=lead("phishtank"), snapshots=[pt_snapshot(), op_snapshot([PAGE])])
    assert ev["level"] == "corroborated"
    assert "OpenPhish" in ev["reason"] and "PhishTank" in ev["reason"]
    pub = evidence.public_view(ev)
    assert pub["level"] == "source-confirmed"
    assert not any(r["source"] == "OpenPhish" for r in pub["records"]) and "OpenPhish" not in pub["sources"]
    assert pub["limitations"][0] == evidence.PRIVATE_NOTE


def test_corroboration_requires_a_verification():
    pt_unverified = [dict(PT_ROWS[0], verified="no")]
    ev = evidence.assess(PAGE, lead=lead("openphish"), snapshots=[pt_snapshot(pt_unverified), op_snapshot([PAGE])])
    assert {r["upstream"] for r in ev["records"]} == {"phishtank", "openphish"}
    assert ev["level"] == "suspected"


def test_two_weak_labels_do_not_corroborate():
    extra = evidence.urlscan_record(SCAN, None, ["phishing"])
    ev = evidence.assess("https://new.test/", lead=lead("openphish"), extra_records=[extra],
                         snapshots=[pt_snapshot(), op_snapshot(OTHER)])
    assert ev["level"] == "suspected"


def test_feed_label_alone_is_suspected_and_says_nothing_verified():
    ev = evidence.assess("https://new.test/login", lead=lead("openphish"), snapshots=[pt_snapshot(), op_snapshot(OTHER)])
    assert ev["level"] == "suspected" and "no source verified" in ev["reason"]


def test_same_host_records_can_only_make_a_page_suspected():
    ev = evidence.assess("https://login.bank-example.test/new-page", snapshots=[pt_snapshot()])
    assert ev["level"] == "suspected"
    assert all(r["match"] == "same_host" for r in ev["records"])
    assert any("other pages on the same host" in x for x in ev["limitations"])


def test_no_record_in_checked_sources_is_unverified_with_the_sources_named():
    ev = evidence.assess("https://quiet.test/", snapshots=[pt_snapshot(), op_snapshot(OTHER)])
    assert ev["level"] == "unverified"
    assert "PhishTank" in ev["reason"] and "OpenPhish" in ev["reason"]
    assert any("does not mean the page was benign" in x for x in ev["limitations"])


def test_unavailable_sources_stay_unavailable_and_are_never_counted_as_checked():
    ev = evidence.assess(PAGE, lead=lead("openphish"),
                         snapshots=[down("PhishTank", "rate_limited"), down("OpenPhish")])
    assert ev["sources"]["PhishTank"]["status"] == "rate_limited"
    assert ev["sources"]["OpenPhish"]["status"] == "unavailable"
    assert not any(r["source"] == "PhishTank" for r in ev["records"])
    assert ev["level"] == "suspected" and "Could not check: OpenPhish, PhishTank" in ev["reason"]
    assert any("level may change" in x for x in ev["limitations"])
    nothing = evidence.assess(PAGE, snapshots=[down("PhishTank"), down("OpenPhish")])
    assert nothing["level"] == "unverified" and "No source could be checked" in nothing["reason"]


def test_conflicting_evidence_is_disputed():
    conflict = {"source": "urlscan.io", "match": "exact", "stance": "contradicts", "strength": "label",
                "upstream": "editor", "detail": "the scan ended on the genuine login page",
                "record_url": SCAN, "observed_at": None}
    ev = evidence.assess(PAGE, lead=lead("phishtank"), extra_records=[conflict], snapshots=[pt_snapshot()])
    assert ev["level"] == "disputed" and "genuine login" in ev["reason"] and "support it" in ev["reason"]


def test_redirect_to_another_host_is_recorded_from_the_scan():
    ev = evidence.assess(PAGE, lead=lead(), final_host="accounts.example.com", snapshots=[])
    assert ev["specimen"]["redirected"] is True
    assert ev["specimen"]["defanged_final_host"] == "accounts[.]example[.]com"
    same = evidence.assess(PAGE, lead=lead(), final_host="login.bank-example[.]test", snapshots=[])
    assert same["specimen"]["redirected"] is False


def test_brand_claims_come_from_sources():
    ev = evidence.assess(PAGE, snapshots=[pt_snapshot()])
    assert ev["brand_claims"] == ["Example Bank"]


# ---------------------------------------------------------------- publication

def published_block(**over):
    ev = evidence.assess(PAGE, lead=lead(), snapshots=[pt_snapshot()], now="2026-11-27T00:00:00Z")
    ev.update(**over)
    return ev


def suspected_block():
    return evidence.assess("https://new.test/login", lead=lead("phishtank"), snapshots=[pt_snapshot()])


def unverified_block():
    return evidence.assess("https://quiet.test/", snapshots=[pt_snapshot()])


def test_sanitize_drops_unsafe_links_and_rejects_unknown_shapes():
    ev = published_block()
    ev["records"][0]["record_url"] = "javascript:alert(1)"  # the urlscan label record
    clean = evidence.sanitize_evidence(ev)
    assert clean["records"][0]["record_url"] is None and clean["level"] == "source-confirmed"
    assert evidence.sanitize_evidence(published_block(level="confirmed")) is None
    bad = published_block()
    bad["sources"]["PhishTank"]["status"] = "fine"
    assert evidence.sanitize_evidence(bad) is None
    assert evidence.sanitize_evidence({"version": 1}) is None
    assert evidence.sanitize_evidence("nope") is None


def test_an_edited_level_is_rejected():
    assert evidence.sanitize_evidence(dict(suspected_block(), level="source-confirmed")) is None
    assert evidence.sanitize_evidence(dict(unverified_block(), level="suspected")) is None


def test_records_cannot_claim_more_authority_than_their_source():
    forged = suspected_block()
    forged["records"].append({"source": "urlscan.io", "match": "exact", "stance": "supports", "strength": "verified",
                              "upstream": "x", "detail": "trust me", "record_url": SCAN})
    forged["level"] = "source-confirmed"
    assert evidence.sanitize_evidence(forged) is None
    no_link = published_block()
    for r in no_link["records"]:
        if r["strength"] == "verified":
            r["record_url"] = None
    assert evidence.sanitize_evidence(no_link) is None


def test_issue_section_round_trips_through_the_issue_parser():
    ev = published_block()
    body = "id: urlscan-x\n\n" + "\n".join(evidence.issue_lines(ev, private=False))
    meta = parse_kv_block(body)
    assert json.loads(meta["evidence_json"])["level"] == "source-confirmed"
    assert "### Evidence level: Source-confirmed" in body and "phish_id=9001" in body
    assert "Not publishable" in "\n".join(evidence.issue_lines(unverified_block(), private=False))
    assert "only as Suspected" in "\n".join(evidence.issue_lines(suspected_block(), private=False))


def test_public_issues_never_contain_openphish_data():
    ev = evidence.assess(PAGE, lead=lead("phishtank"), snapshots=[pt_snapshot(), op_snapshot([PAGE])])
    public = "\n".join(evidence.issue_lines(ev, private=False))
    assert "OpenPhish" not in public and "openphish.com" not in public
    private = "\n".join(evidence.issue_lines(ev, private=True))
    assert "OpenPhish" in private and "Publishable level" in private


def test_issue_text_is_markdown_escaped():
    rows = [dict(PT_ROWS[0], target="[click me](https://evil.test) <b>x</b>")]
    ev = evidence.assess(PAGE, snapshots=[pt_snapshot(rows)])
    text = "\n".join(evidence.issue_lines(ev, private=True)[:-1])
    assert "[click me](https" not in text and "<b>" not in text


def meta_with(ev):
    return {"evidence_json": json.dumps(ev)}


def test_publication_gate():
    _, err = publish_from_issue.evidence_for({})
    assert "No evidence block" in err
    ok, err = publish_from_issue.evidence_for(meta_with(published_block()))
    assert err is None and ok["level"] == "source-confirmed"
    ok, err = publish_from_issue.evidence_for(meta_with(suspected_block()))
    assert err is None and ok["level"] == "suspected"
    _, err = publish_from_issue.evidence_for({"evidence_json": "{broken"})
    assert "malformed" in err
    _, err = publish_from_issue.evidence_for(meta_with(unverified_block()))
    assert "cannot be published" in err
    conflict = {"source": "urlscan.io", "match": "exact", "stance": "contradicts", "strength": "label",
                "upstream": "editor", "detail": "ended on the genuine site", "record_url": SCAN}
    disputed = evidence.assess(PAGE, lead=lead(), extra_records=[conflict], snapshots=[pt_snapshot()])
    assert disputed["level"] == "disputed"
    _, err = publish_from_issue.evidence_for(meta_with(disputed))
    assert "cannot be published" in err


def test_openphish_only_specimens_cannot_be_published():
    ev = evidence.assess("https://new.test/", lead=evidence.openphish_listing(), snapshots=[pt_snapshot()])
    assert ev["level"] == "suspected"  # in private triage
    _, err = publish_from_issue.evidence_for(meta_with(ev))
    assert "Unverified" in err  # once OpenPhish is removed, nothing supports it publicly


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


def issue_body(ev=None, private=False):
    lines = [f"id: urlscan-{UUID}", "source: urlscan.io (source: phishtank)",
             f"public_record_url: {SCAN}", "defanged_url: hxxps://login.bank-example[.]test/secure/verify.php?id=7"]
    return "\n".join(lines + (evidence.issue_lines(ev, private=private) if ev else []))


def test_published_entry_carries_validated_public_evidence(tmp_path, monkeypatch):
    ev = evidence.assess(PAGE, lead=lead("phishtank"), snapshots=[pt_snapshot(), op_snapshot([PAGE])])
    code, items = run_publish(tmp_path, monkeypatch, issue_body(ev, private=True), REVIEW)
    assert code == 0 and items[0]["evidence"]["level"] == "source-confirmed"
    assert "OpenPhish" not in json.dumps(items[0]["evidence"])


def test_unpublishable_levels_and_missing_evidence_publish_nothing(tmp_path, monkeypatch):
    for ev in (unverified_block(), None):
        code, items = run_publish(tmp_path, monkeypatch, issue_body(ev), REVIEW)
        assert code == 1 and items == []


def test_evidence_ack_is_no_longer_accepted(tmp_path, monkeypatch):
    code, items = run_publish(tmp_path, monkeypatch, issue_body(unverified_block()),
                              REVIEW + "\nevidence_ack: please publish anyway")
    assert code == 1 and items == []
    code, items = run_publish(tmp_path, monkeypatch, issue_body(published_block()),
                              REVIEW + "\nevidence_ack: harmless")
    assert code == 1 and items == []  # unknown review field


def test_suspected_publishes_and_stays_suspected(tmp_path, monkeypatch):
    code, items = run_publish(tmp_path, monkeypatch, issue_body(suspected_block()), REVIEW)
    assert code == 0 and items[0]["evidence"]["level"] == "suspected"


# ---------------------------------------------------------------- pipeline integration

def test_ingest_attaches_evidence_and_marks_unread_sources():
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
    assert evidence.public_view(cands[1]["evidence"])["level"] == "unverified"
    assert cands[1]["evidence"]["specimen"]["redirected"] is None  # a feed listing has no scan
    json.dumps(cands)  # serializable without private index fields


def test_openphish_candidates_keep_the_original_address():
    import ingest
    snap = op_snapshot(["https://Mixed.Case.test/Path?Q=1"])
    cand = ingest.fetch_openphish_candidates(snapshot=snap)[0]
    assert cand["defanged_url"] == "hxxps://Mixed[.]Case[.]test/Path?Q=1"
    assert ingest.fetch_openphish_candidates(snapshot=down("OpenPhish")) == []


def shelf_spec(source="phishtank"):
    return {"id": f"urlscan-{UUID}", "defanged_url": "hxxps://login.bank-example[.]test/secure/verify.php?id=7",
            "defanged_domain": "login[.]bank-example[.]test", "source_record_url": SCAN + "report/",
            "captured_at": "2026-11-20T12:00:00Z", "classification": {"source": source, "tags": []}}


def test_shelf_assessment_never_replaces_findings_during_an_outage():
    import archive
    spec = shelf_spec()
    index = {"specimens": [spec]}
    first = archive.assess_specimens(index, [down("PhishTank", "rate_limited"), op_snapshot(OTHER)])
    assert first["assessed"] == 1 and spec["evidence"]["level"] == "suspected"
    outage = archive.assess_specimens(index, [down("PhishTank"), down("OpenPhish")])
    assert outage == {"assessed": 0, "kept": 1} and spec["evidence"]["level"] == "suspected"
    later = archive.assess_specimens(index, [pt_snapshot(), op_snapshot(OTHER)])
    assert later["assessed"] == 1 and spec["evidence"]["level"] == "source-confirmed"
    assert archive.assess_specimens(index, [pt_snapshot(), op_snapshot(OTHER)])["assessed"] == 0


def test_a_partial_outage_carries_earlier_findings_forward_and_says_so():
    import archive
    spec = shelf_spec("openphish")
    index = {"specimens": [spec]}
    archive.assess_specimens(index, [down("PhishTank"), op_snapshot([PAGE])])
    assert spec["evidence"]["level"] == "suspected"
    archive.assess_specimens(index, [pt_snapshot(), down("OpenPhish", "rate_limited")])
    ev = spec["evidence"]
    assert ev["level"] == "corroborated"  # OpenPhish's earlier listing is kept, not lost to the outage
    assert ev["sources"]["OpenPhish"]["detail"].endswith("(carried from an earlier check)")
    assert any("carried over" in x for x in ev["limitations"])
    assert archive.needs_assessment(spec)  # carried results are re-checked next run


def test_shelf_draft_issue_includes_the_private_evidence_section():
    import write_specimen
    spec = {"id": f"urlscan-{UUID}", "source_record_url": SCAN, "defanged_url": "hxxps://a[.]test/",
            "captured_at": "2026-11-20T12:00:00Z", "image": {"path": "archive/shots/x.png", "sha256": "0" * 64},
            "evidence": published_block()}
    body = write_specimen.build_body(spec, [], "o/shelf")
    assert "### Evidence level: Source-confirmed" in body
    assert json.loads(parse_kv_block(body)["evidence_json"])["version"] == evidence.VERSION
    assert "evidence_ack" not in body
    del spec["evidence"]
    assert "### Evidence level: not assessed" in write_specimen.build_body(spec, [], "o/shelf")


def test_existing_published_reviews_are_untouched_and_still_valid():
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "data" / "reviews.json").read_text())
    for item in data["items"]:
        if "evidence" in item:
            assert evidence.sanitize_evidence(item["evidence"]) is not None, item["id"]
