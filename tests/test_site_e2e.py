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


# ---------- commercial playback and scheduler regressions ----------

def interstitial_closed(page, timeout):
    page.wait_for_function("() => document.getElementById('interstitial').hidden", timeout=timeout)


def skip_break(page):
    page.evaluate("document.getElementById('screen').focus()")
    page.keyboard.press("Escape")
    interstitial_closed(page, 3000)


def test_rapid_switching_into_a_break_keeps_the_latest_destination(browser, any_url):
    """A pending static switch must not overwrite the newer break target."""
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
    """Loadeddata alone must not satisfy the watchdog."""
    page = open_page(browser, base_url, init=NEVER_STARTS)
    _, before = next_until_break(page)
    page.wait_for_selector(".commercial video")
    page.wait_for_function("() => document.querySelector('.commercial video').readyState >= 2", timeout=6000)
    interstitial_closed(page, 14000)
    assert ch(page) == expected_next(page, before)
    assert "unavailable" in page.inner_text("#break-status")
    page.context.close()


def test_video_that_stalls_mid_playback_returns_to_the_program(browser, base_url):
    """Playback that freezes without a pause event must time out."""
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
    """A viewer's pause must never trip the stall watchdog."""
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
    """A break that is waiting for a tap still ends on its own, and the ad is not blacklisted."""
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
    """Nothing about commercials may stop ordinary browsing."""
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
    """A break waiting on the viewer must not wait forever."""
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


# ---------- visual refinement regressions ----------

def _fake_screenshot(route):
    # Test-only stand-in for a urlscan capture: a flat mid-grey PNG, so the glass
    # sheen has pixels to tint. The real capture is never fetched in tests.
    import struct, zlib
    w, h = 64, 40
    raw = b"".join(b"\x00" + bytes([128, 128, 128]) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    route.fulfill(status=200, content_type="image/png", body=png)


def _open_with_screenshots(browser, url, *, mobile=False, init=None):
    page = open_page(browser, url, mobile=mobile, reduce=True, init=init)
    # Playwright tries the newest route first, so this one wins for screenshots
    # while open_page's abort-everything route still guards the rest of urlscan.
    page.route("https://urlscan.io/screenshots/**", _fake_screenshot)
    page.reload()
    page.wait_for_selector(".shot-area img")
    page.wait_for_function("() => { const i = document.querySelector('.shot-area img'); return i && i.complete && i.naturalWidth > 0; }")
    return page


NO_GLASS = ".shot-area > a::after { display: none !important; }"


def add_rule(page, rule):
    # The CSP forbids inline <style>, so tests change styles through the CSSOM.
    return page.evaluate("""(rule) => { const s = [...document.styleSheets].find(x => x.href && x.href.includes('styles.css'));
        return s.insertRule(rule, s.cssRules.length); }""", rule)


def remove_rule(page, index):
    page.evaluate("""(i) => { const s = [...document.styleSheets].find(x => x.href && x.href.includes('styles.css')); s.deleteRule(i); }""", index)


def _shot_with_and_without_glass(page, selector, rotated=False):
    box = page.locator(selector).first.bounding_box()
    if rotated:
        # A tilted stamp's bounding box includes screenshot corners. Compare a
        # band through its middle that stays inside the tilted rectangle.
        w, h = page.locator(selector).first.evaluate("e => [e.offsetWidth, e.offsetHeight]")
        bw = w * 0.5
        bh = max(2.0, (h - 2 * (bw / 2) * 0.141) * 0.8)  # tan(8 deg) ~ 0.141
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        box = {"x": cx - bw / 2, "y": cy - bh / 2, "width": bw, "height": bh}
    with_glass = page.screenshot(clip=box, animations="disabled")
    index = add_rule(page, NO_GLASS)
    without = page.screenshot(clip=box, animations="disabled")
    remove_rule(page, index)
    return with_glass, without


@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "phone"])
def test_glass_sheen_tints_only_the_screenshot(browser, base_url, mobile):
    page = _open_with_screenshots(browser, base_url, mobile=mobile)
    # No full-screen overlay is left on the set itself.
    for sel in (".bezel", ".screen", ".program", "#interstitial"):
        for pseudo in ("::before", "::after"):
            assert page.evaluate(f"getComputedStyle(document.querySelector('{sel}'), '{pseudo}').content") in ("none", "normal"), (sel, pseudo)
    shot, plain = _shot_with_and_without_glass(page, ".shot-area img")
    assert shot != plain, "the sheen should still be visible on the screenshot"
    # The bugs and the stamp have translucent backings, so make them opaque for
    # the comparison: any difference left would mean the glass is painted on top.
    add_rule(page, ".stamp, .ch-bug, .station-bug { background: #000 !important; border-color: #000 !important; border-radius: 0 !important; }")
    for sel in (".chyron", ".stamp", ".ch-bug", ".station-bug"):
        if not page.locator(sel).count():
            continue
        tinted, untinted = _shot_with_and_without_glass(page, sel, rotated=sel == ".stamp")
        assert tinted == untinted, f"glass sheen covers {sel}"
    page.context.close()


