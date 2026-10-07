// Hit factor math for USPSA classifiers. Works in the browser (window.QHF) and in Node.
(function (root) {
  // Points per hit. Steel always scores as an A.
  const POINTS = {
    minor: { A: 5, C: 3, D: 1 },
    major: { A: 5, C: 4, D: 2 },
  };
  const MISS_PENALTY = 10;

  // Minimum hit factor to reach a classification percentage.
  function minHitFactor(hhf, percent) {
    return (hhf * percent) / 100;
  }

  // Slowest time (seconds) that still reaches minHF with this many points.
  // Rounded down to the timer's 0.01 s so the time shown always qualifies.
  function maxTime(points, minHF) {
    if (points <= 0 || minHF <= 0) return null;
    return Math.floor((points / minHF) * 100 + 1e-9) / 100;
  }

  // Every way to split the stage's scoring hits into A/C/D/miss.
  // hits: total scoring hits (points / 5); steel: steel targets (A or miss only).
  function combinations(hits, steel, powerFactor) {
    const v = POINTS[powerFactor] || POINTS.minor;
    const paper = hits - steel;
    const rows = [];
    for (let a = hits; a >= 0; a--) {
      for (let c = 0; c <= Math.min(paper, hits - a); c++) {
        for (let d = 0; d <= Math.min(paper - c, hits - a - c); d++) {
          const m = hits - a - c - d;
          const points = a * v.A + c * v.C + d * v.D - m * MISS_PENALTY;
          if (points > 0) rows.push({ a, c, d, m, points });
        }
      }
    }
    rows.sort((x, y) => y.points - x.points || x.m - y.m || y.a - x.a);
    return rows;
  }

  const api = { POINTS, MISS_PENALTY, minHitFactor, maxTime, combinations };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.QHF = api;
})(typeof window !== "undefined" ? window : globalThis);
