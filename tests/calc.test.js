const test = require("node:test");
const assert = require("node:assert");
const { minHitFactor, maxTime, combinations } = require("../calc.js");

test("min hit factor is HHF times the class percentage", () => {
  assert.strictEqual(minHitFactor(12.1268, 95).toFixed(4), "11.5205");
  assert.strictEqual(minHitFactor(10, 40), 4);
});

test("max time rounds down so the time always qualifies", () => {
  // El Presidente, Open, GM: 60 points / 11.52046 = 5.2081 s
  const t = maxTime(60, minHitFactor(12.1268, 95));
  assert.strictEqual(t, 5.2);
  assert.ok(60 / t >= minHitFactor(12.1268, 95));
  assert.strictEqual(maxTime(0, 5), null);
});

test("combinations cover every A/C/D/miss split with positive points", () => {
  const rows = combinations(2, 0, "minor");
  // 2 hits over 4 outcomes = 10 splits; drop the ones at or below zero points
  assert.deepStrictEqual(rows[0], { a: 2, c: 0, d: 0, m: 0, points: 10 });
  assert.ok(rows.every((r) => r.a + r.c + r.d + r.m === 2 && r.points > 0));
  assert.strictEqual(rows.length, 6); // AA AC AD CC CD DD; AM = -5 and worse are dropped
});

test("major scores C and D higher", () => {
  const minor = combinations(1, 0, "minor").map((r) => r.points);
  const major = combinations(1, 0, "major").map((r) => r.points);
  assert.deepStrictEqual(minor, [5, 3, 1]);
  assert.deepStrictEqual(major, [5, 4, 2]);
});

test("steel can only be an A or a miss", () => {
  // 3 hits, all steel: only A/miss splits
  const rows = combinations(3, 3, "minor");
  assert.ok(rows.every((r) => r.c === 0 && r.d === 0));
  // 1 paper + 1 steel: never two C or D hits
  assert.ok(combinations(2, 1, "minor").every((r) => r.c + r.d <= 1));
});