def test_glass_sheen_stays_off_the_static_card_and_commercials(browser, base_url):
    page = _open_with_screenshots(browser, base_url,
                                  init="try { localStorage.setItem('offbrand.breaks.enabled', 'on'); } catch (e) {}")
    page.locator(".watch-btn").first.click()  # CH 00: plays a commercial on demand
    page.wait_for_selector("#interstitial:not([hidden]) video")
    # Hold one frame still so the comparison sees only the overlay, not playback.
    page.evaluate("""() => new Promise(done => { const v = document.querySelector('#interstitial video');
        const hold = () => { v.pause(); v.currentTime = 0.5; v.addEventListener('seeked', () => done(), { once: true }); };
        if (v.readyState >= 1) hold(); else v.addEventListener('loadedmetadata', hold, { once: true }); })""")
    page.wait_for_timeout(300)
    # The paused picture is the part that must stay untouched; the countdown and
    # progress bar around it keep moving on their own.
    tinted, untinted = _shot_with_and_without_glass(page, "#interstitial .ad-stage")
    assert tinted == untinted, "glass sheen covers the commercial"
    # Nothing outside the commercial (no overlay on the screen, the bezel or the
    # program underneath) may paint over it either.
    stage = page.locator("#interstitial .ad-stage").bounding_box()
    as_shown = page.screenshot(clip=stage, animations="disabled")
    index = add_rule(page, ".bezel::before, .bezel::after, .screen::before, .screen::after,"
                           " .program *::before, .program *::after { display: none !important; }")
    bare = page.screenshot(clip=stage, animations="disabled")
    remove_rule(page, index)
    assert as_shown == bare, "an overlay outside the commercial paints over it"
    # Sanity check: the comparison does catch a full-screen overlay like the
    # original .screen::after sheen.
    index = add_rule(page, ".screen::after { content: ''; position: absolute; inset: 0; z-index: 4; pointer-events: none;"
                           " background: radial-gradient(ellipse at center, transparent 62%, rgba(0, 0, 0, 0.34) 100%); }")
    covered, _ = _shot_with_and_without_glass(page, "#interstitial .ad-stage")
    remove_rule(page, index)
    assert covered != untinted
    page.context.close()


def test_station_id_follows_the_channel_count(browser, base_url, grown_url):
    for url in (base_url, grown_url):
        page = open_page(browser, url, wait_originals=False)
        n = channels(page)
        text = page.inner_text("#station-id")
        assert text == f"CH 01–{n:02d} · AFTER DARK BROADCAST", text
        page.context.close()
    source = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"CH 01[–-]\d", source), "the channel range must not be hardcoded"


