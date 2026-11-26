"""Publish a human-reviewed triage issue to data/reviews.json."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sanitize import defang_domain, defang_url, sanitize_text, validate_public_record_url
from voices import load_roster, validate as validate_voice

ROOT = Path(__file__).resolve().parent.parent
REVIEWS_PATH = ROOT / "data" / "reviews.json"


def parse_kv_block(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([a-zA-Z_]+)\s*:\s*(.+)$", line.strip())
        if m:
            fields[m.group(1).lower()] = m.group(2).strip()
    return fields


def main() -> int:
    issue_body = os.environ.get("ISSUE_BODY", "")
    review_comment = os.environ.get("REVIEW_COMMENT", "")
    if not issue_body or not review_comment:
        print("Missing ISSUE_BODY or REVIEW_COMMENT", file=sys.stderr)
        return 1

    meta = parse_kv_block(issue_body)
    review = parse_kv_block(review_comment)

    required_meta = ("id", "source", "public_record_url", "defanged_url")
    required_review = ("brand", "aisle", "verdict", "rating", "critic_note")
    for k in required_meta:
        if k not in meta:
            print(f"Missing metadata field: {k}", file=sys.stderr)
            return 1
    for k in required_review:
        if k not in review:
            print(f"Missing review field: {k}", file=sys.stderr)
            return 1

    if any(review.get(k) in {"Needs editor", "Unassigned"} for k in ("knockoff_label", "verdict", "critic_note")):
        print("Complete the draft and reapply approved.", file=sys.stderr)
        return 1

    record_url = validate_public_record_url(meta["public_record_url"])
    defanged = defang_url(meta["defanged_url"])
    if not record_url or not defanged:
        print("Invalid public_record_url or defanged_url", file=sys.stderr)
        return 1

    tells = [
        sanitize_text(t, max_len=280)
        for t in review.get("tells", "").split("|")
        if sanitize_text(t, max_len=280)
    ]

    voice = validate_voice(review.get("voice"), review.get("edge"))
    if review.get("voice") and not voice:
        print(f"Unknown voice or edge not allowed for it: {review.get('voice')} / {review.get('edge')}", file=sys.stderr)
        return 1
    edge_names = load_roster()["edges"]

    entry = {
        "id": sanitize_text(meta["id"], max_len=80),
        "aisle": sanitize_text(review["aisle"], max_len=40),
        "impersonated_brand": sanitize_text(review["brand"], max_len=80),
        "knockoff_label": sanitize_text(review.get("knockoff_label") or f"Off-Brand {review['brand']}", max_len=90),
        "verdict": sanitize_text(review["verdict"], max_len=60),
        "rating": sanitize_text(review["rating"], max_len=16),
        "defanged_url": defanged,
        "defanged_domain": defang_domain((meta.get("defanged_domain") or "").replace("[.]", ".")),
        "ip": sanitize_text(meta.get("ip"), max_len=64),
        "asn_name": sanitize_text(meta.get("asn_name"), max_len=120),
        "page_title": sanitize_text(meta.get("page_title"), max_len=140),
        "scanned_at": sanitize_text(meta.get("scanned_at"), max_len=40),
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": sanitize_text(meta["source"], max_len=60),
        "public_record_url": record_url,
        "tells": tells,
        "critic_note": sanitize_text(review["critic_note"], max_len=500),
    }
    if review.get("sketchy_segment"):
        entry["sketchy_segment"] = sanitize_text(review["sketchy_segment"], max_len=120)
    if voice:
        entry["voice"], entry["voice_name"], entry["edge"] = voice
        entry["edge_name"] = edge_names[str(voice[2])]["name"]

    data = json.loads(REVIEWS_PATH.read_text(encoding="utf-8"))
    if any(item["id"] == entry["id"] for item in data["items"]):
        print(f"Entry {entry['id']} already published.")
        return 0

    data["items"].insert(0, entry)
    data["last_updated"] = entry["reviewed_at"]
    REVIEWS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Published {entry['id']} to data/reviews.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
