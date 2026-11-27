import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import archive  # noqa: E402
import build_archive  # noqa: E402
import publish_shelf  # noqa: E402
import write_specimen  # noqa: E402
from shelf import Shelf  # noqa: E402

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
    kw.setdefault("thumbnailer", lambda data: b"thumb" + data[-4:])
    return archive.run_sweep(name, 7, client, index, state, Shelf(tmp_path / "shelf"), **kw)


def test_repeat_import_adds_nothing_and_stores_one_file(tmp_path):
    results = [result(i, i) for i in range(1, 6)]
    index, state = fresh()
    first = run("backfill", FakeClient(results), index, state, tmp_path)
    assert first["added"] == 5 and first["complete"]
    state["jobs"]["backfill"]["complete"] = False  # force a second pass over the same results
    second = run("backfill", FakeClient(results), index, state, tmp_path)
    assert second["added"] == 0 and second["repeat"] == 5
    assert len(index["specimens"]) == 5 and len(list((tmp_path / "shelf" / "archive" / "shots").iterdir())) == 5
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
    assert len(index["specimens"]) == 2 and len(list((tmp_path / "shelf" / "archive" / "shots").iterdir())) == 1


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
    assert dry["added"] == 1 and not (tmp_path / "shelf" / "archive" / "shots").exists()
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


def _data(tmp_path, drafts=None, published=()):
    index = _built_index(tmp_path)
    return index, build_archive.build(index, {"items": [{"id": i} for i in published]}, drafts or {}, {})


def test_build_status_and_ordering(tmp_path):
    _, data = _data(tmp_path, {"urlscan-" + uid(1): 7}, ["urlscan-" + uid(2)])
    status = {s["id"]: s["status"] for s in data["specimens"]}
    assert status == {"urlscan-" + uid(1): "drafted", "urlscan-" + uid(2): "published"}
    assert data["specimens"][0]["captured_at"] > data["specimens"][1]["captured_at"]
    assert data["counts"] == {"unwritten": 0, "drafted": 1, "published": 1}


def test_shelf_markdown_has_thumbs_space_used_and_write_action(tmp_path):
    index, data = _data(tmp_path)
    files = build_archive.render_shelf(data, "me/shelf", "me/pub", archive.used_bytes(index), generated_at="T")
    assert "of 500.0 MB" in files["README.md"] and "Unwritten (2)" in files["README.md"]
    page = files["shelf/unwritten-1.md"]
    assert page.count('<img src="../archive/thumbs/') == 2 and 'width="150"' in page
    assert "site1[.]example[.]top" in page.replace("\\", "") and "2026-11-26" in page
    detail = files[f"shelf/specimens/{uid(1)}.md"]
    assert "(../../archive/shots/" in detail and "Write this one" in detail
    assert "actions/workflows/write-specimen.yml" in detail and f"`urlscan-{uid(1)}`" in detail
    _, drafted = _data(tmp_path, {"urlscan-" + uid(1): 7})
    d = build_archive.render_shelf(drafted, "me/shelf", "me/pub", 0)[f"shelf/specimens/{uid(1)}.md"]
    assert "https://github.com/me/shelf/issues/7" in d and "Write this one" not in d
    assert "shelf/unwritten-1.md" in files["README.md"]
    assert "Nothing here yet" in build_archive.render_shelf(drafted, "a/b", "c/d", 0)["shelf/published-1.md"]


def test_hostile_text_is_neutralised_in_markdown():
    out = build_archive.esc('<img src=x onerror=alert(1)> [x](javascript:alert(1)) `c`')
    assert "<" not in out and "[x]" not in out and "`c`" not in out


def test_pagination_splits_long_shelves():
    specs = [{"id": f"urlscan-{n}", "scan_id": f"s{n}", "domain": "a[.]b", "captured_at": f"2026-01-{n % 28 + 1:02d}T00:00:00Z",
              "status": "unwritten", "image": "archive/shots/x.png", "thumb": "archive/thumbs/x.jpg",
              "bullets": [], "source_record_url": "https://urlscan.io/result/x/", "draft_issue": None,
              "repeat_captures": 0} for n in range(45)]
    pages = build_archive.render_list_pages({"specimens": specs}, "all", "All", "space")
    assert sorted(pages) == [f"shelf/all-{i}.md" for i in (1, 2, 3)]
    assert "Older" in pages["shelf/all-1.md"] and "Newer" in pages["shelf/all-3.md"]


