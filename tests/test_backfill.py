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
