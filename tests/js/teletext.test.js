const test = require("node:test");
const assert = require("node:assert/strict");
const { CODES, groups, rating, validId, pageCode } = require("../../site/teletext.js");
const id = "urlscan-00000000-0000-0000-0000-000000000001";
test("page numbers are stable, unknown numeric pages are explicit", () => {
  assert.equal(CODES.length, 9);
  assert.equal(pageCode("#310"), "310");
  assert.equal(pageCode("#999"), "999");
  assert.equal(pageCode("#javascript:alert(1)"), "100");
});
test("only valid specimen IDs become channel links", () => {
  assert.equal(validId(id), true);
  for (const x of [null, "../index", "javascript:alert(1)", id+"?bad"]) assert.equal(validId(x), false);
  const rows = [{id, aisle:"Banking"}, {id:"javascript:alert(1)", aisle:"Fake"}];
  assert.deepEqual(groups(rows), [["Banking", [rows[0]]]]);
});
test("structured evidence only; historic verdict text cannot confer confirmation", () => {
  assert.equal(rating({verdict:"Phishing"}), "Not yet rated");
  assert.equal(rating({evidence:{level:"suspected"}}), "Suspected (not confirmed)");
  assert.equal(rating({evidence:{level:"source-confirmed"}}), "Source-confirmed");
  assert.equal(rating({evidence:{level:"constructor"}}), "Not yet rated");
});