def test_search_field_and_clear_button_are_separate_accessible_controls(browser, base_url):
    page = open_page(browser, base_url, wait_originals=False)
    box = page.get_by_role("searchbox", name="Search reviews")
    assert box.count() == 1
    # The label names only the input; the clear button is not inside it.
    assert page.evaluate("document.querySelector('label[for=search-input]') !== null")
    assert page.evaluate("!document.getElementById('search-clear').closest('label')")
    assert page.locator("#search-clear").is_hidden()
    total = channels(page)
    box.fill("usps")
    clear = page.get_by_role("button", name="Clear search")
    clear.wait_for(state="visible")
    shown = page.locator("#lineup li").count()
    assert 0 < shown < total
    assert page.inner_text("#lineup-count") == f"{shown} of {total}"
    box.focus()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "search-clear"
    page.keyboard.press("Enter")
    assert box.input_value() == ""
    assert page.evaluate("document.activeElement.id") == "search-input"
    assert page.locator("#search-clear").is_hidden()
    assert page.locator("#lineup li").count() == total
    assert page.inner_text("#lineup-count") == f"{total} channels"
    page.context.close()


UNCLIP = ("html, body { overflow: visible !important; }",)


@pytest.mark.parametrize("width", [320, 360, 390, 768, 1024, 1440])
def test_layout_fits_without_the_global_overflow_clip(browser, base_url, width):
    """body { overflow-x: clip } must be a safety net, not the thing hiding a too-wide layout."""
    ctx = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce",
                              is_mobile=width < 700, has_touch=width < 700)
    page = ctx.new_page()
    page.route("https://urlscan.io/**", lambda route: route.abort())
    page.add_init_script("try { localStorage.setItem('offbrand.breaks.enabled', 'off'); } catch (e) {}")
    page.goto(base_url)
    page.wait_for_selector("#lineup li")
    for rule in UNCLIP:
        add_rule(page, rule)
    assert page.evaluate("getComputedStyle(document.body).overflowX") == "visible"
    items = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8"))["items"]
    wide = []
    for n, item in enumerate(items, 1):
        page.evaluate(f"location.hash = {json.dumps('#' + item['id'])}")
        wait_until(page, f"document.getElementById('now').textContent.includes('CH {n:02d}')", timeout=3000)
        for summary in page.locator("details.evidence:not([open]) summary").all():
            summary.click()
        w = page.evaluate("document.documentElement.scrollWidth")
        if w > width:
            culprit = page.evaluate(f"""() => [...document.querySelectorAll('body *')].filter(e => {{
                    if (e.getBoundingClientRect().right <= {width} + 0.5) return false;
                    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {{
                        const o = getComputedStyle(a).overflowX;
                        if (o !== 'visible') return false;  // clipped by its own container: not a page overflow
                    }}
                    return true;
                }}).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right)).slice(0, 4)""")
            wide.append(f"CH {n:02d}: {w}px {culprit}")
    assert not wide, wide
    ctx.close()


def test_signal_led_follows_tuning_and_breaks(browser, base_url):
    page = open_page(browser, base_url,
                     init="try { localStorage.setItem('offbrand.breaks.enabled', 'on'); } catch (e) {}")
    led = "document.querySelector('.bezel').className"
    assert page.evaluate(led) == "bezel"
    page.click("#next")
    assert "is-tuning" in page.evaluate(led)
    interstitial_closed(page, 3000)
    assert page.evaluate(led) == "bezel"
    page.locator(".watch-btn").first.click()
    page.wait_for_selector("#interstitial:not([hidden]) .commercial")
    assert "is-break" in page.evaluate(led)
    skip_break(page)
    assert page.evaluate(led) == "bezel"
    page.context.close()


def test_channel_on_air_stays_visible_in_the_scrolling_lineup(browser, grown_url):
    page = open_page(browser, grown_url, reduce=True, wait_originals=False,
                     init="try { localStorage.setItem('offbrand.breaks.enabled', 'off'); } catch (e) {}")
    assert page.evaluate("(() => { const l = document.getElementById('lineup'); return l.scrollHeight > l.clientHeight; })()"), \
        "expected the lineup to scroll on a wide screen"
    page_scroll = page.evaluate("window.scrollY")
    inside = """(() => { const l = document.getElementById('lineup'), c = l.querySelector('button[aria-current="true"]');
        const a = l.getBoundingClientRect(), b = c.getBoundingClientRect(); return b.top >= a.top - 1 && b.bottom <= a.bottom + 1; })()"""
    page.evaluate("document.getElementById('screen').focus({ preventScroll: true })")
    page.keyboard.press("ArrowLeft")  # wraps to the last channel, far below the fold of the list
    wait_until(page, f"document.getElementById('now').textContent.includes('CH {channels(page)}')", timeout=3000)
    assert page.evaluate(inside)
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    wait_until(page, "document.getElementById('now').textContent.includes('CH 03 ')", timeout=3000)
    assert page.evaluate(inside)
    assert page.evaluate("window.scrollY") == page_scroll, "keeping the lineup in view must not scroll the page"
    page.context.close()


