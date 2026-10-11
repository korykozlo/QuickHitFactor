// Reads a member's classification page from uspsa.org (uspsa.org/classification/<member number>).
// No dependencies: the page is plain server-rendered tables, so a few regexes do the job.

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

function text(html) {
  return html
    .replace(/<[^>]*>/g, "")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) =>
      e[0] === "#" ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : Number(e.slice(1)))
        : ENTITIES[e.toLowerCase()] ?? m)
    .replace(/\s+/g, " ")
    .trim();
}

// "Limited 10" / "Limited_Optics" -> the app's division ids ("limited-10", "limited-optics").
function divisionId(name) {
  return name.trim().toLowerCase().replace(/[\s_]+/g, "-");
}

// "5/14/26" -> "2026-05-14". Two-digit years from 80 up are the 1900s.
function isoDate(s) {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/.exec(s);
  if (!m) return null;
  const y = m[3].length === 4 ? m[3] : (Number(m[3]) >= 80 ? "19" : "20") + m[3];
  return `${y}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}`;
}

function number(s) {
  return /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : null;
}

function field(html, label) {
  const m = new RegExp(`<th[^>]*>\\s*${label}:?\\s*</th>\\s*<td[^>]*>([\\s\\S]*?)</td>`, "i").exec(html);
  return m ? text(m[1]) : null;
}

// Returns null when the page has no member on it (unknown number), otherwise:
// { member: { number, name, joined, expires },
//   divisions: { <id>: { name, class, percent, highPercent, scores: [
//     { date, code, club, flag, percent, hf, entered, source } ] } } }
// Scores keep the page's order (newest first). code is null for a major match, hf null when the page shows "-".
function parseClassificationPage(html) {
  const number_ = field(html, "Member Number");
  if (!number_) return null;
  const member = {
    number: number_,
    name: field(html, "Shooter Name"),
    joined: isoDate(field(html, "Joined USPSA") || ""),
    expires: field(html, "Membership Expiry Date"),
  };

  const divisions = {};
  const div = (name) => (divisions[divisionId(name)] ??= { name, class: null, percent: null, highPercent: null, scores: [] });

  const summary = /<th[^>]*>\s*Classifications\s*<\/th>([\s\S]*?)<\/table>/i.exec(html);
  if (summary) {
    const row = /<th[^>]*>([\s\S]*?)<\/th>\s*<td[^>]*>\s*Class:([\s\S]*?)<\/td>\s*<td[^>]*>\s*Pct:([\s\S]*?)<\/td>\s*<td[^>]*>\s*High Pct:([\s\S]*?)<\/td>/gi;
    for (const [, name, cls, pct, high] of summary[1].matchAll(row)) {
      const d = div(text(name));
      d.class = text(cls);
      d.percent = number(text(pct));
      d.highPercent = number(text(high));
    }
  }

  const tables = /data-division="([^"]+)"[\s\S]*?<tbody[^>]*>([\s\S]*?)<\/tbody>/gi;
  for (const [, key, body] of html.matchAll(tables)) {
    const d = divisions[divisionId(key)] ?? div(text(key).replace(/_/g, " "));
    for (const [, tr] of body.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const cells = [...tr.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/gi)].map((c) => text(c[1]));
      if (cells.length < 8 || cells[0] === "Date") continue;
      const [date, code, club, flag, percent, hf, entered, source] = cells;
      d.scores.push({
        date: isoDate(date), code: code || null, club, flag: flag || null,
        percent: number(percent), hf: number(hf), entered: isoDate(entered), source,
      });
    }
  }

  return { member, divisions };
}

// Cloudflare's "Just a moment..." page, which uspsa.org sends instead of the page to clients it doesn't trust.
function isChallenge(status, html) {
  return (status === 403 || status === 503) && /<title>\s*Just a moment/i.test(html);
}

module.exports = { parseClassificationPage, isChallenge, divisionId, isoDate };
