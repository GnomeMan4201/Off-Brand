"use strict";

// OFF-BRAND // After Dark
// Every value from reviews.json is untrusted scan or editorial text: it is only ever
// set with textContent, never parsed as HTML.

const ALLOWED_RECORD_PREFIXES = [
  "https://urlscan.io/result/",
  "https://openphish.com/",
  "https://phishtank.net/",
  "https://www.phishtank.net/",
];

function isSafeRecordUrl(url) {
  if (typeof url !== "string") return false;
  return ALLOWED_RECORD_PREFIXES.some((prefix) => url.startsWith(prefix));
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function displayOrMissing(val) {
  return val ? String(val) : "Not recorded in public scan";
}

function externalLink(href, className, text) {
  const a = el("a", className, text);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

// urlscan stores a screenshot for every public scan at a fixed address.
// Only a well-formed scan UUID is ever put into that address.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function scanUuid(item) {
  const fromId = typeof item.id === "string" && item.id.startsWith("urlscan-") ? item.id.slice(8) : null;
  if (fromId && UUID_RE.test(fromId)) return fromId;
  const m = typeof item.public_record_url === "string" &&
    item.public_record_url.match(/^https:\/\/urlscan\.io\/result\/([0-9a-f-]{36})\//);
  return m && UUID_RE.test(m[1]) ? m[1] : null;
}

const reducedMotion = (() => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)"); } catch (e) { return { matches: false }; }
})();

const pad2 = (n) => String(n).padStart(2, "0");
const isRated = (item) => Boolean(item.rating && item.rating !== "Unrated");

// ---------- channel audio ----------