# ---------- final visual details ----------
@pytest.mark.parametrize("width", [320, 390, 1440])
def test_commercial_return_label_fits_without_shrinking_transport(browser, base_url, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce",
                              is_mobile=width < 700, has_touch=width < 700)
    page = ctx.new_page()
    page.route("https://urlscan.io/**", lambda route: route.abort())
    page.goto(base_url)
    page.wait_for_selector(".watch-btn")
    page.locator(".watch-btn").first.click()
    button = page.locator(".ad-controls .skip-ad")
    button.wait_for(state="visible")
    page.evaluate("document.fonts.ready")
    assert button.inner_text().startswith("Back to CH")
    result = page.locator(".ad-controls").evaluate("""bar => {
        const back = bar.querySelector('.skip-ad'), range = document.createRange();
        range.selectNodeContents(back);
        const text = [...range.getClientRects()];
        const b = back.getBoundingClientRect(), a = bar.getBoundingClientRect();
        return {
            singleLine: text.length === 1,
            textFits: text.every(r => r.left >= b.left - 1 && r.right <= b.right + 1),
            buttonsFit: [...bar.querySelectorAll('button')].every(e => {
                const r = e.getBoundingClientRect();
                return r.width >= 44 && r.height >= 44 && r.left >= a.left - 1 && r.right <= a.right + 1;
            }),
            noOverflow: bar.scrollWidth <= bar.clientWidth + 1,
        };
    }""")
    assert all(result.values()), (width, result)
    button.click()
    assert page.locator("#interstitial").is_hidden()
    ctx.close()


@pytest.mark.parametrize("width", [320, 390])
def test_mobile_masthead_is_compact_and_stamp_is_contained(browser, base_url, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce",
                              is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.route("https://urlscan.io/**", lambda route: route.abort())
    page.goto(base_url)
    page.wait_for_selector("#lineup li")
    page.evaluate("document.fonts.ready")
    assert page.locator("#station-id").is_visible()
    assert page.locator("#stats-bar").is_visible()
    before = page.locator(".bezel").bounding_box()["y"]
    # Compare with the previous masthead spacing, without hiding any metadata.
    rules = [add_rule(page, rule) for rule in (
        ".masthead { padding-top:16px; gap:8px; }",
        ".masthead-top { gap:6px 16px; padding-bottom:8px; font-size:19px; line-height:1.15; }",
        ".masthead-meta { gap:6px 14px; }",
        ".on-air-pill { padding:2px 8px; }",
        ".masthead-sub { margin-top:4px; gap:10px 24px; }",
        ".stats { padding:4px 10px; font-size:20px; line-height:1.2; }",
        ".crawl-bar { margin-top:16px; }",
        ".tv-layout { padding-top:24px; }",
    )]
    previous = page.locator(".bezel").bounding_box()["y"]
    for i in reversed(rules):
        remove_rule(page, i)
    assert previous - before >= 12, (width, previous, before)

    # Select the widest verdict in the real archive, including uncertainty labels.
    items = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8"))["items"]
    item = max(items, key=lambda x: len(f"{x.get('verdict', '')} · {x.get('rating', '')}"))
    page.evaluate(f"location.hash = {json.dumps('#' + item['id'])}")
    stamp = page.locator(".stamp")
    wait_until(page, f"document.querySelector('.stamp').textContent === {json.dumps(item['verdict'] + ' · ' + item['rating'])}")
    bounds = stamp.evaluate("""e => {
        const a = e.getBoundingClientRect(), b = document.querySelector('.shot-area').getBoundingClientRect();
        return {inside: a.left >= b.left - 1 && a.right <= b.right + 1,
                size: parseFloat(getComputedStyle(e).fontSize), fit: e.scrollWidth <= e.clientWidth + 1};
    }""")
    assert bounds["inside"] and bounds["fit"] and bounds["size"] >= 12, (width, bounds)
    ctx.close()


def test_crawl_and_surf_text_contrast(browser, base_url):
    page = open_page(browser, base_url)
    for selector in (".crawl-label", ".surf-btn"):
        target = page.locator(selector)
        for hover in (False, True):
            if hover:
                target.hover()
                page.wait_for_timeout(200)
            colors = target.evaluate("""e => {
              const c = getComputedStyle(e);
              return [c.color, c.backgroundColor];
            }""")
            def luminance(color):
                rgb = [int(v) / 255 for v in re.findall(r"\d+", color)[:3]]
                return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                           for w, v in zip((.2126, .7152, .0722), rgb))
            lo, hi = sorted(map(luminance, colors))
            assert (hi + .05) / (lo + .05) >= 4.5, (selector, colors)
    page.context.close()


