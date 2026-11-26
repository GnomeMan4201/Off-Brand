"""Fetch real phishing candidates from public records without contacting targets.

Sources:
1. urlscan.io Public Search API (uses URLSCAN_API_KEY if set; falls back to public quota)
2. OpenPhish Community Feed (https://openphish.com/feed.txt)
"""

from __future__ import annotations

import json
import os
import sys
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


def fetch_urlscan_candidates(limit: int = 5) -> list[dict]:
    api_key = os.environ.get("URLSCAN_API_KEY", "").strip()
    params = urlencode({"q": "verdicts.urlscan.malicious:true AND task.tags:phishing", "size": limit})
    url = f"https://urlscan.io/api/v1/search/?{params}"
    headers = {"User-Agent": "OffBrand-Triage/0.1"}
    if api_key:
        headers["API-Key"] = api_key

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
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
        candidates.append(
            {
                "id": f"urlscan-{scan_id}",
                "source": "urlscan.io",
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


def fetch_openphish_candidates(limit: int = 5) -> list[dict]:
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
        candidates.append(
            {
                "id": f"openphish-{abs(hash(raw_url))}",
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


def main() -> int:
    reviews_data = load_json(REVIEWS_PATH, {"items": []})
    seen_ids = set(load_json(SEEN_PATH, []))
    published_ids = {item["id"] for item in reviews_data.get("items", [])}

    raw_candidates = fetch_urlscan_candidates(limit=5)
    if not raw_candidates:
        raw_candidates = fetch_openphish_candidates(limit=5)

    fresh = [
        c for c in raw_candidates if c["id"] not in seen_ids and c["id"] not in published_ids
    ][:3]

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
