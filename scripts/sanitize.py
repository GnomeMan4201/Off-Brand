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
    """Defang without changing identity; reject rather than truncate or fold.

    The text sanitizer is intentionally not used for specimen addresses.
    """
    if not isinstance(url, str) or not url or len(url) > 512:
        return None
    if CONTROL_AND_ZERO_WIDTH_RE.search(url) or any(c.isspace() for c in url):
        return None
    match = re.fullmatch(r"(https?|hxxps?)://([^/?#]+)(.*)", url, re.I)
    if not match:
        return None
    scheme, authority, suffix = match.groups()
    # Do not publish embedded credentials or ambiguous bracket syntax.
    if "@" in authority or (scheme.lower().startswith("http") and "[.]" in authority):
        return None
    if "[" in authority.replace("[.]", "") or "]" in authority.replace("[.]", ""):
        return None
    scheme = "hxxps" if scheme.lower().endswith("s") else "hxxp"
    result = scheme + "://" + authority.replace("[.]", ".").replace(".", "[.]") + suffix
    # Compare the actual keys as a guard against transformations.
    from normalize import normalize
    before, after = normalize(url), normalize(result)
    if not before or not after or before["exact_key"] != after["exact_key"] or len(result) > 512:
        return None
    return result


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
