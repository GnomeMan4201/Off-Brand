from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

def test_teletext_shell_and_deploy():
    text = (SITE / "teletext.html").read_text()
    assert "script-src 'self'" in text
    assert "style-src 'self'" in text
    assert "<style" not in text and " style=" not in text
    assert "teletext.css?v=__BUILD__" in text
    assert "teletext.js?v=__BUILD__" in text
    assert (SITE / "teletext.css").is_file()
    assert (SITE / "teletext.js").is_file()
    assert 'href="teletext.html#100"' in (SITE / "index.html").read_text()
    assert "_site/teletext.html" in (ROOT / ".github/workflows/deploy.yml").read_text()

def test_teletext_only_loads_public_data_and_uses_text_nodes():
    src = (SITE / "teletext.js").read_text()
    assert not re.search(r"innerHTML|insertAdjacentHTML|\beval\s*\(|XMLHttpRequest|window\.open", src)
    assert set(re.findall(r'\bload\("([^"]+)"\)',src)) == {"data/reviews.json","commercials/manifest.json"}
    assert "row.reason" in src
    assert "row.defanged_domain" not in src and "row.public_record_url" not in src
    assert "Not yet rated" in src
    assert "FICTIONAL STATION" in src
