"""Draft a review comment for a triage candidate with a local open-weight model.

The model runs on the GitHub Actions runner through Ollama (no API key, no
third-party inference service). It only writes the critic_note, in the
assigned voice, from the evidence in the scan record. Every other field is
either copied literally from the record or left as a placeholder that the
publisher refuses to publish until an editor fills it in.

Usage (from the ingest workflow):
    python3 scripts/draft.py <candidate.json> <assignment.json>   -> prints comment markdown
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

PLACEHOLDER = "Needs editor verification"
DRAFT_HEADER = "**DRAFT — verify against screenshot**"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("OFFBRAND_MODEL", "qwen2.5:14b")
TIMEOUT_S = int(os.environ.get("OFFBRAND_DRAFT_TIMEOUT", "420"))
MAX_NOTE = 480

SYSTEM_PROMPT = """You write one short comedic review for Off-Brand, a site that reviews real phishing pages like cheap knockoff products.

Hard rules:
- Use ONLY the facts listed under EVIDENCE. Do not add any fact, number, brand, country, language or detail that is not listed there.
- If no brand is listed, do not name any brand or company. Call it "whatever this page is pretending to be".
- Mock the scammer's craftsmanship. Never mock victims, never mock any nationality, language or culture.
- Write 1 to 3 sentences, under 400 characters, plain text. No markdown, no lists, no quotation marks around the whole thing, no URLs, no emoji.
- Write in the assigned VOICE and EDGE. Be funny: a vivid comparison or a deadpan line, not a summary.
- Never speculate. No "likely", "probably", "suggests", "seems to" or "appears to". If a fact isn't listed, leave it out.
- Don't name the voice or start with a label like "Health Inspector:". Just write in that voice.

Example of the style (different, made-up evidence, do not reuse its facts):
EVIDENCE: Domain ends in .xyz | Hosted on a free hosting subdomain (.pages.dev)
REVIEW: Somebody built a vault and then rented the door from a free hosting plan. The .xyz ending is the price tag they forgot to peel off."""


def evidence_lines(c: dict) -> list[str]:
    lines = [f"Defanged address: {c.get('defanged_url')}"]
    if c.get("defanged_domain"):
        lines.append(f"Defanged domain: {c['defanged_domain']}")
    if c.get("record_brand"):
        lines.append(f"Brand named in the scan record: {c['record_brand']}")
    else:
        lines.append("Brand: not identified in the scan record")
    if c.get("page_title"):
        lines.append(f"Page title recorded by the scan: {c['page_title']}")
    if c.get("asn_name"):
        lines.append(f"Hosting network recorded by the scan: {c['asn_name']}")
    for t in c.get("auto_tells", []) or []:
        lines.append(f"Observation: {t}")
    return lines


def build_user_prompt(c: dict, a: dict) -> str:
    return "\n".join([
        f"VOICE: {a['voice_name']}. {a['brief']}",
        f"TONE SAMPLE (style only, not facts): {a['sample']}",
        f"EDGE: {a['edge_name']}. {a['edge_brief']}",
        "",
        "EVIDENCE:",
        *[f"- {l}" for l in evidence_lines(c)],
        "",
        "Write the review now.",
    ])


def clean_note(text: str | None, voice_name: str | None = None) -> str | None:
    """Return a safe single-paragraph note, or None if it can't be used."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text).strip().strip('"“”').strip()
    t = re.sub(r"^(review|critic_note)\s*:\s*", "", t, flags=re.I)
    if voice_name and t.lower().startswith(voice_name.lower()):
        t = t[len(voice_name):].lstrip(" :-—").strip()
    if not t:
        return None
    low = t.lower()
    if "http" in low or "www." in low or "://" in t:
        return None  # never let the model emit anything link-like
    if any(ch in t for ch in "`|<>"):
        return None  # would break the review block or the "|" tells separator
    if len(t) > MAX_NOTE:
        cut = t[:MAX_NOTE]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = cut[: end + 1] if end > 80 else None
    return t


# ---- automatic rule check on the model's note ----
# Words that assert a fact. They're only allowed if the evidence itself says them.
CLAIM_WORDS = (
    "bank", "card", "password", "passcode", "pin", "recovery phrase", "seed phrase", "seed",
    "crypto", "wallet", "bitcoin", "paypal", "amazon", "microsoft", "apple", "google",
    "free hosting", "hosting plan", "vercel", "netlify", "cloudflare", "email", "sms", "text message",
    "account", "login", "log in", "sign in", "invoice", "package", "delivery", "refund", "tax",
)
SPECULATION = ("likely", "probably", "suggests", "seems", "appears", "perhaps", "maybe", "might be")
# Nationality, language and culture are off-limits for jokes (VOICE.md rule 4).
CULTURE = (
    "polish", "poland", "russian", "russia", "chinese", "china", "indian", "india", "nigerian", "nigeria",
    "african", "asian", "european", "american", "mexican", "brazilian", "ukrainian", "romanian",
    "vietnamese", "turkish", "arab", "foreign", "-sounding", "accent", "language",
)
# Punch at the scammer, never the reader or victim (VOICE.md rule 2).
VICTIM = ("gullible", "fool", "idiot", "dumb", "stupid", "naive", "sucker", "moron", "you fall for", "falls for")
GENERIC_LABELS = {"login", "logowanie", "secure", "verify", "verification", "account", "support",
                  "online", "update", "wallet", "signin", "service", "auth", "portal", "home", "www"}


