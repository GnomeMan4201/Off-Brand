"""Select an explicitly approved review, never an arbitrary latest comment."""
from __future__ import annotations

import json
import re
import subprocess


def fetch_json(endpoint: str) -> dict:
    return json.loads(subprocess.run(
        ["gh", "api", endpoint], check=True, capture_output=True, text=True
    ).stdout)


def select_review(repo: str, issue_number: int, comment_id: int, editor: str,
                  actor: str, issue: dict, comment: dict) -> str:
    if not editor or actor.casefold() != editor.casefold():
        raise SystemExit("Only the repository owner may authorize publication.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SystemExit("Invalid repository.")
    if issue_number <= 0 or comment_id <= 0:
        raise SystemExit("Invalid issue or comment ID.")
    if issue.get("number") != issue_number or issue.get("state") != "open" or issue.get("pull_request"):
        raise SystemExit("Expected an open issue.")
    if not {"triage", "approved"} <= {label["name"] for label in issue.get("labels", [])}:
        raise SystemExit("Both triage and approved labels are required.")
    expected = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    if comment.get("id") != comment_id or str(comment.get("issue_url", "")).casefold() != expected.casefold():
        raise SystemExit("The selected comment does not belong to this issue.")
    if str((comment.get("user") or {}).get("login", "")).casefold() != editor.casefold():
        raise SystemExit("The selected review was not written by the repository owner.")
    if comment.get("performed_via_github_app"):
        raise SystemExit("App-generated comments are not eligible for publication.")
    body = comment.get("body")
    if not isinstance(body, str) or not body.strip():
        raise SystemExit("The selected review comment is empty.")
    return body


def fetch_approved_review(repo: str, issue_number: int, comment_id: int,
                          editor: str, actor: str) -> tuple[str, str]:
    # Check the authority and input shapes before requesting anything.
    if not editor or actor.casefold() != editor.casefold():
        raise SystemExit("Only the repository owner may authorize publication.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or min(issue_number, comment_id) <= 0:
        raise SystemExit("Invalid repository, issue or comment ID.")
    issue = fetch_json(f"repos/{repo}/issues/{issue_number}")
    comment = fetch_json(f"repos/{repo}/issues/comments/{comment_id}")
    return issue.get("body") or "", select_review(repo, issue_number, comment_id, editor, actor, issue, comment)
