"""Safe URL normalization for matching records across sources.

Nothing here fetches anything. A defanged URL (hxxps://host[.]tld/...) is refanged
only in memory so it can be compared with a feed entry; the result is never linked,
printed to the public site or requested.

The rule is: never merge two addresses that could be different pages. Only changes
that cannot alter what a server receives are applied:
- scheme and hostname are lowercased (both are case-insensitive), and an internationalized
  hostname is converted to punycode only if it round-trips without loss;
- an explicit default port (:443 for https, :80 for http) is dropped;
- an empty path becomes "/".
Everything else is kept byte for byte: path case, query parameters and their order,
percent-escapes (never decoded, never re-cased), userinfo and the fragment. No Unicode
compatibility folding is applied to the path or query.

Two match keys:
- exact key: the full address including scheme after the steps above.
- scheme key: the same normalized address without its scheme, for related matches
  only. HTTP and HTTPS may serve different content and never confirm each other.
- host key: the hostname alone. A host match says "same site", not "same page".
"""

from __future__ import annotations

import re

# Hosts shared by unrelated tenants. Two different pages here say nothing about each
# other, so host-level matches on them are discarded rather than counted.
SHARED_HOSTS = frozenset({
    "sites.google.com", "docs.google.com", "drive.google.com", "forms.gle",
    "storage.googleapis.com", "firebasestorage.googleapis.com", "www.google.com", "google.com",
    "ipfs.io", "dweb.link", "cloudflare-ipfs.com",
    "app.jotform.com", "form.jotform.com", "eu.jotform.com", "jotform.com",
    "forms.office.com", "onedrive.live.com", "1drv.ms", "login.microsoftonline.com",
    "dropbox.com", "www.dropbox.com", "github.com", "raw.githubusercontent.com",
    "bit.ly", "t.co", "tinyurl.com", "linktr.ee",
    "notion.site", "www.notion.so", "canva.com", "www.canva.com",
})

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_FORBIDDEN = re.compile(r"[\x00-\x20\x7f]")  # controls and spaces never appear in a real URL
_URL = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[^/?#]*)(?P<rest>.*)$", re.S)
_DEFANG_SCHEME = re.compile(r"^hxxp(s?)$", re.IGNORECASE)


def refang_authority(authority: str) -> str:
    """Undo defanging in the host part only; the path and query are never touched."""
    return authority.replace("[.]", ".").replace("[:]", ":").replace("(.)", ".")


def refang(value: str) -> str:
    """Refang a defanged URL or hostname (scheme + authority only)."""
    text = value.strip()
    m = _URL.match(text)
    if not m:
        return refang_authority(text)
    scheme = _DEFANG_SCHEME.sub(r"http\1", m["scheme"])
    return f"{scheme}://{refang_authority(m['authority'])}{m['rest']}"


def _split_rest(rest: str) -> tuple[str, str | None, str | None]:
    frag = None
    if "#" in rest:
        rest, frag = rest.split("#", 1)
    query = None
    if "?" in rest:
        rest, query = rest.split("?", 1)
    return rest, query, frag


def _host(hostport: str) -> tuple[str, str | None] | None:
    if not hostport or hostport.startswith("["):
        return None  # IPv6 literals are not expected from these feeds
    host, port = hostport, None
    if ":" in hostport:
        host, port = hostport.rsplit(":", 1)
        if not port.isdigit():
            return None
    host = host.lower()
    if not host or re.search(r"[\s/\\?#@]", host):
        return None
    if not host.isascii():
        try:
            ascii_host = host.encode("idna").decode("ascii")
            if ascii_host.encode("ascii").decode("idna") != host:
                return None
            host = ascii_host
        except UnicodeError:
            return None  # not a valid IDN; refuse rather than guess
    if port is not None and (not port.isascii() or len(port) > 5 or int(port) > 65535):
        return None
    return host, port


def normalize(url: str | None) -> dict | None:
    """Return {"scheme", "host", "exact_key", "host_key"} or None if unusable."""
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not text or len(text) > 4096 or _FORBIDDEN.search(text):
        return None
    m = _URL.match(refang(text))
    if not m:
        return None
    scheme = m["scheme"].lower()
    if scheme not in _DEFAULT_PORTS:
        return None
    authority = m["authority"]
    userinfo = None
    if "@" in authority:
        userinfo, authority = authority.rsplit("@", 1)  # the host is what follows the last @
    parsed = _host(authority)
    if not parsed:
        return None
    host, port = parsed
    if port == _DEFAULT_PORTS[scheme]:
        port = None
    path, query, frag = _split_rest(m["rest"])
    netloc = host + (f":{port}" if port else "")
    exact = ("//" + (f"{userinfo}@" if userinfo is not None else "") + netloc
             + (path or "/") + (f"?{query}" if query is not None else "")
             + (f"#{frag}" if frag is not None else ""))
    return {"scheme": scheme, "host": netloc, "exact_key": scheme + ":" + exact,
            "scheme_key": exact, "host_key": host}


def is_shared_host(host_key: str | None) -> bool:
    return bool(host_key) and host_key in SHARED_HOSTS
