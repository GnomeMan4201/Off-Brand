import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import archive  # noqa: E402
import build_archive  # noqa: E402
import write_specimen  # noqa: E402

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\n"


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def result(n, hours_ago, url=None, title=None):
    ts = (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "_id": uid(n), "sort": [int((NOW - timedelta(hours=hours_ago)).timestamp() * 1000), uid(n)],
        "task": {"url": url or f"https://site{n}.example.top/login", "time": ts,
                 "source": "openphish", "tags": ["phishing"]},
        "page": {"domain": f"site{n}.example.top", "title": title, "ip": "203.0.113.5"},
    }


class FakeClient:
    """Serves search results in pages of `page_size` using the sort cursor."""

    def __init__(self, results, shots=None, page_size=3):
        self.results, self.shots, self.page_size = results, shots or {}, page_size
        self.screens, self.searches, self.fail_after = [], 0, None

    def search(self, query, cursor):
        self.searches += 1
        start = 0
        if cursor:
            start = next(i for i, r in enumerate(self.results)
                         if ",".join(map(str, r["sort"])) == cursor) + 1
        page = self.results[start:start + self.page_size]
        return {"results": page, "has_more": start + self.page_size < len(self.results)}

    def screenshot(self, scan_uuid):
        self.screens.append(scan_uuid)
        if self.fail_after is not None and len(self.screens) > self.fail_after:
            raise archive.RateLimited("429")
        return self.shots.get(scan_uuid, (PNG + scan_uuid.encode(), "png"))


def fresh():
    return {"version": 1, "specimens": []}, archive.default_state()


