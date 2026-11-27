"""'Write this one': open (or reopen) the editorial triage issue for one archived specimen.

The issue is created in the PRIVATE shelf repo (checked privacy first), never in this
public repo, so screenshots and draft notes stay unpublished.

Uses the existing triage issue format (id/source/public_record_url/... lines and the
`triage` label) so the existing approval -> publish flow works unchanged. The issue
carries the screenshot and attributed evidence bullets and leaves every writing field
blank for the editor. Idempotent: the same specimen always maps to the same issue.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from build_archive import build, evidence_bullets, load, render_shelf, write_shelf
from archive import used_bytes
from evidence import issue_lines
from shelf import Shelf, assert_private, assert_separate_checkout, shelf_dir

ROOT = Path(__file__).resolve().parent.parent
ID_LINE = re.compile(r"^id: (\S+)", re.MULTILINE)


def find_issue(specimen_id: str, issues: list[dict]) -> dict | None:
    """Lowest-numbered issue (open or closed) whose body declares this id."""
    hits = [i for i in issues if specimen_id in ID_LINE.findall(i.get("body") or "")]
    return min(hits, key=lambda i: i["number"]) if hits else None


def build_body(spec: dict, bullets: list[dict], shelf_repo: str) -> str:
    shot_url = f"https://github.com/{shelf_repo}/blob/main/{spec['image']['path']}?raw=true"
    cls = spec.get("classification") or {}
    src = cls.get("source")
    return "\n".join([
        f"id: {spec['id']}",
        f"source: urlscan.io (source: {src})" if src else "source: urlscan.io",
        f"public_record_url: {spec['source_record_url']}",
        f"defanged_url: {spec['defanged_url']}",
        f"defanged_domain: {spec.get('defanged_domain') or ''}",
        f"ip: {spec.get('ip') or ''}",
        f"asn_name: {spec.get('asn_name') or ''}",
        f"page_title: {spec.get('page_title') or ''}",
        f"scanned_at: {spec['captured_at']}",
        "",
        "### Saved screenshot",
        f"![saved screenshot]({shot_url})",
        f"File in the private shelf repo: `{spec['image']['path']}` (sha256 `{spec['image']['sha256']}`)",
        "",
        "### Evidence (attributed; nothing here is written copy)",
        *[f"- {b['text']} _({b['source']})_" for b in bullets],
        "",
        *(issue_lines(spec["evidence"], private=True) if spec.get("evidence") else ["### Evidence level: not assessed"]),
        "",
        "### How to publish from your phone",
        "Reply with a comment using these `key: value` lines (your own words), then add the `approved` label. Copy the comment link and use its numeric comment ID with the publication workflow:",
        "```",
        "brand: ",
        "aisle: <Banking | Crypto & Wallets | Marketplace & Retail | Cloud & SaaS>",
        "knockoff_label: ",
        "verdict: ",
        "rating: ",
        "sketchy_segment: ",
        "tells: ",
        "critic_note: ",
        "```",
    ])


def gh_issues(shelf_repo: str) -> list[dict]:
    out = subprocess.run(
        ["gh", "issue", "list", "-R", shelf_repo, "--label", "triage", "--state", "all",
         "--limit", "1000", "--json", "number,body,url"], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def gh_create(shelf_repo: str, title: str, body: str) -> dict:
    url = subprocess.run(
        ["gh", "issue", "create", "-R", shelf_repo, "--title", title, "--body", body,
         "--label", "triage"], check=True, capture_output=True, text=True).stdout.strip()
    return {"number": int(url.rstrip("/").rsplit("/", 1)[1]), "url": url}


def write_specimen(specimen_id: str, index: dict, drafts: dict, inspections: dict, repo: str,
                   list_issues, create_issue, dry_run: bool = False) -> dict:
    spec = next((s for s in index.get("specimens", []) if s["id"] == specimen_id), None)
    if spec is None:
        raise SystemExit(f"Unknown specimen id: {specimen_id}")
    existing = find_issue(specimen_id, list_issues())
    if existing:
        drafts[specimen_id] = existing["number"]
        return {"action": "existing", "number": existing["number"], "url": existing.get("url")}
    if dry_run:
        return {"action": "would_create", "number": None, "url": None}
    body = build_body(spec, evidence_bullets(spec, inspections.get(specimen_id)), repo)
    created = create_issue(f"[Triage] {spec.get('defanged_domain') or specimen_id}", body)
    drafts[specimen_id] = created["number"]
    return {"action": "created", **created}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--public-repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--shelf-repo", default=os.environ.get("SHELF_REPO", ""))
    a = ap.parse_args()
    if not re.fullmatch(r"urlscan-[0-9a-f-]{36}", a.id.strip()):
        print("Invalid specimen id", file=sys.stderr)
        return 1
    assert_private(a.shelf_repo)
    shelf = Shelf(shelf_dir())
    assert_separate_checkout(shelf.base)
    index = load(shelf.index, {"specimens": []})
    drafts = load(shelf.drafts, {})
    inspections = load(shelf.inspections, {})
    result = write_specimen(a.id.strip(), index, drafts, inspections, a.shelf_repo,
                            lambda: gh_issues(a.shelf_repo),
                            lambda t, b: gh_create(a.shelf_repo, t, b), a.dry_run)
    if not a.dry_run:
        shelf.drafts.parent.mkdir(parents=True, exist_ok=True)
        shelf.drafts.write_text(json.dumps(drafts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        data = build(index, load(ROOT / "data" / "reviews.json", {"items": []}), drafts, inspections)
        write_shelf(shelf.base, render_shelf(data, a.shelf_repo, a.public_repo, used_bytes(index)))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
