const test = require("node:test");
const assert = require("node:assert/strict");
const { addressAnatomy } = require("../../site/enhancements.js");

test("full host, including multipart suffixes and hosted tenants; never guesses domain boundary", () => {
  for (const host of ["example[.]co[.]uk", "bank[.]example[.]com[.]br", "tenant[.]github[.]io",
                      "att-mail-verify[.]square[.]site", "upgov[.]net"]) {
    const a = addressAnatomy("hxxps://" + host + "/login");
    assert.equal(a.host, host);
    assert.equal(a.path, "/login");
    assert.equal(a.ip, false);
    assert.equal(a.registrable, undefined);
  }
});
test("IP literals, explicit default ports, user information and optional components", () => {
  const a = addressAnatomy("hxxps://user:secret@192[.]0[.]2[.]1:443/a?x=1#b");
  assert.deepEqual(a, {scheme:"hxxps",host:"192[.]0[.]2[.]1",ip:true,port:"443",userinfo:true,path:"/a",query:true,fragment:true});
  assert.equal(addressAnatomy("hxxp://[2001:db8::1]:8080/").host,"[2001[:]db8[:][:]1]");
  assert.equal(addressAnatomy("hxxps://例え[.]test/").host,"xn--r8jz45g[.]test");
});
test("rejects unsupported schemes, whitespace, backslashes, invalid ports and missing hosts", () => {
  for (const v of [null,"", "javascript:alert(1)", "hxxps:///abc", "hxxps://x[.]test:65536/",
                    "hxxps://a b.test/", "hxxps://a.test\\b", "Not recorded in public scan"]) {
    assert.equal(addressAnatomy(v),null,v);
  }
});
test("query-only and fragment-only paths keep their meaning without repeating values", () => {
  assert.equal(addressAnatomy("hxxps://example[.]test?q=x").query,true);
  assert.equal(addressAnatomy("hxxps://example[.]test#?q=x").query,false);
  assert.equal(addressAnatomy("hxxps://example[.]test#?q=x").fragment,true);
});