@pytest.mark.parametrize("width", [320, 390, 1440])
def test_station_standards_navigation(browser, base_url, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.route("https://urlscan.io/**", lambda route: route.abort())
    page.goto(base_url)
    page.get_by_role("link", name="Station standards & corrections").click()
    page.wait_for_url("**/methodology.html")
    assert page.get_by_role("heading", name="Station standards", exact=True).is_visible()
    assert page.locator(".standards-levels dt").count() == 6
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("script").count() == 0
    page.get_by_role("navigation", name="On this page").get_by_role("link", name="04 · Corrections").click()
    assert page.url.endswith("#corrections")
    assert page.get_by_role("heading", name="Public correction log").is_visible()
    page.get_by_role("link", name="Return to the broadcast").click()
    page.wait_for_url("**/index.html")
    ctx.close()


@pytest.mark.parametrize("width", [320, 390, 768, 1024, 1440])
def test_craftsmanship_controls_and_loupe(browser, base_url, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("https://urlscan.io/**", lambda route: route.abort())
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.add_init_script("try { localStorage.setItem('offbrand.breaks.enabled', 'off'); } catch (e) {}")
    page.goto(base_url)
    page.wait_for_selector("#address .ob-loupe")
    assert page.locator(".ob-loupe").count() == 1
    page.locator(".shot-missing").wait_for(state="visible")
    original = page.locator(".address-text").inner_text()
    locker = page.locator(".locker").inner_text()
    page.locator(".ob-loupe summary").click()
    assert page.locator(".ob-loupe a").count() == 0
    assert "does not determine the registrable domain" in page.locator(".ob-loupe").inner_text()
    assert page.locator(".address-text").inner_text() == original
    assert page.locator(".locker").inner_text() == locker
    scan = page.get_by_role("button", name="Scanlines: off")
    scan.click()
    assert scan.get_attribute("aria-pressed") == "true"
    page.get_by_role("button", name="Degauss", exact=True).click()
    assert page.locator(".ob-control-strip").evaluate("e => !e.classList.contains('ob-servicing')")
    page.get_by_role("button", name="Station ID", exact=True).click()
    assert page.locator(".ob-test-card").is_visible()
    assert page.locator("#interstitial").is_hidden()
    remote = page.get_by_role("button", name="Remote guide")
    remote.click()
    dialog = page.get_by_role("dialog", name="Remote guide")
    assert dialog.is_visible()
    assert dialog.evaluate("e => e.matches(':modal') && e.contains(document.activeElement)")
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    wait_until(page, "document.activeElement.textContent === 'Remote guide'")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.click("#next")
    wait_until(page, "document.querySelector('.address-text').textContent !== " + json.dumps(original))
    page.wait_for_selector(".ob-loupe")
    assert page.locator(".ob-loupe").count() == 1
    assert not page.locator(".ob-loupe").evaluate("e => e.open")
    assert page.locator(".ob-loupe").evaluate("e => e.dataset.source === document.querySelector('.address-text').textContent")
    assert not problems
    page.reload()
    page.wait_for_selector(".ob-loupe")
    assert page.get_by_role("button", name="Scanlines: on").get_attribute("aria-pressed") == "true"
    ctx.close()
