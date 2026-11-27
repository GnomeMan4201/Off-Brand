"""Publish the owner-selected review comment from a public or private issue."""
import argparse
import os

import publish_from_issue
from approval import fetch_approved_review
from shelf import assert_private


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--comment", type=int, required=True)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    if args.private:
        assert_private(args.repo)
    body, review = fetch_approved_review(
        args.repo, args.issue, args.comment,
        os.environ.get("EDITOR_LOGIN", ""), os.environ.get("GITHUB_ACTOR", ""))
    os.environ["ISSUE_BODY"] = body
    os.environ["REVIEW_COMMENT"] = review
    return publish_from_issue.main(repo=args.repo, issue_number=args.issue)


if __name__ == "__main__":
    raise SystemExit(main())
