"""Security & sanitization helpers for Off-Brand.

Everything coming from a scanned page or external feed is hostile input.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

ALLOWED_RECORD_HOSTS = {
    "urlscan.io",
    "openphish.com",
    "phishtank.net",
    "www.phishtank.net",
}

CONTROL_AND_ZERO_WIDTH_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]"
)


def sanitize_text(value: str | None, max_len: int = 280) -> str | None:
    """Normalize unicode, strip control/bidi/zero-width chars, collapse whitespace."""
    if value is None:
        return None
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = CONTROL_AND_ZERO_WIDTH_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def defang_domain(domain: str | None) -> str | None:
    """Defang a domain or hostname so it cannot be auto-linked."""
    cleaned = sanitize_text(domain, max_len=255)
    if not cleaned:
        return None
    return cleaned.replace(".", "[.]")


def defang_url(url: str | None) -> str | None:
    """Defang a URL (hxxps://host[.]tld/path) and reject non-http(s) schemes."""
    cleaned = sanitize_text(url, max_len=512)
    if not cleaned:
        return None
    lower = cleaned.lower()
    if lower.startswith("https://"):
        rest = cleaned[8:]
        scheme = "hxxps://"
    elif lower.startswith("http://"):
        rest = cleaned[7:]
        scheme = "hxxp://"
    elif lower.startswith("hxxps://") or lower.startswith("hxxp://"):
        scheme, rest = cleaned.split("://", 1)
        scheme = scheme.lower() + "://"
    else:
        return None

    if "/" in rest:
        host, path = rest.split("/", 1)
        path = "/" + path
    else:
        host, path = rest, ""

    host = host.replace("[.]", ".").replace(".", "[.]")
    return f"{scheme}{host}{path}"


def validate_public_record_url(url: str | None) -> str | None:
    """Only allow HTTPS links to known public-record providers."""
    if not url:
        return None
    cleaned = sanitize_text(url, max_len=512)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ALLOWED_RECORD_HOSTS:
        return None
    return cleaned