// Short, locally hosted sound effects. Fetching is silent; AudioContext
// creation and resume occur only as a result of a viewer's gesture.
function channelAudio(button) {
  const Audio = window.AudioContext || window.webkitAudioContext;
  const key = "offbrand.channelSound";
  let enabled = true, ctx = null, active = null, generation = 0;
  const bytes = new Map(), decoded = new Map();
  const paths = { channel: "sounds/broadcast-snow.wav", commercial: "sounds/vhs-rewind.mp3" };
  try { enabled = localStorage.getItem(key) !== "off"; } catch (e) { /* optional storage */ }
  function render() {
    button.setAttribute("aria-pressed", String(enabled));
    button.querySelector("span").textContent = enabled ? "On" : "Off";
  }
  function stop() {
    generation++;
    if (active) { try { active.stop(); } catch (e) { /* already ended */ } active = null; }
  }
  function load(kind) {
    if (!bytes.has(kind)) {
      const pending = fetch(paths[kind]).then(r => {
        if (!r.ok) throw new Error("sound unavailable");
        return r.arrayBuffer();
      }).catch(() => { bytes.delete(kind); return null; });
      bytes.set(kind, pending);
    }
    return bytes.get(kind);
  }
  function preload() { for (const kind of Object.keys(paths)) load(kind); }
  if (Audio) {
    render();
    button.hidden = false;
    if (enabled) preload();
    button.addEventListener("click", () => {
      enabled = !enabled;
      stop();
      if (enabled) preload();
      try { localStorage.setItem(key, enabled ? "on" : "off"); } catch (e) { /* optional storage */ }
      render();
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  }
  function play(kind = "channel", loop = false) {
    if (!Audio || !enabled || document.hidden) return;
    stop();
    const request = generation, requestedAt = performance.now();
    try {
      if (!ctx || ctx.state === "closed") { ctx = new Audio(); decoded.clear(); }
      const audio = ctx;
      const ready = audio.state === "running" ? Promise.resolve() : audio.resume();
      if (!decoded.has(kind)) {
        const pending = load(kind).then(b => b ? new Promise((resolve, reject) => {
          audio.decodeAudioData(b.slice(0), resolve, reject);
        }) : null).catch(() => null);
        decoded.set(kind, pending);
        pending.then(b => { if (!b && decoded.get(kind) === pending) decoded.delete(kind); });
      }
      Promise.all([ready, decoded.get(kind)]).then(([, buffer]) => {
        if (!buffer || !enabled || request !== generation || document.hidden ||
            audio.state !== "running" || performance.now() - requestedAt > (loop ? 600 : 1000)) return;
        const source = audio.createBufferSource();
        source.buffer = buffer;
        source.loop = loop;
        source.connect(audio.destination);
        active = source;
        source.onended = () => { if (active === source) active = null; source.disconnect(); };
        source.start();
      }).catch(() => { /* sound must never block tuning */ });
    } catch (e) { /* unsupported or blocked audio */ }
  }
  return { play, stop };
}

// ---------- screen ----------

function renderShot(item, ch) {
  const area = el("div", "shot-area");
  const missing = () => {
    // Nothing fake: a missing screenshot is shown as missing, never replaced.
    const box = el("div", "shot-missing");
    box.appendChild(el("span", null, "Screenshot unavailable · see scan notes below"));
    box.appendChild(el("strong", null, item.knockoff_label));
    area.replaceChildren(box, el("span", "ch-bug", "CH " + ch));
  };
  const uuid = scanUuid(item);
  if (!uuid) { missing(); return area; }

  const src = `https://urlscan.io/screenshots/${uuid}.png`;
  const link = externalLink(src, null);
  link.setAttribute("aria-label", `Open full screenshot of ${item.knockoff_label}`);
  const img = document.createElement("img");
  img.src = src;
  img.alt = `Screenshot of ${item.knockoff_label}, captured by urlscan.io${item.scanned_at ? " on " + String(item.scanned_at).slice(0, 10) : ""}`;
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.addEventListener("error", missing);
  link.appendChild(img);
  area.appendChild(link);
  area.appendChild(el("span", "ch-bug", "CH " + ch));
  return area;
}

function renderProgram(item, ch) {
  const frag = document.createDocumentFragment();
  frag.appendChild(renderShot(item, ch));

  const bug = el("span", "station-bug", "OFF-BRAND ");
  bug.appendChild(el("span", "rec", "●"));
  bug.setAttribute("aria-hidden", "true");
  frag.appendChild(bug);

  if (isRated(item)) frag.appendChild(el("span", "stamp", `${item.verdict} · ${item.rating}`));

  // Satire lives on the chyron, and only there.
  const chyron = el("div", "chyron");
  const tag = el("span", "chyron-tag", "THE BIT");
  tag.appendChild(el("small", null, "satire"));
  chyron.appendChild(tag);
  chyron.appendChild(el("p", null, item.critic_note));
  frag.appendChild(chyron);
  return frag;
}

function renderAddress(item) {
  const box = document.createDocumentFragment();
  box.appendChild(el("span", "address-label", "ADDRESS AS SCANNED · defanged, not clickable"));
  const p = el("p", "address-text");
  const url = String(item.defanged_url || "");
  const seg = item.sketchy_segment ? String(item.sketchy_segment) : "";
  const at = seg ? url.indexOf(seg) : -1;
  if (at >= 0) {
    p.appendChild(document.createTextNode(url.slice(0, at)));
    p.appendChild(el("mark", null, seg));
    p.appendChild(document.createTextNode(url.slice(at + seg.length)));
  } else {
    p.textContent = url || "Not recorded in public scan";
  }
  box.appendChild(p);
  if (seg) box.appendChild(el("p", "address-note", "Highlighted: the address detail flagged in the review · " + seg));
  if (item.evidence && item.evidence.level === "suspected") {
    box.appendChild(el("p", "address-caution",
      "Suspected, not confirmed phishing. The signs are here, but no source has verified this page. See the evidence locker."));
  }
  return box;
}

// ---------- EVIDENCE LOCKER ----------
// Mirrors scripts/evidence.py. Only links to the exact record pages below are ever made.

const EVIDENCE_LINK_RES = [
  /^https:\/\/urlscan\.io\/result\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/(report\/)?$/,
  /^https:\/\/www\.phishtank\.com\/phish_detail\.php\?phish_id=\d{1,12}$/,
  /^https:\/\/openphish\.com\/feed\.txt$/,
];
const EVIDENCE_LEVELS = {
  "corroborated": { label: "CORROBORATED", blurb: "Independent sources list this exact page." },
  "source-confirmed": { label: "SOURCE-CONFIRMED", blurb: "A verifying source confirmed this exact page." },
  "suspected": { label: "SUSPECTED · NOT CONFIRMED", blurb: "Indicators exist, but no source verified this page as phishing." },
  "unverified": { label: "UNVERIFIED", blurb: "No supporting record in the sources checked." },
  "disputed": { label: "DISPUTED", blurb: "The available records conflict." },
};
const SOURCE_STATUS_TEXT = {
  ok: "checked", rate_limited: "not checked (download limit)", unavailable: "not checked (unavailable)",
  malformed: "not checked (unreadable response)", too_large: "not checked (response too large)",
  not_attempted: "not checked",
};

function isEvidenceLink(url) {
  return typeof url === "string" && EVIDENCE_LINK_RES.some((re) => re.test(url));
}

function renderEvidence(item) {
  const ev = item.evidence && typeof item.evidence === "object" ? item.evidence : null;
  const level = ev && EVIDENCE_LEVELS[ev.level] ? ev.level : null;
  const box = el("section", "locker" + (level ? " locker-" + level : " locker-legacy"));
  box.setAttribute("aria-labelledby", "locker-title");
  const head = el("div", "locker-head");
  head.appendChild(el("h3", null, "EVIDENCE LOCKER")).id = "locker-title";
  const stamp = el("span", "locker-stamp", level ? EVIDENCE_LEVELS[level].label : "NOT YET RATED");
  stamp.setAttribute("aria-label", "Evidence level: " + (level ? EVIDENCE_LEVELS[level].label.toLowerCase() : "not yet rated"));
  head.appendChild(stamp);
  box.appendChild(head);

  if (!level) {
    box.appendChild(el("p", "locker-reason",
      "Aired before evidence levels existed. The scan record linked below is the evidence on file; nothing was added afterward."));
    return box;
  }
  box.appendChild(el("p", "locker-reason", ev.reason || EVIDENCE_LEVELS[level].blurb));
  if (ev.editor_ack) box.appendChild(el("p", "locker-ack", "Editor's note: " + ev.editor_ack));

  const records = Array.isArray(ev.records) ? ev.records : [];
  const sources = ev.sources && typeof ev.sources === "object" ? Object.entries(ev.sources) : [];
  const limits = Array.isArray(ev.limitations) ? ev.limitations : [];
  const more = el("details", "evidence locker-more");
  more.appendChild(el("summary", null, `On file: ${records.length} record${records.length === 1 ? "" : "s"}, ${sources.length} source${sources.length === 1 ? "" : "s"} checked`));
  const list = el("div", "evidence-list");
  for (const r of records) {
    const p = el("p", "locker-record");
    p.appendChild(el("span", "locker-tag", r.match === "exact" ? "EXACT PAGE" : "SAME HOST"));
    p.appendChild(document.createTextNode(` ${r.source || "Source"}: ${r.detail || "record"}`));
    if (r.stance === "contradicts") p.classList.add("locker-against");
    if (isEvidenceLink(r.record_url)) {
      p.appendChild(document.createTextNode(" "));
      p.appendChild(externalLink(r.record_url, "locker-link", "record ↗"));
    }
    list.appendChild(p);
  }
  for (const [name, s] of sources) {
    list.appendChild(el("p", "locker-source", `${name}: ${SOURCE_STATUS_TEXT[s && s.status] || "status unknown"}${s && s.checked_at ? " · " + String(s.checked_at).slice(0, 10) : ""}`));
  }
  if (ev.specimen && ev.specimen.redirected && ev.specimen.defanged_final_host) {
    list.appendChild(el("p", null, "The scan finished on another host: " + ev.specimen.defanged_final_host));
  }
  for (const lim of limits) list.appendChild(el("p", "locker-limit", "Limitation: " + lim));
  more.appendChild(list);
  box.appendChild(more);

  const dates = el("p", "locker-dates");
  const day = (v) => (v ? String(v).slice(0, 10) : "date not recorded");
  dates.appendChild(el("span", null, "Captured " + day(ev.captured_at)));
  dates.appendChild(document.createTextNode(" · "));
  dates.appendChild(el("span", null, "assessed " + day(ev.assessed_at)));
  box.appendChild(dates);
  return box;
}

// ---------- WHAT TO NOTICE ----------

function renderFacts(item) {
  const frag = document.createDocumentFragment();
  const tells = item.tells || [];
  frag.appendChild(el("p", "lead-tell", tells[0] || "Not recorded in public scan"));

  if (tells.length > 1) {
    const more = el("details", "evidence");
    more.appendChild(el("summary", null, `Evidence and assessment (${tells.length - 1} more)`));
    const list = el("div", "evidence-list");
    for (const tell of tells.slice(1)) list.appendChild(el("p", null, tell));
    more.appendChild(list);
    frag.appendChild(more);
  }

  frag.appendChild(renderEvidence(item));

  const meta = el("div", "fact-meta");
  const row = (label, val) => {
    const r = el("div", "fact-meta-row");
    r.appendChild(el("span", "fact-meta-label", label));
    r.appendChild(el("span", "fact-meta-val", val));
    meta.appendChild(r);
  };
  row("Verdict", `${displayOrMissing(item.verdict)} · ${displayOrMissing(item.rating)}`);
  if (item.impersonated_brand && item.impersonated_brand !== "Not established") row("Brand pictured", item.impersonated_brand);
  row("IP", displayOrMissing(item.ip));
  row("ASN", displayOrMissing(item.asn_name));
  row("Page title", displayOrMissing(item.page_title));
  row("Scanned", displayOrMissing(item.scanned_at));
  row("Source", displayOrMissing(item.source));
  frag.appendChild(meta);

  const links = el("div", "fact-links");
  const uuid = scanUuid(item);
  if (uuid) links.appendChild(externalLink("https://urlscan.io/result/" + uuid + "/", null, "Read the urlscan evidence ↗"));
  if (isSafeRecordUrl(item.public_record_url)) links.appendChild(externalLink(item.public_record_url, null, "Verify public record ↗"));
  frag.appendChild(links);
  return frag;
}

// ---------- interstitials ----------

function staticCard(ch) {
  const wrap = el("div", "static");
  const box = el("div", null, "PLEASE STAND BY");
  box.appendChild(document.createElement("br"));
  box.appendChild(el("span", null, "TUNING CH " + ch));
  wrap.appendChild(box);
  return wrap;
}

function psaCard(onSkip) {
  // Copy taken word for word from the field guide below.
  const wrap = el("div", "psa");
  const bars = el("div", "bars");
  bars.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 7; i++) bars.appendChild(el("span"));
  wrap.appendChild(bars);
  const body = el("div", "psa-body");
  body.appendChild(el("span", null, "A PUBLIC SERVICE ANNOUNCEMENT FROM THE FIELD GUIDE"));
  body.appendChild(el("strong", null, "Read the whole address"));
  const p = el("p", null, "On a phone, tap the address bar to expand it. Compare the hostname with the one in your bookmark. In the Allegro capture, the familiar name is the first thing you see. The address ends in ");
  p.appendChild(el("code", null, "aukcja758487593[.]top"));
  p.appendChild(document.createTextNode("."));
  body.appendChild(p);
  const skip = el("button", null, "Back to the program →");
  skip.type = "button";
  skip.addEventListener("click", onSkip);
  body.appendChild(skip);
  wrap.appendChild(body);
  return wrap;
}

// ---------- app ----------

// ---------- commercial breaks: markup ----------

const SVG_NS = "http://www.w3.org/2000/svg";
const ICON_PATHS = {
  play: ["M7 4l13 8-13 8z"],
  pause: ["M9 5v14", "M15 5v14"],
  sound: ["M4 9h4l5-4v14l-5-4H4z", "M17 9a4 4 0 0 1 0 6", "M19.5 6.5a8 8 0 0 1 0 11"],
  muted: ["M4 9h4l5-4v14l-5-4H4z", "M17 9l5 6", "M22 9l-5 6"],
  replay: ["M4 12a8 8 0 1 0 2.4-5.7", "M4 4v4h4"],
  fullscreen: ["M4 9V4h5", "M20 9V4h-5", "M4 15v5h5", "M20 15v5h-5"],
};

// Icons are inline SVG, never emoji or symbol glyphs: iOS draws ▶ and ⏸ as emoji.
function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of ICON_PATHS[name]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  }
  return svg;
}

