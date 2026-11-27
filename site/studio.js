/* Studio B: on-demand text programming. Only existing published evidence is quoted. */
"use strict";
const ACTS = [
  { title:"ACT I / THE COAT", id:"urlscan-01a2129b-243d-7383-b7cb-4f43dd69e5de",
    excerpt:"a User ID box, a password box, and 'Powered by Square' at the bottom.",
    narration:"A borrowed jacket does not tell you who is wearing it. Branding and a familiar form are not proof of ownership." },
  { title:"ACT II / THE CLOCK", id:"urlscan-01a1a3ce-c1c4-7434-a009-89fb985abac0",
    excerpt:"'No dejes que tus puntos caduquen.'",
    narration:"The published review describes an appeal to expiring rewards. Urgency is a reason to slow down and check the request independently, not proof by itself." },
  { title:"ACT III / THE ENVELOPE", id:"urlscan-01a1f8dd-b83d-7541-b503-42125f30510e",
    excerpt:"upgov[.]net, a domain urlscan lists as ten years old, with the page buried at /images/z1dpeth/-/louwhan1/pages/login.php.",
    narration:"Read the full hostname and the path separately. A familiar-looking path or domain age does not establish affiliation." },
  { title:"ACT IV / THE LEDGER", id:"urlscan-01a2121d-6fea-76ca-88bd-5e0ef22f925e",
    excerpt:"The capture stops at 'What you need to register', so the form itself isn't in the record.",
    narration:"A documentary stops where the footage stops. An archived page does not establish what an unseen form collects or who operates it." }
];
const CONTINUITY = [
  {title:"INTERVAL SIGNAL", quote:"You are watching Off-Brand. The studio is slightly cold.", memo:"FICTIONAL ANNOUNCER / Read flatly. Do not smile during the chime.", tones:[440,329.63,277.18]},
  {title:"MARGARET'S MEMO", quote:"Margaret in Tape Control says a nervous-looking font is not evidence.", memo:"FICTIONAL STAFF NOTE / A redirect alone does not establish whether a link is benign or malicious.", tones:[587.33,440]},
  {title:"TECHNICAL DIFFICULTIES", quote:"We regret to announce that the archive is not a time machine.", memo:"FICTIONAL ENGINEERING SLATE / An unavailable capture is not proof that a page is safe.", tones:[330,330]},
  {title:"CARRIER REST", quote:"That is the end of tonight's scheduled curiosities. Get some sleep.", memo:"FICTIONAL SIGN-OFF / On-demand archive remains available.", tones:[329.63,220]}
];
const READINGS = [
  {title:"CARD 01 / PARCEL NOTICE", quote:"hxxps://parcel-redelivery-support[.]tiny-shed-hosting[.]invalid/fee", memo:"A familiar word at the front of a hostname does not prove who operates it. Read the entire hostname."},
  {title:"CARD 02 / MAILBOX ALERT", quote:"hxxps://webmail[.]corp-login[.]free-pages-node[.]invalid/session", memo:"Putting 'webmail' at the front of an address is like taping a badge to a folding chair. It may be legitimate or misleading; check independently."},
  {title:"CARD 03 / LOOKALIKE HOST", quote:"hxxps://verify-urgent-notice[.]invalid/auth/step2", memo:"A name and a path are not proof of affiliation. Do not infer ownership from the last two labels; public and private suffix rules differ."},
  {title:"CARD 04 / THE BORING OPTION", quote:"hxxps://your-own-bookmark[.]example/", memo:"Use a trusted bookmark, official app or independently obtained address. These are reserved fictional examples, not collected specimens."}
];
const PROGRAMS = {
  continuity:{title:"Studio B Continuity Booth",type:"FICTIONAL STATION CONTINUITY",cards:CONTINUITY},
  props:{title:"The Props Department",type:"PUBLISHED REVIEW EXCERPTS · EPISODE 01",cards:ACTS},
  readings:{title:"The Hostname Readings",type:"FICTIONAL EDUCATIONAL EXAMPLES",cards:READINGS}
};
function selectProgram(hash) {
  const key = String(hash).replace(/^#/,"");
  return Object.prototype.hasOwnProperty.call(PROGRAMS,key) ? key : "continuity";
}
function matchExcerpt(items, act) {
  return items.find(item => item && item.id === act.id && Array.isArray(item.tells)
    && item.tells.some(t => typeof t === "string" && t.includes(act.excerpt))) || null;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { ACTS, PROGRAMS, selectProgram, matchExcerpt };
} else {
  const $ = id => document.getElementById(id);
  const release = new URL(document.currentScript.src).searchParams.get("v");
  const channel=new URLSearchParams(location.search).get("channel");
  if (channel && /^urlscan-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(channel)) {
    $("program-guide").href="teletext.html?channel="+encodeURIComponent(channel)+"#412";
    $("return-broadcast").href="index.html#"+channel;
  }
  let key = selectProgram(location.hash), index = 0, items = null, failed = false, timer = null;
  let audio = null, cueToken = 0, cueTimer = null;
  function el(tag,text,cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function stopCue() {
    cueToken++;
    clearTimeout(cueTimer); cueTimer = null;
    const prior = audio; audio = null;
    if (prior && prior.state !== "closed") prior.close().catch(() => {});
    $("cue").setAttribute("aria-disabled","false");
  }
  function stopPlayback() {
    clearInterval(timer); timer = null;
    $("play").setAttribute("aria-pressed","false");
    $("play").textContent = "Play episode";
  }
  function render(focus = false) {
    const p = PROGRAMS[key], card = p.cards[index];
    $("stage").dataset.program = key;
    $("studio-title").textContent = p.title;
    $("type").textContent = p.type;
    $("reel").textContent = "REEL " + String(index+1).padStart(2,"0") + " / " + String(p.cards.length).padStart(2,"0");
    document.title = "OFF-BRAND // " + p.title;
    for (const link of document.querySelectorAll(".lineup a")) {
      if (link.getAttribute("href") === "#" + key) link.setAttribute("aria-current","page");
      else link.removeAttribute("aria-current");
    }
    const body = $("program-card"), source = $("source");
    body.replaceChildren(el("h2",card.title));
    source.replaceChildren();
    if (key === "props") {
      const item = items && matchExcerpt(items,card);
      if (item) {
        body.append(el("p","“" + card.excerpt + "”","quote"),el("p",card.narration,"memo"));
        const a = el("a","Read original review and Evidence Locker");
        a.href = "index.html#" + card.id;
        source.append(el("p","Published editorial excerpt · " + (item.knockoff_label || "Review") + " · not independently re-verified for this episode."),a);
      } else {
        body.append(el("p",!items && !failed ? "Loading the public review archive." : "Excerpt unavailable: its current source could not be matched. No substitute finding has been supplied.","memo"));
      }
    } else {
      body.append(el("p",card.quote,"quote"),el("p",card.memo,"memo"));
      source.append(el("p",key === "continuity" ? "Station fiction; not an actual incident or broadcast schedule." : "Reserved example addresses · no live target, no collected specimen."));
    }
    $("previous").setAttribute("aria-disabled",String(index===0));
    $("next").setAttribute("aria-disabled",String(index===p.cards.length-1));
    $("play").disabled = key === "props" && !items;
    if (focus) $("studio-title").focus();
  }
  function step(delta) {
    stopCue();
    index = Math.max(0,Math.min(PROGRAMS[key].cards.length-1,index+delta));
    render();
  }
  $("previous").addEventListener("click",() => { if (index===0) return; stopPlayback(); step(-1); $("status").textContent="Manual viewing"; });
  $("next").addEventListener("click",() => { if (index===PROGRAMS[key].cards.length-1) return; stopPlayback(); step(1); $("status").textContent="Manual viewing"; });
  $("play").addEventListener("click",() => {
    if (timer) { stopPlayback(); $("status").textContent="Paused"; return; }
    if (index === PROGRAMS[key].cards.length-1) { index=0; render(); }
    $("play").setAttribute("aria-pressed","true");
    $("play").textContent="Pause episode";
    $("status").textContent="Playing · silent card advance";
    timer=setInterval(() => {
      if (index === PROGRAMS[key].cards.length-1) {
        stopPlayback(); $("status").textContent="End of program";
      } else step(1);
    },18000);
  });
  $("cue").addEventListener("click",async () => {
    if ($("cue").getAttribute("aria-disabled")==="true") return;
    stopCue();
    const token=cueToken, Ctx=window.AudioContext || window.webkitAudioContext;
    if (!Ctx) { $("status").textContent="Audio unavailable in this browser"; return; }
    $("cue").setAttribute("aria-disabled","true");
    try {
      audio=new Ctx();
      const ctx=audio;
      cueTimer=setTimeout(() => { if (token===cueToken) stopCue(); },1500);
      await ctx.resume();
      if (token!==cueToken || document.hidden) return;
      const notes=PROGRAMS[key].cards[index].tones || [440,329.63,277.18];
      const start=ctx.currentTime;
      notes.forEach((freq,i) => {
        const t=start+i*.22, osc=ctx.createOscillator(), gain=ctx.createGain();
        osc.type="triangle"; osc.frequency.value=freq;
        gain.gain.setValueAtTime(.0001,t);
        gain.gain.exponentialRampToValueAtTime(.035,t+.02);
        gain.gain.exponentialRampToValueAtTime(.0001,t+.18);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(t); osc.stop(t+.2);
      });
      clearTimeout(cueTimer);
      cueTimer=setTimeout(() => { if (token===cueToken) stopCue(); },1000);
    } catch (_) {
      if (token===cueToken) { stopCue(); $("status").textContent="Audio cue unavailable"; }
    }
  });
  document.querySelector(".skip").addEventListener("click",e => { e.preventDefault(); $("studio-title").focus(); });
  window.addEventListener("hashchange",() => {
    stopPlayback(); stopCue(); key=selectProgram(location.hash); index=0;
    $("status").textContent=""; render(true);
  });
  document.addEventListener("visibilitychange",() => {
    if (document.hidden) { stopPlayback(); stopCue(); $("status").textContent="Paused"; }
  });
  window.addEventListener("pagehide",() => { stopPlayback(); stopCue(); });
  render();
  fetch("data/reviews.json" + (release ? "?v="+encodeURIComponent(release) : ""),{cache:"no-cache"})
    .then(r => { if (!r.ok) throw Error("Unavailable"); return r.json(); })
    .then(d => { if (!Array.isArray(d.items)) throw Error("Malformed"); items=d.items; })
    .catch(() => { failed=true; })
    .finally(() => { if(key==="props") render(); });
}
