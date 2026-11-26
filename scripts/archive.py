"""Collect public urlscan.io scan records and their archived screenshots into archive/.

Nothing here contacts a suspicious site: only urlscan.io is fetched (search API and
its stored screenshots). Collecting never opens an issue.

Two sweeps share one engine and are tracked in data/archive_state.json:
- "scheduled": newest captures down to the last completed sweep's watermark.
- "backfill":  newest captures down to `days` ago, resumable across runs.

A sweep walks newest -> oldest using urlscan's `search_after` cursor, saved after every
item, so a busy day or an interrupted/budget-limited run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from ingest import URLSCAN_FREE_QUERY, load_json
from sanitize import defang_domain, defang_url, sanitize_text, validate_public_record_url

ROOT = Path(__file__).resolve().parent.parent
SHOTS_DIR = ROOT / "archive" / "shots"
INDEX_PATH = ROOT / "data" / "archive.json"
STATE_PATH = ROOT / "data" / "archive_state.json"

PAGE_SIZE = 100  # urlscan search page size
MAX_SHOT_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024  # stop adding past this; see README for limits
MAX_RATE_WAIT = 90  # seconds we are willing to sleep on a 429 before stopping the run
CURSOR_RE = re.compile(r"^[0-9A-Za-z.,:_+-]{1,200}$")
USER_AGENT = "OffBrand-Archive/0.1"
IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"))


class RateLimited(Exception):
    """urlscan asked us to wait longer than we are willing to; stop and resume later."""


class Transient(Exception):
    """Network problem for one item; skip it without recording anything."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------- HTTP

class Client:
    """urlscan.io-only HTTP client that honours rate limits."""

    def __init__(self, api_key: str = "", sleep=time.sleep):
        self.api_key = api_key.strip()
        self.sleep = sleep
        self._opener = build_opener(_NoRedirect)

    def _get(self, url: str, max_bytes: int) -> tuple[int, dict, bytes]:
        if urlparse(url).hostname != "urlscan.io":
            raise ValueError("only urlscan.io may be fetched")
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["API-Key"] = self.api_key
        for attempt in range(4):
            try:
                with self._opener.open(Request(url, headers=headers), timeout=30) as resp:
                    body = resp.read(max_bytes + 1)
                    self._pace(resp.headers)
                    return resp.status, dict(resp.headers), body[:max_bytes + 1]
            except HTTPError as exc:
                if exc.code == 429:
                    wait = _wait_seconds(exc.headers)
                    if wait > MAX_RATE_WAIT or attempt == 3:
                        raise RateLimited(f"urlscan asked for {wait}s wait") from exc
                    self.sleep(wait)
                    continue
                return exc.code, dict(exc.headers or {}), b""
            except (URLError, TimeoutError, OSError) as exc:
                raise Transient(str(exc)) from exc
        raise RateLimited("rate limit retries exhausted")

    def _pace(self, headers) -> None:
        remaining = headers.get("X-Rate-Limit-Remaining")
        if remaining is not None and remaining.strip() == "0":
            wait = _wait_seconds(headers)
            if wait > MAX_RATE_WAIT:
                raise RateLimited(f"rate limit exhausted, resets in {wait}s")
            self.sleep(wait)

    def search(self, query: str, cursor: str | None) -> dict:
        params = {"q": query, "size": PAGE_SIZE}
        if cursor:
            params["search_after"] = cursor
        status, _, body = self._get(
            f"https://urlscan.io/api/v1/search/?{urlencode(params)}", 4 * 1024 * 1024
        )
        if status != 200:
            raise Transient(f"urlscan search HTTP {status}")
        return json.loads(body.decode("utf-8"))

    def screenshot(self, scan_uuid: str) -> tuple[bytes, str] | None:
        """(bytes, ext) or None when urlscan has no screenshot. Raises Transient on errors."""
        status, headers, body = self._get(
            f"https://urlscan.io/screenshots/{scan_uuid}.png", MAX_SHOT_BYTES
        )
        if status in (404, 410):
            return None
        if status != 200:
            raise Transient(f"screenshot HTTP {status}")
        if len(body) > MAX_SHOT_BYTES:
            return None
        for magic, ext in IMAGE_MAGIC:
            if body.startswith(magic):
                return body, ext
        return None


def _wait_seconds(headers) -> int:
    for key in ("Retry-After", "X-Rate-Limit-Reset-After"):
        try:
            return max(1, int(float(headers.get(key, ""))))
        except (TypeError, ValueError):
            continue
    return 60


# ---------------------------------------------------------------- parsing

def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sweep_query(days: int) -> str:
    return URLSCAN_FREE_QUERY.replace("date:>now-7d", f"date:>now-{int(days)}d")


