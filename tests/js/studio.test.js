const test = require("node:test");
const assert = require("node:assert/strict");
const {ACTS,PROGRAMS,selectProgram,matchExcerpt} = require("../../site/studio.js");

test("all four curated excerpts require their own source ID and text", () => {
  assert.equal(ACTS.length,4);
  assert.equal(new Set(ACTS.map(a=>a.id)).size,4);
  for(const act of ACTS) assert.equal(matchExcerpt([{id:act.id,tells:["Before "+act.excerpt+" After"]}],act)?.id,act.id);
});
test("changed, missing or malformed review fails closed", () => {
  const act=ACTS[0];
  for(const rows of [[],[null],[{id:act.id,tells:["different"]}],[{id:act.id,tells:null}],[{id:"other",tells:[act.excerpt]}]])
    assert.equal(matchExcerpt(rows,act),null);
});
test("program names and fictional example addresses are explicit", () => {
  assert.equal(selectProgram("#props"),"props");
  assert.equal(selectProgram("#constructor"),"continuity");
  assert.equal(PROGRAMS.continuity.cards.length,4);
  for(const c of PROGRAMS.readings.cards) assert.match(c.quote,/^hxxps:\/\/[^/]+\[\.\](?:invalid|example)\//);
});
