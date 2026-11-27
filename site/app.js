"use strict";

// OFF-BRAND // After Dark
// Every value from reviews.json is scanned or hand-written text: it is only ever
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
  return box;
}

// ---------- WHAT TO NOTICE ----------

function renderFacts(item) {
  const frag = document.createDocumentFragment();
  const tells = item.tells || [];
  frag.appendChild(el("p", "lead-tell", tells[0] || "Not recorded in public scan"));

  if (tells.length > 1) {
    const more = el("details", "evidence");
    more.appendChild(el("summary", null, "Evidence and assessment"));
    for (const tell of tells.slice(1)) more.appendChild(el("p", null, tell));
    frag.appendChild(more);
  }

  const meta = el("div", "fact-meta");
  const row = (label, val) => meta.appendChild(el("div", null, `${label} · ${val}`));
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
  if (isSafeRecordUrl(item.public_record_url)) links.appendChild(externalLink(item.public_record_url, null, "Verify Public Record ->"));
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

const release = new URL(document.currentScript.src).searchParams.get("v");

async function init() {
  const res = await fetch(release ? `data/reviews.json?v=${encodeURIComponent(release)}` : "data/reviews.json", { cache: "no-cache" });
  const data = await res.json();
  const items = data.items || [];
  const rejected = data.rejected_log || [];

  document.getElementById("last-updated").textContent = `Updated ${String(data.last_updated || "").slice(0, 10)}`;
  document.getElementById("stats-bar").textContent = `${items.length} specimens on air · ${rejected.length} held back at review`;

  const $ = (id) => document.getElementById(id);
  const screen = $("screen"), program = $("program"), inter = $("interstitial");
  const now = $("now"), address = $("address"), facts = $("fact-body");
  const lineupEl = $("lineup"), emptyEl = $("lineup-empty"), searchEl = $("search-input");

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
    if (typeof item.id === "string" && location.hash !== "#" + item.id) history.replaceState(null, "", "#" + item.id);
  }

  function finish() {
    clearTimeout(timer);
    inter.hidden = true;
    inter.replaceChildren();
    if (pending !== null) { const p = pending; pending = null; show(p); }
  }

  function tune(i) {
    if (i === current && pending === null) return;
    if (reducedMotion.matches) { show(i); return; }
    hops += 1;
    clearTimeout(timer);
    pending = i;
    const psa = hops % 4 === 0;
    inter.replaceChildren(psa ? psaCard(() => { finish(); screen.focus({ preventScroll: true }); }) : staticCard(pad2(i + 1)));
    inter.hidden = false;
    timer = setTimeout(finish, psa ? 4500 : 600);
  }

  function step(delta) {
    const list = visible();
    if (!list.length) return;
    let p = list.findIndex(({ i }) => i === (pending ?? current));
    p = p < 0 ? 0 : (p + delta + list.length) % list.length;
    tune(list[p].i);
  }

  function surf() {
    const list = visible();
    const pool = list.length > 1 ? list : items.map((item, i) => ({ item, i }));
    if (pool.length < 2) return;
    let r;
    do { r = pool[Math.floor(Math.random() * pool.length)].i; } while (r === current);
    tune(r);
  }

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
      text.appendChild(el("span", null, item.aisle || "Uncategorized"));
      b.appendChild(text);
      b.addEventListener("click", () => {
        tune(i);
        if (window.matchMedia("(max-width: 900px)").matches) screen.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "start" });
      });
      li.appendChild(b);
      lineupEl.appendChild(li);
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
  searchEl.addEventListener("input", (e) => { query = e.target.value.trim().toLowerCase(); renderLineup(); });

  $("prev").addEventListener("click", () => step(-1));
  $("next").addEventListener("click", () => step(1));
  $("surf").addEventListener("click", surf);
  screen.addEventListener("keydown", (e) => {
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
}

init().catch((err) => {
  const area = el("div", "shot-area");
  area.appendChild(el("div", "shot-missing", `Could not load reviews.json: ${err.message}`));
  document.getElementById("program").replaceChildren(area);
});
