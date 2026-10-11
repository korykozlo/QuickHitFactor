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

  // Classification: best 6 of the latest 8 classifier percentages in a division.
  const CLASSES = [["GM", 95], ["M", 85], ["A", 75], ["B", 60], ["C", 40], ["D", 0]];
  const WINDOW = 8;
  const BEST = 6;

  function classFor(percent) {
    return CLASSES.find(([, min]) => percent >= min)[0];
  }

  // The class above this one, or null for GM.
  function nextClass(cls) {
    const i = CLASSES.findIndex(([id]) => id === cls);
    return i > 0 ? { id: CLASSES[i - 1][0], min: CLASSES[i - 1][1] } : null;
  }

  // Average of the best 6 of the latest 8 (percents are newest first). null when unclassed.
  function classAverage(percents) {
    const best = percents.slice(0, WINDOW).sort((a, b) => b - a).slice(0, BEST);
    return best.length < BEST ? null : best.reduce((t, p) => t + p, 0) / BEST;
  }

  // Lowest percentage on the next classifier that lifts the average to target.
  // The new score becomes the newest, so only the latest 7 existing scores stay in the window.
  // Returns 0 when any score does it, null when one more score can't make 6.
  function neededPercent(percents, target) {
    const others = percents.slice(0, WINDOW - 1).sort((a, b) => b - a);
    if (others.length < BEST - 1) return null;
    if (others.length >= BEST && classAverage(others) >= target) return 0;
    const top = others.slice(0, BEST - 1).reduce((t, p) => t + p, 0);
    return Math.max(0, BEST * target - top);
  }

  const api = { POINTS, MISS_PENALTY, minHitFactor, maxTime, combinations, CLASSES, classFor, nextClass, classAverage, neededPercent };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.QHF = api;
})(typeof window !== "undefined" ? window : globalThis);
