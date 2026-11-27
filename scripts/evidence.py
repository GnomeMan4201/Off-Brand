"""Evidence correlation and confidence levels for Off-Brand specimens.

A specimen's evidence is a list of attributed records plus the status of every source
that was (or could not be) checked. The confidence level is derived from those records
by fixed rules, and every level carries the reason it was given.

Levels (strongest first):
- corroborated:     two or more independent, credible sources list this exact page.
- source-confirmed: a source that verifies submissions (PhishTank) verified this exact page.
- suspected:        indicators exist (a feed label, an automated listing, or a record for
                    another page on the same host) but nothing verified this page.
- unverified:       no supporting record was found in the sources that were checked.
- disputed:         a record conflicts with the phishing classification.

Rules that never bend:
- A source that could not be read is reported as unavailable. It is never counted as
  "not found" and never as support.
- Same-host records never confirm a page; they can only raise it to "suspected".
- Records that come from the same upstream feed count once. A urlscan scan submitted
  from the PhishTank feed is PhishTank's lead, not a second opinion.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from feeds import OPENPHISH_FEED, Snapshot, phishtank_detail_url
from normalize import normalize, refang
from sanitize import defang_domain, defang_url, sanitize_text

VERSION = 1
LEVELS = ("corroborated", "source-confirmed", "suspected", "unverified", "disputed")
LABELS = {
    "corroborated": "Corroborated",
    "source-confirmed": "Source-confirmed",
    "suspected": "Suspected",
    "unverified": "Unverified",
    "disputed": "Disputed",
}
NEEDS_ACK = {"unverified", "disputed"}
STRENGTH_RANK = {"verified": 3, "listed": 2, "label": 1}
SOURCE_STATUSES = {"ok", "rate_limited", "unavailable", "malformed", "too_large", "not_attempted"}
KNOWN_FEEDS = {"phishtank": "PhishTank", "openphish": "OpenPhish"}
UUID_RECORD = re.compile(r"^https://urlscan\.io/result/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/(report/)?$")
PT_RECORD = re.compile(r"^https://www\.phishtank\.com/phish_detail\.php\?phish_id=\d{1,12}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_record_url(url: str | None) -> str | None:
    if not isinstance(url, str):
        return None
    if UUID_RECORD.fullmatch(url) or PT_RECORD.fullmatch(url) or url == OPENPHISH_FEED:
        return url
    return None


# ---------------------------------------------------------------- record builders

def urlscan_record(record_url: str | None, task_source: str | None, tags=(), observed_at=None) -> dict | None:
    """The urlscan scan itself, as a lead. Its label says who submitted it, not a verdict."""
    src = (sanitize_text(task_source, max_len=40) or "").lower()
    tags = [t.lower() for t in (sanitize_text(x, max_len=30) for x in tags or []) if t]
    if src in KNOWN_FEEDS:
        upstream, detail = src, f"scan submitted from the {KNOWN_FEEDS[src]} feed"
    elif "phishing" in tags:
        upstream, detail = "urlscan-submitter", "scan tagged “phishing” by its submitter"
    else:
        return None
    return {"source": "urlscan.io", "match": "exact", "stance": "supports", "strength": "label",
            "upstream": upstream, "detail": detail, "record_url": safe_record_url(record_url),
            "observed_at": observed_at}


def openphish_listing(observed_at=None) -> dict:
    return {"source": "OpenPhish", "match": "exact", "stance": "supports", "strength": "listed",
            "upstream": "openphish", "detail": "Listed in the OpenPhish community feed (automated classification)",
            "record_url": OPENPHISH_FEED, "observed_at": observed_at}


def _phishtank_records(snap: Snapshot, url: str) -> list[dict]:
    exact, host = snap.lookup(url)
    out = []
    for rec, match in [(r, "exact") for r in exact] + [(r, "same_host") for r in host[:3]]:
        verified = rec["verified"]
        detail = ("Verified as phishing by PhishTank" if verified else "Submitted to PhishTank, not yet verified")
        if match == "same_host":
            detail = "PhishTank lists a different page on the same host" + ("" if verified else " (unverified)")
        if rec.get("target"):
            detail += f"; target: {rec['target']}"
        out.append({"source": "PhishTank", "match": match, "stance": "supports",
                    "strength": "verified" if verified else "listed", "upstream": "phishtank",
                    "detail": detail, "record_url": phishtank_detail_url(rec["phish_id"]),
                    "observed_at": rec.get("verified_at") or rec.get("submitted_at"),
                    "brand_claim": rec.get("target")})
    return out


def _openphish_records(snap: Snapshot, url: str) -> list[dict]:
    exact, host = snap.lookup(url)
    out = [openphish_listing(snap.fetched_at) for _ in exact[:1]]
    if host and not exact:
        rec = openphish_listing(snap.fetched_at)
        rec.update(match="same_host", detail="OpenPhish lists a different page on the same host")
        out.append(rec)
    return out


CORRELATORS = {"PhishTank": _phishtank_records, "OpenPhish": _openphish_records}


# ---------------------------------------------------------------- classification

def classify(records: list[dict], sources: dict) -> tuple[str, str]:
    supports = [r for r in records if r["stance"] == "supports"]
    against = [r for r in records if r["stance"] == "contradicts"]
    exact = [r for r in supports if r["match"] == "exact"]
    unread = sorted(n for n, s in sources.items() if s["status"] not in ("ok", "not_attempted"))
    tail = f" Could not check: {', '.join(unread)}." if unread else ""

    if against:
        level = "disputed"
        reason = (f"{len(against)} record(s) conflict with the phishing classification "
                  f"({'; '.join(r['detail'] for r in against[:2])})")
        reason += f", while {len(supports)} support it." if supports else "."
        return level, reason + tail

    credible_upstreams = {r["upstream"] for r in exact if STRENGTH_RANK[r["strength"]] >= 2}
    if len(credible_upstreams) >= 2:
        names = sorted({r["source"] for r in exact if r["upstream"] in credible_upstreams})
        return "corroborated", (f"Independent sources list this exact page: {', '.join(names)}." + tail)

    verified = [r for r in exact if r["strength"] == "verified"]
    if verified:
        shared = [r for r in exact if r["upstream"] == verified[0]["upstream"] and r is not verified[0]]
        reason = f"{verified[0]['source']} verified this exact page as phishing."
        if shared:
            reason += f" The {shared[0]['source']} record came from the same feed, so it is not counted separately."
        return "source-confirmed", reason + tail

    if exact:
        best = max(exact, key=lambda r: STRENGTH_RANK[r["strength"]])
        return "suspected", f"{best['source']}: {best['detail']}; no source verified this page." + tail
    if supports:
        return "suspected", ("Only records for other pages on the same host were found; "
                             "this exact page has no record." + tail)
    checked = sorted(n for n, s in sources.items() if s["status"] == "ok")
    if checked:
        return "unverified", f"No supporting record in the sources checked ({', '.join(checked)})." + tail
    return "unverified", "No source could be checked, so no determination is possible." + tail


def assess(url: str | None, *, lead: dict | None = None, snapshots: list[Snapshot] = (),
           final_host: str | None = None, captured_at: str | None = None,
           extra_records: list[dict] = (), now: str | None = None) -> dict:
    """Correlate one specimen address against the run's feed snapshots."""
    records: list[dict] = [r for r in [lead, *extra_records] if r]
    sources: dict[str, dict] = {}
    for snap in snapshots:
        sources[snap.source] = snap.check()
        if snap.ok and url:
            for rec in CORRELATORS[snap.source](snap, url):
                key = (rec["source"], rec["match"], rec["record_url"])
                if not any((r["source"], r["match"], r["record_url"]) == key for r in records):
                    records.append(rec)
    if lead and lead["source"] == "urlscan.io":
        sources.setdefault("urlscan.io", {"status": "ok", "detail": "scan record", "checked_at": lead.get("observed_at")})

    level, reason = classify(records, sources)
    norm = normalize(url) if url else None
    final = normalize("http://" + refang(final_host)) if final_host else None
    redirected = None if not (norm and final) else norm["host_key"] != final["host_key"]
    limitations = []
    if redirected:
        limitations.append("The scan ended on a different host than the reported address; "
                           "check whether the final page is a copy or the genuine site.")
    if any(r["match"] == "same_host" for r in records):
        limitations.append("Some records describe other pages on the same host, not this page.")
    if sources.get("PhishTank", {}).get("status") == "ok" and not any(r["source"] == "PhishTank" for r in records):
        limitations.append("PhishTank's dump lists only verified phishes still online; a missing "
                           "record does not mean the page was benign.")
    if any(r["source"] == "OpenPhish" for r in records):
        limitations.append("The OpenPhish feed rotates; the feed link shows current entries, not this one.")
    if level in ("suspected", "unverified") and any(s["status"] not in ("ok", "not_attempted") for s in sources.values()):
        limitations.append("A source could not be read in this run; the level may change when it is.")
    limitations.append("Captures document a moment; a page may have changed or gone offline since.")

    return {
        "version": VERSION, "level": level, "reason": reason,
        "assessed_at": now or _now(), "captured_at": captured_at,
        "specimen": {"defanged_url": defang_url(url) if url else None,
                     "defanged_final_host": defang_domain(final["host_key"]) if final else None,
                     "redirected": redirected},
        "records": records, "sources": sources,
        "brand_claims": sorted({r["brand_claim"] for r in records if r.get("brand_claim")}),
        "limitations": limitations,
    }


