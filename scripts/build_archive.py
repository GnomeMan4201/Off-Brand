"""Build the browsable (unpublished) specimen archive site data.

Reads data/archive.json plus review/draft/inspection records and writes
<out>/data.json and the referenced screenshots into <out>/shots/.
Evidence bullets are factual, attributed, and never generated prose.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sanitize import sanitize_text

ROOT = Path(__file__).resolve().parent.parent
MAX_BULLETS = 5


def load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def valid_inspections(items) -> list[dict]:
    """Screenshot observations count only with an observation, an inspector and a pointer."""
    out = []
    for it in items or []:
        obs = sanitize_text(it.get("observation"), max_len=160)
        who = sanitize_text(it.get("inspector"), max_len=40)
        where = sanitize_text(it.get("pointer"), max_len=80)
        if obs and who and where:
            out.append({"observation": obs, "inspector": who, "pointer": where})
    return out


def evidence_bullets(spec: dict, inspections: list[dict] | None = None) -> list[dict]:
    """3-5 short bullets when evidence supports them; unknowns are left out."""
    bullets = []
    if spec.get("page_title"):
        bullets.append({"text": f"Page title in the scan record: \u201c{spec['page_title']}\u201d",
                        "source": "scan record"})
    cls = spec.get("classification") or {}
    label = [x for x in [cls.get("source")] + list(cls.get("tags") or []) if x]
    if label:
        bullets.append({
            "text": f"Labelled by the source as: {', '.join(label)}. "
                    "This is the source's label, not independently confirmed.",
            "source": "scan record",
        })
    for ins in valid_inspections(inspections):
        bullets.append({"text": ins["observation"],
                        "source": f"screenshot, inspected by {ins['inspector']} ({ins['pointer']})"})
    host = ", ".join(x for x in [
        f"IP {spec['ip']}" if spec.get("ip") else None,
        f"ASN {spec['asn_name']}" if spec.get("asn_name") else None] if x)
    if host:
        bullets.append({"text": f"Hosting recorded in the scan: {host}", "source": "scan record"})
    if spec.get("defanged_url"):
        bullets.append({"text": f"Scanned address: {spec['defanged_url']}", "source": "scan record"})
    return bullets[:MAX_BULLETS]


def build(index: dict, reviews: dict, drafts: dict, inspections: dict, repo: str | None,
          out: Path, root: Path = ROOT, now: datetime | None = None) -> dict:
    published = {r["id"] for r in reviews.get("items", [])}
    specimens = []
    (out / "shots").mkdir(parents=True, exist_ok=True)
    for s in sorted(index.get("specimens", []), key=lambda x: (x["captured_at"], x["id"]), reverse=True):
        src = root / s["image"]["path"]
        name = Path(s["image"]["path"]).name
        has_image = src.exists()
        if has_image:
            shutil.copyfile(src, out / "shots" / name)
        issue = drafts.get(s["id"])
        status = "published" if s["id"] in published else ("drafted" if issue else "unwritten")
        specimens.append({
            "id": s["id"], "scan_id": s["scan_id"], "domain": s.get("defanged_domain"),
            "captured_at": s["captured_at"], "status": status,
            "image": f"shots/{name}" if has_image else None,
            "title": s.get("page_title"), "bullets": evidence_bullets(s, inspections.get(s["id"])),
            "source_record_url": s["source_record_url"],
            "draft_issue": issue, "repeat_captures": len(s.get("also_captured", [])),
        })
    data = {
        "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fixture": bool(index.get("fixture")), "repo": repo, "specimens": specimens,
        "counts": {k: sum(1 for x in specimens if x["status"] == k)
                   for k in ("unwritten", "drafted", "published")},
    }
    (out / "data.json").write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    a = ap.parse_args()
    d = ROOT / "data"
    data = build(load(d / "archive.json", {"specimens": []}), load(d / "reviews.json", {"items": []}),
                 load(d / "archive_drafts.json", {}), load(d / "archive_inspections.json", {}),
                 a.repo, a.out)
    print(f"Built archive: {len(data['specimens'])} specimen(s) {data['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
