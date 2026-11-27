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
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from build_archive import build, evidence_bullets, load, render_shelf, write_shelf
from archive import parse_result, used_bytes
from audit_reviews import scan_record
from evidence import assess, urlscan_record
from normalize import normalize
from evidence import issue_lines
from provenance import create_attested_issue, signing_key, verify
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
         "--limit", "1000", "--json", "number,body,url,state"], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def gh_create(shelf_repo: str, title: str, body: str) -> dict:
    return create_attested_issue(shelf_repo, title, body)


def write_specimen(specimen_id: str, index: dict, drafts: dict, inspections: dict, repo: str,
                   list_issues, create_issue, dry_run: bool = False) -> dict:
    spec = next((s for s in index.get("specimens", []) if s["id"] == specimen_id), None)
    if spec is None:
        raise SystemExit(f"Unknown specimen id: {specimen_id}")
    issues = list_issues()
    # The trusted shelf mapping supersedes older unsigned drafts after replacement.
    mapped = drafts.get(specimen_id)
    existing = next((i for i in issues if i["number"] == mapped), None) if mapped else find_issue(specimen_id, issues)
    if mapped and existing is None:
        raise ValueError("The mapped draft was not returned; refusing to create a duplicate.")
    if existing:
        drafts[specimen_id] = existing["number"]
        return {"action": "existing", "number": existing["number"], "url": existing.get("url")}
    if dry_run:
        return {"action": "would_create", "number": None, "url": None}
    body = build_body(spec, evidence_bullets(spec, inspections.get(specimen_id)), repo)
    created = create_issue(f"[Triage] {spec.get('defanged_domain') or specimen_id}", body)
    drafts[specimen_id] = created["number"]
    return {"action": "created", **created}


def replacement_specimen(spec: dict, shelf: Shelf, fetch_scan) -> dict:
    """Rebuild identity from the archived provider record; never trust the old issue."""
    scan_id = spec.get("scan_id")
    if not isinstance(scan_id, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", scan_id):
        raise ValueError("Invalid archived scan identity.")
    if spec.get("id") != "urlscan-" + scan_id:
        raise ValueError("Specimen and scan identifiers disagree.")
    scan, status = fetch_scan(scan_id)
    if status != "ok" or not isinstance(scan, dict):
        raise ValueError("Archived provider record unavailable; no replacement was signed.")
    task = scan.get("task") or {}
    # Require the actual provider response to identify the requested scan.
    if task.get("uuid") != scan_id or task.get("visibility") != "public":
        raise ValueError("Provider record identity or visibility could not be established.")
    fresh = parse_result(dict(scan, _id=scan_id))
    if not fresh:
        raise ValueError("Provider record cannot be safely represented.")
    original, current = normalize(spec.get("defanged_url")), normalize(fresh["defanged_url"])
    if not original or not current or original["exact_key"] != current["exact_key"]:
        raise ValueError("Archived URL differs from the provider record; manual investigation required.")
    if fresh["captured_at"] != spec.get("captured_at"):
        raise ValueError("Archived capture timestamp differs from provider record.")
    image = spec.get("image") or {}
    rel = image.get("path") or ""
    digest = image.get("sha256") or ""
    path = (shelf.base / rel).resolve()
    if (not re.fullmatch(r"[0-9a-f]{64}", digest)
            or shelf.shots.resolve() not in path.parents or not path.is_file()
            or path.stat().st_size > 8 * 1024 * 1024
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
        raise ValueError("Archived screenshot is missing, outside the shelf, or fails its integrity check.")
    cls = fresh["classification"]
    lead = urlscan_record(fresh["source_record_url"], cls.get("source"), cls.get("tags"), fresh["captured_at"])
    # Re-read provider metadata is independently reconstructed. A new feed lookup
    # is not necessary; this draft may be Suspected or Unverified, not confirmed.
    fresh["evidence"] = assess(fresh["defanged_url"], lead=lead,
                                final_host=fresh.get("defanged_domain"), captured_at=fresh["captured_at"])
    # The replacement must not quietly discard contradictory historical evidence.
    old_ev = spec.get("evidence") or {}
    if old_ev.get("level") == "disputed" or any(
            r.get("stance") == "contradicts" for r in old_ev.get("records", []) if isinstance(r, dict)):
        raise ValueError("Historical evidence is disputed; manual investigation required.")
    fresh["image"] = dict(image)
    return fresh


def replace_legacy(specimen_id: str, legacy_number: int, index: dict, drafts: dict,
                   inspections: dict, repo: str, shelf: Shelf, list_issues,
                   create_issue, fetch_scan, dry_run: bool = True) -> dict:
    """Explicitly replace an unsigned mapped draft, never re-sign the old body."""
    spec = next((s for s in index.get("specimens", []) if s["id"] == specimen_id), None)
    if spec is None or drafts.get(specimen_id) != legacy_number:
        raise ValueError("The selected legacy issue is not the trusted mapped draft.")
    issues = list_issues()
    legacy = next((i for i in issues if i["number"] == legacy_number), None)
    if legacy is None:
        raise ValueError("The mapped legacy issue was not returned.")
    key = signing_key()
    try:
        verify(legacy.get("body") or "", repo, legacy_number, key)
    except ValueError:
        pass
    else:
        raise ValueError("The selected issue already has a valid attestation.")
    # A prior partial operation may already have created a signed replacement.
    for issue in issues:
        if issue["number"] == legacy_number:
            continue
        try:
            authenticated = verify(issue.get("body") or "", repo, issue["number"], key)
        except ValueError:
            continue
        if ID_LINE.findall(authenticated) == [specimen_id] and issue.get("state", "OPEN").upper() == "OPEN":
            if not dry_run:
                drafts[specimen_id] = issue["number"]
            return {"action": "replacement_exists", "number": issue["number"], "url": issue.get("url")}
    fresh = replacement_specimen(spec, shelf, fetch_scan)
    if dry_run:
        return {"action": "would_replace", "number": None}
    body = build_body(fresh, evidence_bullets(fresh, inspections.get(specimen_id)), repo)
    created = create_issue("[Triage] " + (fresh.get("defanged_domain") or specimen_id), body)
    drafts[specimen_id] = created["number"]
    return {"action": "replacement_created", **created}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace-legacy", type=int, help="explicit mapped legacy issue number; creates a fresh draft")
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
    try:
        if a.replace_legacy is not None:
            result = replace_legacy(a.id.strip(), a.replace_legacy, index, drafts, inspections,
                                    a.shelf_repo, shelf, lambda: gh_issues(a.shelf_repo),
                                    lambda t, b: gh_create(a.shelf_repo, t, b),
                                    lambda uuid: scan_record(uuid, api_key=os.environ.get("URLSCAN_API_KEY", "")),
                                    a.dry_run)
        else:
            result = write_specimen(a.id.strip(), index, drafts, inspections, a.shelf_repo,
                                    lambda: gh_issues(a.shelf_repo),
                                    lambda t, b: gh_create(a.shelf_repo, t, b), a.dry_run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not a.dry_run:
        shelf.drafts.parent.mkdir(parents=True, exist_ok=True)
        shelf.drafts.write_text(json.dumps(drafts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        data = build(index, load(ROOT / "data" / "reviews.json", {"items": []}), drafts, inspections)
        write_shelf(shelf.base, render_shelf(data, a.shelf_repo, a.public_repo, used_bytes(index)))
    print(json.dumps({"action": result["action"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
