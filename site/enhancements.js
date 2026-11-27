/* OFF-BRAND: optional station craftsmanship. Never changes evidence or tuning. */
(function () {
  "use strict";

  // Browser URL parsing is local only. Do not infer registrable domains from
  // the last two labels: public/private suffixes, IPs and IDNs differ.
  function addressAnatomy(raw) {
    if (typeof raw !== "string" || raw.length > 4096 || /[\x00-\x20\x7f\\]/.test(raw)) return null;
    const m = raw.match(/^(hxxps?|https?):\/\/([^/?#]+)(.*)$/i);
    if (!m) return null;
    const authority = m[2].replace(/\[\.\]|\(\.\)/g, ".").replace(/\[:\]/g, ":");
    let parsed;
    try { parsed = new URL(m[1].replace(/^hxxp/i, "http") + "://" + authority + "/"); }
    catch (_) { return null; }
    if (!parsed.hostname) return null;
    const hostport = authority.slice(authority.lastIndexOf("@") + 1);
    const port = hostport.match(/(?:\]|[^:]):(\d+)$/);
    const ip = /^\[/.test(parsed.hostname) || /^\d+(?:\.\d+){3}$/.test(parsed.hostname);
    const safeHost = parsed.hostname.replace(/\./g, "[.]").replace(/:/g, "[:]");
    const tail = m[3];
    return {
      scheme: parsed.protocol.replace(/^http/, "hxxp").slice(0, -1),
      host: safeHost, ip, port: port ? port[1] : "",
      userinfo: authority.includes("@"),
      path: tail.split(/[?#]/, 1)[0] || "/",
      query: tail.split("#", 1)[0].includes("?"),
      fragment: tail.includes("#")
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { addressAnatomy };
    return;
  }

  const byId = id => document.getElementById(id);
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderLoupe() {
    const address = byId("address");
    const source = address && address.querySelector(".address-text");
    if (!source) return;
    const old = address.querySelector(".ob-loupe");
    if (old && old.dataset.source === source.textContent) return;
    if (old) old.remove();
    const parsed = addressAnatomy(source.textContent);
    if (!parsed) return;
    const panel = el("details", "ob-loupe");
    panel.dataset.source = source.textContent;
    panel.appendChild(el("summary", null, "Knockoff Loupe · inspect the address"));
    const fields = el("dl", "ob-loupe-fields");
    function field(label, value) {
      const block = el("div");
      block.append(el("dt", null, label), el("dd", null, value));
      fields.appendChild(block);
    }
    field("Scheme", parsed.scheme);
    field(parsed.ip ? "Browser-parsed IP address" : "Browser-parsed hostname", parsed.host);
    if (parsed.port) field("Explicit port", parsed.port);
    if (parsed.userinfo) field("User information", "Present before @ (not repeated here)");
    field("Path", parsed.path.length > 120 ? parsed.path.slice(0, 120) + "… (abridged)" : parsed.path);
    if (parsed.query || parsed.fragment) field("Extra components",
      [parsed.query && "Query", parsed.fragment && "Fragment"].filter(Boolean).join(" and ") + " present");
    panel.appendChild(fields);
    panel.appendChild(el("p", "ob-loupe-note", parsed.ip
      ? "This is an IP address, not a registered domain. Compare the destination with a trusted service."
      : "Read the full hostname, not just a familiar label or path. This view does not determine the registrable domain, hosting provider, ownership or phishing verdict."));
    panel.appendChild(el("p", "ob-loupe-note", "Parsed locally for illustration; no target is opened. The original scanned address above is unchanged."));
    address.appendChild(panel);
  }

  const address = byId("address");
  if (address) {
    const observer = new MutationObserver(records => {
      // Only react to the core renderer's replacement of direct children.
      if (records.some(r => [...r.addedNodes].some(n => n.nodeType === 1 && n.classList.contains("address-text")))) renderLoupe();
    });
    observer.observe(address, { childList: true });
    renderLoupe();
  }

  const deck = document.querySelector(".deck");
  if (!deck) return;
  const strip = el("section", "ob-control-strip");
  strip.setAttribute("aria-label", "Station control room");
  const top = el("div", "ob-control-top");
  const clock = el("span", "ob-clock");
  const note = el("span", "ob-control-note");
  const notes = [
    "TAPE ROOM / Keep the original address in view.",
    "ENGINEERING / A capture is one moment, not a live feed.",
    "NEWS DESK / Satire belongs in the chyron.",
    "STANDARDS / A source label is not a verdict."
  ];
  let index = 0;
  function updateClock() {
    const now = new Date();
    clock.textContent = "LOCAL CLOCK " + String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
  }
  updateClock();
  // Avoid second-by-second announcements and unnecessary animation.
  setInterval(updateClock, 15000);
  note.textContent = notes[index];
  top.append(clock, note);
  strip.appendChild(top);
  const controls = el("div", "ob-controls");
  function button(label) {
    const b = el("button", "ob-switch", label);
    b.type = "button";
    controls.appendChild(b);
    return b;
  }
  const scan = button("Scanlines");
  const degauss = button("Degauss");
  const calibrate = button("Station ID");
  const remote = button("Remote guide");
  strip.appendChild(controls);
  const signal = el("p", "ob-signal", "ENGINEERING / Monitor standing by");
  signal.setAttribute("role", "status");
  strip.appendChild(signal);
  deck.appendChild(strip);

  const screen = byId("screen");
  let scanOn = false;
  try { scanOn = localStorage.getItem("offbrand.scanlines") === "on"; } catch (_) {}
  function syncScan() {
    if (screen) screen.classList.toggle("ob-scanlines", scanOn);
    scan.setAttribute("aria-pressed", String(scanOn));
    scan.textContent = "Scanlines: " + (scanOn ? "on" : "off");
  }
  syncScan();
  scan.addEventListener("click", () => {
    scanOn = !scanOn;
    syncScan();
    try { localStorage.setItem("offbrand.scanlines", scanOn ? "on" : "off"); } catch (_) {}
  });
  // Simulated service effect on the equipment label, never on evidence or video.
  let resetTimer;
  degauss.addEventListener("click", () => {
    strip.classList.remove("ob-servicing");
    clearTimeout(resetTimer);
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      void strip.offsetWidth;
      strip.classList.add("ob-servicing");
      resetTimer = setTimeout(() => strip.classList.remove("ob-servicing"), 450);
    }
    signal.textContent = "ENGINEERING / Simulated degauss complete";
  });

  const calibration = el("details", "ob-calibration");
  calibration.id = "ob-calibration";
  const summary = el("summary", null, "Engineering test card");
  const card = el("div", "ob-test-card");
  card.append(el("strong", null, "CH 99 // OFF-BRAND"), el("span", null, "STATION IDENTIFICATION · TEST PATTERN"));
  const desc = el("p", null, "A fictional calibration card. This is not a specimen or a live channel. Your current broadcast continues unchanged.");
  calibration.append(summary, card, desc);
  strip.appendChild(calibration);
  calibrate.setAttribute("aria-expanded", "false");
  calibrate.setAttribute("aria-controls", calibration.id);
  function syncCalibration() { calibrate.setAttribute("aria-expanded", String(calibration.open)); }
  calibration.addEventListener("toggle", syncCalibration);
  calibrate.addEventListener("click", () => {
    calibration.open = !calibration.open;
    syncCalibration();
  });

  // Native modal handles Tab containment, Escape, and inert background. No
  // global shortcut interception and no dependency on a commercial state.
  const dialog = el("dialog", "ob-remote");
  const title = el("h2", null, "Remote guide");
  title.id = "ob-remote-title";
  dialog.setAttribute("aria-labelledby", title.id);
  const list = el("dl");
  for (const [key, meaning] of [
    ["← / →", "Tab to the broadcast screen, or click a blank part of the screen, then use the arrow keys."],
    ["Tab / Shift+Tab", "Move between available controls."],
    ["Enter / Space", "Activate focused buttons."],
    ["Escape", "Close this guide; with focus on the broadcast screen or its commercial controls, dismiss an active break."],
    ["Scanlines / Degauss", "Optional appearance controls. No effect on evidence ratings."],
    ["Station ID", "Reveal the fictional calibration card below the controls."]
  ]) list.append(el("dt", null, key), el("dd", null, meaning));
  const close = el("button", "ob-switch", "Close guide");
  close.type = "button";
  close.autofocus = true;
  dialog.append(title, list, close);
  document.body.appendChild(dialog);
  remote.setAttribute("aria-haspopup", "dialog");
  remote.addEventListener("click", () => {
    if (!dialog.open) dialog.showModal();
  });
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => remote.focus());

  const txtLink = byId("teletext-link");
  function syncTextLink() {
    if (!txtLink) return;
    const id = location.hash.slice(1);
    const query = /^urlscan-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id)
      ? "?channel=" + encodeURIComponent(id) : "";
    txtLink.href = "teletext.html" + query + "#100";
    const studio = byId("studio-guide-link"), originals = byId("originals-guide-link");
    if (studio) studio.href = "studio.html" + query + "#continuity";
    if (originals) originals.href = "teletext.html" + query + "#606";
  }
  syncTextLink();
  const program = byId("program");
  if (program) new MutationObserver(() => {
    syncTextLink();
    index = (index + 1) % notes.length;
    note.textContent = notes[index];
  }).observe(program, { childList: true });
})();
