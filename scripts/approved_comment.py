"""Select the editor's review or the intake bot's draft as of the approval event."""

import json
import os
import subprocess
from pathlib import Path


def select(comments, cutoff, owner):
    eligible = [
        c
        for c in comments
        if c["created_at"] <= cutoff
        and (
            c["user"]["login"] == owner
            or (
                c["user"]["login"] == "github-actions[bot]"
                and c["body"].startswith("DRAFT, verify against screenshot")
            )
        )
    ]
    if not eligible:
        raise ValueError("Post a review or wait for the draft, then reapply approved.")
    latest = max(eligible, key=lambda c: c["id"])
    if latest["updated_at"] > cutoff:
        raise ValueError(
            "Review changed after approval. Check it and reapply approved."
        )
    return latest["body"]


if __name__ == "__main__":
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    issue = event["issue"]
    path = f"repos/{{owner}}/{{repo}}/issues/{issue['number']}/comments?per_page=100"
    pages = json.loads(
        subprocess.check_output(["gh", "api", "--paginate", "--slurp", path])
    )
    print(
        select(
            [c for page in pages for c in page],
            issue["updated_at"],
            event["repository"]["owner"]["login"],
        )
    )
