"""Open one triage issue per staged candidate, then post a model draft on it.

Run by the ingest and backfill workflows after scripts/ingest.py.
Needs `gh` (GH_TOKEN) and, for drafts, a running Ollama server.
Set OFFBRAND_NO_DRAFT=1 to open issues without drafts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft import draft  # noqa: E402
from voices import assign_batch, assignment_markdown  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def issue_body(c: dict, a: dict) -> str:
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
        "### Auto-detected observations",
        *[f"- {t}" for t in c.get("auto_tells", [])],
        "",
        *assignment_markdown(a),
        "",
        "### How to publish from your phone",
        "A draft review is posted below as a comment. Check it against the screenshot on the public record, "
        "fix anything wrong, replace every `Needs editor verification`, then add the `approved` label.",
        "Only the review inside the ```review block of the latest trusted comment posted before you add the label is published.",
    ])


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    p = ROOT / "data" / "pending_candidates.json"
    if not p.exists():
        return 0
    candidates = json.loads(p.read_text(encoding="utf-8"))
    if not candidates:
        return 0
    published = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8")).get("items", [])
    assignments = assign_batch(published, [c["id"] for c in candidates])
    no_draft = os.environ.get("OFFBRAND_NO_DRAFT") == "1"
    timings = []

    for c in candidates:
        a = assignments[c["id"]]
        title = f"[Triage] {c.get('defanged_domain') or c['id']}"
        url = gh("issue", "create", "--title", title, "--body", issue_body(c, a), "--label", "triage")
        print(f"opened {url}")
        if no_draft:
            continue
        comment, secs = draft(c, a)
        if secs is not None:
            timings.append(secs)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(comment)
        gh("issue", "comment", url, "--body-file", f.name)
        print(f"drafted {url} in {secs:.1f}s" if secs is not None else f"drafted {url} (no model output)")

    if timings:
        print(f"draft timing: n={len(timings)} avg={sum(timings)/len(timings):.1f}s max={max(timings):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
