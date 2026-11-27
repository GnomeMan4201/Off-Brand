"""End-to-end checks for After Dark and its commercial breaks.

Skipped unless Playwright and a Chrome with H.264 support are available.
Point OFFBRAND_CHROME at a Chrome binary to choose one; otherwise
/usr/bin/google-chrome is used if it exists.
"""
import functools
import http.server
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
CHROME = os.environ.get("OFFBRAND_CHROME") or "/usr/bin/google-chrome"
if not Path(CHROME).exists():
    pytest.skip("no Chrome binary for end-to-end tests", allow_module_level=True)


# Nothing here assumes how many specimens are on the shelf: the publishing
# pipeline keeps adding them. The channel count is read from the review data
# the fixture actually stages, and the click budgets come from breaks.js.
STAGED = {}  # origin -> number of specimens in that staged site's reviews.json


def channels(page):
    origin = re.match(r"https?://[^/]+", page.url).group(0)
    return STAGED[origin]


_BREAKS_SRC = (ROOT / "site" / "breaks.js").read_text(encoding="utf-8")
MAX_CHANGES = int(re.search(r"const MAX_CHANGES = (\d+);", _BREAKS_SRC).group(1))
PAST_THRESHOLD = MAX_CHANGES + 1  # enough channel changes that a due break must have fired


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _stage(tmp_path_factory, grow_to=None):
    # Stage the site exactly the way .github/workflows/deploy.yml does.
    out = tmp_path_factory.mktemp("_site")
    shutil.copytree(ROOT / "site", out, dirs_exist_ok=True)
    (out / "data").mkdir()
    shutil.copy(ROOT / "data" / "reviews.json", out / "data" / "reviews.json")
    index = out / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("__BUILD__", "e2e"), encoding="utf-8")
    reviews_path = out / "data" / "reviews.json"
    if grow_to:
        # Test-only copy of a larger archive: the real specimens repeated with
        # unique ids. It lives in the temp dir and is never published.
        data = json.loads(reviews_path.read_text(encoding="utf-8"))
        real = data["items"]
        data["items"] = [dict(real[k % len(real)], id=f"{real[k % len(real)]['id']}-copy{k}") if k >= len(real) else real[k]
                         for k in range(grow_to)]
        reviews_path.write_text(json.dumps(data), encoding="utf-8")
    count = len(json.loads(reviews_path.read_text(encoding="utf-8")).get("items") or [])
    if count < 2:
        pytest.skip("channel switching needs at least two published specimens")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    STAGED[origin] = count
    return server, origin + "/index.html"


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    server, url = _stage(tmp_path_factory)
    yield url
    server.shutdown()


@pytest.fixture(scope="module")
def grown_url(tmp_path_factory):
    server, url = _stage(tmp_path_factory, grow_to=103)  # three-digit channel numbers
    yield url
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--autoplay-policy=user-gesture-required"])
        yield b
        b.close()


@pytest.fixture(params=["published archive", "grown archive"])
def any_url(request):
    """The real staged data, and a 103-specimen copy, for count-sensitive tests."""
    return request.getfixturevalue("base_url" if request.param == "published archive" else "grown_url")


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



def wait_until(page, js, timeout=5000, interval=50):
    """Poll a page expression from Python.

    page.wait_for_function() with an expression string makes Playwright compile
    that string inside the page while polling, which the site's CSP
    (script-src 'self', no 'unsafe-eval') correctly refuses with an EvalError.
    page.evaluate() runs over the DevTools protocol instead, so the CSP stays
    exactly as strict as production and the test still waits for the condition.
    """
    deadline = time.monotonic() + timeout / 1000
    while True:
        if page.evaluate(js):
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout} ms waiting for: {js}")
        page.wait_for_timeout(interval)

def ch(page):
    return int(re.search(r"CH (\d+)", page.inner_text("#now")).group(1))


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


def next_until_break(page, limit=PAST_THRESHOLD):
    for n in range(1, limit + 1):
        before = ch(page)
        page.click("#next")
        if settle(page):
            return n, before
    raise AssertionError(f"no commercial break within {limit} channel changes")


