"""Static contract for the public station standards page."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from evidence import LABELS

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, name):
        super().__init__()
        self.tags = []
        self.feed((ROOT / "site" / name).read_text())

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_methodology_static_links_and_fragments():
    page = Page("methodology.html")
    ids = [a["id"] for _, a in page.tags if "id" in a]
    assert len(ids) == len(set(ids))
    assert {"standards", "process", "confidence", "limits", "corrections"} <= set(ids)
    for tag, a in page.tags:
        if tag not in {"a", "link"} or "href" not in a:
            continue
        u = urlsplit(a["href"])
        if u.scheme:
            assert u.scheme == "https" and u.netloc == "github.com"
        elif u.path:
            assert (ROOT / "site" / u.path).is_file()
        elif u.fragment:
            assert u.fragment in ids
    assert not any(t in {"script", "iframe", "form", "img"} for t, _ in page.tags)
    assert sum(t == "h1" for t, _ in page.tags) == 1


def test_evidence_labels_and_restrictions_are_documented():
    text = (ROOT / "site" / "methodology.html").read_text()
    for label in LABELS.values():
        assert f"<dt>{label}</dt>" in text
    for phrase in ("Not yet rated", "current sources do not award this level",
                   "New publication is blocked", "not a negative result",
                   "does not automatically permit redistribution", "Issues are public"):
        assert phrase in text
    assert "script-src 'none'" in text


def test_broadcast_links_and_deploy_cache_bust():
    page = Page("index.html")
    links = {a.get("href") for t, a in page.tags if t == "a"}
    assert {"methodology.html", "methodology.html#corrections"} <= links
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "scripts/stage_site.py _site" in deploy
    from stage_site import PAGES
    assert {"index.html", "methodology.html"} <= set(PAGES)
