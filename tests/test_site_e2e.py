"""End-to-end checks for After Dark and its commercial breaks.

Skipped unless Playwright and a Chrome with H.264 support are available.
Point OFFBRAND_CHROME at a Chrome binary to choose one; otherwise
/usr/bin/google-chrome is used if it exists.
"""
import functools
import http.server
import os
import re
import shutil
import threading
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
CHROME = os.environ.get("OFFBRAND_CHROME") or "/usr/bin/google-chrome"
if not Path(CHROME).exists():
    pytest.skip("no Chrome binary for end-to-end tests", allow_module_level=True)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    # Stage the site exactly the way .github/workflows/deploy.yml does.
    out = tmp_path_factory.mktemp("_site")
    shutil.copytree(ROOT / "site", out, dirs_exist_ok=True)
    (out / "data").mkdir()
    shutil.copy(ROOT / "data" / "reviews.json", out / "data" / "reviews.json")
    index = out / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("__BUILD__", "e2e"), encoding="utf-8")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--autoplay-policy=user-gesture-required"])
        yield b
        b.close()


def open_page(browser, base_url, *, mobile=False, reduce=False, block_video=False, init=None, routes=None, wait_originals=True):
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1000},
        reduced_motion="reduce" if reduce else "no-preference",
        is_mobile=mobile, has_touch=mobile,
    )
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("response", lambda r: page.problems.append(f"{r.status} {r.url}") if r.status >= 400 and "127.0.0.1" in r.url else None)
    page.route("https://urlscan.io/**", lambda route: route.abort())  # never leave the test box
    if block_video:
        page.route("**/commercials/*.mp4", lambda route: route.fulfill(status=404, body="gone"))
    for pattern, handler in (routes or {}).items():
        page.route(pattern, handler)
    if init:
        page.add_init_script(init)
    page.goto(base_url)
    page.wait_for_selector("#lineup li")
    if wait_originals:
        page.wait_for_selector("#originals:not([hidden])")
    return page


def ch(page):
    return int(re.search(r"CH (\d\d)", page.inner_text("#now")).group(1))


def settle(page):
    """Let a static or PSA interstitial finish; return True if a break started instead."""
    for _ in range(60):
        if page.locator(".bumper, .commercial").count():
            return True
        if page.locator(".psa").count():
            page.click(".psa button")
        if page.locator("#interstitial").is_hidden():
            return False
        page.wait_for_timeout(100)
    raise AssertionError("interstitial never cleared")


def next_until_break(page, limit=8):
    for n in range(1, limit + 1):
        before = ch(page)
        page.click("#next")
        if settle(page):
            return n, before
    raise AssertionError(f"no commercial break within {limit} channel changes")


def wait_playing(page):
    page.wait_for_selector(".commercial video", timeout=6000)
    page.wait_for_function("() => { const v = document.querySelector('.commercial video'); return v && v.currentTime > 0.2; }", timeout=8000)


def expected_next(before):
    return before % 9 + 1


def test_breaks_rotate_start_muted_and_return_to_the_target(browser, base_url):
    page = open_page(browser, base_url)
    titles = []
    for _ in range(4):
        n, before = next_until_break(page)
        assert 4 <= n <= 7, f"break after {n} changes"
        assert page.locator(".bumper p").inner_text().strip()
        wait_playing(page)
        video = page.locator(".commercial video")
        assert video.evaluate("v => v.muted") is True
        assert video.get_attribute("autoplay") is None
        titles.append(page.inner_text(".ad-top span"))
        page.click(".skip-ad")
        assert page.locator("#interstitial").is_hidden()
        assert ch(page) == expected_next(before)
    assert len(set(titles)) == 4, titles  # no repeats until the rotation is used up
    assert not page.problems, page.problems
    page.context.close()


def test_failed_video_falls_back_and_browsing_continues(browser, base_url):
    page = open_page(browser, base_url, block_video=True)
    _, before = next_until_break(page)
    page.wait_for_function("() => document.getElementById('interstitial').hidden", timeout=10000)
    assert ch(page) == expected_next(before)
    assert "unavailable" in page.inner_text("#break-status")
    for _ in range(3):  # ordinary browsing is unaffected
        b = ch(page)
        page.click("#next")
        settle(page)
        page.wait_for_function("() => document.getElementById('interstitial').hidden", timeout=10000)
        assert ch(page) == expected_next(b)
    page.context.close()


def test_turning_breaks_off_persists_across_reloads(browser, base_url):
    page = open_page(browser, base_url)
    page.click("#breaks-toggle")
    assert page.get_attribute("#breaks-toggle", "aria-pressed") == "false"
    page.reload()
    page.wait_for_selector("#lineup li")
    assert page.get_attribute("#breaks-toggle", "aria-pressed") == "false"
    for _ in range(9):
        page.click("#next")
        assert settle(page) is False
    page.click("#breaks-toggle")
    page.reload()
    page.wait_for_selector("#lineup li")
    assert page.get_attribute("#breaks-toggle", "aria-pressed") == "true"
    page.context.close()