def run(name, client, index, state, tmp_path, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("max_pages", 50)
    return archive.run_sweep(name, 7, client, index, state, shots_dir=tmp_path / "shots", **kw)


def test_repeat_import_adds_nothing_and_stores_one_file(tmp_path):
    results = [result(i, i) for i in range(1, 6)]
    index, state = fresh()
    first = run("backfill", FakeClient(results), index, state, tmp_path)
    assert first["added"] == 5 and first["complete"]
    state["jobs"]["backfill"]["complete"] = False  # force a second pass over the same results
    second = run("backfill", FakeClient(results), index, state, tmp_path)
    assert second["added"] == 0 and second["repeat"] == 5
    assert len(index["specimens"]) == 5 and len(list((tmp_path / "shots").iterdir())) == 5
    assert [s["captured_at"] for s in index["specimens"]] == sorted(
        (s["captured_at"] for s in index["specimens"]), reverse=True)


def test_identical_image_same_site_is_noted_but_changed_image_is_kept(tmp_path):
    url = "https://same.example.top/login"
    results = [result(1, 1, url=url), result(2, 2, url=url), result(3, 3, url=url)]
    shots = {uid(1): (PNG + b"v2", "png"), uid(2): (PNG + b"v1", "png"), uid(3): (PNG + b"v1", "png")}
    index, state = fresh()
    stats = run("backfill", FakeClient(results, shots), index, state, tmp_path)
    assert stats["added"] == 2  # newer visibly-changed capture + older original; unchanged repeat folded in
    older = next(s for s in index["specimens"] if s["scan_id"] == uid(2))
    assert older["also_captured"][0]["scan_id"] == uid(3)
    assert len({s["image"]["sha256"] for s in index["specimens"]}) == 2


def test_same_image_on_different_sites_stores_one_file_two_specimens(tmp_path):
    shots = {uid(1): (PNG + b"same", "png"), uid(2): (PNG + b"same", "png")}
    index, state = fresh()
    run("backfill", FakeClient([result(1, 1), result(2, 2)], shots), index, state, tmp_path)
    assert len(index["specimens"]) == 2 and len(list((tmp_path / "shots").iterdir())) == 1


def test_interrupted_backfill_resumes_without_skipping_older_captures(tmp_path):
    results = [result(i, i) for i in range(1, 11)]
    index, state = fresh()
    client = FakeClient(results)
    client.fail_after = 4  # rate limited on the 5th screenshot
    r1 = run("backfill", client, index, state, tmp_path)
    assert r1["added"] == 4 and not r1["complete"] and "rate_limited" in r1["stopped"]
    saved = state["jobs"]["backfill"]["cursor"]
    assert saved == ",".join(map(str, results[3]["sort"]))  # right after the 4th item

    resumed = FakeClient(results)
    r2 = run("backfill", resumed, index, state, tmp_path)
    assert r2["complete"] and r2["added"] == 6
    assert uid(1) not in resumed.screens  # nothing re-fetched
    assert resumed.screens[0] == uid(5)   # first unprocessed capture, not later ones
    assert {s["scan_id"] for s in index["specimens"]} == {uid(i) for i in range(1, 11)}
    assert run("backfill", FakeClient(results), index, state, tmp_path)["stopped"] == "already_complete"


def test_budget_limited_runs_page_through_everything(tmp_path):
    results = [result(i, i) for i in range(1, 8)]
    index, state = fresh()
    for _ in range(10):
        stats = run("backfill", FakeClient(results), index, state, tmp_path, max_new=2, max_pages=1)
        if stats["complete"]:
            break
    assert len(index["specimens"]) == 7


def test_missing_screenshot_is_not_archived_and_not_retried(tmp_path):
    index, state = fresh()

    class NoShot(FakeClient):
        def screenshot(self, scan_uuid):
            self.screens.append(scan_uuid)
            return None if scan_uuid == uid(2) else (PNG + b"x", "png")

    c = NoShot([result(1, 1), result(2, 2), result(3, 3)])
    stats = run("backfill", c, index, state, tmp_path)
    assert stats["added"] == 2 and stats["missing_screenshot"] == 1
    assert "urlscan-" + uid(2) in state["no_screenshot"]
    assert all(s["scan_id"] != uid(2) for s in index["specimens"])
    state["jobs"]["backfill"]["complete"] = False
    c2 = NoShot([result(1, 1), result(2, 2), result(3, 3)])
    run("backfill", c2, index, state, tmp_path)
    assert uid(2) not in c2.screens


def test_window_stops_at_old_captures_and_dry_run_writes_nothing(tmp_path):
    results = [result(1, 1), result(2, 24 * 9)]  # second is 9 days old
    index, state = fresh()
    dry = run("backfill", FakeClient(results), index, state, tmp_path, dry_run=True)
    assert dry["added"] == 1 and not (tmp_path / "shots").exists()
    assert state["no_screenshot"] == {}
    index2, state2 = fresh()
    real = run("backfill", FakeClient(results), index2, state2, tmp_path)
    assert real["added"] == 1 and [s["scan_id"] for s in index2["specimens"]] == [uid(1)]


def test_scheduled_sweep_resumes_gap_then_sets_watermark(tmp_path):
    results = [result(i, i) for i in range(1, 8)]
    index, state = fresh()
    s1 = run("scheduled", FakeClient(results), index, state, tmp_path, max_pages=1)
    assert not s1["complete"] and state["jobs"]["scheduled"]["watermark"] is None
    s2 = run("scheduled", FakeClient(results), index, state, tmp_path, max_pages=10)
    assert s2["complete"] and len(index["specimens"]) == 7
    wm = state["jobs"]["scheduled"]["watermark"]
    assert wm == results[0]["task"]["time"].replace(".000Z", "Z")
    newer = [result(20, 0.5)] + results
    s3 = run("scheduled", FakeClient(newer), index, state, tmp_path)
    assert s3["added"] == 1 and s3["complete"]


def test_source_label_is_not_an_independent_verdict(tmp_path):
    index, state = fresh()
    run("backfill", FakeClient([result(1, 1)]), index, state, tmp_path)
    cls = index["specimens"][0]["classification"]
    assert cls["basis"] == "source_label" and cls["independently_confirmed"] is False
    assert cls["source"] == "openphish" and cls["tags"] == ["phishing"]


def test_rate_limit_429_sleeps_then_gives_up_when_wait_too_long(monkeypatch):
    slept = []
    c = archive.Client(sleep=slept.append)
    calls = {"n": 0}

    class Resp:
        status, headers = 200, {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return b"{}"

    def fake_open(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HTTPError(req.full_url, 429, "x", {"Retry-After": "5"}, None)
        return Resp()

    monkeypatch.setattr(c._opener, "open", fake_open)
    assert c._get("https://urlscan.io/api/v1/search/", 100)[0] == 200 and slept == [5]
    monkeypatch.setattr(c._opener, "open", lambda req, timeout: (_ for _ in ()).throw(
        HTTPError(req.full_url, 429, "x", {"Retry-After": "3600"}, None)))
    try:
        c._get("https://urlscan.io/api/v1/search/", 100)
        assert False
    except archive.RateLimited:
        pass
    try:
        c._get("https://evil.example/x", 1)
        assert False
    except ValueError:
        pass


def _built_index(tmp_path):
    index, state = fresh()
    run("backfill", FakeClient([result(1, 1, title="Sign in"), result(2, 2)]), index, state, tmp_path)
    return index


def test_bullets_are_attributed_and_screenshot_claims_need_an_inspection(tmp_path):
    spec = next(s for s in _built_index(tmp_path)["specimens"] if s["scan_id"] == uid(1))
    plain = build_archive.evidence_bullets(spec)
    assert 3 <= len(plain) <= 5 and all(b["source"] == "scan record" for b in plain)
    text = " ".join(b["text"] for b in plain).lower()
    assert "password" not in text and "countdown" not in text
    assert "not independently confirmed" in text and "Sign in" in plain[0]["text"]
    bare = build_archive.evidence_bullets({"defanged_url": "hxxps://a[.]b/", "classification": {}})
    assert len(bare) == 1  # unknowns are left out, not padded
    bad = [{"observation": "Has a password field"}]  # no inspector / pointer -> ignored
    assert build_archive.evidence_bullets(spec, bad) == plain
    good = [{"observation": "Form asks for a password", "inspector": "editor", "pointer": "centre of image"}]
    withshot = build_archive.evidence_bullets(spec, good)
    assert any(b["source"].startswith("screenshot, inspected by editor") for b in withshot)
    assert len(withshot) <= 5


def test_build_status_and_filtering_data(tmp_path):
    index = _built_index(tmp_path)
    out = tmp_path / "out"
    data = build_archive.build(index, {"items": [{"id": "urlscan-" + uid(2)}]},
                               {"urlscan-" + uid(1): 7}, {}, "o/r", out, root=ROOT_FOR(tmp_path))
    status = {s["id"]: s["status"] for s in data["specimens"]}
    assert status == {"urlscan-" + uid(1): "drafted", "urlscan-" + uid(2): "published"}
    assert data["specimens"][0]["captured_at"] > data["specimens"][1]["captured_at"]
    assert (out / "data.json").exists() and len(list((out / "shots").iterdir())) == 2


def ROOT_FOR(tmp_path):  # specimens store paths like archive/shots/<sha>; mirror under tmp root
    root = tmp_path / "root"
    (root / "archive").mkdir(parents=True, exist_ok=True)
    src, dst = tmp_path / "shots", root / "archive" / "shots"
    if src.exists() and not dst.exists():
        dst.symlink_to(src)
    return root


def test_opening_the_same_draft_twice_creates_one_issue(tmp_path):
    index = _built_index(tmp_path)
    sid, issues, creates, drafts = "urlscan-" + uid(1), [], [], {}

    def create(title, body):
        creates.append((title, body))
        issues.append({"number": 41, "body": body, "url": "https://github.com/o/r/issues/41"})
        return {"number": 41, "url": "https://github.com/o/r/issues/41"}

    first = write_specimen.write_specimen(sid, index, drafts, {}, "O/r", lambda: list(issues), create)
    second = write_specimen.write_specimen(sid, index, drafts, {}, "O/r", lambda: list(issues), create)
    assert (first["action"], second["action"]) == ("created", "existing")
    assert len(creates) == 1 and drafts == {sid: 41} and second["number"] == 41
    title, body = creates[0]
    assert title.startswith("[Triage] site1")
    assert body.startswith(f"id: {sid}\n") and "public_record_url: https://urlscan.io/result/" in body
    assert "![saved screenshot](https://o.github.io/r/archive/shots/" in body
    assert "voice:" not in body and "edge:" not in body       # no assigned voice
    assert "critic_note: \n" in body                           # writing space left blank
    # collecting alone never created an issue
    assert write_specimen.write_specimen(sid, index, {}, {}, "O/r", lambda: [], create,
                                         dry_run=True)["action"] == "would_create"
    assert len(creates) == 1


def test_issue_body_round_trips_through_existing_publish_parser(tmp_path):
    from publish_from_issue import parse_kv_block
    index = _built_index(tmp_path)
    spec = index["specimens"][0]
    meta = parse_kv_block(write_specimen.build_body(spec, build_archive.evidence_bullets(spec), "O/r"))
    for k in ("id", "source", "public_record_url", "defanged_url"):
        assert meta[k]
