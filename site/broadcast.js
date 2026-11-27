"use strict";
const deck = document.querySelector("#aisle-grid");
const lineup = document.querySelector("#lineup");
const channelStatus = document.querySelector("#station-id");
const previous = document.querySelector("#prev");
const next = document.querySelector("#next");
let channels = [];
let selected = -1;
let preferred = "DANTE";

function tune(index, returnToScreen = false) {
  selected = index;
  channels.forEach((card, i) => {
    card.hidden = i !== index;
    lineup.children[i].setAttribute("aria-pressed", String(i === index));
  });
  const title = channels[index].querySelector("h2").textContent;
  preferred = title;
  channelStatus.textContent = "CH " + String(index + 1).padStart(2, "0") + " / " + title;
  if (returnToScreen) {
    next.focus({preventScroll: true});
    channelStatus.closest("nav").scrollIntoView({block: "start"});
  }
}

function rebuildGuide() {
  channels = Array.from(deck.querySelectorAll(".card"));
  lineup.replaceChildren();
  for (const [i, card] of channels.entries()) {
    const button = document.createElement("button");
    const number = document.createElement("span");
    number.textContent = String(i + 1).padStart(2, "0");
    button.append(number, card.querySelector("h2").textContent);
    button.addEventListener("click", () => tune(i, true));
    lineup.append(button);
  }
  previous.disabled = next.disabled = channels.length < 2;
  if (channels.length) tune(Math.max(0, channels.findIndex(card => card.querySelector("h2").textContent === preferred)));
  else channelStatus.textContent = "No matching channels";
}
function stepChannel(delta) {
  if (channels.length > 1) tune((selected + delta + channels.length) % channels.length);
}
previous.addEventListener("click", () => stepChannel(-1));
next.addEventListener("click", () => stepChannel(1));
new MutationObserver(rebuildGuide).observe(deck, {childList: true});
rebuildGuide();
