// QuickHitFactor server: serves the static app and GET /api/member/<number>, which reads the
// member's classification page from uspsa.org and returns it as JSON. No dependencies (Node 18+).
//
//   PORT            port to listen on (default 8000)
//   ALLOWED_ORIGIN  value for Access-Control-Allow-Origin, for a front end hosted elsewhere (default *)
//   USPSA_PAGES_DIR read <dir>/<NUMBER>.html instead of fetching, for pages saved from a browser
//   CACHE_MINUTES   how long a looked-up member is kept (default 15)
//   SCRAPE_FALLBACK set to 0 to skip the Playwright fallback when uspsa.org blocks a plain request

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { parseClassificationPage, isChallenge } = require("./uspsa.js");

const { execFile } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.env.PORT) || 8000;
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || "*";
const PAGES_DIR = process.env.USPSA_PAGES_DIR;
const CACHE_MS = (Number(process.env.CACHE_MINUTES) || 15) * 60 * 1000;
const SCRAPE_FALLBACK = process.env.SCRAPE_FALLBACK !== "0";
const USER_AGENT = "QuickHitFactor/1.0 (+https://github.com/korykozlo/QuickHitFactor)";

const pageUrl = (num) => `https://uspsa.org/classification/${encodeURIComponent(num)}`;

class LookupError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

function getPythonBin() {
  const candidates = [
    process.env.PYTHON_BIN,
    path.join(ROOT, ".venv", "bin", "python3"),
    path.join(ROOT, ".venv", "bin", "python"),
    path.join(ROOT, "venv", "bin", "python3"),
    path.join(ROOT, "venv", "bin", "python"),
    "python3",
    "python",
  ].filter(Boolean);

  for (const bin of candidates) {
    if (bin.includes(path.sep) && fs.existsSync(bin)) return bin;
  }
  return "python3";
}

function scrapeWithPlaywright(num) {
  return new Promise((resolve, reject) => {
    const pythonBin = getPythonBin();
    const script = path.join(ROOT, "tools", "scrape_uspsa.py");
    execFile(pythonBin, [script, num, "--dump-html"], {
      maxBuffer: 25 * 1024 * 1024,
      timeout: 60000,
    }, (err, stdout, stderr) => {
      if (err) {
        console.error("Playwright scraping error:", stderr || err.message);
        let msg = "Failed to scrape profile via Playwright.";
        if (stderr && stderr.includes("playwright is required")) {
          msg = "Playwright is not installed. Setup with: python3 -m venv .venv && .venv/bin/pip install playwright beautifulsoup4 && .venv/bin/playwright install chromium";
        } else if (stderr && stderr.includes("TimeoutError")) {
          msg = "Scraping timed out waiting for USPSA page to load.";
        } else if (stderr) {
          const lines = stderr.trim().split("\n");
          msg = lines[lines.length - 1] || msg;
        }
        return reject(new LookupError(502, "scrape_error", msg));
      }
      resolve(stdout);
    });
  });
}

const PAGE_CACHE_HOURS = Number(process.env.PAGE_CACHE_HOURS) || 24;
const PAGE_CACHE_MS = PAGE_CACHE_HOURS * 60 * 60 * 1000;

async function loadPage(num) {
  const dir = PAGES_DIR || path.join(ROOT, "data", "pages");
  let cachedFile = null;
  let cachedHtml = null;

  if (fs.existsSync(dir)) {
    const file = fs.readdirSync(dir).find((f) => f.toUpperCase() === `${num}.HTML`);
    if (file) {
      cachedFile = path.join(dir, file);
      cachedHtml = fs.readFileSync(cachedFile, "utf8");
      // Static test fixtures or custom PAGES_DIR do not expire
      if (PAGES_DIR) return cachedHtml;

      const stat = fs.statSync(cachedFile);
      const isFresh = (Date.now() - stat.mtimeMs) < PAGE_CACHE_MS;
      if (isFresh) return cachedHtml;
    }
    if (PAGES_DIR) throw new LookupError(404, "notfound", "Member not found.");
  }

  let html = null;
  let blocked = false;
  try {
    const res = await fetch(pageUrl(num), {
      headers: { "User-Agent": USER_AGENT, Accept: "text/html" },
      signal: AbortSignal.timeout(6000),
    });
    const text = await res.text();
    if (isChallenge(res.status, text)) {
      blocked = true;
    } else if (res.status === 404) {
      throw new LookupError(404, "notfound", "Member not found.");
    } else if (res.ok) {
      html = text;
    }
  } catch (e) {
    if (e instanceof LookupError) throw e;
    blocked = true;
  }

  // If simple HTTP fetch was blocked by Cloudflare, scrape using Playwright
  if (!html && blocked) {
    if (!SCRAPE_FALLBACK) {
      if (cachedHtml) return cachedHtml;
      throw new LookupError(502, "blocked", "uspsa.org blocked the request. Try again later.");
    }
    try {
      html = await scrapeWithPlaywright(num);
    } catch (e) {
      // If live scraping fails but an older cached copy exists, fall back to it
      if (cachedHtml) {
        console.warn(`Scrape failed for ${num}; serving stale cached file.`);
        return cachedHtml;
      }
      if (e instanceof LookupError) throw e;
      throw new LookupError(502, "blocked", "uspsa.org blocked the request and scraping failed.");
    }
  }

  if (!html) {
    if (cachedHtml) return cachedHtml;
    throw new LookupError(502, "unreachable", "Couldn't retrieve profile from uspsa.org.");
  }

  // Cache to data/pages/<NUM>.html for fast subsequent lookups
  if (!PAGES_DIR) {
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, `${num}.html`), html, "utf8");
    } catch {}
  }

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
  ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8" };
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