def test_keyboard_controls_the_break(browser, base_url):
    page = open_page(browser, base_url)
    _, before = next_until_break(page)
    wait_playing(page)
    page.focus(".ad-controls button[aria-label='Pause']")
    page.keyboard.press("Enter")
    assert page.locator(".commercial video").evaluate("v => v.paused") is True
    page.focus(".ad-controls button[aria-label='Turn sound on']")
    page.keyboard.press("Enter")
    assert page.locator(".commercial video").evaluate("v => v.muted") is False
    page.keyboard.press("Escape")
    assert page.locator("#interstitial").is_hidden()
    assert ch(page) == expected_next(before)
    assert page.evaluate("document.activeElement.id") == "screen"  # focus is not lost
    page.context.close()


def test_changing_channel_during_a_break_skips_it(browser, base_url):
    page = open_page(browser, base_url)
    _, before = next_until_break(page)
    page.click("#next")
    assert page.locator("#interstitial").is_hidden()
    assert ch(page) == expected_next(expected_next(before))
    page.context.close()


def test_reduced_motion_never_autoplays(browser, base_url):
    page = open_page(browser, base_url, reduce=True)
    _, before = next_until_break(page)
    assert page.locator(".bumper.noisy").count() == 0
    page.wait_for_timeout(2500)
    assert page.locator(".commercial video").count() == 0  # waits for the viewer
    page.click(".bumper-actions button:has-text('Skip to CH')")
    assert ch(page) == expected_next(before)
    page.context.close()


def test_originals_play_on_request_with_sound_on_mobile(browser, base_url):
    page = open_page(browser, base_url, mobile=True)
    start = ch(page)
    rows = page.locator(".listing")
    assert rows.count() >= 1
    assert page.inner_text(".listing time >> nth=0") == "2:00:00 AM"
    rows.nth(1).locator(".watch-btn").click()
    wait_playing(page)
    assert page.locator(".commercial video").evaluate("v => v.muted") is False
    assert "OFF-BRAND ORIGINALS" in page.inner_text(".ad-top span")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.click(".skip-ad")
    assert ch(page) == start
    assert not page.problems, page.problems
    page.context.close()


def test_page_has_a_favicon_and_no_missing_files(browser, base_url):
    page = open_page(browser, base_url)
    icon = page.evaluate("fetch('favicon.svg').then(r => r.status)")
    assert icon == 200
    page.wait_for_timeout(500)
    assert not page.problems, page.problems
    page.context.close()


# ---------- regressions found in review of PR #19 ----------

def interstitial_closed(page, timeout):
    page.wait_for_function("() => document.getElementById('interstitial').hidden", timeout=timeout)


def skip_break(page):
    page.evaluate("document.getElementById('screen').focus()")
    page.keyboard.press("Escape")
    interstitial_closed(page, 3000)


def test_rapid_switching_into_a_break_keeps_the_latest_destination(browser, base_url):
    """Issue 1: a pending static switch must not overwrite the newer break target."""
    page = open_page(browser, base_url)
    for _ in range(3):  # several breaks, each reached by clicking faster than the static clears
        start = ch(page)
        clicks = 0
        while not page.locator(".bumper, .commercial").count():
            assert clicks < 8, "no break within 8 rapid clicks"
            page.click("#next")
            clicks += 1
            page.wait_for_timeout(60)
        skip_break(page)
        assert ch(page) == (start - 1 + clicks) % 9 + 1, f"after {clicks} rapid clicks from CH {start:02d}"
    page.context.close()


def test_rapid_lineup_pick_into_a_break_lands_on_the_pick(browser, base_url):
    page = open_page(browser, base_url)
    target = None
    for _ in range(9):
        page.click("#next")
        page.wait_for_timeout(60)
        pick = (ch(page) + 3) % 9  # 0-based index of a channel several steps away
        page.locator("#lineup button").nth(pick).click()
        target = pick + 1
        page.wait_for_timeout(60)
        if page.locator(".bumper, .commercial").count():
            break
        settle(page)
        interstitial_closed(page, 6000)
    else:
        raise AssertionError("no break reached")
    skip_break(page)
    assert ch(page) == target
    page.context.close()


NEVER_STARTS = """
HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
"""

AUTOPLAY_BLOCKED = """
HTMLMediaElement.prototype.play = function () { return Promise.reject(new DOMException('blocked', 'NotAllowedError')); };
"""


