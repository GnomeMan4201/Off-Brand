"""Read-only health check for Off-Brand's intelligence sources.

Checks urlscan.io (one search request), the OpenPhish community feed and the PhishTank
dump: HTTP status, response format, record counts, data freshness, rate limiting and the
last successful retrieval (carried from the previous report, if one is supplied).

It only contacts the providers' own hosts (scripts/feeds.py refuses anything else and
any redirect away from them). It never contacts a reported site, never writes to data/,
never opens issues and never publishes anything. Output: a JSON report and a Markdown
summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import feeds
from ingest import URLSCAN_FREE_QUERY

ROOT = Path(__file__).resolve().parent.parent
# How old the newest data may be before it is called stale.
FRESH_WITHIN = {"urlscan.io": timedelta(days=2), "OpenPhish": timedelta(days=2), "PhishTank": timedelta(days=3)}
URLSCAN_PROBE = "https://urlscan.io/api/v1/search/?" + urlencode({"q": URLSCAN_FREE_QUERY, "size": 1})


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fn in (lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")),
               lambda t: datetime.strptime(t, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)):
        try:
            dt = fn(str(ts).strip())
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def freshness(source: str, newest: str | None, now: datetime) -> str:
    dt = _parse(newest)
    if dt is None:
        return "unknown"
    return "fresh" if now - dt <= FRESH_WITHIN[source] else "stale"


def probe_urlscan(opener=None, api_key: str | None = None) -> feeds.Snapshot:
    key = (api_key if api_key is not None else os.environ.get("URLSCAN_API_KEY", "")).strip()
    try:
        raw, meta = feeds._http_get(URLSCAN_PROBE, 4 * 1024 * 1024, opener, {"API-Key": key} if key else None)
    except Exception as exc:  # noqa: BLE001 - mapped to an explicit status
        snap = feeds._failure("urlscan.io", exc)
        if key:
            snap.detail = snap.detail.replace(key, "<key>")
        return snap
    try:
        payload = json.loads(raw.decode("utf-8"))
        results = payload["results"]
        if not isinstance(results, list):
            raise ValueError("results is not a list")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return feeds.Snapshot("urlscan.io", "malformed", f"unexpected search response: {exc}"[:160], feeds.now_iso(), meta=meta)
    total = payload.get("total")
    meta["record_count"] = total if isinstance(total, int) else len(results)
    newest = (results[0].get("task") or {}).get("time") if results and isinstance(results[0], dict) else None
    meta["newest_record_at"] = newest
    remaining = (meta.get("rate_limit") or {}).get("X-Rate-Limit-Remaining")
    detail = f"search OK, {meta['record_count']} matching scans in the last 7 days"
    if remaining is not None:
        detail += f"; {remaining} search requests left in this window"
    return feeds.Snapshot("urlscan.io", "ok", detail, feeds.now_iso(), meta=meta)


def row(snap: feeds.Snapshot, previous: dict, now: datetime) -> dict:
    meta = dict(snap.meta or {})
    count = meta.get("record_count", len(snap.records) if snap.ok else None)
    newest = meta.get("newest_record_at") or meta.get("last_modified")
    last_ok = snap.fetched_at if snap.ok else (previous.get(snap.source) or {}).get("last_success")
    return {
        "source": snap.source, "status": snap.status, "detail": snap.detail,
        "http_status": meta.get("http_status"),
        "format_valid": snap.ok,
        "record_count": count, "skipped_records": snap.skipped if snap.ok else None,
        "newest_data": newest, "freshness": freshness(snap.source, newest, now) if snap.ok else "unknown",
        "rate_limited": snap.status == "rate_limited",
        "rate_limit": meta.get("rate_limit") or {},
        "checked_at": snap.fetched_at, "last_success": last_ok,
    }


def markdown(report: dict) -> str:
    lines = ["## Off-Brand source health", "",
             f"Checked {report['checked_at']}. Read-only: no issues, no publishing, no reported sites contacted.", "",
             "| Source | Status | HTTP | Format | Records | Newest data | Freshness | Rate limited | Last success |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in report["sources"]:
        lines.append("| {source} | {status} | {http} | {fmt} | {count} | {newest} | {fresh} | {rl} | {last} |".format(
            source=r["source"], status=r["status"], http=r["http_status"] or "—",
            fmt="valid" if r["format_valid"] else "—", count=r["record_count"] if r["record_count"] is not None else "—",
            newest=r["newest_data"] or "—", fresh=r["freshness"], rl="yes" if r["rate_limited"] else "no",
            last=r["last_success"] or "never recorded"))
    lines.append("")
    for r in report["sources"]:
        lines.append(f"- **{r['source']}**: {r['detail']}")
    skipped = report.get("not_checked") or []
    if skipped:
        lines.append(f"- Not checked this run (by request): {', '.join(skipped)}")
    return "\n".join(lines) + "\n"


CHECKS = {
    "urlscan.io": lambda: probe_urlscan(),
    "OpenPhish": lambda: feeds.fetch_openphish(),
    "PhishTank": lambda: feeds.fetch_phishtank(),
}


def run(selected: list[str], previous: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    prev = {r["source"]: r for r in (previous.get("sources") or []) if isinstance(r, dict) and "source" in r}
    rows = [row(CHECKS[name](), prev, now) for name in selected]
    for name in CHECKS:
        if name not in selected and name in prev:
            rows.append(dict(prev[name], status="not_checked", detail="not checked this run (by request)",
                             rate_limited=False))
    return {"checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": rows,
            "not_checked": [n for n in CHECKS if n not in selected]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip", action="append", default=[], choices=sorted(CHECKS),
                    help="source to leave out (e.g. PhishTank, to save its few daily downloads)")
    ap.add_argument("--previous", type=Path, help="previous report JSON, for last successful retrieval")
    ap.add_argument("--out", type=Path, required=True, help="where to write the JSON report")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any checked source is not ok")
    a = ap.parse_args(argv)
    out = a.out.resolve()
    if (ROOT / "data").resolve() in out.parents:
        print("Refusing to write the report into data/.", file=sys.stderr)
        return 2
    previous = {}
    if a.previous and a.previous.exists():
        try:
            previous = json.loads(a.previous.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    report = run([n for n in CHECKS if n not in a.skip], previous)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(markdown(report))
    bad = [r for r in report["sources"] if r["status"] not in ("ok", "not_checked")]
    return 1 if a.strict and bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