def test_write_shelf_stays_inside_shelf_dir(tmp_path):
    build_archive.write_shelf(tmp_path / "shelf", {"README.md": "x", "shelf/a.md": "y"})
    assert (tmp_path / "shelf" / "shelf" / "a.md").exists() and not (tmp_path / "README.md").exists()


def test_cap_stops_before_cursor_advances_and_resumes_when_space_is_added(tmp_path):
    index, state = fresh()
    c = FakeClient([result(1, 1), result(2, 2), result(3, 3)])
    one = len(PNG + uid(1).encode()) + len(b"thumb" + (PNG + uid(1).encode())[-4:])
    stats = run("backfill", c, index, state, tmp_path, max_bytes=one * 2 + 1)
    assert stats["added"] == 2 and stats["stopped"] == "archive_full" and not stats["complete"]
    assert "id" not in stats["deferred"]
    assert state["last_full"]["id"] == "urlscan-" + uid(3)
    assert archive.used_bytes(index) <= one * 2 + 1
    stats2 = run("backfill", FakeClient([result(1, 1), result(2, 2), result(3, 3)]), index, state,
                 tmp_path, max_bytes=10 ** 6)
    assert stats2["added"] == 1 and stats2["complete"] and "last_full" not in state
    assert len(index["specimens"]) == 3


def test_cap_cli_logs_sizes_only_and_saves_private_resume_point(tmp_path, monkeypatch, capsys):
    results = [result(1, 1), result(2, 2)]
    shelf_path = tmp_path / "shelf"
    monkeypatch.setattr(archive, "shelf_dir", lambda: shelf_path)
    monkeypatch.setattr(archive, "assert_separate_checkout", lambda _: None)
    monkeypatch.setattr(archive, "Client", lambda _: FakeClient(results))
    run_sweep = archive.run_sweep

    def fixture_sweep(*args, **kwargs):
        return run_sweep(*args, **kwargs, now=NOW, thumbnailer=lambda data: b"thumb")

    monkeypatch.setattr(archive, "run_sweep", fixture_sweep)
    assert archive.main(["--mode", "backfill", "--max-mb", "0.00005"]) == 0
    logs = capsys.readouterr()
    assert uid(1) not in logs.out + logs.err
    assert uid(2) not in logs.out + logs.err
    assert '"image_bytes"' in logs.out and "CAPTURE DID NOT FIT: 1 capture" in logs.out
    state = json.loads((shelf_path / "data" / "archive_state.json").read_text())
    assert state["last_full"]["id"] == "urlscan-" + uid(2)
    assert state["jobs"]["backfill"]["cursor"] == ",".join(map(str, results[0]["sort"]))