def test_video_that_loads_but_never_starts_returns_to_the_program(browser, base_url):
    """Issue 2a: loadeddata alone must not satisfy the watchdog."""
    page = open_page(browser, base_url, init=NEVER_STARTS)
    _, before = next_until_break(page)
    page.wait_for_selector(".commercial video")
    page.wait_for_function("() => document.querySelector('.commercial video').readyState >= 2", timeout=6000)
    interstitial_closed(page, 14000)
    assert ch(page) == expected_next(before)
    assert "unavailable" in page.inner_text("#break-status")
    page.context.close()


def test_video_that_stalls_mid_playback_returns_to_the_program(browser, base_url):
    """Issue 2b: playback that freezes without a pause event must time out."""
    page = open_page(browser, base_url)
    _, before = next_until_break(page)
    wait_playing(page)
    page.wait_for_function("() => document.querySelector('.commercial video').currentTime > 1", timeout=8000)
    page.evaluate("document.querySelector('.commercial video').playbackRate = 0")  # frozen, not paused
    assert page.evaluate("document.querySelector('.commercial video').paused") is False
    interstitial_closed(page, 14000)
    assert ch(page) == expected_next(before)
    page.context.close()


def test_intentional_pause_is_not_treated_as_a_failure(browser, base_url):
    """Issue 2c: a viewer's pause must never trip the stall watchdog."""
    page = open_page(browser, base_url)
    next_until_break(page)
    wait_playing(page)
    page.click(".ad-controls button[aria-label='Pause']")
    page.wait_for_timeout(11000)
    assert page.locator(".commercial video").count() == 1
    assert "unavailable" not in page.inner_text("#break-status")
    page.click(".ad-controls button[aria-label='Play']")
    page.wait_for_function("() => !document.querySelector('.commercial video').paused", timeout=3000)
    page.click(".skip-ad")
    page.context.close()


def test_autoplay_refusal_does_not_strand_the_viewer(browser, base_url):
    """Issue 2d: a break that is waiting for a tap still ends on its own, and the ad is not blacklisted."""
    page = open_page(browser, base_url, init=AUTOPLAY_BLOCKED)
    _, before = next_until_break(page)
    page.wait_for_selector(".ad-overlay")
    interstitial_closed(page, 14000)
    assert ch(page) == expected_next(before)
    assert page.locator(".watch-btn[disabled]").count() == 0  # not marked as broken
    page.context.close()


def _browse_nine(page):
    for _ in range(9):
        b = ch(page)
        page.click("#next")
        assert settle(page) is False, "a break started without its pieces"
        interstitial_closed(page, 6000)
        assert ch(page) == expected_next(b)
    assert not [p for p in page.problems if p.startswith("pageerror")], page.problems


@pytest.mark.parametrize("failure", ["breaks.js 404", "manifest 404", "manifest garbage", "manifest wrong shape"])
def test_specimens_still_browse_when_break_pieces_fail(browser, base_url, failure):
    """Issue 3: nothing about commercials may stop ordinary browsing."""
    routes = {
        "breaks.js 404": {"**/breaks.js*": lambda r: r.fulfill(status=404, body="gone")},
        "manifest 404": {"**/commercials/manifest.json*": lambda r: r.fulfill(status=404, body="gone")},
        "manifest garbage": {"**/commercials/manifest.json*": lambda r: r.fulfill(status=200, body="{not json", content_type="application/json")},
        "manifest wrong shape": {"**/commercials/manifest.json*": lambda r: r.fulfill(status=200, body='{"commercials": {"id": 1}, "bumpers": null}', content_type="application/json")},
    }[failure]
    page = open_page(browser, base_url, routes=routes, wait_originals=False)
    page.problems[:] = [p for p in page.problems if "breaks.js" not in p and "manifest.json" not in p]
    assert page.inner_text("#now").startswith("Now showing CH")
    assert page.locator("#originals").is_hidden()
    assert page.locator(".station-pref").is_hidden()  # no switch for a feature that is not there
    _browse_nine(page)
    page.context.close()


def test_reduced_motion_break_ends_by_itself_if_nobody_chooses(browser, base_url):
    """Issue 2e: a break waiting on the viewer must not wait forever."""
    page = open_page(browser, base_url, reduce=True)
    _, before = next_until_break(page)
    assert page.locator(".bumper-actions").count() == 1
    interstitial_closed(page, 16000)
    assert ch(page) == expected_next(before)
    page.context.close()


def test_hiding_the_tab_mid_commercial_is_not_a_failure(browser, base_url):
    page = open_page(browser, base_url)
    next_until_break(page)
    wait_playing(page)
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    assert page.locator(".commercial video").evaluate("v => v.paused") is True
    page.wait_for_timeout(10000)
    assert page.locator(".commercial video").count() == 1, "tab switch was treated as a stall"
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.wait_for_function("() => !document.querySelector('.commercial video').paused", timeout=3000)
    page.click(".skip-ad")
    page.context.close()
