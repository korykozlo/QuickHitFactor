const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

process.env.USPSA_PAGES_DIR = path.join(__dirname, "fixtures");
const { server } = require("../server/server.js");

test("server answers member lookups and serves the app", async (t) => {
  await new Promise((r) => server.listen(0, r));
  t.after(() => server.close());
  const base = `http://localhost:${server.address().port}`;

  const ok = await fetch(`${base}/api/member/a161327`);
  assert.strictEqual(ok.status, 200);
  assert.strictEqual(ok.headers.get("access-control-allow-origin"), "*");
  const body = await ok.json();
  assert.strictEqual(body.member.name, "Kory K");
  assert.strictEqual(body.divisions["carry-optics"].class, "B");
  assert.strictEqual(body.source, "https://uspsa.org/classification/A161327");

  assert.strictEqual((await fetch(`${base}/api/member/A999999`)).status, 404);
  assert.strictEqual((await fetch(`${base}/api/member/no%20way!`)).status, 400);
  assert.strictEqual((await fetch(`${base}/`)).status, 200);
  assert.strictEqual((await fetch(`${base}/data/classifiers.json`)).status, 200);
  assert.strictEqual((await fetch(`${base}/server/server.js`)).status, 404);
  assert.strictEqual((await fetch(`${base}/%2e%2e/etc/passwd`)).status, 404);
});