function iconButton(name, label, onClick) {
  const b = el("button");
  b.type = "button";
  b.setAttribute("aria-label", label);
  b.appendChild(icon(name));
  b.addEventListener("click", onClick);
  return b;
}

function setIcon(button, name, label) {
  button.replaceChildren(icon(name));
  button.setAttribute("aria-label", label);
}

function actionRow(actions) {
  const row = el("div", "bumper-actions");
  for (const [label, fn] of actions) {
    const b = el("button", null, label);
    b.type = "button";
    b.addEventListener("click", fn);
    row.appendChild(b);
  }
  return row;
}

function bumperCard(line, { noisy, actions }) {
  const card = el("div", "bumper" + (noisy ? " noisy" : ""));
  card.appendChild(el("span", "bumper-kicker", "PLEASE STAND BY"));
  card.appendChild(el("strong", null, "COMMERCIAL BREAK"));
  if (line) card.appendChild(el("p", null, line));
  const bars = el("div", "bars");
  bars.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 7; i++) bars.appendChild(el("span"));
  card.appendChild(bars);
  if (actions) card.appendChild(actionRow(actions));
  card.appendChild(el("span", "bumper-foot", "CH 00 · OFF-BRAND ORIGINALS"));
  return card;
}

const release = new URL(document.currentScript.src).searchParams.get("v");

