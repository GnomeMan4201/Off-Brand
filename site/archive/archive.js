"use strict";

const STATUS = { unwritten: "Unwritten", drafted: "Drafted", published: "Published" };
let DATA = { specimens: [] };
let filter = "all";

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
const safeImage = (p) => typeof p === "string" && /^shots\/[0-9a-f]{64}\.(png|jpg)$/.test(p);
const safeRecord = (u) => typeof u === "string" && /^https:\/\/urlscan\.io\/result\/[0-9a-f-]{36}\//.test(u);
const safeRepo = (r) => typeof r === "string" && /^[\w.-]+\/[\w.-]+$/.test(r);
const day = (iso) => String(iso || "").slice(0, 10) || "unknown date";

function renderFilters() {
  const box = document.getElementById("filters");
  box.textContent = "";
  [["all", "All"], ["unwritten", "Unwritten"], ["drafted", "Drafted"], ["published", "Published"]].forEach(([key, label]) => {
    const n = key === "all" ? DATA.specimens.length : DATA.specimens.filter((s) => s.status === key).length;
    const b = el("button", "", `${label} ${n}`);
    b.type = "button";
    b.setAttribute("aria-pressed", String(filter === key));
    b.addEventListener("click", () => { filter = key; renderFilters(); renderSheet(); });
    box.append(b);
  });
}

function renderSheet() {
  const sheet = document.getElementById("sheet");
  sheet.textContent = "";
  const list = DATA.specimens
    .filter((s) => filter === "all" || s.status === filter)
    .sort((a, b) => String(b.captured_at).localeCompare(String(a.captured_at)));
  document.getElementById("count").textContent = `${list.length} specimen(s), newest first`;
  if (!list.length) sheet.append(el("p", "hint", "Nothing here yet."));
  for (const s of list) {
    const card = el("button", "card");
    card.type = "button";
    card.addEventListener("click", () => { location.hash = encodeURIComponent(s.id); });
    if (safeImage(s.image)) {
      const img = el("img", "thumb");
      img.src = s.image; img.alt = ""; img.loading = "lazy"; img.decoding = "async";
      card.append(img);
    } else card.append(el("div", "noshot", "no screenshot"));
    const meta = el("div", "meta");
    meta.append(el("div", "domain", s.domain || "unknown domain"), el("div", "date", day(s.captured_at)),
      el("span", `badge ${s.status}`, STATUS[s.status] || s.status));
    card.append(meta);
    sheet.append(card);
  }
}

function renderDetail(s) {
  const d = document.getElementById("detail");
  d.textContent = "";
  const back = el("button", "back", "\u2190 Back");
  back.type = "button";
  back.addEventListener("click", () => { location.hash = ""; });
  d.append(back, el("h2", "", s.domain || "unknown domain"),
    el("div", "date", `Captured ${s.captured_at} \u00b7 ${STATUS[s.status] || s.status}`));
  if (safeImage(s.image)) {
    const a = el("a");
    a.href = s.image; a.target = "_blank"; a.rel = "noopener noreferrer";
    const img = el("img", "bigshot");
    img.src = s.image; img.alt = `Saved screenshot of ${s.domain || "the page"}`;
    a.append(img); d.append(a);
  } else d.append(el("p", "hint", "No saved screenshot."));
  if (s.bullets && s.bullets.length) {
    const ul = el("ul");
    for (const b of s.bullets) {
      const li = el("li", "", b.text);
      li.append(el("span", "src", `Source: ${b.source}`));
      ul.append(li);
    }
    d.append(ul);
  } else d.append(el("p", "hint", "No factual bullets supported by the record."));
  const actions = el("div", "actions");
  if (safeRecord(s.source_record_url)) {
    const r = el("a", "action", "Source record");
    r.href = s.source_record_url; r.target = "_blank"; r.rel = "noopener noreferrer";
    actions.append(r);
  }
  if (safeRepo(DATA.repo)) {
    if (s.draft_issue) {
      const a = el("a", "action primary", `Open draft #${s.draft_issue}`);
      a.href = `https://github.com/${DATA.repo}/issues/${Number(s.draft_issue)}`;
      actions.append(a);
    } else if (s.status !== "published") {
      const a = el("a", "action primary", "Write this one");
      a.href = `https://github.com/${DATA.repo}/actions/workflows/write-specimen.yml`;
      actions.append(a);
    }
  }
  d.append(actions);
  if (!s.draft_issue && s.status === "unwritten") {
    const h = el("p", "hint", "On the page that opens: Run workflow, paste this id, run. It opens your draft issue once, then this button becomes \u201cOpen draft\u201d. ");
    h.append(el("code", "", s.id));
    d.append(h);
  }
}

function route() {
  const id = decodeURIComponent(location.hash.slice(1));
  const s = DATA.specimens.find((x) => x.id === id);
  const d = document.getElementById("detail");
  if (s) { renderDetail(s); d.hidden = false; d.scrollTop = 0; } else d.hidden = true;
}

fetch("data.json", { cache: "no-cache" })
  .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
  .then((data) => {
    DATA = data;
    document.getElementById("fixture-banner").hidden = !data.fixture;
    renderFilters(); renderSheet(); route();
    window.addEventListener("hashchange", route);
  })
  .catch((err) => { document.getElementById("sheet").textContent = `Could not load data.json: ${err.message}`; });
