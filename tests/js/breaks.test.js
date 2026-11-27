"use strict";
// Run with: node --test tests/js/*.test.js   (pytest also runs it: tests/test_commercials.py)
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const B = require(path.join(__dirname, "..", "..", "site", "breaks.js"));

function memoryBacking() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
}
function seq(...values) { let i = 0; return () => values[i++ % values.length]; }

const good = {
  commercials: [
    { id: "one", title: "One", runtime_seconds: 20, src: "commercials/one.mp4", poster: "commercials/one.jpg" },
    { id: "two", title: "Two", runtime_seconds: 28, src: "commercials/two.mp4" },
  ],
  bumpers: ["Paid for by absolutely nobody.", "  ", 7],
};

test("manifest keeps well-formed entries", () => {
  const m = B.validateManifest(good);
  assert.deepEqual(m.commercials.map((c) => c.id), ["one", "two"]);
  assert.equal(m.commercials[0].poster, "commercials/one.jpg");
  assert.equal(m.commercials[1].poster, "");
  assert.deepEqual(m.bumpers, ["Paid for by absolutely nobody."]);
});

test("manifest rejects unsafe or malformed media paths", () => {
  const bad = [
    "https://evil.example/ad.mp4", "//evil.example/ad.mp4", "commercials/../index.mp4",
    "commercials/Ad.mp4", "commercials/ad.mov", "commercials/ad.mp4?x=1", "/commercials/ad.mp4",
    "javascript:alert(1)", "commercials/sub/ad.mp4",
  ];
  for (const src of bad) {
    const m = B.validateManifest({ commercials: [{ id: "x", title: "X", runtime_seconds: 10, src }] });
    assert.equal(m.commercials.length, 0, src);
  }
  const posterBad = B.validateManifest({ commercials: [{ id: "x", title: "X", runtime_seconds: 10, src: "commercials/x.mp4", poster: "https://evil.example/p.jpg" }] });
  assert.equal(posterBad.commercials[0].poster, "");
});

test("manifest drops duplicates, disabled entries and bad runtimes", () => {
  const m = B.validateManifest({ commercials: [
    { id: "a", title: "A", runtime_seconds: 10, src: "commercials/a.mp4" },
    { id: "a", title: "A again", runtime_seconds: 10, src: "commercials/a2.mp4" },
    { id: "b", title: "B", runtime_seconds: 10, src: "commercials/b.mp4", enabled: false },
    { id: "c", title: "C", runtime_seconds: 0, src: "commercials/c.mp4" },
    { id: "d", title: "", runtime_seconds: 10, src: "commercials/d.mp4" },
  ] });
  assert.deepEqual(m.commercials.map((c) => c.id), ["a"]);
  assert.deepEqual(B.validateManifest(null), { commercials: [], bumpers: [] });
  assert.deepEqual(B.validateManifest({ commercials: "nope" }).commercials, []);
});

test("rotation plays every commercial once before any repeat", () => {
  const ids = ["a", "b", "c", "d"];
  const rot = B.createRotation(ids, B.safeStore(memoryBacking()));
  for (let cycle = 0; cycle < 5; cycle++) {
    const got = [rot.next(), rot.next(), rot.next(), rot.next()];
    assert.deepEqual([...got].sort(), ids, `cycle ${cycle}`);
  }
});

test("a new cycle never opens with the commercial that just played", () => {
  for (let trial = 0; trial < 200; trial++) {
    const rot = B.createRotation(["a", "b", "c"], B.safeStore(memoryBacking()));
    let last = null;
    for (let k = 0; k < 12; k++) {
      const id = rot.next();
      assert.notEqual(id, last);
      last = id;
    }
  }
});

test("rotation progress survives a reload and ignores stale ids", () => {
  const backing = memoryBacking();
  const first = B.createRotation(["a", "b", "c"], B.safeStore(backing), seq(0));
  const played = [first.next(), first.next()];
  backing.setItem(B.SEEN_KEY, JSON.stringify(played.concat(["removed-ad"])));
  const second = B.createRotation(["a", "b", "c"], B.safeStore(backing));
  const remaining = ["a", "b", "c"].filter((id) => !played.includes(id));
  assert.deepEqual([second.next()], remaining);
});

test("failed commercials leave the rotation", () => {
  const rot = B.createRotation(["a", "b"], B.safeStore(memoryBacking()));
  rot.markFailed("a");
  for (let k = 0; k < 6; k++) assert.equal(rot.next(), "b");
  rot.markFailed("b");
  assert.equal(rot.available(), false);
  assert.equal(rot.next(), null);
});

test("corrupt saved rotation state is ignored", () => {
  const backing = memoryBacking();
  backing.setItem(B.SEEN_KEY, "{not json");
  const rot = B.createRotation(["a"], B.safeStore(backing));
  assert.equal(rot.next(), "a");
});

test("breaks come due after 4 to 7 channel changes", () => {
  for (const r of [0, 0.25, 0.5, 0.99]) {
    const s = B.createScheduler(() => r);
    let n = 0;
    while (!s.tick()) n += 1;
    assert.ok(n + 1 >= 4 && n + 1 <= 7, `fired after ${n + 1}`);
    s.reset();
    assert.equal(s.state().count, 0);
  }
});

test("break preference defaults on and persists off", () => {
  const backing = memoryBacking();
  const store = B.safeStore(backing);
  assert.equal(B.loadEnabled(store), true);
  B.saveEnabled(store, false);
  assert.equal(B.loadEnabled(B.safeStore(backing)), false);
  B.saveEnabled(store, true);
  assert.equal(B.loadEnabled(B.safeStore(backing)), true);
});

test("storage that throws degrades to memory", () => {
  const hostile = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("full"); } };
  const store = B.safeStore(hostile);
  B.saveEnabled(store, false);
  assert.equal(B.loadEnabled(store), false);
  assert.equal(B.loadEnabled(B.safeStore(null)), true);
});

test("bumpers never repeat back to back", () => {
  const deck = B.createBumperDeck(["x", "y", "z"]);
  let last = "";
  for (let k = 0; k < 300; k++) { const b = deck.next(); assert.notEqual(b, last); last = b; }
  assert.equal(B.createBumperDeck(["only"]).next(), "only");
  assert.equal(B.createBumperDeck([]).next(), "");
});

test("runtimes and air times format like a TV guide", () => {
  assert.equal(B.formatRuntime(28), "0:28");
  assert.equal(B.formatRuntime(65), "1:05");
  assert.deepEqual(B.airTimes([{ runtime_seconds: 20 }, { runtime_seconds: 28 }, { runtime_seconds: 23 }]), ["2:00:00 AM", "2:00:20 AM", "2:00:48 AM"]);
  assert.deepEqual(B.airTimes([{ runtime_seconds: 5 }], 0), ["12:00:00 AM"]);
});

test("bumper deck cannot hang on a stuck random source", () => {
  for (const r of [0, 0.999999, 1]) {
    const deck = B.createBumperDeck(["x", "y", "z"], () => r);
    let last = "";
    for (let k = 0; k < 50; k++) { const b = deck.next(); assert.notEqual(b, last); assert.ok(b); last = b; }
  }
});
