"""Bulk intelligence feeds used for evidence correlation: PhishTank and OpenPhish.

Each feed is downloaded at most once per run and looked up locally, so no suspect URL
is ever sent anywhere and no suspect site is contacted.

A feed that could not be read returns a snapshot whose status says why
("rate_limited", "unavailable", "malformed", "too_large"). Callers must report that
status; an unread feed is never the same as "no record found".

PhishTank notes (checked November 2026):
- New PhishTank accounts and application keys have not been issued since 2020.
  Without a key the hourly dump allows only a few downloads per day; an existing
  key can be supplied as PHISHTANK_APP_KEY.
- The dump (online-valid) lists only phishes PhishTank has verified AND believes are
  still online. A specimen that went offline drops out, so absence is not evidence
  that a page was benign.
- PhishTank data is licensed for use, with attribution; Off-Brand stores only the
  phish ID, verification flags and timestamps and links back to PhishTank's own page.
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
from urllib.request import Request, urlopen

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
    _exact: dict = field(default_factory=dict, repr=False)
    _host: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for rec in self.records:
            key = rec.get("_norm")
            if not key:
                continue
            self._exact.setdefault(key["exact_key"], []).append(rec)
            if not is_shared_host(key["host_key"]):
                self._host.setdefault(key["host_key"], []).append(rec)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def check(self) -> dict:
        return {"status": self.status, "detail": self.detail, "checked_at": self.fetched_at}

    def lookup(self, url: str | None) -> tuple[list[dict], list[dict]]:
        """(exact matches, same-host-but-different-page matches). Empty if not ok."""
        norm = normalize(url)
        if not self.ok or not norm:
            return [], []
        exact = list(self._exact.get(norm["exact_key"], []))
        seen = {id(r) for r in exact}
        host = [r for r in self._host.get(norm["host_key"], []) if id(r) not in seen]
        return exact, host


def _http_get(url: str, max_bytes: int, opener=None) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with (opener or urlopen)(req, timeout=60) as resp:
        body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise OverflowError(f"response larger than {max_bytes} bytes")
    return body


def _failure(source: str, exc: Exception) -> Snapshot:
    if isinstance(exc, HTTPError):
        if exc.code in (429, 509):
            return Snapshot(source, "rate_limited", f"HTTP {exc.code}: download limit reached", now_iso())
        if exc.code in (401, 403):
            return Snapshot(source, "unavailable", f"HTTP {exc.code}: access refused", now_iso())
        return Snapshot(source, "unavailable", f"HTTP {exc.code}", now_iso())
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
        raw = _http_get(url, MAX_COMPRESSED, opener)
    except Exception as exc:  # noqa: BLE001 - mapped to an explicit status
        snap = _failure("PhishTank", exc)
        if key:
            snap.detail = snap.detail.replace(key, "<key>")
        return snap
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            expanded = gz.read(MAX_EXPANDED + 1)
        if len(expanded) > MAX_EXPANDED:
            return Snapshot("PhishTank", "too_large", "expanded dump exceeds size cap", now_iso())
        records, skipped = parse_phishtank(json.loads(expanded.decode("utf-8")))
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return Snapshot("PhishTank", "malformed", sanitize_text(str(exc), 160) or "unreadable dump", now_iso())
    mode = "keyed download" if key else "public download"
    return Snapshot("PhishTank", "ok", f"{len(records)} verified online entries ({mode})",
                    now_iso(), records, skipped)


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
        raw = _http_get(OPENPHISH_FEED, MAX_TEXT_FEED, opener)
    except Exception as exc:  # noqa: BLE001
        return _failure("OpenPhish", exc)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return Snapshot("OpenPhish", "malformed", "feed is not UTF-8 text", now_iso())
    if text.lstrip().startswith(("<", "{")):
        return Snapshot("OpenPhish", "malformed", "feed did not return a URL list", now_iso())
    records, skipped = parse_openphish(text)
    return Snapshot("OpenPhish", "ok", f"{len(records)} listed URLs in the community feed",
                    now_iso(), records, skipped)


def not_attempted(source: str, why: str) -> Snapshot:
    return Snapshot(source, "not_attempted", why, None)