def wait_playing(page):
    page.wait_for_selector(".commercial video", timeout=6000)
    page.wait_for_function("() => { const v = document.querySelector('.commercial video'); return v && v.currentTime > 0.2; }", timeout=8000)


def expected_next(page, before):
    return before % channels(page) + 1


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
        assert ch(page) == expected_next(page, before)
    assert len(set(titles)) == 4, titles  # no repeats until the rotation is used up
    assert not page.problems, page.problems
    page.context.close()


def test_failed_video_falls_back_and_browsing_continues(browser, base_url):
    page = open_page(browser, base_url, block_video=True)
    _, before = next_until_break(page)
    page.wait_for_function("() => document.getElementById('interstitial').hidden", timeout=10000)
    assert ch(page) == expected_next(page, before)
    assert "unavailable" in page.inner_text("#break-status")
    for _ in range(3):  # ordinary browsing is unaffected
        b = ch(page)
        page.click("#next")
        settle(page)
        page.wait_for_function("() => document.getElementById('interstitial').hidden", timeout=10000)
        assert ch(page) == expected_next(page, b)
    page.context.close()


def test_turning_breaks_off_persists_across_reloads(browser, base_url):
    page = open_page(browser, base_url)
    page.click("#breaks-toggle")
    assert page.get_attribute("#breaks-toggle", "aria-pressed") == "false"
    page.reload()
    page.wait_for_selector("#lineup li")
    assert page.get_attribute("#breaks-toggle", "aria-pressed") == "false"
    for _ in range(PAST_THRESHOLD):
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
    assert ch(page) == expected_next(page, before)
    assert page.evaluate("document.activeElement.id") == "screen"  # focus is not lost
    page.context.close()


def test_changing_channel_during_a_break_skips_it(browser, base_url):
    page = open_page(browser, base_url)
    _, before = next_until_break(page)
    page.click("#next")
    assert page.locator("#interstitial").is_hidden()
    assert ch(page) == expected_next(page, expected_next(page, before))
    page.context.close()


def test_reduced_motion_never_autoplays(browser, base_url):
    page = open_page(browser, base_url, reduce=True)
    _, before = next_until_break(page)
    assert page.locator(".bumper.noisy").count() == 0
    page.wait_for_timeout(2500)
    assert page.locator(".commercial video").count() == 0  # waits for the viewer
    page.click(".bumper-actions button:has-text('Skip to CH')")
    assert ch(page) == expected_next(page, before)
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


def test_rapid_switching_into_a_break_keeps_the_latest_destination(browser, any_url):
    """Issue 1: a pending static switch must not overwrite the newer break target."""
    page = open_page(browser, any_url)
    for _ in range(3):  # several breaks, each reached by clicking faster than the static clears
        start = ch(page)
        clicks = 0
        while not page.locator(".bumper, .commercial").count():
            assert clicks < PAST_THRESHOLD, f"no break within {PAST_THRESHOLD} rapid clicks"
            page.click("#next")
            clicks += 1
            page.wait_for_timeout(60)
        skip_break(page)
        assert ch(page) == (start - 1 + clicks) % channels(page) + 1, f"after {clicks} rapid clicks from CH {start:02d}"
    page.context.close()


def test_rapid_lineup_pick_into_a_break_lands_on_the_pick(browser, any_url):
    page = open_page(browser, any_url)
    target = None
    hop = min(3, channels(page) - 1)
    # Each round is "Next, then a quick lineup pick while Next's static is still
    # running". The scenario under test is a break triggered by the pick. When
    # the break lands on Next instead, skip it and go again.
    for _ in range(PAST_THRESHOLD * 4):
        page.click("#next")
        page.wait_for_timeout(60)
        if page.locator(".bumper, .commercial").count():
            skip_break(page)
            continue
        pick = (ch(page) - 1 + hop) % channels(page)  # 0-based index of a channel a few steps away
        page.locator("#lineup button").nth(pick).click()
        target = pick + 1
        page.wait_for_timeout(60)
        if page.locator(".bumper, .commercial").count():
            break
        settle(page)
        interstitial_closed(page, 6000)
    else:
        raise AssertionError("a break never landed on a lineup pick")
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
    assert ch(page) == expected_next(page, before)
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
    assert ch(page) == expected_next(page, before)
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
    assert ch(page) == expected_next(page, before)
    assert page.locator(".watch-btn[disabled]").count() == 0  # not marked as broken
    page.context.close()


