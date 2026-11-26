"""Fetch real phishing candidates from public records without contacting targets.

Sources:
1. urlscan.io Public Search API (free-tier searchable fields only; uses URLSCAN_API_KEY if set)
Only urlscan results with retrievable archived screenshots enter the editorial queue.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import UUID

from sanitize import (
    defang_domain,
    defang_url,
    sanitize_text,
    validate_public_record_url,
)

ROOT = Path(__file__).resolve().parent.parent
REVIEWS_PATH = ROOT / "data" / "reviews.json"
SEEN_PATH = ROOT / "data" / "seen.json"

SUSPICIOUS_TLDS = {".top", ".xyz", ".click", ".icu", ".buzz", ".shop", ".cfd", ".sbs"}
FREE_PAAS_SUFFIXES = (
    ".vercel.app",
    ".pages.dev",
    ".netlify.app",
    ".workers.dev",
    ".github.io",
)

# Hints for scheduling only. Unknown records share a bucket.
BRANDS = {
    "Microsoft",
    "Office 365",
    "PayPal",
    "Apple",
    "Google",
    "Amazon",
    "Facebook",
    "MetaMask",
    "Coinbase",
    "Allegro",
    "DHL",
    "USPS",
    "Netflix",
    "Adobe",
    "DocuSign",
    "Dropbox",
    "Instagram",
    "Steam",
    "Roblox",
    "Telegram",
}
# Free-tier urlscan.io search fields only (verdicts.* and brand.* require Pro+).
# task.source:(openphish OR phishtank) captures scans originated from those feeds;
# task.tags:phishing captures community-tagged phishing submissions.
URLSCAN_FREE_QUERY = (
    "(task.source:openphish OR task.source:phishtank OR task.tags:phishing) "
    "AND task.visibility:public AND page.status:200 AND date:>now-7d"
)


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
            tells.append(f"Domain ends in ({tld})")
            break
    for suffix in FREE_PAAS_SUFFIXES:
        if lower_dom.endswith(suffix):
            tells.append(f"Hostname uses hosting suffix ({suffix})")
            break
    if lower_dom.count(".") >= 2:
        tells.append("Hostname contains multiple labels")
    parsed = urlparse(raw_url)
    if any(
        k in parsed.path.lower()
        for k in ("login", "logowanie", "verify", "wallet", "signin")
    ):
        tells.append("Credential/wallet lure keyword in URL path")
    return tells


def fetch_urlscan_candidates(limit: int = 25) -> list[dict]:
    api_key = os.environ.get("URLSCAN_API_KEY", "").strip()
    params = urlencode({"q": URLSCAN_FREE_QUERY, "size": limit})
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
        record_url = validate_public_record_url(
            f"https://urlscan.io/result/{scan_id}/report/"
        )
        defanged = defang_url(raw_url)
        domain = page.get("domain") or urlparse(raw_url).hostname
        if not defanged or not record_url:
            continue
        if not domain:
            continue

        source_tag = sanitize_text(task.get("source"), max_len=40)
        source_label = (
            f"urlscan.io (source: {source_tag})" if source_tag else "urlscan.io"
        )

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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def screenshot(scan_id):
    try:
        uid = str(UUID(scan_id))
    except (ValueError, TypeError):
        return None
    url = f"https://urlscan.io/screenshots/{uid}.png"
    try:
        with build_opener(NoRedirect()).open(url, timeout=8) as response:
            if response.read(8) == bytes.fromhex("89504e470d0a1a0a"):
                return url
    except (OSError, HTTPError):
        pass
    return None


def brand_hint(candidate, brands):
    text = (
        candidate["defanged_domain"] + " " + (candidate["page_title"] or "")
    ).casefold()
    for brand in sorted(brands, key=len, reverse=True):
        if brand.casefold() in text or brand.casefold().replace(" ", "") in text:
            return brand.casefold()
    return "unknown"


def select_candidates(candidates, known, history, limit, brands, verify=screenshot):
    selected = []
    recent = list(history[-2:])
    remaining = list(candidates)
    while remaining and len(selected) < limit:
        for index, candidate in enumerate(remaining):
            brand = brand_hint(candidate, brands)
            if candidate["id"] in known:
                continue
            if recent == [brand, brand]:
                continue
            url = verify(candidate["id"].removeprefix("urlscan-"))
            known.add(candidate["id"])
            if not url:
                continue
            candidate.update(screenshot=url, brand_hint=brand)
            selected.append(candidate)
            recent = (recent + [brand])[-2:]
            remaining.pop(index)
            break
        else:
            break
    return selected


if __name__ == "__main__":
    # Local preview uses the same screenshot and diversity checks without opening issues.

    known = set(load_json(SEEN_PATH, []))
    known.update(r["id"] for r in load_json(REVIEWS_PATH, {"items": []})["items"])
    preview = select_candidates(fetch_urlscan_candidates(100), known, [], 5, BRANDS)
    (ROOT / "data/pending_candidates.json").write_text(
        json.dumps(preview, indent=2) + "\n"
    )