def evidence_text(c: dict) -> str:
    return " ".join(evidence_lines(c)).lower()


def note_problems(note: str, c: dict) -> list[str]:
    """Reasons a model note breaks the rules. Empty list = passes."""
    low = note.lower()
    ev = evidence_text(c)
    problems = []
    for w in SPECULATION:
        if re.search(rf"\b{re.escape(w)}\b", low):
            problems.append(f"speculation ('{w}')")
    for w in CULTURE:
        if w in low:
            problems.append(f"nationality/language reference ('{w}')")
    for w in VICTIM:
        if w in low:
            problems.append(f"mocks the reader or victim ('{w}')")
    if re.search(r"[^\x00-\u024f\u2010-\u2027\u2030-\u205e]", note):
        problems.append("unexpected non-Latin characters")
    for w in CLAIM_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", low) and w not in ev:
            problems.append(f"claim not in evidence ('{w}')")
    if not c.get("record_brand"):
        host = (c.get("defanged_domain") or "").replace("[.]", ".").lower()
        squashed = re.sub(r"[^a-z0-9]", "", low)
        for label in re.split(r"[.\-]", host):
            word = re.sub(r"\d+$", "", label)
            if len(word) >= 5 and word not in GENERIC_LABELS and word in squashed:
                problems.append(f"names a brand the record doesn't ('{word}')")
    return problems


def ollama_chat(system: str, user: str) -> tuple[str | None, float]:
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": 0.7, "num_predict": 220},
    }).encode()
    req = Request(f"{OLLAMA_URL}/api/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urlopen(req, timeout=TIMEOUT_S) as r:
            out = json.load(r)
        return (out.get("message") or {}).get("content"), time.monotonic() - t0
    except (URLError, TimeoutError, ValueError) as exc:
        print(f"[warn] model call failed: {exc}", file=sys.stderr)
        return None, time.monotonic() - t0


def literal_tells(c: dict) -> str:
    tells = [t.replace("|", "/") for t in (c.get("auto_tells") or [])]
    return " | ".join(tells) if tells else PLACEHOLDER


def render_comment(c: dict, a: dict, note: str | None, seconds: float | None, rejected: list[str] | None = None) -> str:
    brand = c.get("record_brand") or PLACEHOLDER
    fields = [
        f"brand: {brand}",
        f"aisle: {PLACEHOLDER}",
        f"knockoff_label: {PLACEHOLDER}",
        f"verdict: {PLACEHOLDER}",
        f"rating: {PLACEHOLDER}",
        f"sketchy_segment: {PLACEHOLDER}",
        f"tells: {literal_tells(c)}",
        f"critic_note: {note or PLACEHOLDER}",
        f"voice: {a['voice']}",
        f"edge: {a['edge']}",
    ]
    timing = f"{seconds:.1f}s" if seconds is not None else "n/a"
    return "\n".join([
        DRAFT_HEADER,
        "",
        "Check every line against the screenshot on the public record. Replace each "
        f"`{PLACEHOLDER}`; the publisher refuses to publish while any remain. "
        "Edit this comment in place (or post your revision as a new comment), then add `approved`.",
        "",
        "```review",
        *fields,
        "```",
        "",
        f"<sub>Drafted by local model `{MODEL}` in {timing}. Only `critic_note` is model-written; "
        "`brand` and `tells` are copied from the scan record."
        + (f" Rule check rejected {len(rejected)} attempt(s) before this one." if rejected and note else "")
        + (" No attempt passed the rule check, so `critic_note` is left for you." if rejected and not note else "")
        + "</sub>",
    ])


MAX_ATTEMPTS = int(os.environ.get("OFFBRAND_DRAFT_ATTEMPTS", "3"))


def draft(c: dict, a: dict, chat=ollama_chat) -> tuple[str, float | None]:
    """Up to MAX_ATTEMPTS model calls; keep the first note that passes the rule check."""
    total, rejected, note = 0.0, [], None
    for _ in range(MAX_ATTEMPTS):
        raw, secs = chat(SYSTEM_PROMPT, build_user_prompt(c, a))
        total += secs or 0.0
        cand = clean_note(raw, a.get("voice_name"))
        if not cand:
            rejected.append("unusable output")
            continue
        problems = note_problems(cand, c)
        if problems:
            rejected.append("; ".join(problems))
            print(f"[draft] rejected: {problems} :: {cand}", file=sys.stderr)
            continue
        note = cand
        break
    return render_comment(c, a, note, total, rejected), total


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    c = json.loads(open(argv[1], encoding="utf-8").read())
    a = json.loads(open(argv[2], encoding="utf-8").read())
    body, secs = draft(c, a)
    print(body)
    print(f"draft_seconds={secs if secs is not None else 'n/a'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
