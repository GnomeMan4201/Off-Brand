"""Fetch real phishing candidates from public records without contacting targets.

Sources:
1. urlscan.io Public Search API (free-tier searchable fields only; uses URLSCAN_API_KEY if set)
2. OpenPhish Community Feed (https://openphish.com/feed.txt) as fallback
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from sanitize import defang_domain, defang_url, sanitize_text, validate_public_record_url

ROOT = Path(__file__).resolve().parent.parent
REVIEWS_PATH = ROOT / "data" / "reviews.json"
SEEN_PATH = ROOT / "data" / "seen.json"

SUSPICIOUS_TLDS = {".top", ".xyz", ".click", ".icu", ".buzz", ".shop", ".cfd", ".sbs"}
FREE_PAAS_SUFFIXES = (".vercel.app", ".pages.dev", ".netlify.app", ".workers.dev", ".github.io")

# Free-tier urlscan.io search fields only (verdicts.* and brand.* require Pro+).
# task.source:(openphish OR phishtank) captures scans originated from those feeds;
# task.tags:phishing captures community-tagged phishing submissions.
URLSCAN_FREE_QUERY = (
    "(task.source:openphish OR task.source:phishtank OR task.tags:phishing) "
    "AND task.visibility:public AND page.status:200 AND date:>now-7d"
)
BACKFILL_CAP = 30
BACKFILL_FETCH_SIZE = 100


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def infer_tells(raw_url: str, domain: str | None) -> list[str]:
    tells: list[str] = []
    if not domain:
        return tells
    lower_dom = domain.lower()
    for tld in SUSPICIOUS_TLDS:
        if lower_dom.endswith(tld):
            tells.append(f"Disposable/budget TLD ({tld})")
            break
    for suffix in FREE_PAAS_SUFFIXES:
        if lower_dom.endswith(suffix):
            tells.append(f"Hosted on free static PaaS ({suffix})")
            break
    if lower_dom.count(".") >= 2:
        tells.append("Brand/keyword stuffed into subdomain")
    parsed = urlparse(raw_url)
    if any(k in parsed.path.lower() for k in ("login", "logowanie", "verify", "wallet", "signin")):
        tells.append("Credential/wallet lure keyword in URL path")
    return tells


def fetch_urlscan_candidates(limit: int = 25, days: int = 7) -> list[dict]:
    api_key = os.environ.get("URLSCAN_API_KEY", "").strip()
    query = URLSCAN_FREE_QUERY.replace("date:>now-7d", f"date:>now-{int(days)}d")
    params = urlencode({"q": query, "size": limit})
    url = f"https://urlscan.io/api/v1/search/?{params}"
    headers = {"User-Agent": "OffBrand-Triage/0.1"}
    if api_key:
        headers["API-Key"] = api_key

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"[warn] urlscan.io HTTP {exc.code}: {body}", file=sys.stderr)
        return []
    except (URLError, TimeoutError) as exc:
        print(f"[warn] urlscan.io fetch skipped: {exc}", file=sys.stderr)
        return []

    candidates = []
    for item in payload.get("results", []):
        task = item.get("task", {})
        page = item.get("page", {})
        raw_url = task.get("url") or page.get("url")
        scan_id = item.get("_id")
        if not raw_url or not scan_id:
            continue
        record_url = validate_public_record_url(f"https://urlscan.io/result/{scan_id}/report/")
        defanged = defang_url(raw_url)
        domain = page.get("domain") or urlparse(raw_url).hostname
        if not defanged or not record_url:
            continue

        source_tag = sanitize_text(task.get("source"), max_len=40)
        source_label = f"urlscan.io (source: {source_tag})" if source_tag else "urlscan.io"

        candidates.append(
            {
                "id": f"urlscan-{scan_id}",
                "source": source_label,
                "public_record_url": record_url,
                "defanged_url": defanged,
                "defanged_domain": defang_domain(domain),
                "ip": sanitize_text(page.get("ip"), max_len=64),
                "asn_name": sanitize_text(page.get("asnname"), max_len=120),
                "page_title": sanitize_text(page.get("title"), max_len=140),
                "scanned_at": sanitize_text(task.get("time"), max_len=40),
                "auto_tells": infer_tells(raw_url, domain),
            }
        )
    return candidates


def fetch_openphish_candidates(limit: int = 25) -> list[dict]:
    req = Request("https://openphish.com/feed.txt", headers={"User-Agent": "OffBrand-Triage/0.1"})
    try:
        with urlopen(req, timeout=20) as resp:
            lines = resp.read().decode("utf-8", errors="replace").splitlines()
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"[warn] OpenPhish fetch skipped: {exc}", file=sys.stderr)
        return []

    candidates = []
    for raw_url in lines[:limit]:
        raw_url = raw_url.strip()
        if not raw_url:
            continue
        defanged = defang_url(raw_url)
        domain = urlparse(raw_url).hostname
        if not defanged or not domain:
            continue
        url_digest = hashlib.sha256(raw_url.encode("utf-8")).hexdigest()[:16]
        candidates.append(
            {
                "id": f"openphish-{url_digest}",
                "source": "OpenPhish Community Feed",
                "public_record_url": "https://openphish.com/feed.txt",
                "defanged_url": defanged,
                "defanged_domain": defang_domain(domain),
                "ip": None,
                "asn_name": None,
                "page_title": None,
                "scanned_at": None,
                "auto_tells": infer_tells(raw_url, domain),
            }
        )
    return candidates


def filter_fresh(candidates: list[dict], known_ids: set[str]) -> list[dict]:
    excluded = known_ids.copy()
    fresh = []
    for candidate in candidates:
        candidate_id = candidate["id"]
        if candidate_id in excluded:
            continue
        fresh.append(candidate)
        excluded.add(candidate_id)
        if len(fresh) == 3:
            break
    return fresh


def parse_scanned_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def has_urlscan_screenshot(candidate: dict) -> bool:
    """True if urlscan holds an archived screenshot. Contacts urlscan only, never the target."""
    cid = candidate["id"]
    if not cid.startswith("urlscan-"):
        return False
    req = Request(
        f"https://urlscan.io/screenshots/{cid[len('urlscan-'):]}.png",
        headers={"User-Agent": "OffBrand-Triage/0.1"},
    )
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.headers.get_content_type().startswith("image/")
    except (HTTPError, URLError, TimeoutError):
        return False


def select_backfill(
    candidates: list[dict],
    known_ids: set[str],
    limit: int = BACKFILL_CAP,
    days: int = 7,
    now: datetime | None = None,
    screenshot_check=has_urlscan_screenshot,
) -> list[dict]:
    """Up to `limit` distinct, recent, screenshot-backed candidates not already known."""
    limit = max(0, min(int(limit), BACKFILL_CAP))
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    excluded = set(known_ids)
    seen_urls: set[str] = set()
    picked: list[dict] = []
    for c in candidates:
        if len(picked) >= limit:
            break
        if c["id"] in excluded or c["defanged_url"] in seen_urls:
            continue
        scanned = parse_scanned_at(c.get("scanned_at"))
        if scanned is None or scanned < cutoff:
            continue
        if not screenshot_check(c):
            continue
        picked.append(c)
        excluded.add(c["id"])
        seen_urls.add(c["defanged_url"])
    return picked


def run_backfill(limit: int, days: int) -> int:
    reviews_data = load_json(REVIEWS_PATH, {"items": []})
    seen_ids = set(load_json(SEEN_PATH, []))
    known_ids = seen_ids | {item["id"] for item in reviews_data.get("items", [])}
    picked = select_backfill(
        fetch_urlscan_candidates(limit=BACKFILL_FETCH_SIZE, days=days), known_ids, limit, days
    )
    out_path = ROOT / "data" / "pending_candidates.json"
    out_path.write_text(json.dumps(picked, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Backfill staged {len(picked)} candidate(s) from the last {days} day(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    parser.add_argument("--limit", type=int, default=BACKFILL_CAP)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if args.mode == "backfill":
        return run_backfill(args.limit, args.days)

    reviews_data = load_json(REVIEWS_PATH, {"items": []})
    seen_ids = set(load_json(SEEN_PATH, []))
    published_ids = {item["id"] for item in reviews_data.get("items", [])}

    known_ids = seen_ids | published_ids
    fresh = filter_fresh(fetch_urlscan_candidates(limit=25), known_ids)
    if not fresh:
        fresh = filter_fresh(fetch_openphish_candidates(limit=25), known_ids)

    out_path = ROOT / "data" / "pending_candidates.json"
    out_path.write_text(json.dumps(fresh, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    if fresh:
        for c in fresh:
            seen_ids.add(c["id"])
        SEEN_PATH.write_text(json.dumps(sorted(seen_ids), indent=2) + "\n", encoding="utf-8")

    print(f"Staged {len(fresh)} new candidate(s) for human review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
