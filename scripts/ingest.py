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
import re
import sys
from datetime import datetime, timezone
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
    "AND task.visibility:public AND page.status:200 AND date:>now-{days}d"
)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def infer_tells(raw_url: str, domain: str | None) -> list[str]:
    """Literal, checkable observations only. None of these identify a brand."""
    tells: list[str] = []
    if not domain:
        return tells
    lower_dom = domain.lower()
    for tld in SUSPICIOUS_TLDS:
        if lower_dom.endswith(tld):
            tells.append(f"Domain ends in {tld}, a low-cost top-level domain often seen in phishing")
            break
    for suffix in FREE_PAAS_SUFFIXES:
        if lower_dom.endswith(suffix):
            tells.append(f"Hosted on a free hosting subdomain ({suffix})")
            break
    dots = lower_dom.count(".")
    if dots >= 2:
        tells.append(f"Hostname has {dots + 1} dot-separated labels (subdomain depth only; does not show which brand is imitated)")
    path = urlparse(raw_url).path.lower()
    for k in ("login", "logowanie", "verify", "wallet", "signin"):
        if k in path:
            tells.append(f"URL path contains '{k}'")
            break
    return tells


def record_brand(item: dict) -> str | None:
    """A brand only when the scan record itself names one. Never guessed from the domain."""
    candidates = []
    b = item.get("brand")
    if isinstance(b, list):
        candidates += b
    elif isinstance(b, dict):
        candidates.append(b)
    brands = ((item.get("verdicts") or {}).get("urlscan") or {}).get("brands")
    if isinstance(brands, list):
        candidates += brands
    for c in candidates:
        if isinstance(c, dict):
            name = c.get("name") or c.get("key")
        else:
            name = c if isinstance(c, str) else None
        name = sanitize_text(name, max_len=60)
        if name:
            return name
    return None


def fetch_urlscan_candidates(limit: int = 100, days: int = 7) -> list[dict]:
    api_key = os.environ.get("URLSCAN_API_KEY", "").strip()
    params = urlencode({"q": URLSCAN_FREE_QUERY.format(days=int(days)), "size": limit})
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
                "scan_uuid": scan_id,
                "record_brand": record_brand(item),
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
                "scan_uuid": None,
                "record_brand": None,
            }
        )
    return candidates


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
INTAKE_LOG_PATH = ROOT / "data" / "intake_log.json"
DAILY_CAP = 10
BACKFILL_CAP = 30
BRAND_RUN_LIMIT = 2  # never more than 2 of the same named brand in a row


def screenshot_available(scan_uuid: str | None) -> bool:
    """Ask urlscan (never the phishing site) whether the archived screenshot exists."""
    if not scan_uuid or not UUID_RE.match(scan_uuid):
        return False
    url = f"https://urlscan.io/screenshots/{scan_uuid}.png"
    for method in ("HEAD", "GET"):
        req = Request(url, method=method, headers={"User-Agent": "OffBrand-Triage/0.1"})
        try:
            with urlopen(req, timeout=20) as resp:
                ctype = resp.headers.get("Content-Type", "")
                return resp.status == 200 and ctype.startswith("image/")
        except HTTPError as exc:
            if exc.code == 405 and method == "HEAD":
                continue
            return False
        except (URLError, TimeoutError):
            return False
    return False


def select_candidates(
    candidates: list[dict],
    known_ids: set[str],
    limit: int,
    recent_brands: list[str],
    has_screenshot=screenshot_available,
) -> list[dict]:
    """Pick up to `limit` new candidates that have an archived screenshot,
    keeping brand variety where the record names a brand."""
    excluded = set(known_ids)
    chosen: list[dict] = []
    brands = list(recent_brands)
    for c in candidates:
        if len(chosen) >= limit:
            break
        if c["id"] in excluded:
            continue
        excluded.add(c["id"])
        brand = (c.get("record_brand") or "").strip().lower() or None
        if brand and len(brands) >= BRAND_RUN_LIMIT and all(b == brand for b in brands[-BRAND_RUN_LIMIT:]):
            continue
        if not has_screenshot(c.get("scan_uuid")):
            continue
        chosen.append(c)
        if brand:
            brands.append(brand)
    return chosen


def load_intake_log() -> dict:
    log = load_json(INTAKE_LOG_PATH, {})
    log.setdefault("daily", {})
    log.setdefault("recent_brands", [])
    log.setdefault("backfill_runs", [])
    return log


def save_intake_log(log: dict, today: str) -> None:
    keep = sorted(log["daily"])[-14:]
    log["daily"] = {d: log["daily"][d] for d in keep}
    log["recent_brands"] = log["recent_brands"][-20:]
    log["backfill_runs"] = log["backfill_runs"][-20:]
    INTAKE_LOG_PATH.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("daily", "backfill"), default="daily")
    ap.add_argument("--limit", type=int, default=None,
                    help="daily: ignored (shared cap of 10/day); backfill: max 30")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args(argv)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = load_intake_log()

    if args.mode == "daily":
        used = int(log["daily"].get(today, 0))
        limit = max(0, DAILY_CAP - used)
        print(f"Daily intake: {used}/{DAILY_CAP} used today, {limit} remaining.")
    else:
        limit = min(BACKFILL_CAP, args.limit or BACKFILL_CAP)
        print(f"Backfill intake: up to {limit} from the last {args.days} days.")

    reviews_data = load_json(REVIEWS_PATH, {"items": []})
    seen_ids = set(load_json(SEEN_PATH, []))
    published_ids = {item["id"] for item in reviews_data.get("items", [])}
    known_ids = seen_ids | published_ids

    fresh: list[dict] = []
    if limit > 0:
        fresh = select_candidates(
            fetch_urlscan_candidates(limit=100, days=args.days), known_ids, limit, log["recent_brands"]
        )
        # OpenPhish has no archived screenshots, so it can only be used if a
        # future version links its URLs to urlscan scans. Kept for the record.
        if not fresh:
            print("No urlscan candidates with archived screenshots; OpenPhish fallback has none, skipping.")

    out_path = ROOT / "data" / "pending_candidates.json"
    out_path.write_text(json.dumps(fresh, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    if fresh:
        for c in fresh:
            seen_ids.add(c["id"])
            if c.get("record_brand"):
                log["recent_brands"].append(c["record_brand"].strip().lower())
        SEEN_PATH.write_text(json.dumps(sorted(seen_ids), indent=2) + "\n", encoding="utf-8")
    if args.mode == "daily":
        log["daily"][today] = int(log["daily"].get(today, 0)) + len(fresh)
    else:
        log["backfill_runs"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     "days": args.days, "count": len(fresh)})
    save_intake_log(log, today)

    print(f"Staged {len(fresh)} new candidate(s) for human review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
