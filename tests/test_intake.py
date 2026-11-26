import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from approved_comment import select
from draft_review import draft_comment
from ingest import select_candidates
from queue_reviews import issue_body, unpack
from voices import pick


def candidate(i, brand):
    return {
        "id": f"urlscan-{i}",
        "defanged_domain": "sample[.]invalid",
        "page_title": brand,
        "defanged_url": "hxxps://sample[.]invalid/login",
        "ip": None,
        "asn_name": None,
        "scanned_at": None,
        "source": "urlscan.io",
        "public_record_url": "https://urlscan.io/",
        "auto_tells": ["Login path"],
    }


def test_intake_history_and_screenshot():
    records = [
        candidate(i, b) for i, b in enumerate(["Abrand", "Bbrand", "Bbrand", "Abrand"])
    ]
    batch = select_candidates(
        records,
        set(),
        ["abrand", "abrand"],
        5,
        {"Abrand", "Bbrand"},
        verify=lambda i: None if i == "1" else "archived",
    )
    assert [c["id"] for c in batch] == ["urlscan-2", "urlscan-0", "urlscan-3"]


def test_issue_recovery_and_draft():
    record = candidate(0, "Observed <!-- --> title")
    record.update(screenshot="https://urlscan.io/", brand_hint="unknown")
    voice = pick([], record["id"])
    payload = unpack({"body": issue_body(record, voice, "backfill")})
    assert payload == {"record": record, "assignment": voice, "mode": "backfill"}
    draft = draft_comment(
        record,
        voice,
        lambda r, a: json.dumps(
            {"brand": "Invented", "critic_note": "Read the address."}
        ),
    )
    assert draft.startswith("DRAFT, verify against screenshot")
    assert "brand: Unknown" in draft and "voice: " + voice["voice"] in draft


def test_only_trusted_review_before_approval():
    def comment(i, user, body):
        return {
            "id": i,
            "user": {"login": user},
            "body": body,
            "created_at": "01",
            "updated_at": "01",
        }

    comments = [
        comment(1, "github-actions[bot]", "DRAFT, verify against screenshot"),
        comment(2, "editor", "corrected"),
        comment(3, "visitor", "unreviewed"),
    ]
    assert select(comments, "02", "editor") == "corrected"
    comments[1]["updated_at"] = "03"
    try:
        select(comments, "02", "editor")
    except ValueError:
        return
    raise AssertionError("edited review accepted")


def test_backfill_and_daily_allowances_are_independent():
    from queue_reviews import allowance

    today = "2026-11-25"

    def queued(mode, date):
        return {"created_at": date + "T12:00:00Z"}, {"mode": mode}

    tracked = [queued("regular", today)] * 8 + [queued("backfill", "2026-11-24")] * 29
    assert allowance("regular", tracked, today) == 2
    assert allowance("backfill", tracked, today) == 1
    assert allowance("regular", tracked, "2026-11-26") == 5
    assert allowance("backfill", tracked + [queued("backfill", today)], today) == 0
