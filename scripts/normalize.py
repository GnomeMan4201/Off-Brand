"""Safe URL normalization for matching records across sources.

Nothing here fetches anything. A defanged URL (hxxps://host[.]tld/...) is refanged
only in memory so it can be compared with a feed entry; the result is never linked,
printed to the public site or requested.

Two match keys:
- exact key: host + path + query (scheme ignored, fragment dropped). Two records
  with the same exact key describe the same page address.
- host key: the hostname alone. A host match says "same site", not "same page".
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from sanitize import sanitize_text

# Hosts shared by unrelated tenants. Two different pages here say nothing about each
# other, so host-level matches on them are discarded rather than counted.
SHARED_HOSTS = frozenset({
    "sites.google.com", "docs.google.com", "drive.google.com", "forms.gle",
    "storage.googleapis.com", "firebasestorage.googleapis.com",
    "ipfs.io", "dweb.link", "cloudflare-ipfs.com",
    "app.jotform.com", "form.jotform.com", "eu.jotform.com", "jotform.com",
    "forms.office.com", "onedrive.live.com", "1drv.ms",
    "dropbox.com", "www.dropbox.com", "github.com", "raw.githubusercontent.com",
    "bit.ly", "t.co", "tinyurl.com", "linktr.ee",
    "notion.site", "www.notion.so", "canva.com", "www.canva.com",
})

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def refang(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^hxxp(s?)://", r"http\1://", text, flags=re.IGNORECASE)
    return text.replace("[.]", ".").replace("[:]", ":").replace("(.)", ".")


def _host(netloc: str) -> str | None:
    if "@" in netloc:  # userinfo is a classic disguise; the host is what follows it
        netloc = netloc.rsplit("@", 1)[1]
    host, port = netloc, None
    if netloc.startswith("["):
        return None  # IPv6 literals are not expected from these feeds
    if ":" in netloc:
        host, port = netloc.rsplit(":", 1)
        if not port.isdigit():
            return None
    host = host.strip().rstrip(".").lower()
    if not host or not re.fullmatch(r"[^\s/\\?#]+", host):
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass  # keep the lowercase form; comparison is still consistent
    return host + (f":{port}" if port else "")


def normalize(url: str | None) -> dict | None:
    """Return {"scheme", "host", "exact_key", "host_key"} or None if unusable."""
    cleaned = sanitize_text(url, max_len=2048)
    if not cleaned:
        return None
    parts = urlsplit(refang(cleaned))
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        return None
    host = _host(parts.netloc)
    if not host:
        return None
    if host.endswith(":" + _DEFAULT_PORTS[scheme]):
        host = host.rsplit(":", 1)[0]
    path = parts.path or "/"
    exact = host + path + (f"?{parts.query}" if parts.query else "")
    return {"scheme": scheme, "host": host, "exact_key": exact, "host_key": host.split(":")[0]}


def is_shared_host(host_key: str | None) -> bool:
    return bool(host_key) and host_key in SHARED_HOSTS