def parse_result(item: dict) -> dict | None:
    """Turn one urlscan search result into a specimen record (no image yet)."""
    task, page = item.get("task") or {}, item.get("page") or {}
    try:
        scan_uuid = str(UUID(str(item.get("_id"))))
    except ValueError:
        return None
    raw_url = task.get("url") or page.get("url")
    captured = parse_time(task.get("time"))
    record = validate_public_record_url(f"https://urlscan.io/result/{scan_uuid}/report/")
    defanged = defang_url(raw_url)
    if not (raw_url and captured and record and defanged):
        return None
    domain = page.get("domain") or urlparse(raw_url).hostname
    source = sanitize_text(task.get("source"), max_len=40)
    tags = [t for t in (sanitize_text(x, max_len=30) for x in (task.get("tags") or [])[:10]) if t]
    return {
        "id": f"urlscan-{scan_uuid}",
        "scan_id": scan_uuid,
        "source_record_url": record,
        "captured_at": iso(captured),
        "defanged_url": defanged,
        "defanged_domain": defang_domain(domain),
        "page_title": sanitize_text(page.get("title"), max_len=140),
        "ip": sanitize_text(page.get("ip"), max_len=64),
        "asn_name": sanitize_text(page.get("asnname"), max_len=120),
        # A provider/community label, never our own verdict.
        "classification": {
            "basis": "source_label",
            "source": source,
            "tags": tags,
            "independently_confirmed": False,
        },
    }


# ---------------------------------------------------------------- storage

def load_index(path: Path = INDEX_PATH) -> dict:
    return load_json(path, {"version": 1, "specimens": []})


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def default_state() -> dict:
    return {"version": 1, "jobs": {}, "no_screenshot": {}}


def job_state(state: dict, name: str) -> dict:
    return state["jobs"].setdefault(
        name, {"cursor": None, "head_ts": None, "watermark": None, "complete": False}
    )


def add_specimen(index: dict, spec: dict, data: bytes, ext: str, shots_dir: Path,
                 imported_at: str, write: bool = True) -> str:
    """Add a capture. Returns 'added', 'repeat' (same scan or unchanged site), or 'full'."""
    specs = index["specimens"]
    if any(s["id"] == spec["id"] for s in specs):
        return "repeat"
    digest = hashlib.sha256(data).hexdigest()
    for s in specs:
        if s["defanged_url"] == spec["defanged_url"] and s["image"]["sha256"] == digest:
            # Same site, byte-identical image: not a visible change. Note the extra capture.
            extra = {"scan_id": spec["scan_id"], "captured_at": spec["captured_at"]}
            if extra not in s.setdefault("also_captured", []):
                s["also_captured"].append(extra)
            return "repeat"
    path = shots_dir / f"{digest}.{ext}"
    total = sum(s["image"]["bytes"] for s in specs)
    if not path.exists() and total + len(data) > MAX_ARCHIVE_BYTES:
        return "full"
    if write and not path.exists():
        shots_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    spec = dict(spec, imported_at=imported_at,
                image={"sha256": digest, "path": f"archive/shots/{digest}.{ext}",
                       "bytes": len(data), "content_type": "image/png" if ext == "png" else "image/jpeg"})
    specs.append(spec)
    specs.sort(key=lambda s: (s["captured_at"], s["id"]), reverse=True)
    return "added"


# ---------------------------------------------------------------- sweep engine

