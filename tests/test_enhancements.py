"""Integration contract for the optional broadcast craftsmanship layer."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def test_enhancement_assets_are_loaded_after_core():
    html = (SITE / "index.html").read_text()
    for name in ("enhancements.css", "enhancements.js"):
        assert (SITE / name).is_file()
        assert f'{name}?v=__BUILD__' in html
    assert html.index('src="app.js?') < html.index('src="enhancements.js?')
    assert html.index('href="styles.css?') < html.index('href="enhancements.css?')
    assert 'script-src \'none\'' in (SITE / "methodology.html").read_text()


def test_enhancements_do_not_inject_markup_or_contact_targets():
    js = (SITE / "enhancements.js").read_text()
    assert not re.search(r"innerHTML|insertAdjacentHTML|\beval\s*\(|\bfetch\s*\(|XMLHttpRequest|window\.open", js)
    assert ".address-text" in js
    assert "does not determine the registrable domain" in js
    assert not re.search(r"\b(?:OBSERVED|ASSESSMENT|UNKNOWN|FIELD LESSON)\b", js)
