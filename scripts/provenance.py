"""Authenticate collected triage issue bodies, not editor comments.

HMAC authenticates the trusted workflow's snapshot, NOT the truth of a provider
claim. The owner retains the approval gate. No target URL is ever contacted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess

KEY_ENV = "OFFBRAND_PROVENANCE_KEY"
MARKER = "evidence_attestation: "
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SIG_RE = re.compile(r"v1:[0-9a-f]{64}")


def signing_key(value: str | None = None) -> bytes:
    value = os.environ.get(KEY_ENV, "") if value is None else value
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("Configure OFFBRAND_PROVENANCE_KEY as 32 random bytes encoded in hex.")
    return bytes.fromhex(value)


def canonical_body(body: str) -> str:
    if not isinstance(body, str):
        raise ValueError("Invalid collection body.")
    return body.replace("\r\n", "\n").rstrip("\n")


def _tag(body: str, repo: str, issue: int, key: bytes) -> str:
    if not REPO_RE.fullmatch(repo) or type(issue) is not int or issue <= 0 or len(key) != 32:
        raise ValueError("Invalid provenance context.")
    message = json.dumps(["offbrand-collection-v1", repo.lower(), issue, body],
                         ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return "v1:" + hmac.new(key, message, hashlib.sha256).hexdigest()


def attest(body: str, repo: str, issue: int, key: bytes) -> str:
    body = canonical_body(body)
    if any(line.strip().startswith(MARKER.strip()) for line in body.splitlines()):
        raise ValueError("Collection body already contains an attestation marker.")
    return body + "\n\n" + MARKER + _tag(body, repo, issue, key)


def verify(body: str, repo: str, issue: int, key: bytes) -> str:
    """Return authenticated body; never print the body, tag or key on failure."""
    body = canonical_body(body)
    unsigned, separator, tail = body.rpartition("\n\n" + MARKER)
    if (not separator or not SIG_RE.fullmatch(tail)
            or any(line.strip().startswith(MARKER.strip()) for line in unsigned.splitlines())
            or not hmac.compare_digest(tail, _tag(unsigned, repo, issue, key))):
        raise ValueError("Missing or invalid collection attestation; refuse publication.")
    return unsigned


def create_attested_issue(repo: str, title: str, body: str, runner=subprocess.run) -> dict:
    """Create then attest using the actual assigned issue number.

    A failed edit leaves an unsigned issue, which can never be published. Do not
    sign the body returned from GitHub: only sign the original collector output.
    """
    key = signing_key()
    body = canonical_body(body)
    if not REPO_RE.fullmatch(repo) or any(line.strip().startswith(MARKER.strip()) for line in body.splitlines()):
        raise ValueError("Invalid collection issue.")
    try:
        url = runner(["gh", "issue", "create", "-R", repo, "--title", title, "--body", body,
                      "--label", "triage"], check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError:
        raise ValueError("Collection issue creation failed.") from None
    match = re.fullmatch(r"https://github\.com/" + re.escape(repo) + r"/issues/([1-9][0-9]*)", url, re.IGNORECASE)
    if not match:
        raise ValueError("Unexpected created issue URL; no attestation issued.")
    issue = int(match[1])
    signed = attest(body, repo, issue, key)
    try:
        runner(["gh", "issue", "edit", str(issue), "-R", repo, "--body", signed],
               check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        raise ValueError("Collection issue created but attestation failed; it cannot publish.") from None
    return {"number": issue, "url": url}
