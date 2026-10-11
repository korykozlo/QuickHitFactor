"""Python development server for QuickHitFactor.

Serves static app files and provides GET /api/member/<number>, scraping
member profiles with Playwright when needed.

Usage:
  python3 server/server.py [port]
"""

import asyncio
import json
import mimetypes
import os
import re
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

# Ensure tools/ is on path to import scrape_uspsa
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

try:
    from scrape_uspsa import parse_data, scrape_uspsa_profile
except ImportError:
    parse_data = None
    scrape_uspsa_profile = None

PORT = int(os.environ.get("PORT", 8000))
PAGES_DIR = os.environ.get("USPSA_PAGES_DIR") or os.path.join(ROOT, "data", "pages")
CACHE: dict = {}


def get_member_page(num: str) -> str:
    """Retrieve raw HTML for member number from cache or Playwright."""
    os.makedirs(PAGES_DIR, exist_ok=True)
    cache_file = os.path.join(PAGES_DIR, f"{num.upper()}.html")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return f.read()

    if scrape_uspsa_profile is None:
        raise RuntimeError("Playwright scraper module could not be imported.")

    print(f"Scraping USPSA profile for {num} using Playwright...")
    html = asyncio.run(scrape_uspsa_profile(num, headless=False))
    if html:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass
    return html


class QuickHitFactorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # API endpoint: /api/member/<number>
        m = re.match(r"^/api/member/([^/]+)$", path, re.IGNORECASE)
        if m:
            num = m.group(1).strip().upper()
            if not re.match(r"^[A-Z0-9]{2,12}$", num):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid", "message": "That isn't a USPSA member number."})
                return

            if num in CACHE:
                self._send_json(HTTPStatus.OK, CACHE[num])
                return

            try:
                html = get_member_page(num)
                parsed_data = parse_data(html)
                if not parsed_data.get("success") or not parsed_data.get("member", {}).get("number"):
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "notfound", "message": "Member not found."})
                    return

                response_data = {
                    **parsed_data,
                    "source": f"https://uspsa.org/classification/{num}",
                }
                CACHE[num] = response_data
                self._send_json(HTTPStatus.OK, response_data)
            except Exception as e:
                print(f"Error looking up {num}: {e}", file=sys.stderr)
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": "scrape_failed", "message": f"Scraping failed: {e}"})
            return

        # Serve static files (fallback to index.html for root)
        if path == "/" or not path:
            self.path = "/index.html"
        super().do_GET()

    def _send_json(self, status: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = ThreadingHTTPServer(("0.0.0.0", port), QuickHitFactorHandler)
    print(f"QuickHitFactor Python server running at http://localhost:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")


if __name__ == "__main__":
    main()

