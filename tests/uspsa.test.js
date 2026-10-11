const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { parseClassificationPage, isChallenge, isoDate } = require("../server/uspsa.js");
const { countedScores, classAverage } = require("../calc.js");

const page = parseClassificationPage(fs.readFileSync(path.join(__dirname, "fixtures/A161327.html"), "utf8"));

test("reads the member and each division's class from a uspsa.org classification page", () => {
  assert.deepStrictEqual(page.member, { number: "A161327", name: "Kory K", joined: "2024-07-26", expires: "Jul 28, 2027" });
  assert.strictEqual(Object.keys(page.divisions).length, 9);
  assert.deepStrictEqual(
    { class: page.divisions["carry-optics"].class, percent: page.divisions["carry-optics"].percent },
    { class: "B", percent: 62.8102 });
  assert.strictEqual(page.divisions["limited-10"].class, "U");
  assert.strictEqual(page.divisions["limited-optics"].percent, 67.845);
});

test("reads classifier scores and major matches", () => {
  const lo = page.divisions["limited-optics"].scores;
  assert.strictEqual(lo.length, 27);
  assert.deepStrictEqual(lo[0], { date: "2026-05-14", code: null, flag: "Y", percent: 76.6067, hf: null, entered: "2026-05-17",
    source: "Major Match", club: lo[0].club });
  assert.deepStrictEqual({ ...lo[1], club: undefined }, { date: "2026-04-26", code: "24-04", flag: "Y", percent: 59.2943, hf: 5.5841,
    entered: "2026-04-27", source: "Stage Score", club: undefined });
});

test("best 6 of the latest 8 counted scores matches the percentage USPSA has on file", () => {
  for (const id of ["carry-optics", "limited-optics"]) {
    const d = page.divisions[id];
    assert.strictEqual(classAverage(countedScores(d.scores).map((s) => s.p)).toFixed(4), d.percent.toFixed(4));
  }
});

test("counted scores: 110% cap, most recent override, zeros count, M flags dropped", () => {
  const got = countedScores([
    { date: "2026-08-01", code: "25-04", percent: 0, flag: "P" },
    { date: "2026-07-01", code: null, percent: 80, flag: "Y" },
    { date: "2026-06-01", code: "23-01", percent: 120, flag: "Y" },
    { date: "2026-05-01", code: "25-04", percent: 95, flag: "Y" },
    { date: "2026-04-01", code: "22-01", percent: 70, flag: "M" },
  ]);
  assert.deepStrictEqual(got.map((s) => [s.code, s.p]), [["25-04", 0], [null, 80], ["23-01", 110]]);
});

test("rows with no entry date and pages with no member", () => {
  const html = `<table><tr><th scope="row">Member Number:</th><td>B1</td></tr></table>
    <a data-division="Carry_Optics">x</a><table><tbody id="Carry_Optics-dropDown">
    <tr><td>Date</td><td>Number</td><td>Club</td><td>F</td><td>Percent</td><td>HF</td><td>Entered</td><td>Source</td></tr>
    <tr><td>8/19/26</td><td></td><td>Nats &amp; More</td><td>Y</td><td>75.6066</td><td>-</td><td>-</td><td>Major Match</td></tr>
    </tbody></table>`;
  const s = parseClassificationPage(html).divisions["carry-optics"].scores[0];
  assert.deepStrictEqual([s.club, s.entered, s.hf], ["Nats & More", null, null]);
  assert.strictEqual(parseClassificationPage("<html><body>No member</body></html>"), null);
  assert.strictEqual(isoDate("7/09/99"), "1999-07-09");
});

test("spots Cloudflare's bot check", () => {
  assert.ok(isChallenge(403, "<html><head><title>Just a moment...</title>"));
  assert.ok(!isChallenge(200, "<title>Classifier Lookup - USPSA.ORG</title>"));
});
