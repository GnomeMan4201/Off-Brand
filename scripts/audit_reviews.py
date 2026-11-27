"""Read-only evidence audit of every published review in data/reviews.json.

For each review it re-reads the urlscan.io scan record named in the review (to recover
the scan's submission source, tags and final host), looks the scanned address up in the
PhishTank dump and, optionally, the OpenPhish feed, and computes the evidence level with
the same rules as new specimens (scripts/evidence.py).

It never modifies data/reviews.json or anything else in data/, never contacts a reported
site, and writes only the report files named on the command line. By default the report
uses only sources that may be republished (OpenPhish is private-triage only); pass
--include-private-sources for a local, unshared run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import evidence
import feeds
from normalize import refang

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / "data" / "reviews.json"
UUID_RE = re.compile(r"^https://urlscan\.io/result/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/")
BUCKETS = (
    ("exact_corroboration", "Exact URL corroboration (Corroborated)"),
    ("source_confirmed", "Source-confirmed"),
    ("suspected", "Suspected (not confirmed)"),
    ("domain_only", "Domain-only matches (other pages on the same host, nothing for this page)"),
    ("missing_evidence", "Missing evidence (Unverified)"),
    ("conflicting", "Conflicting evidence (Disputed)"),
    ("unavailable_sources", "At least one source unavailable"),
)


def scan_record(uuid: str, opener=None, api_key: str = "") -> tuple[dict | None, str]:
    """(urlscan result JSON, status). Only urlscan.io is contacted."""
    url = f"https://urlscan.io/api/v1/result/{uuid}/"
    try:
        raw, _ = feeds._http_get(url, 16 * 1024 * 1024, opener, {"API-Key": api_key} if api_key else None)
    except Exception as exc:  # noqa: BLE001
        snap = feeds._failure("urlscan.io", exc)
        return None, snap.status
    try:
        data = json.loads(raw.decode("utf-8"))
        return (data, "ok") if isinstance(data, dict) else (None, "malformed")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "malformed"


def audit_item(item: dict, snapshots: list, scan: dict | None, scan_status: str, public: bool) -> dict:
    task, page = (scan or {}).get("task") or {}, (scan or {}).get("page") or {}
    url = refang(item.get("defanged_url") or "")
    lead = evidence.urlscan_record(item.get("public_record_url"), task.get("source"), task.get("tags"),
                                   item.get("scanned_at")) if scan else None
    ev = evidence.assess(url, lead=lead, snapshots=snapshots, final_host=page.get("domain"),
                         captured_at=item.get("scanned_at"))
    if scan_status != "ok":
        ev["sources"]["urlscan.io"] = {"status": scan_status, "detail": "scan record could not be re-read",
                                       "checked_at": None}
        ev["level"], ev["reason"] = evidence.classify(ev["records"], ev["sources"])
    if public:
        ev = evidence.public_view(ev)
    feed_records = [r for r in ev["records"] if r["source"] != "urlscan.io"]
    exact = [r for r in feed_records if r["match"] == "exact"]
    host = [r for r in feed_records if r["match"] == "same_host"]
    unavailable = sorted(n for n, s in ev["sources"].items() if s["status"] not in ("ok", "not_attempted"))
    buckets = {
        "exact_corroboration": ev["level"] == "corroborated",
        "source_confirmed": ev["level"] == "source-confirmed",
        "suspected": ev["level"] == "suspected",
        "domain_only": bool(host) and not exact,
        "missing_evidence": ev["level"] == "unverified",
        "conflicting": ev["level"] == "disputed",
        "unavailable_sources": bool(unavailable),
    }
    return {
        "id": item.get("id"), "brand": item.get("impersonated_brand"), "level": ev["level"],
        "reason": ev["reason"], "exact_feed_matches": [f"{r['source']} ({r['strength']})" for r in exact],
        "same_host_matches": [r["source"] for r in host], "unavailable_sources": unavailable,
        "scan_source": task.get("source"), "redirected": ev["specimen"]["redirected"],
        "published_level": (item.get("evidence") or {}).get("level"), "buckets": buckets, "evidence": ev,
    }


def report_markdown(report: dict) -> str:
    lines = ["## Off-Brand historical evidence audit", "",
             f"Run {report['run_at']}. {report['review_count']} published reviews. Read-only: no review was changed.",
             f"Sources: " + ", ".join(f"{n} {s}" for n, s in report["sources"].items()),
             f"View: {'public (republishable sources only)' if report['public_view'] else 'private (includes OpenPhish; do not share)'}",
             "", "| Bucket | Reviews |", "|---|---|"]
    for key, label in BUCKETS:
        lines.append(f"| {label} | {report['counts'][key]} |")
    lines += ["", "| Review | Brand | Level | Exact feed matches | Same-host only | Unavailable | Redirected |",
              "|---|---|---|---|---|---|---|"]
    for r in report["items"]:
        lines.append("| `{id}` | {brand} | {level} | {exact} | {host} | {unav} | {redir} |".format(
            id=r["id"], brand=(r["brand"] or "").replace("|", "/"), level=evidence.LABELS[r["level"]],
            exact=", ".join(r["exact_feed_matches"]) or "—", host=", ".join(r["same_host_matches"]) or "—",
            unav=", ".join(r["unavailable_sources"]) or "—",
            redir={True: "yes", False: "no", None: "unknown"}[r["redirected"]]))
    lines += ["", "PhishTank's dump lists only verified phishes that are still online, so older specimens are "
              "often absent from it; that absence is not evidence the page was benign."]
    return "\n".join(lines) + "\n"


def run(reviews: dict, snapshots: list, fetch_scan, public: bool = True, pause: float = 0.0) -> dict:
    items, scan_stopped, scan_status = [], None, Counter()
    for item in reviews.get("items", []):
        m = UUID_RE.match(item.get("public_record_url") or "")
        scan, status = (None, "not_attempted")
        if m and fetch_scan and not scan_stopped:
            scan, status = fetch_scan(m.group(1))
            if status == "rate_limited":
                scan_stopped = status  # stop asking; remaining items are marked unavailable
            time.sleep(pause)
        elif scan_stopped:
            status = scan_stopped
        scan_status[status] += 1
        items.append(audit_item(item, snapshots, scan, status, public))
    counts = Counter()
    for it in items:
        for key, hit in it["buckets"].items():
            counts[key] += int(hit)
    return {
        "run_at": feeds.now_iso(), "review_count": len(items), "public_view": public,
        "sources": {s.source: s.status for s in snapshots if public is False or s.public}
        | {"urlscan.io": ("scan records not re-read" if not fetch_scan else
                          "scan records re-read: " + ", ".join(f"{n} {k}" for k, n in sorted(scan_status.items())))},
        "counts": {k: counts[k] for k, _ in BUCKETS}, "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--no-urlscan", action="store_true", help="do not re-read urlscan scan records")
    ap.add_argument("--include-private-sources", action="store_true",
                    help="also use OpenPhish (private report; do not publish or share it)")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between urlscan record requests")
    a = ap.parse_args(argv)
    out = a.out_dir.resolve()
    if out == (ROOT / "data").resolve() or (ROOT / "data").resolve() in out.parents:
        print("Refusing to write the audit report into data/.", file=sys.stderr)
        return 2
    reviews = json.loads(REVIEWS.read_text(encoding="utf-8"))
    snapshots = [feeds.fetch_phishtank()]
    if a.include_private_sources:
        snapshots.append(feeds.fetch_openphish())
    key = os.environ.get("URLSCAN_API_KEY", "").strip()
    fetch = None if a.no_urlscan else (lambda uuid: scan_record(uuid, api_key=key))
    report = run(reviews, snapshots, fetch, public=not a.include_private_sources, pause=a.pause)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = report_markdown(report)
    (out / "audit.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
