"""The Evidence Locker on the broadcast: levels, legacy reviews, safe links, phones.

The staged site is a temporary copy. One real specimen is given a synthetic evidence
block (reserved example names, test-only), the rest stay exactly as published.
"""
import functools
import http.server
import json
import shutil
import threading

import pytest

from test_site_e2e import CHROME, ROOT, _Quiet, browser, pw, wait_until  # noqa: F401

SYNTHETIC = {
    "version": 1, "level": "source-confirmed",
    "reason": "PhishTank verified this exact page as phishing.",
    "assessed_at": "2026-11-27T00:00:00Z", "captured_at": "2026-11-20T12:00:00Z",
    "specimen": {"defanged_url": "hxxps://login[.]bank-example[.]test/", "defanged_final_host": "accounts[.]example[.]com",
                 "redirected": True},
    "records": [
        {"source": "PhishTank", "match": "exact", "stance": "supports", "strength": "verified", "upstream": "phishtank",
         "detail": "Verified as phishing by PhishTank", "record_url": "https://www.phishtank.com/phish_detail.php?phish_id=9001"},
        {"source": "Mallory", "match": "same_host", "stance": "supports", "strength": "listed", "upstream": "x",
         "detail": "<img src=x onerror=alert(1)>", "record_url": "javascript:alert(1)"},
    ],
    "sources": {"PhishTank": {"status": "ok", "checked_at": "2026-11-27T00:00:00Z"},
                "OpenPhish": {"status": "rate_limited", "checked_at": "2026-11-27T00:00:00Z"}},
    "limitations": ["Captures document a moment; a page may have changed or gone offline since."],
    "editor_ack": "Kept for the redirect lesson.",
}


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    out = tmp_path_factory.mktemp("_site_evidence")
    shutil.copytree(ROOT / "site", out, dirs_exist_ok=True)
    (out / "data").mkdir()
    data = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8"))
    if len(data["items"]) < 2:
        pytest.skip("needs two published specimens")
    data["items"][0] = dict(data["items"][0], evidence=SYNTHETIC)
    if len(data["items"]) >= 3:
        data["items"][2] = dict(data["items"][2], evidence=dict(
            SYNTHETIC, level="suspected", editor_ack=None,
            reason="urlscan.io: scan submitted from the PhishTank feed; no source verified this page.",
            records=[SYNTHETIC["records"][0] | {"source": "urlscan.io", "strength": "label",
                                                 "detail": "scan submitted from the PhishTank feed",
                                                 "record_url": "https://urlscan.io/result/01a1f8dd-b83d-7541-b503-42125f30510e/"}]))
    (out / "data" / "reviews.json").write_text(json.dumps(data), encoding="utf-8")
    index = out / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("__BUILD__", "e2e"), encoding="utf-8")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html", data["items"]
    server.shutdown()


def tune(browser, url, item, width=1440, mobile=False):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce",
                              is_mobile=mobile, has_touch=mobile)
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(str(e)))
    page.on("dialog", lambda d: (page.problems.append("dialog"), d.dismiss()))
    page.route("https://urlscan.io/**", lambda route: route.abort())
    page.add_init_script("try { localStorage.setItem('offbrand.breaks.enabled', 'off'); } catch (e) {}")
    page.goto(url + "#" + item["id"])
    page.wait_for_selector(".locker")
    wait_until(page, f"document.getElementById('now').textContent.length > 0")
    return ctx, page


def test_locker_shows_level_reason_records_and_unread_sources(browser, staged):
    url, items = staged
    ctx, page = tune(browser, url, items[0])
    locker = page.locator(".locker")
    assert locker.locator(".locker-stamp").inner_text() == "SOURCE-CONFIRMED"
    assert locker.locator(".locker-stamp").get_attribute("aria-label") == "Evidence level: source-confirmed"
    assert "PhishTank verified this exact page" in locker.inner_text()
    assert "Editor's note: Kept for the redirect lesson." in locker.inner_text()
    page.click(".locker-more summary")
    text = locker.inner_text()
    assert "OpenPhish: not checked (download limit)" in text and "PhishTank: checked" in text
    assert "EXACT PAGE" in text and "SAME HOST" in text
    assert "accounts[.]example[.]com" in text
    links = [a.get_attribute("href") for a in locker.locator("a").all()]
    assert links == ["https://www.phishtank.com/phish_detail.php?phish_id=9001"]
    assert all(a.get_attribute("rel") == "noopener noreferrer" for a in locker.locator("a").all())
    assert locker.locator("img").count() == 0  # record text is never parsed as HTML
    assert page.problems == []
    ctx.close()


def test_reviews_without_evidence_say_not_yet_rated(browser, staged):
    url, items = staged
    ctx, page = tune(browser, url, items[1])
    assert page.locator(".locker-stamp").inner_text() == "NOT YET RATED"
    assert "not independently confirmed" in page.locator(".locker").inner_text()
    assert page.locator(".fact-links a").count() >= 1  # the original record link is still there
    ctx.close()


def test_locker_is_a_labelled_region_with_a_keyboard_reachable_toggle(browser, staged):
    url, items = staged
    ctx, page = tune(browser, url, items[0])
    labelled = page.evaluate("""() => { const s = document.querySelector('.locker');
        const id = s.getAttribute('aria-labelledby'); return document.getElementById(id)?.textContent; }""")
    assert labelled == "EVIDENCE LOCKER"
    page.focus(".locker-more summary")
    page.keyboard.press("Enter")
    assert page.evaluate("document.querySelector('.locker-more').open")
    ctx.close()


@pytest.mark.parametrize("width", [320, 390])
def test_locker_fits_small_phones(browser, staged, width):
    url, items = staged
    ctx, page = tune(browser, url, items[0], width=width, mobile=True)
    page.click(".locker-more summary")
    right = page.evaluate("Math.max(...[...document.querySelectorAll('.locker, .locker *')].map(e => e.getBoundingClientRect().right))")
    assert right <= width + 0.5
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    ctx.close()


def test_suspected_is_never_presented_as_confirmed(browser, staged):
    url, items = staged
    if len(items) < 3:
        pytest.skip("needs three published specimens")
    ctx, page = tune(browser, url, items[2])
    assert page.locator(".locker-stamp").inner_text() == "SUSPECTED · NOT CONFIRMED"
    caution = page.locator(".address-caution")
    assert caution.count() == 1 and "not confirmed phishing" in caution.inner_text()
    lineup = page.locator(f"#lineup button[data-i='2']").inner_text()
    assert "suspected, not confirmed" in lineup
    # Confirmed and legacy specimens carry no caution line.
    page.evaluate(f"location.hash = {json.dumps('#' + items[0]['id'])}")
    wait_until(page, "!document.querySelector('.address-caution')")
    ctx.close()