async function init() {
  const res = await fetch(release ? `data/reviews.json?v=${encodeURIComponent(release)}` : "data/reviews.json", { cache: "no-cache" });
  const data = await res.json();
  const items = data.items || [];
  const rejected = data.rejected_log || [];

  document.getElementById("last-updated").textContent = `Updated ${String(data.last_updated || "").slice(0, 10)}`;
  document.getElementById("stats-bar").textContent = `${items.length} specimens on air · ${rejected.length} held back at review`;
  // The station ID follows the shelf: CH 01–NN, where NN is the last channel.
  const stationId = document.getElementById("station-id");
  if (stationId) {
    const range = items.length > 1 ? `CH 01–${pad2(items.length)}` : items.length === 1 ? "CH 01" : "OFF AIR";
    stationId.textContent = `${range} · AFTER DARK BROADCAST`;
  }

  const $ = (id) => document.getElementById(id);
  const bezel = document.querySelector(".bezel");
  const screen = $("screen"), program = $("program"), inter = $("interstitial");
  const now = $("now"), address = $("address"), facts = $("fact-body");
  const lineupEl = $("lineup"), emptyEl = $("lineup-empty"), searchEl = $("search-input");
  const searchClearEl = $("search-clear"), lineupCountEl = $("lineup-count");
  const setBezelState = (state) => {
    if (!bezel) return;
    bezel.classList.toggle("is-tuning", state === "tuning");
    bezel.classList.toggle("is-break", state === "break");
  };

  // The crawl: every satirical caption, looping. Hidden from screen readers;
  // the same text is on the chyron for each channel.
  const crawlBar = document.querySelector(".crawl-bar");
  const crawl = $("crawl"), crawlBtn = $("crawl-toggle");
  for (const item of items.concat(items)) crawl.appendChild(el("span", null, `${item.knockoff_label} — “${item.critic_note}”`));
  const setCrawl = (paused) => {
    crawlBar.classList.toggle("paused", paused);
    crawlBtn.textContent = paused ? "Play" : "Pause";
    crawlBtn.setAttribute("aria-label", (paused ? "Play" : "Pause") + " the crawl of satirical captions");
  };
  setCrawl(reducedMotion.matches);
  crawlBtn.addEventListener("click", () => setCrawl(!crawlBar.classList.contains("paused")));

  if (!items.length) {
    const area = el("div", "shot-area");
    area.appendChild(el("div", "shot-missing", "The shelf is empty."));
    program.appendChild(area);
    return;
  }

  let current = 0, hops = 0, timer = null, pending = null;
  let activeAisle = "All", query = "";
  const channelSound = channelAudio($("channel-sound"));

  function visible() {
    return items.map((item, i) => ({ item, i })).filter(({ item }) => {
      const aisleMatch = activeAisle === "All" || item.aisle === activeAisle;
      const hay = [item.impersonated_brand, item.knockoff_label, item.defanged_url, item.critic_note, ...(item.tells || [])]
        .join(" ").toLowerCase();
      return aisleMatch && hay.includes(query);
    });
  }

  function show(i) {
    const item = items[i];
    const ch = pad2(i + 1);
    current = i;
    program.replaceChildren(renderProgram(item, ch));
    address.replaceChildren(renderAddress(item));
    facts.replaceChildren(renderFacts(item));
    now.textContent = `Now showing CH ${ch} · ${item.knockoff_label} · ${item.aisle || "Uncategorized"}`;
    for (const b of lineupEl.querySelectorAll("button")) b.setAttribute("aria-current", String(Number(b.dataset.i) === i));
    revealInLineup();
    if (typeof item.id === "string" && location.hash !== "#" + item.id) history.replaceState(null, "", "#" + item.id);
  }

  // On wide screens the lineup is its own scroll box. Keep the channel on air
  // visible inside it without scrolling the page.
  function revealInLineup() {
    const cur = lineupEl.querySelector('button[aria-current="true"]');
    if (!cur || lineupEl.scrollHeight <= lineupEl.clientHeight) return;
    const r = cur.getBoundingClientRect(), box = lineupEl.getBoundingClientRect();
    if (r.top < box.top) lineupEl.scrollTop -= box.top - r.top;
    else if (r.bottom > box.bottom) lineupEl.scrollTop += r.bottom - box.bottom;
  }

  function finish() {
    setBezelState("on");
    channelSound.stop();
    clearTimeout(timer);
    inter.hidden = true;
    inter.replaceChildren();
    if (pending !== null) { const p = pending; pending = null; show(p); }
  }

  function tune(i, userInitiated = false) {
    // Only genuine viewer-requested channel changes produce a tuning sound.
    const from = breakState ? breakState.target : (pending ?? current);
    // Changing channel during a break skips it and goes where the viewer asked.
    if (breakState) {
      endBreak(i);
      if (userInitiated && i !== from) channelSound.play();
      return;
    }
    if (i === from) return;
    channelSound.stop();
    if (breakDue()) {
      if (userInitiated) channelSound.play("commercial");
      startBreak(i);
      return;
    }
    sinceBreak += 1;
    if (reducedMotion.matches) {
      finish();
      show(i);
      if (userInitiated) channelSound.play();
      return;
    }
    hops += 1;
    clearTimeout(timer);
    pending = i;
    // The field-guide PSA keeps its every-4th slot, but never right after a commercial.
    const psa = hops % 4 === 0 && sinceBreak > 2;
    inter.replaceChildren(psa ? psaCard(() => { finish(); screen.focus({ preventScroll: true }); }) : staticCard(pad2(i + 1)));
    setBezelState("tuning");
    inter.hidden = false;
    // Snow plays only while the tuning card is visible. A PSA gets one
    // short cue instead of 4.5 seconds of noise.
    if (userInitiated) channelSound.play("channel", !psa);
    timer = setTimeout(finish, psa ? 4500 : 600);
  }

  function step(delta) {
    const list = visible();
    if (!list.length) return;
    const from = breakState ? breakState.target : (pending ?? current);
    let p = list.findIndex(({ i }) => i === from);
    p = p < 0 ? 0 : (p + delta + list.length) % list.length;
    tune(list[p].i, true);
  }

  function surf() {
    const list = visible();
    const pool = list.length > 1 ? list : items.map((item, i) => ({ item, i }));
    if (pool.length < 2) return;
    let r;
    do { r = pool[Math.floor(Math.random() * pool.length)].i; } while (r === current);
    tune(r, true);
  }

  // ---------- commercial breaks ----------
  // Breaks are optional, start muted, and any failure falls straight back to
  // the specimen the viewer was heading to. Nothing here can block browsing.

  // breaks.js is optional. If it failed to load, the station runs without
  // commercials and every Breaks.* call below is unreachable.
  const Breaks = window.OffBrandBreaks && typeof window.OffBrandBreaks.createRotation === "function" ? window.OffBrandBreaks : null;
  const store = Breaks ? Breaks.safeStore((() => { try { return window.localStorage; } catch (e) { return null; } })()) : null;
  const breakStatus = $("break-status");
  const toggleBtn = $("breaks-toggle");
  const prefBox = $("station-pref");
  const originals = $("originals");
  const listings = $("listings");
  const scheduler = Breaks ? Breaks.createScheduler() : null;
  let breaksOn = Breaks ? Breaks.loadEnabled(store) : false;
  let commercials = [], byId = new Map(), rotation = null, bumperDeck = null;
  let breakState = null, sinceBreak = 99;
  const STALL_MS = 8000;   // no playback progress for this long ends the break
  const CHOICE_MS = 12000; // a reduced-motion bumper waits this long for a choice

  const announce = (msg) => { breakStatus.textContent = ""; breakStatus.textContent = msg; };

  function renderToggle() {
    toggleBtn.setAttribute("aria-pressed", String(breaksOn));
    toggleBtn.querySelector("span").textContent = breaksOn ? "On" : "Off";
  }
  renderToggle();

  function setBreaks(on) {
    breaksOn = on;
    if (Breaks) Breaks.saveEnabled(store, on);
    renderToggle();
    if (!on && breakState && !breakState.voluntary) endBreak();
    announce(on ? "Commercial breaks are on." : "Commercial breaks are off. Off-Brand Originals stay on CH 00.");
  }
  toggleBtn.addEventListener("click", () => setBreaks(!breaksOn));

  function breakDue() {
    if (!Breaks || !breaksOn || !rotation || !rotation.available()) return false;
    if (!scheduler.tick()) return false;
    scheduler.reset();
    return true;
  }

  function teardown() {
    const s = breakState;
    if (!s) return false;
    for (const t of s.timers) { clearTimeout(t); clearInterval(t); }
    if (s.video) {
      s.video.pause();
      s.video.removeAttribute("src");
      s.video.load(); // abort any download in flight
    }
    if (document.fullscreenElement && inter.contains(document.fullscreenElement)) document.exitFullscreen().catch(() => {});
    const hadFocus = inter.contains(document.activeElement);
    setBezelState("on");
    inter.hidden = true;
    inter.replaceChildren();
    breakState = null;
    return hadFocus;
  }

  function endBreak(to) {
    const s = breakState;
    if (!s) return;
    channelSound.stop();
    const hadFocus = teardown();
    sinceBreak = 0;
    show(to === undefined ? s.target : to);
    if (hadFocus) screen.focus({ preventScroll: true });
  }

  function failBreak(c) {
    if (rotation) rotation.markFailed(c.id);
    const btn = listings.querySelector(`[data-id="${c.id}"]`);
    if (btn) { btn.disabled = true; btn.textContent = "Off the air"; }
    announce(`${c.title} is unavailable right now. Back to the program.`);
    endBreak();
  }

  function startBreak(target, opts) {
    opts = opts || {};
    clearTimeout(timer);
    inter.replaceChildren();
    // `target` is the viewer's newest request. A static switch still in flight
    // is older, so it is dropped, never substituted.
    pending = null;
    const id = opts.id || (rotation && rotation.next());
    const c = id && byId.get(id);
    if (!c) { show(target); return; }
    setBezelState("break");
    breakState = { target, c, voluntary: Boolean(opts.voluntary), timers: [], video: null };
    now.textContent = `Now showing CH 00 · Off-Brand Originals · ${c.title}`;

    if (opts.voluntary) { playCommercial(true); return; }

    const line = bumperDeck.next();
    const skip = () => endBreak();
    if (reducedMotion.matches) {
      // No motion, no autoplay: the viewer chooses.
      inter.replaceChildren(bumperCard(line, { noisy: false, actions: [["Watch the commercial", () => playCommercial(false)], ["Skip to CH " + pad2(target + 1), skip]] }));
      // Nobody chose? The break ends by itself; nothing waits on the viewer forever.
      breakState.timers.push(setTimeout(() => { if (breakState && !breakState.video) endBreak(); }, CHOICE_MS));
    } else {
      inter.replaceChildren(bumperCard(line, { noisy: true }));
      breakState.timers.push(setTimeout(() => playCommercial(false), 1900));
    }
    inter.hidden = false;
    announce(`Commercial break: ${c.title}. Press Escape or Skip to return to channel ${target + 1}.`);
  }

  function playCommercial(withSound) {
    const s = breakState;
    if (!s) return;
    channelSound.stop();
    const c = s.c;
    const back = "CH " + pad2(s.target + 1);

    const wrap = el("div", "commercial");
    const top = el("div", "ad-top");
    top.appendChild(el("span", null, `${s.voluntary ? "OFF-BRAND ORIGINALS" : "COMMERCIAL"} · ${c.title} · ${Breaks.formatRuntime(c.runtime_seconds)}`));
    if (!s.voluntary) {
      const off = el("button", null, "Turn off breaks");
      off.type = "button";
      off.addEventListener("click", () => setBreaks(false));
      top.appendChild(off);
    }
    wrap.appendChild(top);

    const stage = el("div", "ad-stage");
    const video = document.createElement("video");
    video.muted = !withSound;
    if (!withSound) video.setAttribute("muted", "");
    video.playsInline = true;
    video.setAttribute("playsinline", "");
    video.setAttribute("webkit-playsinline", "");
    video.preload = "auto";
    video.disablePictureInPicture = true;
    video.setAttribute("aria-label", `Commercial: ${c.title}. ${c.captions_vtt ? "English captions available." : c.captions === "burned-in" ? "Captions are part of the picture." : "Captions are not available."}`);
    if (c.poster) video.poster = c.poster;
    if (c.captions_vtt) {
      const track = document.createElement("track");
      track.kind = "captions";
      track.srclang = "en";
      track.label = "English";
      track.src = c.captions_vtt;
      track.default = true;
      video.appendChild(track);
    }
    stage.appendChild(video);
    wrap.appendChild(stage);

    const bar = el("div", "ad-progress");
    const fill = el("span");
    bar.appendChild(fill);
    bar.setAttribute("aria-hidden", "true");
    wrap.appendChild(bar);

    const controls = el("div", "ad-controls");
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "Commercial controls");
    const playBtn = iconButton("pause", "Pause", () => (video.paused ? video.play().catch(() => {}) : video.pause()));
    const soundBtn = iconButton(video.muted ? "muted" : "sound", video.muted ? "Turn sound on" : "Mute", () => {
      video.muted = !video.muted;
      if (!video.muted && video.paused) video.play().catch(() => {});
    });
    const replayBtn = iconButton("replay", "Replay from the start", () => { clearOverlay(); video.currentTime = 0; video.play().catch(() => {}); });
    controls.append(playBtn, soundBtn, replayBtn);
    const canFull = wrap.requestFullscreen || wrap.webkitRequestFullscreen || video.webkitEnterFullscreen;
    if (canFull) {
      controls.appendChild(iconButton("fullscreen", "Fullscreen", () => {
        try {
          if (wrap.requestFullscreen) wrap.requestFullscreen().catch(() => {});
          else if (wrap.webkitRequestFullscreen) wrap.webkitRequestFullscreen();
          else video.webkitEnterFullscreen(); // iPhone Safari: native player
        } catch (e) { /* stay inline */ }
      }));
    }
    const skipBtn = el("button", "skip-ad", s.voluntary ? `Back to ${back} »` : "Skip ad »");
    skipBtn.type = "button";
    skipBtn.addEventListener("click", () => endBreak());
    controls.appendChild(skipBtn);
    wrap.appendChild(controls);

    let overlay = null;
    function clearOverlay() { if (overlay) { overlay.remove(); overlay = null; } }
    function showOverlay(title, actions) {
      clearOverlay();
      overlay = el("div", "ad-overlay");
      overlay.appendChild(el("strong", null, title));
      overlay.appendChild(actionRow(actions));
      stage.appendChild(overlay);
    }

    // Watchdog: the break must keep making progress. A video that errors,
    // never starts, or freezes mid-play returns the viewer to the program after
    // STALL_MS. Only a pause the viewer chose (our button or the native player)
    // stops the clock; pauses we make ourselves (tab hidden) do not count.
    const fail = () => { if (breakState === s) failBreak(c); };
    let userPaused = false, blocked = false, lastTime = -1, lastProgress = Date.now();
    s.systemPause = false;
    s.timers.push(setInterval(() => {
      if (breakState !== s) return;
      const t = Date.now();
      if (userPaused || video.ended || document.hidden) { lastProgress = t; return; }
      if (video.currentTime !== lastTime) { lastTime = video.currentTime; lastProgress = t; return; }
      if (t - lastProgress < STALL_MS) return;
      if (blocked) {
        // Autoplay was refused and nobody tapped Play: not the video's fault,
        // so it stays in rotation. The break just ends.
        announce("Commercial skipped. Back to the program.");
        endBreak();
      } else {
        fail();
      }
    }, 500));
    video.addEventListener("error", fail);
    video.addEventListener("play", () => { userPaused = false; blocked = false; clearOverlay(); setIcon(playBtn, "pause", "Pause"); });
    video.addEventListener("pause", () => {
      if (!video.ended && !s.systemPause) userPaused = true;
      s.systemPause = false;
      setIcon(playBtn, "play", "Play");
    });
    video.addEventListener("volumechange", () => setIcon(soundBtn, video.muted ? "muted" : "sound", video.muted ? "Turn sound on" : "Mute"));
    video.addEventListener("timeupdate", () => {
      if (video.duration) fill.style.width = Math.min(100, (video.currentTime / video.duration) * 100) + "%";
    });
    video.addEventListener("ended", () => {
      if (s.voluntary) showOverlay(`That was ${c.title}`, [["Replay", () => replayBtn.click()], [`Back to ${back}`, () => endBreak()]]);
      else endBreak();
    });

    s.video = video;
    inter.replaceChildren(wrap);
    inter.hidden = false;
    video.src = c.src;
    const attempt = video.play();
    if (attempt && attempt.catch) {
      attempt.catch((err) => {
        if (breakState !== s) return;
        // Autoplay refused (Low Power Mode, browser policy): wait for a tap, not a failure.
        if (err && err.name === "NotAllowedError") blocked = true;
        if (err && err.name === "NotAllowedError") showOverlay(c.title, [["Play", () => video.play().catch(() => {})], [s.voluntary ? `Back to ${back}` : "Skip ad", () => endBreak()]]);
      });
    }
  }

  function playOriginal(id) {
    channelSound.stop();
    const target = breakState ? breakState.target : (pending ?? current);
    teardown();
    clearTimeout(timer);
    pending = null;
    inter.hidden = true;
    screen.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "center" });
    startBreak(target, { id, voluntary: true });
    const skip = inter.querySelector(".skip-ad");
    if (skip) skip.focus({ preventScroll: true });
  }

  function renderListings() {
    const times = Breaks.airTimes(commercials);
    listings.replaceChildren();
    commercials.forEach((c, k) => {
      const li = el("li", "listing");
      li.appendChild(el("time", null, times[k]));
      if (c.poster) {
        const img = document.createElement("img");
        img.src = c.poster;
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        li.appendChild(img);
      } else {
        li.appendChild(el("span"));
      }
      const info = el("div");
      info.appendChild(el("h3", null, c.title));
      info.appendChild(el("span", "runtime", `${Breaks.formatRuntime(c.runtime_seconds)} · captions ${c.captions_vtt ? "available" : c.captions === "burned-in" ? "in picture" : "not available"}`));
      if (c.description) info.appendChild(el("p", null, c.description));
      li.appendChild(info);
      const watch = el("button", "watch-btn", "Watch on CH 00");
      watch.type = "button";
      watch.dataset.id = c.id;
      watch.setAttribute("aria-label", `Watch ${c.title}, ${Breaks.formatRuntime(c.runtime_seconds)}, with sound`);
      watch.addEventListener("click", () => playOriginal(c.id));
      li.appendChild(watch);
      listings.appendChild(li);
    });
  }

  async function loadCommercials() {
    if (!Breaks) throw new Error("breaks.js unavailable");
    const r = await fetch(release ? `commercials/manifest.json?v=${encodeURIComponent(release)}` : "commercials/manifest.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("manifest " + r.status);
    const m = Breaks.validateManifest(await r.json());
    commercials = m.commercials;
    byId = new Map(commercials.map((c) => [c.id, c]));
    bumperDeck = Breaks.createBumperDeck(m.bumpers.length ? m.bumpers : ["Unfortunately, we’ll be right back."]);
    rotation = Breaks.createRotation(commercials.map((c) => c.id), store);
    if (commercials.length) { renderListings(); originals.hidden = false; prefBox.hidden = false; }
  }

  // Leaving the tab pauses the commercial; coming back resumes it. Neither
  // counts as the viewer pausing, so the watchdog stays honest.
  document.addEventListener("visibilitychange", () => {
    const s = breakState;
    if (!s || !s.video) return;
    if (document.hidden && !s.video.paused) {
      s.systemPause = true;
      s.resumeOnShow = true;
      s.video.pause();
    } else if (!document.hidden && s.resumeOnShow) {
      s.resumeOnShow = false;
      s.video.play().catch(() => {});
    }
  });

  function renderLineup() {
    const list = visible();
    lineupEl.replaceChildren();
    for (const { item, i } of list) {
      const li = el("li");
      const b = el("button");
      b.type = "button";
      b.dataset.i = String(i);
      b.setAttribute("aria-current", String(i === current));
      b.appendChild(el("span", "ch-num", pad2(i + 1)));
      const text = el("span", "ch-text");
      text.appendChild(el("strong", null, item.knockoff_label));
      const suspected = item.evidence && item.evidence.level === "suspected";
      text.appendChild(el("span", null, (item.aisle || "Uncategorized") + (suspected ? " · suspected, not confirmed" : "")));
      b.appendChild(text);
      b.addEventListener("click", () => {
        tune(i, true);
        if (window.matchMedia("(max-width: 900px)").matches) screen.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "start" });
      });
      li.appendChild(b);
      lineupEl.appendChild(li);
    }
    revealInLineup();
    if (lineupCountEl) {
      lineupCountEl.textContent = list.length === items.length ? `${items.length} channels` : `${list.length} of ${items.length}`;
    }
    emptyEl.hidden = list.length > 0;
    const off = list.length < 2;
    $("prev").disabled = $("next").disabled = off;
  }

  // aisle filters
  const filtersEl = $("aisle-filters");
  const aisles = ["All", ...new Set(items.map((i) => i.aisle).filter(Boolean))];
  for (const aisle of aisles) {
    const btn = el("button", "filter-btn", aisle);
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(aisle === activeAisle));
    btn.addEventListener("click", () => {
      activeAisle = aisle;
      for (const b of filtersEl.children) b.setAttribute("aria-pressed", String(b === btn));
      renderLineup();
    });
    filtersEl.appendChild(btn);
  }
  const syncSearchClear = () => { if (searchClearEl) searchClearEl.hidden = !searchEl.value.length; };
  searchEl.addEventListener("input", (e) => { query = e.target.value.trim().toLowerCase(); syncSearchClear(); renderLineup(); });
  if (searchClearEl) {
    searchClearEl.addEventListener("click", () => {
      searchEl.value = "";
      query = "";
      syncSearchClear();
      renderLineup();
      searchEl.focus();
    });
  }

  $("prev").addEventListener("click", () => step(-1));
  $("next").addEventListener("click", () => step(1));
  $("surf").addEventListener("click", surf);
  screen.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && breakState) { e.preventDefault(); endBreak(); return; }
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  });

  // held back
  const rejectedList = $("rejected-list");
  for (const r of rejected) {
    const li = el("li");
    li.appendChild(el("strong", null, r.defanged_domain));
    li.appendChild(el("p", null, r.reason));
    if (isSafeRecordUrl(r.public_record_url)) li.appendChild(externalLink(r.public_record_url, null, "[Public Record]"));
    rejectedList.appendChild(li);
  }

  // A shared link (#urlscan-…) tunes straight to that specimen.
  const fromHash = () => items.findIndex((it) => typeof it.id === "string" && "#" + it.id === location.hash);
  window.addEventListener("hashchange", () => { const i = fromHash(); if (i >= 0) tune(i); });

  renderLineup();
  const start = fromHash();
  show(start >= 0 ? start : 0);

  // Commercials load after the shelf is on screen. If anything goes wrong the
  // station simply runs without breaks.
  loadCommercials().catch(() => { rotation = null; });
}

init().catch((err) => {
  const area = el("div", "shot-area");
  area.appendChild(el("div", "shot-missing", `Could not load reviews.json: ${err.message}`));
  document.getElementById("program").replaceChildren(area);
});
