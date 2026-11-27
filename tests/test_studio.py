from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/"site"

def test_studio_shell_and_integration():
    html=(SITE/"studio.html").read_text()
    assert "script-src 'self'" in html and "style-src 'self'" in html
    assert "<style" not in html and " style=" not in html
    assert 'studio.js?v=__BUILD__' in html and 'studio.css?v=__BUILD__' in html
    assert "NOT A LIVE SCHEDULE" in html
    from stage_site import PAGES
    assert "studio.html" in PAGES
    assert "scripts/stage_site.py _site" in (ROOT/".github/workflows/deploy.yml").read_text()
    for page in ("continuity","props","readings"):
        assert "studio.html#"+page in (SITE/"teletext.js").read_text()

def test_studio_uses_only_public_archive_and_explicit_audio():
    js=(SITE/"studio.js").read_text()
    assert not re.search(r"innerHTML|insertAdjacentHTML|\beval\s*\(|XMLHttpRequest|window\.open",js)
    assert re.findall(r'\bfetch\("([^"]+)"',js)==["data/reviews.json"]
    assert 'matchExcerpt(items,card)' in js
    assert 'visibilitychange' in js and 'pagehide' in js
    assert 'prior.close()' in js and 'ctx.resume()' in js
    assert 'FICTIONAL STATION CONTINUITY' in js
