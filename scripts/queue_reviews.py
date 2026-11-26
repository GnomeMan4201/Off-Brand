"""Stage screenshot-backed issues and recover any missing draft comments on retry."""

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from draft_review import draft_comment
from ingest import BRANDS, fetch_urlscan_candidates, select_candidates
from voices import assign_batch, assignment_markdown

MARK = "<!-- off-brand-intake-v1 "
DRAFT = "DRAFT, verify against screenshot"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def pages(path):
    return [
        item
        for page in json.loads(gh("api", "--paginate", "--slurp", path))
        for item in page
    ]


def read_queue():
    issues = pages("repos/{owner}/{repo}/issues?state=all&per_page=100")
    return sorted(
        (
            i
            for i in issues
            if i["user"]["login"] == "github-actions[bot]"
            and i.get("body")
            and "pull_request" not in i
        ),
        key=lambda i: i["number"],
    )


def unpack(issue):
    first = issue["body"].splitlines()[0]
    if first.startswith(MARK) and first.endswith(" -->"):
        return json.loads(first[len(MARK) : -4])
    return None


def issue_body(record, assignment, mode):
    payload = {"record": record, "assignment": assignment, "mode": mode}
    encoded = (
        json.dumps(payload, ensure_ascii=True)
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("-", r"\u002d")
    )
    fields = [
        "id",
        "source",
        "public_record_url",
        "defanged_url",
        "defanged_domain",
        "ip",
        "asn_name",
        "page_title",
        "scanned_at",
    ]
    lines = [f"{key}: {record[key] or ''}".replace("`", "′") for key in fields]
    return "\n".join(
        [
            MARK + encoded + " -->",
            "Archived evidence · [Screenshot](" + record["screenshot"] + ")",
            "",
            "```text",
            *lines,
            "```",
            "",
            "[Public scan record](" + record["public_record_url"] + ")",
            "",
            "Recorded tells",
            *record["auto_tells"],
            "",
            *assignment_markdown(assignment),
            "Check the screenshot, then approve the draft or post a corrected review before adding `approved`.",
        ]
    )


def ensure_draft(number, payload, comments):
    if any(
        c["user"]["login"] == "github-actions[bot]" and c["body"].startswith(DRAFT)
        for c in comments
    ):
        return
    body = draft_comment(payload["record"], payload["assignment"])
    gh("issue", "comment", str(number), "--body", body)


def allowance(mode, tracked, today):
    if mode == "backfill":
        limit = 30 - sum(p["mode"] == mode for _, p in tracked)
    else:
        used = sum(
            p["mode"] == "regular" and i["created_at"][:10] == today for i, p in tracked
        )
        limit = min(5, 10 - used)
    return max(0, limit)


def main():
    mode = os.environ.get("INTAKE_MODE") or "regular"
    issues = read_queue()
    tracked = [(issue, payload) for issue in issues if (payload := unpack(issue))]
    for issue, payload in tracked:
        if issue["state"] == "open":
            comments = (
                pages(
                    f"repos/{{owner}}/{{repo}}/issues/{issue['number']}/comments?per_page=100"
                )
                if issue["comments"]
                else []
            )
            ensure_draft(issue["number"], payload, comments)

    limit = allowance(mode, tracked, datetime.now(UTC).date().isoformat())
    if limit <= 0:
        print("Intake allowance already filled.")
        return
    reviews = json.loads(Path("data/reviews.json").read_text())["items"]
    known = set(json.loads(Path("data/seen.json").read_text())) | {
        r["id"] for r in reviews
    }
    for issue in issues:
        known.update(re.findall(r"^id: (\S+)$", issue["body"], re.MULTILINE))
    brands = BRANDS | {
        r["impersonated_brand"] for r in reviews if r.get("impersonated_brand")
    }
    fresh = select_candidates(
        fetch_urlscan_candidates(limit=100),
        known,
        [p["record"]["brand_hint"] for _, p in tracked],
        limit,
        brands,
    )
    assignments = assign_batch(reviews, [r["id"] for r in fresh])
    for record in fresh:
        assignment = assignments[record["id"]]
        url = gh(
            "issue",
            "create",
            "--title",
            "[Triage] " + record["defanged_domain"],
            "--body",
            issue_body(record, assignment, mode),
            "--label",
            "triage",
        )
        ensure_draft(
            int(url.rsplit("/", 1)[1]), {"record": record, "assignment": assignment}, []
        )
    print(f"Opened {len(fresh)} of {limit} eligible slots.")


if __name__ == "__main__":
    main()
