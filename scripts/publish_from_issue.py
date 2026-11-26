"""Publish a human-reviewed triage issue to data/reviews.json.

What gets published is exactly the review the editor approved:
- the ```review block (legacy: plain key: value lines) of the latest comment
  by a trusted author (repo owner/member/collaborator, or the drafting bot)
  that was posted before the `approved` label was added;
- if that comment was edited after the label was added, nothing is published
  (remove and re-add the label to approve the new text);
- comments posted after the label never replace it;
- any unresolved placeholder ("Needs editor verification", template <...>)
  blocks publication.

Inputs (written by the publish workflow with `gh api`):
  ISSUE_JSON      path to the issue object
  COMMENTS_JSONL  path to the issue's comments, one JSON object per line
  EVENTS_JSONL    path to the issue's events, one JSON object per line
On failure the reason is written to PUBLISH_ERROR_PATH for the workflow to post.
"""

from __future__ import annotations

import hashlib
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

PLACEHOLDER = "Needs editor verification"
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
BOT_LOGIN = "github-actions[bot]"
REVIEW_BLOCK_RE = re.compile(r"```review[ \t]*\n(.*?)\n```", re.DOTALL)
TEMPLATE_RE = re.compile(r"<[^<>\n]{2,60}>")  # e.g. "<Target Brand>" left from the old template
REQUIRED_META = ("id", "source", "public_record_url", "defanged_url")
REQUIRED_REVIEW = ("brand", "aisle", "verdict", "rating", "critic_note")


class PublishError(Exception):
    pass


def parse_kv_block(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([a-zA-Z_]+)\s*:\s*(.+)$", line.strip())
        if m:
            fields[m.group(1).lower()] = m.group(2).strip()
    return fields


def extract_review(body: str | None) -> dict[str, str] | None:
    """The ```review block if present; otherwise legacy plain key: value lines."""
    if not body:
        return None
    m = REVIEW_BLOCK_RE.search(body)
    if m:
        fields = parse_kv_block(m.group(1))
    elif "critic_note:" in body:
        fields = parse_kv_block(body)
    else:
        return None
    return fields if "critic_note" in fields else None


def is_trusted(comment: dict) -> bool:
    login = (comment.get("user") or {}).get("login")
    return comment.get("author_association") in TRUSTED_ASSOCIATIONS or login == BOT_LOGIN


def approved_at(events: list[dict], label: str = "approved") -> str:
    times = [e["created_at"] for e in events
             if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == label]
    if not times:
        raise PublishError("Couldn't find when the `approved` label was added.")
    return max(times)


def select_review(comments: list[dict], label_time: str) -> tuple[dict, dict[str, str]]:
    eligible = []
    for c in comments:
        if not is_trusted(c) or c.get("created_at", "") > label_time:
            continue
        review = extract_review(c.get("body"))
        if review:
            eligible.append((c, review))
    if not eligible:
        raise PublishError("No review from a trusted author was posted before the `approved` label was added.")
    comment, review = max(eligible, key=lambda cr: cr[0]["created_at"])
    if comment.get("updated_at", comment["created_at"]) > label_time:
        raise PublishError(
            "The review comment was edited after `approved` was added, so it isn't clear which version you "
            "approved. Remove the `approved` label and add it again to publish the current text."
        )
    return comment, review


def unresolved_fields(review: dict[str, str]) -> list[str]:
    bad = []
    for k, v in review.items():
        if PLACEHOLDER.lower() in v.lower() or TEMPLATE_RE.search(v):
            bad.append(k)
    for k in REQUIRED_REVIEW:
        if not review.get(k, "").strip() and k not in bad:
            bad.append(k)
    return bad


def build_entry(meta: dict[str, str], review: dict[str, str]) -> dict:
    for k in REQUIRED_META:
        if k not in meta:
            raise PublishError(f"Issue metadata is missing `{k}`.")
    bad = unresolved_fields(review)
    if bad:
        raise PublishError("These fields still need the editor: " + ", ".join(f"`{b}`" for b in bad) + ".")

    record_url = validate_public_record_url(meta["public_record_url"])
    defanged = defang_url(meta["defanged_url"])
    if not record_url or not defanged:
        raise PublishError("Invalid `public_record_url` or `defanged_url` in the issue metadata.")

    tells = [sanitize_text(t, max_len=280) for t in review.get("tells", "").split("|")]
    tells = [t for t in tells if t]

    voice = validate_voice(review.get("voice"), review.get("edge"))
    if review.get("voice") and not voice:
        raise PublishError(f"Unknown voice, or edge not allowed for it: `{review.get('voice')}` / `{review.get('edge')}`.")
    edge_names = load_roster()["edges"]

    entry = {
        "id": sanitize_text(meta["id"], max_len=80),
        "aisle": sanitize_text(review["aisle"], max_len=40),
        "impersonated_brand": sanitize_text(review["brand"], max_len=80),
        "knockoff_label": sanitize_text(review.get("knockoff_label") or f"Off-Brand {review['brand']}", max_len=90),
        "verdict": sanitize_text(review["verdict"], max_len=60),
        "rating": sanitize_text(review["rating"], max_len=16),
        "defanged_url": defanged,
        "defanged_domain": defang_domain(meta.get("defanged_domain")),
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
    return entry


def read_jsonl(path: str) -> list[dict]:
    """Parse a stream of JSON values, whatever the line formatting."""
    text = Path(path).read_text(encoding="utf-8")
    dec, i, out = json.JSONDecoder(), 0, []
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return out
        obj, i = dec.raw_decode(text, i)
        out.extend(obj if isinstance(obj, list) else [obj])


def publish(issue: dict, comments: list[dict], events: list[dict]) -> tuple[dict, dict]:
    if (issue.get("user") or {}).get("login") != BOT_LOGIN:
        raise PublishError("Only triage issues opened by the intake bot can be published.")
    label_time = approved_at(events)
    comment, review = select_review(comments, label_time)
    entry = build_entry(parse_kv_block(issue.get("body") or ""), review)
    return entry, comment


def main() -> int:
    err_path = Path(os.environ.get("PUBLISH_ERROR_PATH", "/tmp/publish_error.txt"))
    try:
        issue = json.loads(Path(os.environ["ISSUE_JSON"]).read_text(encoding="utf-8"))
        entry, comment = publish(issue, read_jsonl(os.environ["COMMENTS_JSONL"]),
                                 read_jsonl(os.environ["EVENTS_JSONL"]))
    except PublishError as exc:
        err_path.write_text(str(exc), encoding="utf-8")
        print(f"Not published: {exc}", file=sys.stderr)
        return 1

    data = json.loads(REVIEWS_PATH.read_text(encoding="utf-8"))
    if any(item["id"] == entry["id"] for item in data["items"]):
        print(f"Entry {entry['id']} already published.")
        return 0
    data["items"].insert(0, entry)
    data["last_updated"] = entry["reviewed_at"]
    REVIEWS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    digest = hashlib.sha256((comment.get("body") or "").encode("utf-8")).hexdigest()
    receipt = os.environ.get("PUBLISH_RECEIPT_PATH")
    if receipt:
        Path(receipt).write_text(
            f"Published to Off-Brand from {comment.get('html_url', 'the approved comment')} "
            f"(SHA-256 of the approved text: `{digest[:16]}`).", encoding="utf-8")
    print(f"Published {entry['id']} to data/reviews.json from comment {comment.get('id')} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
