"""Bulk intelligence feeds used for evidence correlation: PhishTank and OpenPhish.

Each feed is downloaded at most once per run and looked up locally, so no suspect URL
is ever sent anywhere and no suspect site is contacted.

A feed that could not be read returns a snapshot whose status says why
("rate_limited", "unavailable", "malformed", "too_large"). Callers must report that
status; an unread feed is never the same as "no record found".

Source limits and licensing are documented in docs/SOURCES.md. In short:
- PhishTank: new accounts/keys not issued since 2020; unkeyed dump downloads are limited
  to a few per day. The dump lists only verified phishes still online. Its license terms
  page could not be retrieved; treat redistribution terms as unconfirmed.
- OpenPhish: the Community Feed terms allow personal/independent research use but bar
  displaying or redistributing the information to third parties without written
  permission. OpenPhish records are therefore used for private triage only and are
  stripped from anything published (see evidence.public_view).

Downloads only go to the fixed feed hosts below; a redirect to any other host is refused.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from normalize import is_shared_host, normalize
from sanitize import sanitize_text

USER_AGENT = os.environ.get(
    "OFFBRAND_FEED_USER_AGENT",
    "OffBrand-Evidence/0.2 (+https://github.com/GnomeMan4201/Off-Brand)")
PHISHTANK_DUMP = "https://data.phishtank.com/data/online-valid.json.gz"
PHISHTANK_KEYED = "https://data.phishtank.com/data/{key}/online-valid.json.gz"
OPENPHISH_FEED = "https://openphish.com/feed.txt"
MAX_COMPRESSED = 64 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_TEXT_FEED = 8 * 1024 * 1024
KEY_RE = re.compile(r"^[A-Za-z0-9]{16,128}$")
FEED_HOST_SUFFIXES = ("phishtank.com", "openphish.com", "urlscan.io")
# Observed 2026-11-27: openphish.com/feed.txt redirects to OpenPhish's own GitHub repository,
# and the PhishTank dump redirects to cdn.phishtank.com. Only these exact extra places are allowed.
REDIRECT_PREFIXES = ("https://raw.githubusercontent.com/openphish/public_feed/",)
# Sources whose records may appear on the public site. OpenPhish's terms bar display to
# third parties without written permission, so its records stay in private triage.
PUBLIC_SOURCES = frozenset({"urlscan.io", "PhishTank"})


def allowed_feed_host(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == s or host.endswith("." + s) for s in FEED_HOST_SUFFIXES)


def allowed_redirect(url: str) -> bool:
    return allowed_feed_host(url) or any(url.startswith(p) for p in REDIRECT_PREFIXES)


class FeedHostOnly(HTTPRedirectHandler):
    """Follow redirects only to the feed providers' own hosts (and OpenPhish's GitHub feed)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_redirect(newurl):
            raise URLError(f"refused redirect to a non-feed host ({urlsplit(newurl).hostname})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(FeedHostOnly)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def phishtank_detail_url(phish_id) -> str | None:
    """PhishTank's own record page, built from a numeric ID, never copied from input."""
    pid = str(phish_id).strip()
    return f"https://www.phishtank.com/phish_detail.php?phish_id={pid}" if pid.isdigit() else None


def _ts(value) -> str | None:
    text = sanitize_text(value, max_len=40)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Snapshot:
    """One feed as read in this run."""
    source: str
    status: str  # ok | rate_limited | unavailable | malformed | too_large | not_attempted
    detail: str = ""
    fetched_at: str | None = None
    records: list[dict] = field(default_factory=list)
    skipped: int = 0
    meta: dict = field(default_factory=dict)  # http_status, last_modified, bytes, newest_record_at
    _exact: dict = field(default_factory=dict, repr=False)
    _host: dict = field(default_factory=dict, repr=False)
    _scheme: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for rec in self.records:
            key = rec.get("_norm")
            if not key:
                continue
            self._exact.setdefault(key["exact_key"], []).append(rec)
            self._scheme.setdefault(key["scheme_key"], []).append(rec)
            if not is_shared_host(key["host_key"]):
                self._host.setdefault(key["host_key"], []).append(rec)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def check(self) -> dict:
        return {"status": self.status, "detail": self.detail, "checked_at": self.fetched_at}

    @property
    def public(self) -> bool:
        return self.source in PUBLIC_SOURCES

    def lookup(self, url: str | None) -> tuple[list[dict], list[dict]]:
        """(exact matches, related matches with scheme-only first). Empty if not ok."""
        norm = normalize(url)
        if not self.ok or not norm:
            return [], []
        exact = list(self._exact.get(norm["exact_key"], []))
        seen = {id(r) for r in exact}
        scheme_only = [r for r in self._scheme.get(norm["scheme_key"], []) if id(r) not in seen]
        seen.update(id(r) for r in scheme_only)
        host = [r for r in self._host.get(norm["host_key"], []) if id(r) not in seen]
        return exact, scheme_only + host


RATE_HEADERS = ("X-Rate-Limit-Limit", "X-Rate-Limit-Remaining", "X-Rate-Limit-Window",
                "X-Rate-Limit-Reset", "X-Rate-Limit-Reset-After", "Retry-After")


def _http_get(url: str, max_bytes: int, opener=None, headers: dict | None = None) -> tuple[bytes, dict]:
    """(body, meta). Only fixed feed hosts may be fetched."""
    if not allowed_feed_host(url):
        raise URLError("refused: not a feed host")
    req = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with (opener or _OPENER.open)(req, timeout=60) as resp:
        body = resp.read(max_bytes + 1)
        hdrs = getattr(resp, "headers", None) or {}
        meta = {"http_status": getattr(resp, "status", None),
                "last_modified": hdrs.get("Last-Modified"),
                "rate_limit": {h: hdrs.get(h) for h in RATE_HEADERS if hdrs.get(h) is not None}}
    if len(body) > max_bytes:
        raise OverflowError(f"response larger than {max_bytes} bytes")
    meta["bytes"] = len(body)
    return body, meta


def _failure(source: str, exc: Exception) -> Snapshot:
    if isinstance(exc, HTTPError):
        hdrs = exc.headers or {}
        meta = {"http_status": exc.code,
                "rate_limit": {h: hdrs.get(h) for h in RATE_HEADERS if hdrs.get(h) is not None}}
        if exc.code in (429, 509):
            return Snapshot(source, "rate_limited", f"HTTP {exc.code}: download limit reached", now_iso(), meta=meta)
        if exc.code in (401, 403):
            return Snapshot(source, "unavailable", f"HTTP {exc.code}: access refused", now_iso(), meta=meta)
        return Snapshot(source, "unavailable", f"HTTP {exc.code}", now_iso(), meta=meta)
    if isinstance(exc, OverflowError):
        return Snapshot(source, "too_large", str(exc), now_iso())
    if isinstance(exc, (URLError, TimeoutError, OSError)):
        return Snapshot(source, "unavailable", f"network error: {sanitize_text(str(exc), 160)}", now_iso())
    raise exc


# ---------------------------------------------------------------- PhishTank

def parse_phishtank(payload) -> tuple[list[dict], int]:
    """Validated PhishTank entries plus a count of skipped malformed ones."""
    if not isinstance(payload, list):
        raise ValueError("PhishTank dump is not a JSON list")
    out, skipped = [], 0
    for row in payload:
        if not isinstance(row, dict):
            skipped += 1
            continue
        detail = phishtank_detail_url(row.get("phish_id"))
        norm = normalize(row.get("url"))
        verified = str(row.get("verified", "")).lower()
        if not detail or not norm or verified not in ("yes", "no"):
            skipped += 1
            continue
        target = sanitize_text(row.get("target"), max_len=80)
        out.append({
            "phish_id": str(row["phish_id"]).strip(),
            "record_url": detail,
            "verified": verified == "yes",
            "online": str(row.get("online", "")).lower() == "yes",
            "submitted_at": _ts(row.get("submission_time")),
            "verified_at": _ts(row.get("verification_time")),
            "target": None if (target or "").lower() in ("", "other") else target,
            "_norm": norm,
        })
    return out, skipped


def fetch_phishtank(opener=None, app_key: str | None = None) -> Snapshot:
    key = (app_key if app_key is not None else os.environ.get("PHISHTANK_APP_KEY", "")).strip()
    if key and not KEY_RE.fullmatch(key):
        return Snapshot("PhishTank", "unavailable", "PHISHTANK_APP_KEY is not a valid key format", now_iso())
    url = PHISHTANK_KEYED.format(key=key) if key else PHISHTANK_DUMP
    try:
        raw, meta = _http_get(url, MAX_COMPRESSED, opener)
    except Exception as exc:  # noqa: BLE001 - mapped to an explicit status
        snap = _failure("PhishTank", exc)
        if key:
            snap.detail = snap.detail.replace(key, "<key>")
        return snap
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            expanded = bytearray()
            while len(expanded) <= MAX_EXPANDED:
                chunk = gz.read(min(1024 * 1024, MAX_EXPANDED + 1 - len(expanded)))
                if not chunk:
                    break
                expanded.extend(chunk)
        if len(expanded) > MAX_EXPANDED:
            return Snapshot("PhishTank", "too_large", "expanded dump exceeds size cap", now_iso(), meta=meta)
        records, skipped = parse_phishtank(json.loads(expanded.decode("utf-8")))
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return Snapshot("PhishTank", "malformed", sanitize_text(str(exc), 160) or "unreadable dump", now_iso(), meta=meta)
    if not records:
        return Snapshot("PhishTank", "malformed", f"dump parsed but held no usable entries ({skipped} skipped)",
                        now_iso(), meta=meta)
    meta["newest_record_at"] = max((r["verified_at"] or r["submitted_at"] or "" for r in records), default=None) or None
    mode = "keyed download" if key else "public download"
    return Snapshot("PhishTank", "ok", f"{len(records)} verified online entries ({mode})",
                    now_iso(), records, skipped, meta=meta)


# ---------------------------------------------------------------- OpenPhish

def parse_openphish(text: str) -> tuple[list[dict], int]:
    out, skipped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        norm = normalize(line)
        if not norm:
            skipped += 1
            continue
        out.append({"record_url": OPENPHISH_FEED, "_norm": norm, "_line": line})
    return out, skipped


def fetch_openphish(opener=None) -> Snapshot:
    try:
        raw, meta = _http_get(OPENPHISH_FEED, MAX_TEXT_FEED, opener)
    except Exception as exc:  # noqa: BLE001
        return _failure("OpenPhish", exc)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return Snapshot("OpenPhish", "malformed", "feed is not UTF-8 text", now_iso(), meta=meta)
    if text.lstrip().startswith(("<", "{")):
        return Snapshot("OpenPhish", "malformed", "feed did not return a URL list", now_iso(), meta=meta)
    records, skipped = parse_openphish(text)
    if not records:
        return Snapshot("OpenPhish", "malformed", f"feed held no usable URLs ({skipped} skipped)", now_iso(), meta=meta)
    return Snapshot("OpenPhish", "ok", f"{len(records)} listed URLs in the community feed",
                    now_iso(), records, skipped, meta=meta)


def not_attempted(source: str, why: str) -> Snapshot:
    return Snapshot(source, "not_attempted", why, None)