def test_collector_workflow_pipeline_propagates_collector_failure(tmp_path):
    workflow = (ROOT_DIR / ".github" / "workflows" / "archive.yml").read_text()
    step = workflow.split("      - name: Collect (urlscan.io only, no target contact)", 1)[1]
    script = step.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
    script = "\n".join(line.removeprefix("          ") for line in script.splitlines())
    env = dict(os.environ, MODE="backfill", DAYS="7", MAX_PAGES="1", MAX_MB="500",
               DRY_RUN="true", RESTART="false", GITHUB_STEP_SUMMARY=str(tmp_path / "summary"))
    result = subprocess.run(["bash", "-e", "-c", "python3() { return 42; }\n" + script],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 42


def test_unreadable_image_counts_as_missing_screenshot(tmp_path):
    index, state = fresh()

    def bad(_data):
        raise ValueError("unreadable")

    stats = run("backfill", FakeClient([result(1, 1)]), index, state, tmp_path, thumbnailer=bad)
    assert stats["added"] == 0 and stats["missing_screenshot"] == 1 and index["specimens"] == []


def test_real_thumbnail_is_small_jpeg():
    Image = __import__("pytest").importorskip("PIL.Image")
    import io
    buf = io.BytesIO()
    Image.new("RGB", (1280, 3000), "red").save(buf, "PNG")
    t = archive.make_thumbnail(buf.getvalue())
    im = Image.open(io.BytesIO(t))
    assert im.format == "JPEG" and im.width <= 320 and im.height <= 240
    try:
        archive.make_thumbnail(b"not an image")
        assert False
    except ValueError:
        pass


def test_shelf_must_be_private_and_separate(tmp_path):
    import shelf as sh

    def runner(out, code=0):
        return lambda args: type("R", (), {"returncode": code, "stdout": out, "stderr": ""})()

    sh.assert_private("o/s", runner("true\n"))
    for bad in (runner("false\n"), runner("", 1)):
        try:
            sh.assert_private("o/s", bad)
            assert False
        except SystemExit:
            pass
    try:
        sh.assert_private("", runner("true"))
        assert False
    except SystemExit:
        pass
    try:
        sh.assert_separate_checkout(tmp_path)
        assert False
    except SystemExit:
        pass


def test_publish_requires_approved_label_and_review_comment(monkeypatch, tmp_path):
    index = _built_index(tmp_path)
    spec = index["specimens"][0]
    body = write_specimen.build_body(spec, [], "o/shelf")
    comment = "brand: Acme\naisle: Banking\nverdict: Fake\nrating: 3\ncritic_note: mine"
    for issue in ({"body": body, "labels": [], "comments": [{"body": comment}]},
                  {"body": body, "labels": [{"name": "approved"}], "comments": []}):
        try:
            publish_shelf.publish(issue)
            assert False
        except SystemExit:
            pass
    seen = {}
    monkeypatch.setattr(publish_shelf.publish_from_issue, "main",
                        lambda: seen.update(b=__import__("os").environ["ISSUE_BODY"],
                                            c=__import__("os").environ["REVIEW_COMMENT"]) or 0)
    assert publish_shelf.publish({"body": body, "labels": [{"name": "approved"}],
                                  "comments": [{"body": "older"}, {"body": comment}]}) == 0
    assert seen["c"] == comment and seen["b"] == body


def test_no_scheduled_triage_and_workflows_keep_shelf_private():
    wf = ROOT_DIR / ".github" / "workflows"
    ingest = (wf / "ingest.yml").read_text()
    assert "schedule:" not in ingest and "workflow_dispatch" in ingest
    assert "cron" not in (wf / "ingest.yml").read_text()
    assert "ARCHIVE_SCHEDULE_ENABLED == 'true'" in (wf / "archive.yml").read_text()
    for name in ("archive.yml", "write-specimen.yml", "publish-shelf.yml"):
        text = (wf / name).read_text()
        assert "check-private" in text and "SHELF_TOKEN" in text
    deploy = (wf / "deploy.yml").read_text()
    assert "archive" not in deploy and "shelf" not in deploy
    gi = (ROOT_DIR / ".gitignore").read_text()
    assert "/shelf/" in gi and "/archive/" in gi and "/data/archive*.json" in gi
    assert not (ROOT_DIR / "site" / "archive").exists()


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_opening_the_same_draft_twice_creates_one_issue(tmp_path):
    index = _built_index(tmp_path)
    sid, issues, creates, drafts = "urlscan-" + uid(1), [], [], {}

    def create(title, body):
        creates.append((title, body))
        issues.append({"number": 41, "body": body, "url": "https://github.com/o/r/issues/41"})
        return {"number": 41, "url": "https://github.com/o/r/issues/41"}

    first = write_specimen.write_specimen(sid, index, drafts, {}, "o/shelf", lambda: list(issues), create)
    second = write_specimen.write_specimen(sid, index, drafts, {}, "o/shelf", lambda: list(issues), create)
    assert (first["action"], second["action"]) == ("created", "existing")
    assert len(creates) == 1 and drafts == {sid: 41} and second["number"] == 41
    title, body = creates[0]
    assert title.startswith("[Triage] site1")
    assert body.startswith(f"id: {sid}\n") and "public_record_url: https://urlscan.io/result/" in body
    assert "![saved screenshot](https://github.com/o/shelf/blob/main/archive/shots/" in body and "?raw=true)" in body
    assert "voice:" not in body and "edge:" not in body       # no assigned voice
    assert "critic_note: \n" in body                           # writing space left blank
    # collecting alone never created an issue
    assert write_specimen.write_specimen(sid, index, {}, {}, "o/shelf", lambda: [], create,
                                         dry_run=True)["action"] == "would_create"
    assert len(creates) == 1


def test_issue_body_round_trips_through_existing_publish_parser(tmp_path):
    from publish_from_issue import parse_kv_block
    index = _built_index(tmp_path)
    spec = index["specimens"][0]
    meta = parse_kv_block(write_specimen.build_body(spec, build_archive.evidence_bullets(spec), "o/shelf"))
    for k in ("id", "source", "public_record_url", "defanged_url"):
        assert meta[k]
