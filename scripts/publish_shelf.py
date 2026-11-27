"""Approve a drafted specimen for public release.

Reads the draft issue from the PRIVATE shelf repo, requires the `approved` label (set by
the editor), and hands the issue body + the editor's last comment to the existing
publish_from_issue.py. Only fields that script validates reach data/reviews.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

import publish_from_issue
from shelf import assert_private


def fetch_issue(shelf_repo: str, number: int) -> dict:
    out = subprocess.run(["gh", "issue", "view", str(number), "-R", shelf_repo, "--json",
                          "body,labels,comments,state"], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def publish(issue: dict) -> int:
    if "approved" not in {l["name"] for l in issue.get("labels", [])}:
        raise SystemExit("Draft is not labeled `approved`; nothing published.")
    comments = issue.get("comments") or []
    if not comments:
        raise SystemExit("Draft has no review comment; nothing published.")
    os.environ["ISSUE_BODY"] = issue.get("body") or ""
    os.environ["REVIEW_COMMENT"] = comments[-1]["body"]
    return publish_from_issue.main()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--shelf-repo", default=os.environ.get("SHELF_REPO", ""))
    a = ap.parse_args()
    assert_private(a.shelf_repo)
    return publish(fetch_issue(a.shelf_repo, a.issue))


if __name__ == "__main__":
    raise SystemExit(main())
