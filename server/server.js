// QuickHitFactor server: serves the static app and GET /api/member/<number>, which reads the
// member's classification page from uspsa.org and returns it as JSON. No dependencies (Node 18+).
//
//   PORT            port to listen on (default 8000)
//   ALLOWED_ORIGIN  value for Access-Control-Allow-Origin, for a front end hosted elsewhere (default *)
//   USPSA_PAGES_DIR read <dir>/<NUMBER>.html instead of fetching, for pages saved from a browser
//   CACHE_MINUTES   how long a looked-up member is kept (default 15)

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { parseClassificationPage, isChallenge } = require("./uspsa.js");

const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.env.PORT) || 8000;
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || "*";
const PAGES_DIR = process.env.USPSA_PAGES_DIR;
const CACHE_MS = (Number(process.env.CACHE_MINUTES) || 15) * 60 * 1000;
const USER_AGENT = "QuickHitFactor/1.0 (+https://github.com/korykozlo/QuickHitFactor)";

const pageUrl = (num) => `https://uspsa.org/classification/${encodeURIComponent(num)}`;

class LookupError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

async function loadPage(num) {
  if (PAGES_DIR) {
    const file = fs.readdirSync(PAGES_DIR).find((f) => f.toUpperCase() === `${num}.HTML`);
    if (!file) throw new LookupError(404, "notfound", "Member not found.");
    return fs.readFileSync(path.join(PAGES_DIR, file), "utf8");
  }
  let res;
  try {
    res = await fetch(pageUrl(num), {
      headers: { "User-Agent": USER_AGENT, Accept: "text/html" },
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new LookupError(502, "unreachable", "Couldn't reach uspsa.org.");
  }
  const html = await res.text();
  if (isChallenge(res.status, html)) throw new LookupError(502, "blocked", "uspsa.org turned the request away with a bot check.");
  if (res.status === 404) throw new LookupError(404, "notfound", "Member not found.");
  if (!res.ok) throw new LookupError(502, "upstream", `uspsa.org answered ${res.status}.`);
  return html;
}

const cache = new Map(); // number -> { at, promise }

function lookup(num) {
  const hit = cache.get(num);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.promise;
  const promise = loadPage(num).then((html) => {
    const page = parseClassificationPage(html);
    if (!page) throw new LookupError(404, "notfound", "Member not found.");
    return { ...page, source: pageUrl(num), fetchedAt: new Date().toISOString() };
  });
  // Keep answers (found or not found), drop failures so the next request tries again.
  promise.catch((e) => { if (!(e instanceof LookupError && e.code === "notfound")) cache.delete(num); });
  cache.set(num, { at: Date.now(), promise });
  return promise;
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json",
  ".png": "image/png", ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8" };
const PUBLIC = ["index.html", "calc.js", "og-image.png", "data/", "diagrams/"];

function send(res, status, body, headers = {}) {
  res.writeHead(status, { "Access-Control-Allow-Origin": ALLOWED_ORIGIN, ...headers });
  res.end(body);
}

function sendJson(res, status, obj) {
  send(res, status, JSON.stringify(obj), { "Content-Type": "application/json", "Cache-Control": "no-store" });
}

function serveStatic(res, urlPath) {
  const rel = decodeURIComponent(urlPath).replace(/^\/+/, "") || "index.html";
  const file = path.resolve(ROOT, rel);
  if (!file.startsWith(ROOT + path.sep) || !PUBLIC.some((p) => (p.endsWith("/") ? rel.startsWith(p) : rel === p))) {
    return send(res, 404, "Not found");
  }
  fs.readFile(file, (err, data) => {
    if (err) return send(res, 404, "Not found");
    send(res, 200, data, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (req.method === "OPTIONS") return send(res, 204, "", { "Access-Control-Allow-Methods": "GET" });
  if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, "Method not allowed");

  const m = /^\/api\/member\/([^/]+)$/.exec(url.pathname);
  if (m) {
    const num = decodeURIComponent(m[1]).trim().toUpperCase();
    if (!/^[A-Z0-9]{2,12}$/.test(num)) return sendJson(res, 400, { error: "invalid", message: "That isn't a USPSA member number." });
    return lookup(num).then(
      (page) => sendJson(res, 200, page),
      (e) => e instanceof LookupError ? sendJson(res, e.status, { error: e.code, message: e.message })
        : (console.error(e), sendJson(res, 500, { error: "server", message: "Something went wrong." })),
    );
  }
  if (url.pathname.startsWith("/api/")) return sendJson(res, 404, { error: "notfound", message: "Unknown endpoint." });
  serveStatic(res, url.pathname);
});

if (require.main === module) {
  server.listen(PORT, () => console.log(`QuickHitFactor on http://localhost:${PORT}${PAGES_DIR ? ` (pages from ${PAGES_DIR})` : ""}`));
}

module.exports = { server, lookup };