def _browse_past_threshold(page):
    for _ in range(PAST_THRESHOLD):
        b = ch(page)
        page.click("#next")
        assert settle(page) is False, "a break started without its pieces"
        interstitial_closed(page, 6000)
        assert ch(page) == expected_next(page, b)
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
    _browse_past_threshold(page)
    page.context.close()


def test_reduced_motion_break_ends_by_itself_if_nobody_chooses(browser, base_url):
    """Issue 2e: a break waiting on the viewer must not wait forever."""
    page = open_page(browser, base_url, reduce=True)
    _, before = next_until_break(page)
    assert page.locator(".bumper-actions").count() == 1
    interstitial_closed(page, 16000)
    assert ch(page) == expected_next(page, before)
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


def test_lineup_matches_the_staged_review_count(browser, any_url):
    page = open_page(browser, any_url)
    assert page.locator("#lineup button").count() == channels(page)
    last = channels(page)
    page.click("#prev")  # wraps from the first channel to the last, whatever the count
    settle(page)
    interstitial_closed(page, 6000)
    assert ch(page) == last
    page.context.close()


# ---------- clear chyron and optional channel audio ----------
@pytest.mark.parametrize("mobile", [False, True])
def test_crt_texture_is_scoped_to_the_picture(browser, base_url, mobile):
    page = open_page(browser, base_url, mobile=mobile, reduce=True)
    assert page.locator("#screen > .scanlines").count() == 0
    assert page.locator(".shot-area").evaluate(
        "e => getComputedStyle(e, '::after').backgroundImage.includes('repeating-linear-gradient')"
    )
    assert page.locator(".chyron").evaluate("e => getComputedStyle(e).zIndex") == "1"
    assert page.locator(".chyron-tag").is_visible()
    assert page.locator(".chyron p").is_visible()
    page.context.close()


# Spy on real Web Audio source starts; the tests do not require speakers.
AUDIO_SPY = """
window.tuningStarts = 0;
window.tuningDurations = [];
window.tuningEvents = [];
window.tuningActive = 0;
window.tuningMaxActive = 0;
const Audio = window.AudioContext || window.webkitAudioContext;
const original = Audio.prototype.createBufferSource;
Audio.prototype.createBufferSource = function () {
    const source = original.call(this);
    const start = source.start.bind(source), stop = source.stop.bind(source);
    let active = false;
    const ended = () => { if (active) { active = false; window.tuningActive--; } };
    source.addEventListener("ended", ended);
    source.start = (...args) => {
        const result = start(...args);
        active = true;
        window.tuningActive++;
        window.tuningMaxActive = Math.max(window.tuningMaxActive, window.tuningActive);
        window.tuningStarts++;
        window.tuningDurations.push(source.buffer.duration);
        window.tuningEvents.push({loop: source.loop, static: !!document.querySelector("#interstitial:not([hidden]) .static")});
        return result;
    };
    source.stop = (...args) => { const result = stop(...args); ended(); return result; };
    return source;
};
"""


def test_channel_sound_is_gesture_only_and_preference_persists(browser, base_url):
    page = open_page(browser, base_url, reduce=True, init=AUDIO_SPY)
    toggle = page.locator("#channel-sound")
    assert toggle.get_attribute("aria-pressed") == "true"
    assert page.evaluate("window.tuningStarts") == 0
    page.click("#next")
    wait_until(page, "window.tuningStarts === 1", timeout=5000)
    page.locator("#lineup button[aria-current='true']").click()
    assert page.evaluate("window.tuningStarts") == 1
    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "false"
    page.click("#prev")
    page.wait_for_timeout(250)
    assert page.evaluate("window.tuningStarts") == 1
    page.reload()
    page.wait_for_selector("#lineup button")
    assert toggle.get_attribute("aria-pressed") == "false"
    page.click("#next")
    page.wait_for_timeout(250)
    assert page.evaluate("window.tuningStarts") == 0
    toggle.click()
    page.focus("#screen")
    page.keyboard.press("ArrowLeft")
    wait_until(page, "window.tuningStarts === 1", timeout=5000)
    assert not page.problems, page.problems
    page.context.close()


