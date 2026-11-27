"""Shared test setup: no test may download a real intelligence feed.

PhishTank allows only a few unkeyed downloads a day, and live feeds change every hour,
so feed access is replaced with a network failure unless a test supplies its own opener.
"""
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import feeds  # noqa: E402

_real_http_get = feeds._http_get


@pytest.fixture(autouse=True)
def no_live_feeds(monkeypatch):
    def guarded(url, max_bytes, opener=None, headers=None):
        if opener is None:
            raise URLError("live feed access is disabled in tests")
        return _real_http_get(url, max_bytes, opener, headers)

    monkeypatch.setattr(feeds, "_http_get", guarded)