# ---------------------------------------------------------------- publication

def sanitize_evidence(ev) -> dict | None:
    """Re-validate an evidence block before it is published. Unknown shapes are rejected."""
    if not isinstance(ev, dict) or ev.get("version") != VERSION or ev.get("level") not in LEVELS:
        return None
    reason = sanitize_text(ev.get("reason"), max_len=400)
    if not reason:
        return None
    records = []
    for r in (ev.get("records") or [])[:12]:
        if not isinstance(r, dict) or r.get("stance") not in ("supports", "contradicts") \
                or r.get("match") not in ("exact", "same_host") or r.get("strength") not in STRENGTH_RANK:
            return None
        records.append({
            "source": sanitize_text(r.get("source"), max_len=40),
            "match": r["match"], "stance": r["stance"], "strength": r["strength"],
            "upstream": sanitize_text(r.get("upstream"), max_len=40),
            "detail": sanitize_text(r.get("detail"), max_len=200),
            "record_url": safe_record_url(r.get("record_url")),
            "observed_at": sanitize_text(r.get("observed_at"), max_len=40),
        })
    sources = {}
    for name, s in list((ev.get("sources") or {}).items())[:8]:
        if not isinstance(s, dict) or s.get("status") not in SOURCE_STATUSES:
            return None
        sources[sanitize_text(name, max_len=40)] = {
            "status": s["status"], "detail": sanitize_text(s.get("detail"), max_len=160),
            "checked_at": sanitize_text(s.get("checked_at"), max_len=40)}
    spec = ev.get("specimen") or {}
    return {
        "version": VERSION, "level": ev["level"], "reason": reason,
        "assessed_at": sanitize_text(ev.get("assessed_at"), max_len=40),
        "captured_at": sanitize_text(ev.get("captured_at"), max_len=40),
        "specimen": {"defanged_url": defang_url(spec.get("defanged_url")),
                     "defanged_final_host": defang_domain(refang(spec["defanged_final_host"]))
                     if spec.get("defanged_final_host") else None,
                     "redirected": spec.get("redirected") if isinstance(spec.get("redirected"), bool) else None},
        "records": records, "sources": sources,
        "brand_claims": [b for b in (sanitize_text(x, max_len=80) for x in (ev.get("brand_claims") or [])[:4]) if b],
        "limitations": [x for x in (sanitize_text(t, max_len=240) for t in (ev.get("limitations") or [])[:6]) if x],
    }


def issue_lines(ev: dict) -> list[str]:
    """Readable evidence section for a triage issue, plus one machine line the publisher reads."""
    lines = [f"### Evidence level: {LABELS[ev['level']]}", "", f"> {ev['reason']}", ""]
    if ev.get("specimen", {}).get("redirected"):
        lines.append(f"- Scan ended on another host: `{ev['specimen']['defanged_final_host']}`")
    for r in ev["records"]:
        where = f" ({r['record_url']})" if r.get("record_url") else ""
        lines.append(f"- [{r['match'].replace('_', '-')}] {r['source']}: {r['detail']}{where}")
    for name, s in ev["sources"].items():
        lines.append(f"- Source check — {name}: {s['status']} ({s.get('detail') or 'no detail'})")
    for lim in ev["limitations"]:
        lines.append(f"- Limitation — {lim}")
    if ev["level"] in NEEDS_ACK:
        lines += ["", f"**{LABELS[ev['level']]} specimens publish only with an `evidence_ack:` line "
                      "in your review explaining why it is still worth airing.**"]
    lines += ["", "evidence_json: " + json.dumps(ev, ensure_ascii=True, separators=(",", ":"), sort_keys=True)]
    return lines