def run_sweep(name: str, days: int, client, index: dict, state: dict, *,
              shots_dir: Path = SHOTS_DIR, max_pages: int = 5, max_new: int = 100,
              max_seconds: float = 1500, now: datetime | None = None, clock=time.monotonic,
              dry_run: bool = False, restart: bool = False, save=None) -> dict:
    """Run one budgeted slice of a sweep. `save()` persists index+state after each page."""
    now = now or datetime.now(timezone.utc)
    job = job_state(state, name)
    stats = {"job": name, "pages": 0, "added": 0, "repeat": 0, "missing_screenshot": 0,
             "skipped_invalid": 0, "errors": 0, "stopped": None, "complete": False}
    if restart:
        job.update(cursor=None, head_ts=None, complete=False)
        if name == "backfill":
            job["watermark"] = None
    if name == "backfill" and job["complete"]:
        stats.update(stopped="already_complete", complete=True)
        return stats

    mid_sweep = job["cursor"] is not None
    if name == "backfill":
        stop_ts = now - timedelta(days=days)
    else:
        stop_ts = parse_time(job["watermark"]) or (now - timedelta(days=days))
    if not mid_sweep:
        job["head_ts"] = None
    cursor = job["cursor"] if mid_sweep and CURSOR_RE.match(job["cursor"] or "") else None
    if mid_sweep and cursor is None:
        job["cursor"] = None
    query = sweep_query(max(days, 1))
    started, known = clock(), {s["id"] for s in index["specimens"]}

    def budget_left() -> str | None:
        if stats["added"] >= max_new:
            return "max_new_reached"
        if clock() - started > max_seconds:
            return "time_budget"
        return None

    while True:
        if stats["pages"] >= max_pages:
            stats["stopped"] = "max_pages"
            break
        try:
            payload = client.search(query, cursor)
        except RateLimited as exc:
            stats["stopped"] = f"rate_limited: {exc}"
            break
        except (Transient, ValueError) as exc:
            stats["stopped"], stats["errors"] = f"search_error: {exc}", stats["errors"] + 1
            break
        stats["pages"] += 1
        results = payload.get("results") or []
        reached_end = False
        for item in results:
            captured = parse_time((item.get("task") or {}).get("time"))
            if captured and captured < stop_ts:
                reached_end = True
                break
            reason = budget_left()
            if reason:
                stats["stopped"] = reason
                break
            sort = item.get("sort")
            item_cursor = ",".join(str(x) for x in sort) if sort else None
            spec = parse_result(item)
            if spec is None:
                stats["skipped_invalid"] += 1
            else:
                if job["head_ts"] is None:
                    job["head_ts"] = spec["captured_at"]
                if spec["id"] in known:
                    stats["repeat"] += 1
                elif spec["id"] in state["no_screenshot"]:
                    stats["missing_screenshot"] += 1
                else:
                    try:
                        shot = client.screenshot(spec["scan_id"])
                    except RateLimited as exc:
                        stats["stopped"] = f"rate_limited: {exc}"
                        break
                    except Transient as exc:
                        # Do not advance past this item: it is retried on the next run.
                        stats["errors"] += 1
                        stats["stopped"] = f"screenshot_error: {exc}"
                        break
                    if shot is None:
                        stats["missing_screenshot"] += 1
                        if not dry_run:
                            state["no_screenshot"][spec["id"]] = iso(now)
                    else:
                        outcome = add_specimen(index, spec, shot[0], shot[1], shots_dir,
                                               iso(now), write=not dry_run)
                        if outcome == "added":
                            stats["added"] += 1
                            known.add(spec["id"])
                        elif outcome == "repeat":
                            stats["repeat"] += 1
                        else:
                            stats["stopped"] = "archive_full"
                            break
            if item_cursor:
                cursor = item_cursor
                job["cursor"] = cursor
        else:
            if not results or not payload.get("has_more"):
                reached_end = True
        if not dry_run and save:
            save()
        if reached_end:
            job.update(cursor=None, complete=True if name == "backfill" else False)
            if name == "scheduled" and job["head_ts"]:
                job["watermark"] = job["head_ts"]
            job["head_ts"] = None
            stats["complete"] = True
            break
        if stats["stopped"]:
            break
        if not cursor:
            stats["stopped"] = "no_cursor"
            break
    if dry_run:
        # Dry runs never persist cursor movement.
        stats["dry_run"] = True
    elif save:
        save()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["scheduled", "backfill"], required=True)
    ap.add_argument("--days", type=int, default=7, help="window (backfill) / first-run lookback (scheduled)")
    ap.add_argument("--max-pages", type=int, default=5)
    ap.add_argument("--max-new", type=int, default=100, help="max new screenshots saved per run")
    ap.add_argument("--max-seconds", type=float, default=1500)
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    ap.add_argument("--restart", action="store_true", help="discard saved progress for this mode")
    args = ap.parse_args(argv)

    days = max(1, min(args.days, 30))
    index, state = load_index(), load_json(STATE_PATH, default_state())
    state.setdefault("jobs", {}), state.setdefault("no_screenshot", {})

    def save():
        save_json(INDEX_PATH, index)
        save_json(STATE_PATH, state)

    client = Client(os.environ.get("URLSCAN_API_KEY", ""))
    stats = run_sweep(args.mode, days, client, index, state, max_pages=max(1, args.max_pages),
                      max_new=max(1, args.max_new), max_seconds=args.max_seconds,
                      dry_run=args.dry_run, restart=args.restart, save=save)
    print(json.dumps(stats, indent=2))
    label = "DRY RUN: would add" if args.dry_run else "Added"
    print(f"{label} {stats['added']} specimen(s); {stats['repeat']} repeat, "
          f"{stats['missing_screenshot']} without screenshot; "
          f"{'complete' if stats['complete'] else 'will resume: ' + str(stats['stopped'])}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
