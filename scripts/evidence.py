"""Evidence correlation and confidence levels for Off-Brand specimens.

A specimen's evidence is a list of attributed records plus the status of every source
that was (or could not be) checked. The confidence level is derived from those records
by fixed rules (classify), and every level carries the reason it was given.

Levels (strongest first):
- corroborated:     reserved for demonstrably independent evidence; not awarded by current sources.
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
  from the PhishTank feed is PhishTank's lead, not a second opinion. Declared origin
  alone cannot establish independence.
- The level is always recomputed from the records. Nothing an editor writes changes it.
- Only Corroborated, Source-confirmed and Suspected may be published, and Suspected is
  always shown as "not confirmed".
- OpenPhish records are used for private triage only (its terms bar redistribution);
  the published level is recomputed without them (public_view).
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

from feeds import OPENPHISH_FEED, PUBLIC_SOURCES, Snapshot, phishtank_detail_url
from normalize import normalize, refang
from sanitize import defang_domain, defang_url, sanitize_text

VERSION = 3
LEVELS = ("corroborated", "source-confirmed", "suspected", "unverified", "disputed")
LABELS = {
    "corroborated": "Corroborated",
    "source-confirmed": "Source-confirmed",
    "suspected": "Suspected (not confirmed)",
    "unverified": "Unverified",
    "disputed": "Disputed",
}
PUBLISHABLE = frozenset({"corroborated", "source-confirmed", "suspected"})
STRENGTH_RANK = {"verified": 3, "listed": 2, "label": 1}
SOURCE_STATUSES = {"ok", "rate_limited", "unavailable", "malformed", "too_large", "not_attempted"}
KNOWN_FEEDS = {"phishtank": "PhishTank", "openphish": "OpenPhish"}
# Which source may claim which strength. A record outside this table is rejected.
STRENGTH_SOURCES = {"verified": {"PhishTank"}, "listed": {"PhishTank", "OpenPhish"}, "label": {"urlscan.io"}}
UUID_RECORD = re.compile(r"^https://urlscan\.io/result/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/(report/)?$")
PT_RECORD = re.compile(r"^https://www\.phishtank\.com/phish_detail\.php\?phish_id=\d{1,12}$")
PRIVATE_NOTE = "Some triage sources cannot be republished and are not counted in this level."


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
    norm = normalize(url) or {}
    out = []
    for rec, match in [(r, "exact") for r in exact] + [(r, "same_host") for r in host[:3]]:
        verified = rec["verified"]
        detail = ("Verified as phishing by PhishTank" if verified else "Submitted to PhishTank, not yet verified")
        if match == "same_host" and rec["_norm"]["scheme_key"] == norm.get("scheme_key"):
            match = "scheme_only"
            detail = "PhishTank lists a related URL with a different scheme; this URL is not verified"
        elif match == "same_host":
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
        norm = normalize(url) or {}
        scheme_only = any(r["_norm"]["scheme_key"] == norm.get("scheme_key") for r in host)
        rec.update(match="scheme_only" if scheme_only else "same_host",
                   detail="OpenPhish lists a related URL with a different scheme" if scheme_only
                   else "OpenPhish lists a different page on the same host")
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
        reason = (f"{len(against)} record(s) conflict with the phishing classification "
                  f"({'; '.join(r['detail'] for r in against[:2])})")
        reason += f", while {len(supports)} support it." if supports else "."
        return "disputed", reason + tail

    verified = [r for r in exact if r["strength"] == "verified"]
    # Current providers do not establish independence. Distinct source names and
    # submitter labels are insufficient. Corroborated is reserved for future evidence.

    if verified:
        shared = [r for r in exact if r["upstream"] == verified[0]["upstream"] and r is not verified[0]]
        if verified[0].get("historical"):
            reason = f"{verified[0]['source']} previously verified this exact page as phishing; this is historical evidence."
        else:
            reason = f"{verified[0]['source']} verified this exact page as phishing."
        if shared:
            reason += f" The {shared[0]['source']} record came from the same feed, so it is not counted separately."
        return "source-confirmed", reason + tail

    if exact:
        best = max(exact, key=lambda r: STRENGTH_RANK[r["strength"]])
        return "suspected", f"{best['source']}: {best['detail']}; no source verified this page." + tail
    if any(r["match"] == "scheme_only" for r in supports):
        return "suspected", "A related URL uses a different scheme; this exact URL is not verified." + tail
    if supports:
        return "suspected", ("Only records for other pages on the same host were found; "
                             "this exact page has no record." + tail)
    checked = sorted(n for n, s in sources.items() if s["status"] == "ok")
    if checked:
        return "unverified", f"No supporting record in the sources checked ({', '.join(checked)})." + tail
    return "unverified", "No source could be checked, so no determination is possible." + tail


def _limitations(level, records, sources, redirected) -> list[str]:
    out = []
    if redirected:
        out.append("The scan ended on a different host than the reported address; "
                   "check whether the final page is a copy or the genuine site.")
    if any(r["match"] == "scheme_only" for r in records):
        out.append("HTTP and HTTPS may serve different content; scheme-only matches do not confirm this page.")
    if any(r["match"] == "same_host" for r in records):
        out.append("Some records describe other pages on the same host, not this page.")
    if sources.get("PhishTank", {}).get("status") == "ok" and not any(r["source"] == "PhishTank" for r in records):
        out.append("PhishTank's dump lists only verified phishes still online; a missing "
                   "record does not mean the page was benign.")
    if any(r["source"] == "OpenPhish" for r in records):
        out.append("The OpenPhish feed rotates; the feed link shows current entries, not this one.")
    if level in ("suspected", "unverified") and any(s["status"] not in ("ok", "not_attempted") for s in sources.values()):
        out.append("A source could not be read in this run; the level may change when it is.")
    if any((s.get("detail") or "").endswith("(carried from an earlier check)") for s in sources.values()):
        out.append("At least one source result was carried over from an earlier check because the source was unavailable or not checked.")
    if any(r.get("historical") for r in records):
        out.append("Historical records are retained with their original observation dates; they do not establish current page behavior.")
    out.append("Captures document a moment; a page may have changed or gone offline since.")
    return out


def assess(url: str | None, *, lead: dict | None = None, snapshots: list[Snapshot] = (),
           final_host: str | None = None, captured_at: str | None = None,
           extra_records: list[dict] = (), previous: dict | None = None, now: str | None = None) -> dict:
    """Correlate one specimen address against the run's feed snapshots.

    `previous` is an earlier assessment of the same specimen. When a feed cannot be read
    now but was read successfully before, its earlier records are carried forward and
    labelled as such, so an outage never silently erases findings.
    """
    records: list[dict] = [r for r in [lead, *extra_records] if r]
    sources: dict[str, dict] = {}
    norm = normalize(url)
    prev_norm = normalize((previous or {}).get("specimen", {}).get("defanged_url"))
    if not norm or not prev_norm or norm["exact_key"] != prev_norm["exact_key"]:
        previous = None
    prev_sources = (previous or {}).get("sources") or {}

    def add(rec):
        key = (rec["source"], rec["match"], rec["record_url"])
        if not any((r["source"], r["match"], r["record_url"]) == key for r in records):
            records.append(rec)

    for snap in snapshots:
        if snap.ok:
            sources[snap.source] = dict(snap.check(), last_success=snap.fetched_at)
            if url:
                for rec in CORRELATORS[snap.source](snap, url):
                    add(rec)
        elif (prev_sources.get(snap.source, {}).get("status") == "ok"
              or prev_sources.get(snap.source, {}).get("last_success")):
            old = prev_sources[snap.source]
            current = snap.check()
            current["last_success"] = old.get("last_success") or old.get("checked_at")
            current["detail"] = f"{current.get('detail') or 'unavailable'} (carried from an earlier check)"
            sources[snap.source] = current
            for rec in (previous or {}).get("records") or []:
                if rec.get("source") == snap.source:
                    add(dict(rec, historical=True))
        else:
            sources[snap.source] = snap.check()
        if snap.source == "PhishTank":
            for rec in (previous or {}).get("records") or []:
                if (rec.get("source") == "PhishTank" and rec.get("match") == "exact"
                        and rec.get("strength") == "verified" and rec.get("stance") == "supports"):
                    add(dict(rec, historical=True))
    if lead and lead["source"] == "urlscan.io":
        sources.setdefault("urlscan.io", {"status": "ok", "detail": "scan record", "checked_at": lead.get("observed_at")})

    level, reason = classify(records, sources)
    norm = normalize(url) if url else None
    final = normalize("https://" + refang(final_host) + "/") if final_host else None
    redirected = None if not (norm and final) else norm["host_key"] != final["host_key"]
    return {
        "version": VERSION, "level": level, "reason": reason,
        "assessed_at": now or _now(), "captured_at": captured_at,
        "specimen": {"defanged_url": defang_url(url) if url else None,
                     "defanged_final_host": defang_domain(final["host_key"]) if final else None,
                     "redirected": redirected},
        "records": records, "sources": sources,
        "brand_claims": sorted({r["brand_claim"] for r in records if r.get("brand_claim")}),
        "limitations": _limitations(level, records, sources, redirected),
    }


def public_view(ev: dict) -> dict:
    """The assessment as it may be shown publicly: republishable sources only, level recomputed."""
    records = [r for r in ev["records"] if r.get("source") in PUBLIC_SOURCES]
    sources = {n: s for n, s in ev["sources"].items() if n in PUBLIC_SOURCES}
    # A private conflict must block publication, not disappear through filtering.
    private_conflict = any(r.get("stance") == "contradicts" for r in ev["records"] if r.get("source") not in PUBLIC_SOURCES)
    hidden = len(records) != len(ev["records"]) or len(sources) != len(ev["sources"])
    level, reason = classify(records, sources)
    if private_conflict:
        level, reason = "disputed", "A restricted record conflicts with the classification; publication is blocked."
    limits = _limitations(level, records, sources, ev.get("specimen", {}).get("redirected"))
    if hidden:
        limits.insert(0, PRIVATE_NOTE)
    out = dict(ev, records=records, sources=sources, level=level, reason=reason, limitations=limits,
               brand_claims=sorted({r["brand_claim"] for r in records if r.get("brand_claim")}))
    return out


# ---------------------------------------------------------------- publication

def _clean_record(r) -> dict | None:
    if not isinstance(r, dict) or r.get("stance") not in ("supports", "contradicts") \
            or r.get("match") not in ("exact", "same_host", "scheme_only") or r.get("strength") not in STRENGTH_RANK:
        return None
    source = sanitize_text(r.get("source"), max_len=40)
    if r["stance"] == "supports" and source not in STRENGTH_SOURCES[r["strength"]]:
        return None  # a record may not claim more authority than its source has
    url = safe_record_url(r.get("record_url"))
    if r["strength"] == "verified" and not (url and PT_RECORD.fullmatch(url)):
        return None  # a verification must point at the verifier's own record
    return {
        "source": source, "match": r["match"], "stance": r["stance"], "strength": r["strength"],
        "upstream": sanitize_text(r.get("upstream"), max_len=40),
        "detail": sanitize_text(r.get("detail"), max_len=200),
        "record_url": url, "observed_at": sanitize_text(r.get("observed_at"), max_len=40),
        "historical": r.get("historical") is True,
    }


def sanitize_evidence(ev) -> dict | None:
    """Re-validate an evidence block before it is published.

    Unknown shapes are rejected, and the level is recomputed from the records: a block
    whose stated level differs from what its records support is rejected outright.
    The result is the public view (republishable sources only).
    """
    if not isinstance(ev, dict) or ev.get("version") != VERSION or ev.get("level") not in LEVELS:
        return None
    records = []
    for r in (ev.get("records") or [])[:12]:
        clean = _clean_record(r)
        if clean is None:
            return None
        records.append(clean)
    sources = {}
    for name, s in list((ev.get("sources") or {}).items())[:8]:
        if not isinstance(s, dict) or s.get("status") not in SOURCE_STATUSES:
            return None
        sources[sanitize_text(name, max_len=40)] = {
            "status": s["status"], "detail": sanitize_text(s.get("detail"), max_len=160),
            "checked_at": sanitize_text(s.get("checked_at"), max_len=40),
            "last_success": sanitize_text(s.get("last_success"), max_len=40)}
    if classify(records, sources)[0] != ev["level"]:
        return None
    spec = ev.get("specimen") or {}
    cleaned = {
        "version": VERSION, "level": ev["level"],
        "assessed_at": sanitize_text(ev.get("assessed_at"), max_len=40),
        "captured_at": sanitize_text(ev.get("captured_at"), max_len=40),
        "specimen": {"defanged_url": defang_url(spec.get("defanged_url")),
                     "defanged_final_host": defang_domain(refang(spec["defanged_final_host"]))
                     if isinstance(spec.get("defanged_final_host"), str) else None,
                     "redirected": spec.get("redirected") if isinstance(spec.get("redirected"), bool) else None},
        "records": records, "sources": sources, "brand_claims": [], "limitations": [],
    }
    return public_view(cleaned)


def _md(text) -> str:
    """Neutralise markdown and HTML in record text shown in a GitHub issue."""
    return re.sub(r"([\\`*_\[\]()#|~!<>])", r"\\\1", html.escape(str(text or ""), quote=False))


def issue_lines(ev: dict, private: bool) -> list[str]:
    """Evidence section for a triage issue plus the machine line the publisher reads.

    private=False (issues in the public repository) shows and embeds only the public view.
    """
    shown = ev if private else public_view(ev)
    pub = public_view(ev)
    lines = [f"### Evidence level: {LABELS[shown['level']]}", "", f"> {_md(shown['reason'])}", ""]
    if private and pub["level"] != ev["level"]:
        lines += [f"**Publishable level (without private-triage sources): {LABELS[pub['level']]}**", ""]
    if shown.get("specimen", {}).get("redirected"):
        lines.append(f"- Scan ended on another host: `{shown['specimen']['defanged_final_host']}`")
    for r in shown["records"]:
        where = f" ({r['record_url']})" if r.get("record_url") else ""
        lines.append(f"- [{r['match'].replace('_', '-')}] {_md(r['source'])}: {_md(r['detail'])}{where}")
    for name, s in shown["sources"].items():
        lines.append(f"- Source check — {_md(name)}: {s['status']} ({_md(s.get('detail') or 'no detail')})")
    for lim in shown["limitations"]:
        lines.append(f"- Limitation — {_md(lim)}")
    if pub["level"] not in PUBLISHABLE:
        lines += ["", f"**Not publishable: the publishable evidence level is {LABELS[pub['level']]}.**"]
    elif pub["level"] == "suspected":
        lines += ["", "**Publishable only as Suspected (not confirmed phishing).**"]
    embedded = ev if private else pub
    lines += ["", "evidence_json: " + json.dumps(embedded, ensure_ascii=True, separators=(",", ":"), sort_keys=True)]
    return lines
