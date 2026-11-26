"""Open triage issues for staged backfill candidates, skipping ones that already have an issue.

Reads data/pending_candidates.json (written by `ingest.py --mode backfill`).
Seen IDs are recorded only after an issue is opened (live runs only), so a failed
run can be retried. Issue title/body match the scheduled intake's triage format.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from voices import assign_batch, assignment_markdown

ROOT = Path(__file__).resolve().parent.parent
ID_LINE = re.compile(r"^id: (\S+)", re.MULTILINE)


def build_title(c: dict) -> str:
    return f"[Triage] {c.get('defanged_domain') or c['id']}"


def build_body(c: dict, a: dict) -> str:
    return "\n".join([
        f"id: {c['id']}",
        f"source: {c['source']}",
        f"public_record_url: {c['public_record_url']}",
        f"defanged_url: {c['defanged_url']}",
        f"defanged_domain: {c.get('defanged_domain') or ''}",
        f"ip: {c.get('ip') or ''}",
        f"asn_name: {c.get('asn_name') or ''}",
        f"page_title: {c.get('page_title') or ''}",
        f"scanned_at: {c.get('scanned_at') or ''}",
        "",
        "### Auto-detected tells",
        *[f"- {t}" for t in c.get("auto_tells", [])],
        "",
        *assignment_markdown(a),
        "",
        "### How to publish from your phone",
        "Reply with a comment using these `key: value` lines, then add the `approved` label:",
        "```",
        "brand: <Target Brand>",
        "aisle: <Banking | Crypto & Wallets | Marketplace & Retail | Cloud & SaaS>",
        "knockoff_label: <Funny product name>",
        "verdict: <e.g. Dollar-Store Knockoff>",
        "rating: <e.g. 2/10>",
        "sketchy_segment: <the exact part of the URL that gives it away>",
        "tells: <Tell 1> | <Tell 2>",
        "critic_note: <1-3 sentences in the assigned voice>",
        f"voice: {a['voice']}",
        f"edge: {a['edge']}",
        "```",
    ])


def issue_ids(issues: list[dict]) -> set[str]:
    ids: set[str] = set()
    for issue in issues:
        ids.update(ID_LINE.findall(issue.get("body") or ""))
    return ids


def open_issues(candidates, published, existing_issues, create_issue) -> list[str]:
    """Create issues for candidates lacking one (open or closed). Returns created ids."""
    have = issue_ids(existing_issues)
    todo = [c for c in candidates if c["id"] not in have]
    assignments = assign_batch(published, [c["id"] for c in todo])
    created = []
    for c in todo:
        create_issue(build_title(c), build_body(c, assignments[c["id"]]))
        created.append(c["id"])
    return created


def gh_existing_issues() -> list[dict]:
    out = subprocess.run(
        ["gh", "issue", "list", "--label", "triage", "--state", "all", "--limit", "1000",
         "--json", "body"],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def gh_create_issue(title: str, body: str) -> None:
    subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body", body, "--label", "triage"],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print what would be opened")
    args = parser.parse_args()

    pending = ROOT / "data" / "pending_candidates.json"
    candidates = json.loads(pending.read_text(encoding="utf-8")) if pending.exists() else []
    published = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8")).get("items", [])
    seen_path = ROOT / "data" / "seen.json"
    seen = set(json.loads(seen_path.read_text(encoding="utf-8"))) if seen_path.exists() else set()

    if args.dry_run:
        created = open_issues(candidates, published, gh_existing_issues(),
                              lambda t, b: print(f"[dry-run] would open: {t}"))
        print(f"Dry run: {len(created)} issue(s) would be created.")
        return 0

    created = open_issues(candidates, published, gh_existing_issues(), gh_create_issue)
    # Candidates that already had an issue are marked seen too.
    seen.update(c["id"] for c in candidates)
    seen_path.write_text(json.dumps(sorted(seen), indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(created)} issue(s); {len(candidates) - len(created)} already had one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