def test_recorded_cues_differ_for_channel_and_commercial(browser, base_url):
    page = open_page(browser, base_url, reduce=True, init=AUDIO_SPY)
    for _ in range(PAST_THRESHOLD):
        page.click("#next")
        if page.locator(".bumper").count():
            wait_until(page, "window.tuningDurations.at(-1) > 0.8", timeout=5000)
            break
        wait_until(page, "window.tuningDurations.length > 0 && window.tuningDurations.at(-1) < 0.7", timeout=5000)
        page.wait_for_timeout(550)
    else:
        raise AssertionError("commercial break did not occur")
    durations = page.evaluate("window.tuningDurations")
    assert any(0.57 < d < 0.59 for d in durations)
    assert 0.8 < durations[-1] < 1.1
    page.locator("#channel-sound").click()
    skip_break(page)
    page.context.close()


def test_missing_recorded_sound_does_not_block_tuning(browser, base_url):
    page = open_page(browser, base_url, reduce=True, routes={
        "**/sounds/*": lambda r: r.fulfill(status=404, body="missing")
    })
    before = ch(page)
    page.click("#next")
    assert ch(page) == expected_next(page, before)
    assert not [p for p in page.problems if p.startswith("pageerror")], page.problems
    page.context.close()


def test_no_specimen_widens_the_page_on_a_phone(browser, base_url):
    """Every published review must fit a 390 px screen, however long its defanged addresses."""
    items = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8"))["items"]
    page = open_page(browser, base_url, mobile=True, reduce=True,
                     init="try { localStorage.setItem('offbrand.breaks.enabled', 'off'); } catch (e) {}")
    wide = []
    for n, item in enumerate(items, 1):
        page.evaluate(f"location.hash = {json.dumps('#' + item['id'])}")
        wait_until(page, f"document.getElementById('now').textContent.includes('CH {n:02d}')", timeout=3000)
        width = page.evaluate("document.documentElement.scrollWidth")
        if width > 390:
            wide.append(f"CH {n:02d} {item['knockoff_label']}: {width}px")
    assert not wide, wide
    page.context.close()


@pytest.mark.parametrize("width", [320, 360, 390])
def test_page_chrome_fits_small_phones(browser, base_url, width):
    """Masthead, deck and guide must fit narrow phones (the logo cannot wrap)."""
    ctx = browser.new_context(viewport={"width": width, "height": 800}, reduced_motion="reduce", is_mobile=True)
    page = ctx.new_page()
    page.route("https://urlscan.io/**", lambda route: route.abort())
    page.goto(base_url)
    page.wait_for_selector("#lineup li")
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    ctx.close()


def test_broadcast_snow_stops_when_static_card_clears(browser, base_url):
    page = open_page(browser, base_url, init=AUDIO_SPY)
    page.click("#next")
    wait_until(page, "window.tuningStarts === 1")
    assert page.evaluate("window.tuningEvents[0]") == {"loop": True, "static": True}
    interstitial_closed(page, 3000)
    assert page.evaluate("window.tuningActive") == 0
    assert page.evaluate("window.tuningStarts") == 1
    page.context.close()


def test_rapid_tuning_never_overlaps_snow(browser, base_url):
    page = open_page(browser, base_url, init=AUDIO_SPY)
    page.click("#next")
    wait_until(page, "window.tuningStarts === 1")
    page.click("#next")
    wait_until(page, "window.tuningStarts === 2")
    assert page.evaluate("window.tuningMaxActive") == 1
    page.click("#channel-sound")
    assert page.evaluate("window.tuningActive") == 0
    interstitial_closed(page, 3000)
    assert page.evaluate("window.tuningStarts") == 2
    page.context.close()
