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

function renderShot(item) {
  const uuid = scanUuid(item);
  if (!uuid) return null;
  const src = `https://urlscan.io/screenshots/${uuid}.png`;

  const fig = el("figure", "shot");
  const link = el("a", "shot-link");
  link.href = src;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `Open full screenshot of ${item.knockoff_label}`);

  const img = document.createElement("img");
  img.src = src;
  img.alt = `Screenshot of ${item.knockoff_label}`;
  img.loading = "lazy";
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.addEventListener("error", () => {
    // Nothing fake: a missing screenshot is shown as missing, never replaced.
    fig.replaceChildren(el("div", "shot-missing", "Screenshot unavailable · see scan notes below"));
  });

  link.appendChild(img);
  fig.appendChild(link);
  fig.appendChild(el("figcaption", null,
    `Captured by urlscan.io${item.scanned_at ? " \u00b7 " + String(item.scanned_at).slice(0, 10) : ""}`));
  return fig;
}

function renderCard(item) {
  const card = el("article", "card");

  const top = el("div", "card-top");
  top.appendChild(el("span", "aisle-badge", item.aisle || "Uncategorized"));
  if (item.rating && item.rating !== "Unrated") {
    top.appendChild(el("span", "sticker", item.verdict + " · " + item.rating));
  }
  card.appendChild(top);
  card.appendChild(el("h2", null, item.knockoff_label));
  const shot = renderShot(item);
  if (shot) card.appendChild(shot);
  card.appendChild(el("p", "critic-note", item.critic_note));

  const tells = item.tells || [];
  if (tells.length) {
    const lesson = el("section", "lesson");
    lesson.appendChild(el("h3", null, "What to notice"));
    lesson.appendChild(el("p", null, tells[0]));
    if (tells.length > 1) {
      const more = el("details", "lesson-more");
      more.appendChild(el("summary", null, "Take a closer look"));
      for (const tell of tells.slice(1)) more.appendChild(el("p", null, tell));
      lesson.appendChild(more);
    }
    card.appendChild(lesson);
  }
  const details = el("details", "scan-details");
  details.appendChild(el("summary", null, "Inspect the scan"));
  if (item.impersonated_brand && item.impersonated_brand !== "Not established") {
    details.appendChild(el("p", "brand-target", "Brand pictured · " + item.impersonated_brand));
  }
  details.appendChild(el("div", "defanged-box", item.defanged_url));
  if (item.sketchy_segment) details.appendChild(el("p", "brand-target", "Address detail · " + item.sketchy_segment));
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

  details.appendChild(meta);
  card.appendChild(details);
  return card;
}

const release = new URL(document.currentScript.src).searchParams.get("v");

async function init() {
  const res = await fetch(release ? `data/reviews.json?v=${encodeURIComponent(release)}` : "data/reviews.json", { cache: "no-cache" });
  const data = await res.json();
  const items = data.items || [];
  const rejected = data.rejected_log || [];

  document.getElementById("last-updated").textContent = `Updated ${String(data.last_updated || "").slice(0, 10)}`;

  const statsBar = document.getElementById("stats-bar");
  statsBar.appendChild(el("span", "stat-chip", `${items.length} REVIEWS`));
  statsBar.appendChild(el("span", "stat-chip", `${rejected.length} HELD BACK`));

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
      gridEl.appendChild(el("p", null, "No reviews match. Try another aisle or search."));
      return;
    }
    filtered.forEach((item) => gridEl.appendChild(renderCard(item)));
  }

  aisles.forEach((aisle) => {
    const btn = el("button", "filter-btn", aisle);
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(aisle === activeAisle));
    if (aisle === activeAisle) btn.classList.add("active");
    btn.addEventListener("click", () => {
      activeAisle = aisle;
      document.querySelectorAll(".filter-btn").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-pressed", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-pressed", "true");
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
