/* OB-TEXT uses existing public data only. No target requests, telemetry or new verdicts. */
"use strict";
const PAGES = Object.freeze({
  "100": "Station index", "101": "Continuity desk", "204": "Investigation notes",
  "310": "The Cutting Room Floor", "412": "Special programming", "505": "Broadcast archive",
  "606": "Off-Brand Originals", "701": "Station standards", "888": "Goodnight from Studio B"
});
const CODES = Object.keys(PAGES).sort();
const SPECIMEN = /^urlscan-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const RATINGS = Object.freeze({"corroborated":"Corroborated","source-confirmed":"Source-confirmed",
  "suspected":"Suspected (not confirmed)","unverified":"Unverified","disputed":"Disputed"});
function validId(id) { return typeof id === "string" && SPECIMEN.test(id); }
function groups(items) {
  const result = new Map();
  for (const item of items) {
    if (!validId(item.id)) continue;
    const name = typeof item.aisle === "string" && item.aisle ? item.aisle : "Uncategorized";
    if (!result.has(name)) result.set(name, []);
    result.get(name).push(item);
  }
  return [...result].sort(([a],[b]) => a.localeCompare(b));
}
function rating(item) {
  const level = item.evidence && item.evidence.level;
  return Object.prototype.hasOwnProperty.call(RATINGS, level) ? RATINGS[level] : "Not yet rated";
}
function pageCode(hash) { return /^#\d{3}$/.test(hash) ? hash.slice(1) : "100"; }

if (typeof module !== "undefined" && module.exports) {
  module.exports = { PAGES, CODES, validId, groups, rating, pageCode };
} else {
  const $ = id => document.getElementById(id);
  const body = $("txt-body"), title = $("txt-title"), input = $("txt-number"), status = $("txt-status");
  const release = new URL(document.currentScript.src).searchParams.get("v");
  const query = new URLSearchParams(location.search);
  const selected = query.get("channel");
  if (validId(selected)) $("txt-return").href = "index.html#" + selected;
  let reviews = null, commercials = null, reviewError = false, commercialError = false;
  let active = pageCode(location.hash), chosen = validId(selected) ? selected : "";
  function el(tag, text, cls) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function link(label, href) { const a = el("a", label); a.href = href; return a; }
  function para(text, cls) { body.appendChild(el("p", text, cls)); }
  function note(text) { para(text, "txt-note"); }
  function tuneLink(item) { return link(item.knockoff_label || item.impersonated_brand || "Untitled review", "index.html#" + item.id); }
  function list(items) {
    const ul = el("ul", null, "txt-rows");
    for (const item of items.filter(x => validId(x.id))) {
      const li = el("li");
      li.append(tuneLink(item), el("div", (item.aisle || "Uncategorized") + " · " + rating(item), "txt-kicker"));
      ul.appendChild(li);
    }
    return ul;
  }
  function waiting(kind) {
    const failed = kind === "reviews" ? reviewError : commercialError;
    note(failed ? "This public data file could not be read. No records have been invented. Return to the broadcast or reload this page."
                : "Waiting for the public station data.");
  }
  function showInvestigation() {
    note("These are the original published editorial notes, not new forensic findings. Their prose may combine observations and interpretations. The Evidence Locker on the broadcast is authoritative for structured ratings.");
    if (!reviews) return waiting("reviews");
    const items = reviews.items.filter(x => validId(x.id));
    if (!items.length) return note("No usable published review IDs.");
    const select = el("select");
    select.id = "txt-review-select";
    const label = el("label", "SELECT PUBLISHED REVIEW");
    label.htmlFor = select.id;
    const wrap = el("div", null, "txt-select");
    wrap.append(label,select);
    for (const item of items) {
      const option = el("option", item.knockoff_label || item.id);
      option.value = item.id; select.appendChild(option);
    }
    select.value = items.some(x => x.id === chosen) ? chosen : items[0].id;
    const record = el("section", null, "txt-record");
    function show() {
      const item = items.find(x => x.id === select.value);
      if (!item) return;
      chosen = item.id;
      record.replaceChildren(el("h2", item.knockoff_label || "Review"), el("p", "Evidence level: " + rating(item), "txt-kicker"));
      const ol = el("ol");
      for (const tell of Array.isArray(item.tells) ? item.tells : []) ol.appendChild(el("li", tell));
      record.append(ol);
      if (!item.evidence) record.append(el("p", "Historical review: not independently rated under the current methodology.", "txt-note"));
      record.append(link("Open this channel and its Evidence Locker", "index.html#" + item.id));
    }
    select.addEventListener("change", show);
    body.append(wrap,record);
    show();
  }
  function render(focus = false) {
    const code = active;
    $("txt-page-code").textContent = "P." + code;
    input.value = code;
    for (const a of document.querySelectorAll(".txt-nav a")) {
      if (a.getAttribute("href") === "#" + code) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    title.textContent = PAGES[code] || "Page not transmitted";
    document.title = "OB-TEXT P." + code + " // " + title.textContent;
    body.replaceChildren();
    switch (code) {
      case "100": {
        para("Station information, underneath the picture.", "txt-kicker");
        para("You are watching Off-Brand. Please do not adjust your expectations.");
        const ul = el("ul", null, "txt-rows txt-index");
        for (const id of CODES.filter(x => x !== "100")) {
          const li = el("li"); li.append(link(PAGES[id], "#" + id),el("span",id)); ul.appendChild(li);
        }
        body.appendChild(ul);
        break;
      }
      case "101":
        para("FICTIONAL STATION CONTINUITY", "txt-kicker");
        body.appendChild(el("div", "You are watching Off-Brand. Please do not adjust your expectations.", "txt-bumper"));
        para("Studio B has no announcements at this time. This is a fictional station message, not a report of a technical incident.");
        break;
      case "204": showInvestigation(); break;
      case "310": {
        note("Actual public editorial exclusions, reproduced as anonymous tape labels. These reasons are recorded editorial decisions, not a new finding that a website is safe or malicious. Identifiers and addresses are deliberately omitted.");
        if (!reviews) { waiting("reviews"); break; }
        const tapes = el("div", null, "txt-tapes");
        reviews.rejected_log.forEach((row,i) => {
          const tape = el("details", null, "txt-tape");
          tape.append(el("summary", "TAPE " + String(i+1).padStart(3,"0") + " / WITHHELD"),
            el("p", row.reason || "No reason recorded."));
          tapes.appendChild(tape);
        });
        if (!reviews.rejected_log.length) para("No recorded public exclusions.");
        else body.appendChild(tapes);
        break;
      }
      case "412":
        note("On-demand programming grouped by the archive's existing categories. These are not scheduled transmission times or independently verified shared techniques.");
        if (!reviews) { waiting("reviews"); break; }
        if (!groups(reviews.items).length) para("No usable published review IDs.");
        for (const [name,items] of groups(reviews.items)) {
          const d = el("details", null, "txt-program");
          d.append(el("summary", name + " · " + items.length + " reviews"),list(items));
          body.appendChild(d);
        }
        break;
      case "505":
        note("Published review index. Choose a channel to return to the main broadcast. Ratings reflect recorded evidence, not current provider checks.");
        if (!reviews) { waiting("reviews"); break; }
        para("Public data updated: " + (reviews.last_updated || "Not recorded"),"txt-kicker");
        body.appendChild(list(reviews.items));
        break;
      case "606": {
        note("Original commercials from the station's existing manifest. Watch them through the broadcast's Off-Brand Originals section; no autoplay here.");
        if (!commercials) { waiting("commercials"); break; }
        const ul = el("ul", null, "txt-rows");
        for (const c of commercials.commercials) ul.appendChild(el("li", c.title || "Untitled commercial"));
        body.append(ul,link("Return to the broadcast and watch Originals", $("txt-return").getAttribute("href")));
        break;
      }
      case "701":
        para("How the station evaluates evidence, handles uncertainty and records corrections.");
        body.append(link("Read station standards","methodology.html"),el("p"),link("Open corrections desk","methodology.html#corrections"));
        break;
      case "888":
        para("FICTIONAL STATION SIGN-OFF", "txt-kicker");
        body.appendChild(el("div","The entertainment can be fictional. The evidence cannot.","txt-bumper"));
        para("Read the full hostname. Verify unexpected requests through a trusted channel. Never confuse an archived screenshot with proof of what a live page does.");
        para("Goodnight from Studio B. The archive remains available.");
        body.appendChild(link("Return to the broadcast",$("txt-return").getAttribute("href")));
        break;
      default:
        note("No page is assigned to this number.");
        body.appendChild(link("Return to P.100", "#100"));
    }
    if (focus) title.focus();
  }
  function go(code) {
    if (!/^\d{3}$/.test(code)) {
      status.textContent = "Enter a three-digit page number.";
      input.focus();
      return;
    }
    status.textContent = "";
    if (location.hash === "#" + code) { active = code; render(true); }
    else location.hash = code;
  }
  document.querySelector(".txt-skip").addEventListener("click", e => { e.preventDefault(); title.focus(); });
  $("txt-go").addEventListener("click", () => go(input.value.trim()));
  input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(input.value.trim()); } });
  function step(dir) {
    const i = CODES.indexOf(active);
    go(CODES[i < 0 ? 0 : (i + dir + CODES.length) % CODES.length]);
  }
  $("txt-prev").addEventListener("click", () => step(-1));
  $("txt-next").addEventListener("click", () => step(1));
  window.addEventListener("hashchange", () => { if (location.hash === "#txt-content") return; active = pageCode(location.hash); status.textContent = ""; render(true); });
  function clock() {
    const now = new Date();
    $("txt-clock").textContent = "LOCAL TIME " + String(now.getHours()).padStart(2,"0") + ":" + String(now.getMinutes()).padStart(2,"0");
  }
  clock(); setInterval(clock,15000);
  render();
  function load(path) {
    return fetch(path + (release ? "?v=" + encodeURIComponent(release) : ""), {cache:"no-cache"})
      .then(r => { if (!r.ok) throw new Error("Unavailable"); return r.json(); });
  }
  load("data/reviews.json").then(d => {
    if (!Array.isArray(d.items) || !Array.isArray(d.rejected_log) || d.items.some(x => !x || typeof x !== "object") || d.rejected_log.some(x => !x || typeof x !== "object")) throw new Error("Malformed");
    reviews = d;
  }).catch(() => { reviewError = true; }).finally(() => {
    if (["204","310","412","505"].includes(active)) render();
  });
  load("commercials/manifest.json").then(d => {
    if (!Array.isArray(d.commercials) || d.commercials.some(x => !x || typeof x !== "object")) throw new Error("Malformed");
    commercials = d;
  }).catch(() => { commercialError = true; }).finally(() => {
    if (active === "606") render();
  });
}
