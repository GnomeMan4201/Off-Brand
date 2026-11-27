/* OFF-BRAND After Dark: commercial-break logic.
 *
 * Pure functions only: no DOM. app.js owns the player UI. Loaded as a classic
 * script in the browser (window.OffBrandBreaks) and as a CommonJS module by
 * the Node tests in tests/js/.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.OffBrandBreaks = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Every media path must be a plain file inside commercials/: no schemes,
  // no "..", no query strings. Anything else is dropped from the manifest.
  const NAME = "[a-z0-9][a-z0-9-]{0,63}";
  const SRC_RE = new RegExp("^commercials/" + NAME + "\\.mp4$");
  const POSTER_RE = new RegExp("^commercials/" + NAME + "\\.(?:jpg|png|webp)$");
  const VTT_RE = new RegExp("^commercials/" + NAME + "\\.vtt$");
  const ID_RE = new RegExp("^" + NAME + "$");

  const PREF_KEY = "offbrand.breaks.enabled";
  const SEEN_KEY = "offbrand.breaks.seen";
  const MIN_CHANGES = 4;
  const MAX_CHANGES = 7;

  const str = (v, max) => (typeof v === "string" ? v.trim().slice(0, max) : "");

  function validateManifest(raw) {
    const out = { commercials: [], bumpers: [] };
    if (!raw || typeof raw !== "object") return out;
    const ids = new Set();
    for (const c of Array.isArray(raw.commercials) ? raw.commercials : []) {
      if (!c || typeof c !== "object") continue;
      const id = str(c.id, 64);
      const title = str(c.title, 120);
      const src = str(c.src, 200);
      const runtime = Number(c.runtime_seconds);
      if (!ID_RE.test(id) || ids.has(id) || !title || !SRC_RE.test(src)) continue;
      if (!Number.isFinite(runtime) || runtime <= 0 || runtime > 600) continue;
      if (c.enabled === false) continue;
      ids.add(id);
      const poster = str(c.poster, 200);
      const vtt = str(c.captions_vtt, 200);
      out.commercials.push({
        id,
        title,
        src,
        runtime_seconds: Math.round(runtime),
        poster: POSTER_RE.test(poster) ? poster : "",
        description: str(c.description, 400),
        captions: str(c.captions, 40),
        captions_vtt: VTT_RE.test(vtt) ? vtt : "",
      });
    }
    for (const b of Array.isArray(raw.bumpers) ? raw.bumpers : []) {
      const text = str(b, 160);
      if (text) out.bumpers.push(text);
    }
    return out;
  }

  // localStorage can be missing, full, or throw (private modes, sandboxes).
  // Everything degrades to in-memory state.
  function safeStore(backing) {
    const mem = new Map();
    return {
      get(key) {
        try { if (backing) { const v = backing.getItem(key); if (v !== null) return v; } } catch (e) { /* fall through */ }
        return mem.has(key) ? mem.get(key) : null;
      },
      set(key, value) {
        mem.set(key, String(value));
        try { if (backing) backing.setItem(key, String(value)); } catch (e) { /* memory copy stands */ }
      },
    };
  }

  function loadEnabled(store) { return store.get(PREF_KEY) !== "off"; }
  function saveEnabled(store, on) { store.set(PREF_KEY, on ? "on" : "off"); }

  // Shuffle-bag rotation: nothing repeats until every playable commercial has
  // aired once, and a new cycle never opens with the one that just played.
  function createRotation(ids, store, rand) {
    rand = rand || Math.random;
    const all = ids.slice();
    const failed = new Set();
    let last = null;
    let seen = [];
    try {
      const saved = JSON.parse(store.get(SEEN_KEY) || "[]");
      if (Array.isArray(saved)) seen = saved.filter((id) => all.includes(id));
    } catch (e) { seen = []; }
    const persist = () => store.set(SEEN_KEY, JSON.stringify(seen));
    const playable = () => all.filter((id) => !failed.has(id));

    return {
      available() { return playable().length > 0; },
      next() {
        const pool = playable();
        if (!pool.length) return null;
        let fresh = pool.filter((id) => !seen.includes(id));
        if (!fresh.length) {
          seen = [];
          fresh = pool.length > 1 ? pool.filter((id) => id !== last) : pool;
        }
        const pick = fresh[Math.floor(rand() * fresh.length)];
        seen.push(pick);
        last = pick;
        persist();
        return pick;
      },
      markFailed(id) { failed.add(id); },
      seen() { return seen.slice(); },
    };
  }

  // A break comes due after a random 4–7 channel changes.
  function createScheduler(rand, min, max) {
    rand = rand || Math.random;
    min = min || MIN_CHANGES;
    max = max || MAX_CHANGES;
    const draw = () => min + Math.floor(rand() * (max - min + 1));
    let count = 0;
    let threshold = draw();
    return {
      tick() { count += 1; return count >= threshold; },
      reset() { count = 0; threshold = draw(); },
      state() { return { count, threshold }; },
    };
  }

  function createBumperDeck(list, rand) {
    rand = rand || Math.random;
    let last = -1;
    return {
      next() {
        if (!list.length) return "";
        if (list.length === 1) return list[0];
        // Choose among the others directly: no retry loop, so even a stuck
        // random source can never hang the page.
        const others = list.map((_, k) => k).filter((k) => k !== last);
        const i = others[Math.min(others.length - 1, Math.floor(rand() * others.length))];
        last = i;
        return list[i];
      },
    };
  }

  function formatRuntime(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  // Listings air back to back from 2:00 AM, using each commercial's runtime.
  function airTimes(commercials, startMinutes) {
    let t = (startMinutes === undefined ? 120 : startMinutes) * 60;
    return commercials.map((c) => {
      const h24 = Math.floor(t / 3600) % 24;
      const m = Math.floor((t % 3600) / 60);
      const s = t % 60;
      const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
      const label = h12 + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0") + (h24 < 12 ? " AM" : " PM");
      t += c.runtime_seconds;
      return label;
    });
  }

  return {
    validateManifest, safeStore, loadEnabled, saveEnabled, createRotation,
    createScheduler, createBumperDeck, formatRuntime, airTimes,
    PREF_KEY, SEEN_KEY, MIN_CHANGES, MAX_CHANGES,
  };
});
