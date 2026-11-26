"use strict";

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

function renderCard(item) {
  const card = el("article", "card");

  const top = el("div", "card-top");
  top.appendChild(el("span", "aisle-badge", item.aisle || "Uncategorized"));
  top.appendChild(el("span", "sticker", `${item.verdict} (${item.rating})`));
  card.appendChild(top);

  card.appendChild(el("h2", null, item.knockoff_label));
  card.appendChild(el("div", "brand-target", `Impersonating: ${item.impersonated_brand}`));
  card.appendChild(el("div", "defanged-box", item.defanged_url));
  card.appendChild(el("p", "critic-note", item.critic_note));

  const btn = el("button", "drill-btn", "INSPECT THE TELLS");
  btn.type = "button";
  btn.setAttribute("aria-expanded", "false");

  const tellsPanel = el("div", "tells-panel");
  tellsPanel.hidden = true;
  if (item.sketchy_segment) {
    tellsPanel.appendChild(el("strong", null, `Dead giveaway: ${item.sketchy_segment}`));
  }
  const ul = el("ul");
  (item.tells || []).forEach((tell) => ul.appendChild(el("li", null, tell)));
  tellsPanel.appendChild(ul);

  btn.addEventListener("click", () => {
    const opening = tellsPanel.hidden;
    tellsPanel.hidden = !opening;
    btn.setAttribute("aria-expanded", String(opening));
    btn.textContent = opening ? "HIDE THE TELLS" : "INSPECT THE TELLS";
  });

  card.appendChild(btn);
  card.appendChild(tellsPanel);

  const meta = el("div", "receipt-meta");
  meta.appendChild(el("div", null, `IP: ${displayOrMissing(item.ip)}`));
  meta.appendChild(el("div", null, `ASN: ${displayOrMissing(item.asn_name)}`));
  meta.appendChild(el("div", null, `Page Title: ${displayOrMissing(item.page_title)}`));
  meta.appendChild(el("div", null, `Scanned: ${displayOrMissing(item.scanned_at)}`));
  meta.appendChild(el("div", null, `Source: ${displayOrMissing(item.source)}`));

  if (isSafeRecordUrl(item.public_record_url)) {
    const link = el("a", "record-link", "Verify Public Record ->");
    link.href = item.public_record_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    meta.appendChild(link);
  }

  card.appendChild(meta);
  return card;
}

async function init() {
  const res = await fetch("data/reviews.json");
  const data = await res.json();
  const items = data.items || [];
  const rejected = data.rejected_log || [];

  document.getElementById("last-updated").textContent = `UPDATED: ${data.last_updated || "UNKNOWN"}`;

  const statsBar = document.getElementById("stats-bar");
  statsBar.appendChild(el("span", "stat-chip", `${items.length} REVIEWED KNOCKOFFS`));
  statsBar.appendChild(el("span", "stat-chip", `${rejected.length} HELD BACK IN TRIAGE`));

  const aisles = ["All", ...new Set(items.map((i) => i.aisle).filter(Boolean))];
  let activeAisle = "All";
  let query = "";

  const filtersEl = document.getElementById("aisle-filters");
  const gridEl = document.getElementById("aisle-grid");
  const searchEl = document.getElementById("search-input");

  function render() {
    gridEl.textContent = "";
    const filtered = items.filter((item) => {
      const aisleMatch = activeAisle === "All" || item.aisle === activeAisle;
      const hay = [
        item.impersonated_brand,
        item.knockoff_label,
        item.defanged_url,
        item.critic_note,
        ...(item.tells || []),
      ]
        .join(" ")
        .toLowerCase();
      return aisleMatch && hay.includes(query);
    });

    if (filtered.length === 0) {
      gridEl.appendChild(el("p", null, "No knockoffs match that filter."));
      return;
    }
    filtered.forEach((item) => gridEl.appendChild(renderCard(item)));
  }

  aisles.forEach((aisle) => {
    const btn = el("button", "filter-btn", aisle);
    btn.type = "button";
    if (aisle === activeAisle) btn.classList.add("active");
    btn.addEventListener("click", () => {
      activeAisle = aisle;
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      render();
    });
    filtersEl.appendChild(btn);
  });

  searchEl.addEventListener("input", (e) => {
    query = e.target.value.trim().toLowerCase();
    render();
  });

  const rejectedList = document.getElementById("rejected-list");
  rejected.forEach((r) => {
    const li = el("li");
    li.appendChild(el("strong", null, `${r.defanged_domain}: `));
    li.appendChild(document.createTextNode(`${r.reason} `));
    if (isSafeRecordUrl(r.public_record_url)) {
      const a = el("a", null, "[Public Record]");
      a.href = r.public_record_url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.appendChild(a);
    }
    rejectedList.appendChild(li);
  });

  render();
}

init().catch((err) => {
  const gridEl = document.getElementById("aisle-grid");
  gridEl.textContent = `Could not load reviews.json: ${err.message}`;
});
