import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backfill_issues import open_issues  # noqa: E402
from ingest import select_backfill  # noqa: E402

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def cand(cid, days_ago, url=None):
    return {
        "id": cid, "source": "urlscan.io", "public_record_url": f"https://urlscan.io/result/{cid}/",
        "defanged_url": url or f"hxxps://{cid}[.]example/login", "defanged_domain": f"{cid}[.]example",
        "ip": None, "asn_name": None, "page_title": None,
        "scanned_at": (NOW - timedelta(days=days_ago)).isoformat(), "auto_tells": ["t"],
    }


FIXTURE = (
    [cand(f"urlscan-ok{i}", 1) for i in range(32)]
    + [cand("urlscan-expired", 9), cand("urlscan-noshot", 1), cand("urlscan-published", 1),
       cand("urlscan-dupe-url", 1, url="hxxps://urlscan-ok0[.]example/login")]
)
NO_SHOT = {"urlscan-noshot"}
PUBLISHED = [{"id": "urlscan-published"}]


def stage(known):
    return select_backfill(FIXTURE, known, limit=30, days=7, now=NOW,
                           screenshot_check=lambda c: c["id"] not in NO_SHOT)


def test_run_twice_creates_zero_on_second_run():
    issues = []  # GitHub's issue list, carried from run 1 into run 2
    known = {"urlscan-published"}  # seen.json is deliberately NOT updated between runs

    def run():
        staged = stage(known)
        return staged, open_issues(staged, PUBLISHED, list(issues),
                                   lambda t, b: issues.append({"body": b}))

    staged1, created1 = run()
    staged2, created2 = run()
    print(f"run1 created {len(created1)}, run2 created {len(created2)}")
    assert len(created1) == 30 and len(issues) == 30
    ids = {c["id"] for c in staged1}
    assert len(ids) == 30
    assert not ids & {"urlscan-expired", "urlscan-noshot", "urlscan-published", "urlscan-dupe-url"}
    assert [c["id"] for c in staged2] == [c["id"] for c in staged1]
    assert created2 == [] and len(issues) == 30


def test_seen_ids_are_skipped_and_limit_capped():
    assert stage({"urlscan-ok0"})[0]["id"] == "urlscan-ok1"
    assert len(select_backfill(FIXTURE, set(), limit=99, now=NOW, screenshot_check=lambda c: True)) == 30


def test_issue_format_matches_triage_template():
    issues = []
    open_issues([cand("urlscan-ok0", 1)], [], [], lambda t, b: issues.append((t, b)))
    title, body = issues[0]
    assert title == "[Triage] urlscan-ok0[.]example"
    assert body.startswith("id: urlscan-ok0\n") and "### How to publish from your phone" in body


def select(cands, known=frozenset(), shot=lambda c: True):
    return select_backfill(cands, set(known), limit=30, days=7, now=NOW, screenshot_check=shot)


def test_expired_candidate_excluded_below_cap():
    got = select([cand("urlscan-fresh", 1), cand("urlscan-expired", 9)])
    assert [c["id"] for c in got] == ["urlscan-fresh"]


def test_missing_screenshot_excluded_below_cap():
    got = select([cand("urlscan-shot", 1), cand("urlscan-noshot", 1)],
                 shot=lambda c: c["id"] != "urlscan-noshot")
    assert [c["id"] for c in got] == ["urlscan-shot"]


def test_already_published_excluded_below_cap():
    got = select([cand("urlscan-new", 1), cand("urlscan-published", 1)], known={"urlscan-published"})
    assert [c["id"] for c in got] == ["urlscan-new"]


def test_duplicate_url_keeps_only_first_id():
    url = "hxxps://same[.]example/login"
    got = select([cand("urlscan-first", 1, url=url), cand("urlscan-second", 1, url=url)])
    assert [c["id"] for c in got] == ["urlscan-first"]


def test_dry_run_entry_point_creates_nothing_and_keeps_seen_json(tmp_path, monkeypatch, capsys):
    import json
    import backfill_issues as bi

    (tmp_path / "data").mkdir()
    pending = tmp_path / "data" / "pending_candidates.json"
    pending.write_text(json.dumps([cand("urlscan-eligible", 1)]))
    (tmp_path / "data" / "reviews.json").write_text('{"items": []}')
    seen = tmp_path / "data" / "seen.json"
    seen.write_text('["urlscan-old"]\n')
    before = seen.read_bytes()

    create_calls, list_calls = [], []
    monkeypatch.setattr(bi, "ROOT", tmp_path)
    monkeypatch.setattr(bi, "gh_existing_issues", lambda: list_calls.append(1) or [])
    monkeypatch.setattr(bi, "gh_create_issue", lambda t, b: create_calls.append((t, b)))
    monkeypatch.setattr(bi.subprocess, "run", lambda *a, **k: create_calls.append(a))
    monkeypatch.setattr(sys, "argv", ["backfill_issues.py", "--dry-run"])

    assert bi.main() == 0
    out = capsys.readouterr().out
    assert "would open: [Triage] urlscan-eligible[.]example" in out
    assert "1 issue(s) would be created" in out
    assert list_calls == [1]
    assert create_calls == []
    assert seen.read_bytes() == before
