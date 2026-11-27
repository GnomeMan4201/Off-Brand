import json
from html.parser import HTMLParser
from pathlib import Path

from build_reading_edition import build

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_reading_edition_preserves_public_archive_and_is_script_free():
    data = json.loads((ROOT / "data/reviews.json").read_text())
    text = build(data)
    page = Page(text)
    assert len([a for t, a in page.tags if t == "article"]) == len(data["items"])
    assert not any(t in ("script", "iframe", "form", "img") for t, _ in page.tags)
    assert "script-src 'none'" in text
    assert "Not yet rated" in text
    assert "existing published review text" in text
    from stage_site import PAGES
    assert "reading.html" in PAGES
    assert "scripts/stage_site.py _site" in (ROOT / ".github/workflows/deploy.yml").read_text()


def test_hostile_record_text_cannot_create_tags_or_active_target_links():
    payload = '<img src=x onerror="alert(1)">'
    data = {"items": [{"id":"javascript:alert(1)","knockoff_label":payload,
                       "defanged_url":"https://example.invalid/", "tells":[payload],
                       "evidence":{"level":"suspected"}}]}
    text = build(data)
    page = Page(text)
    assert not any(t == "img" for t, _ in page.tags)
    assert all(not a.get("href","").startswith(("javascript:", "https://example.invalid")) for t,a in page.tags)
    assert "Suspected, not confirmed" in text
    assert "&lt;img" in text
    assert "No published reviews" in build({"items":[]})


def test_unknown_evidence_never_receives_rating():
    assert "Not yet rated" in build({"items":[{"evidence":{"level":"invented"}}]})
