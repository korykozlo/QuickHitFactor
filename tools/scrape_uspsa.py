"""Scrape and parse USPSA member classification profiles using Playwright and BeautifulSoup.

Features:
  - Scrapes member classification profiles from uspsa.org/classification/<member>
  - Headed or stealth Playwright execution to navigate Cloudflare protection
  - Extracts shooter info, RO certification, classification summary, and match history
  - Calculates the needed hit factor, score percentage, and combinations/max times
    to reach the next class in any division (e.g. B -> A; GM has no class above).

Usage:
  python tools/scrape_uspsa.py A161327
  python tools/scrape_uspsa.py A161327 --division carry-optics
  python tools/scrape_uspsa.py --file tests/fixtures/A161327.html --division carry-optics
  python tools/scrape_uspsa.py A161327 --dump-html
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    async_playwright = None
    PlaywrightTimeoutError = Exception


# Classification thresholds (USPSA)
CLASSES: List[Tuple[str, float]] = [
    ("GM", 95.0),
    ("M", 85.0),
    ("A", 75.0),
    ("B", 60.0),
    ("C", 40.0),
    ("D", 0.0),
]
WINDOW = 8
BEST = 6
MAX_PERCENT = 110.0

POINTS = {
    "minor": {"A": 5, "C": 3, "D": 1},
    "major": {"A": 5, "C": 4, "D": 2},
}
MISS_PENALTY = 10


def division_id(name: str) -> str:
    """Normalize division name to kebab-case ID (e.g. 'Carry Optics' -> 'carry-optics')."""
    return re.sub(r"[\s_]+", "-", name.strip().lower())


def _parse_float(val: Optional[str]) -> Optional[float]:
    """Parse string to float, returning None if empty or dash ('-')."""
    if not val or val.strip() in ("-", ""):
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


def _parse_iso_date(val: Optional[str]) -> Optional[str]:
    """Convert USPSA date formats (e.g. '5/14/26' or '7/09/99') to ISO 'YYYY-MM-DD'."""
    if not val or val.strip() in ("-", ""):
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$", val.strip())
    if not m:
        return None
    month, day, year = m.groups()
    if len(year) == 2:
        y = int(year)
        year = f"19{y:02d}" if y >= 80 else f"20{y:02d}"
    return f"{year}-{int(month):02d}-{int(day):02d}"


# --- Classification Math (mirrors calc.js) ---

def next_class(cls: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the class above cls, or None if GM (no class above) or unclassified."""
    if not cls:
        return None
    for i, (name, min_pct) in enumerate(CLASSES):
        if name.upper() == cls.upper():
            if i > 0:
                return {"id": CLASSES[i - 1][0], "min": CLASSES[i - 1][1]}
            return None  # GM has no class above
    return None


def class_for(percent: float) -> str:
    """Return the class for a given average percentage."""
    for name, min_pct in CLASSES:
        if percent >= min_pct:
            return name
    return "D"


def counted_scores(scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter and sort scores that count toward classification.

    Rules:
      - Drop flag 'M' (matches/scores not counted or overridden)
      - Each score capped at MAX_PERCENT (110%)
      - Later attempt on same classifier code replaces earlier attempt
      - Higher percent on same date considered more recent
      - Sorted newest first
    """
    kept = [
        s for s in scores
        if s.get("flag") != "M" and s.get("date") and isinstance(s.get("percent"), (int, float)) and s["percent"] >= 0
    ]
    latest: Dict[str, str] = {}
    for s in kept:
        code = s.get("classifier") or s.get("code")
        date = s.get("iso_date") or s.get("date")
        if code and (code not in latest or date > latest[code]):
            latest[code] = date

    valid = []
    for s in kept:
        code = s.get("classifier") or s.get("code")
        date = s.get("iso_date") or s.get("date")
        if not code or date == latest[code]:
            p = min(MAX_PERCENT, float(s["percent"]))
            valid.append({
                "date": date,
                "code": code,
                "p": p,
                "raw": s,
            })

    # Sort newest first, then higher percent
    valid.sort(key=lambda x: (x["date"], x["p"]), reverse=True)
    return valid


def class_average(percents: List[float]) -> Optional[float]:
    """Average of the best 6 of the latest 8 scores."""
    if len(percents) < BEST:
        return None
    window = percents[:WINDOW]
    top6 = sorted(window, reverse=True)[:BEST]
    return sum(top6) / BEST


def needed_percent(existing_percents: List[float], target_pct: float) -> Optional[float]:
    """Lowest percentage on the next classifier that lifts rolling average to target.

    The new score becomes the newest score, pushing the 8th score out of the window.
    So only the latest 7 existing scores remain in the window.
    Returns:
      - 0.0 if any score achieves it (already above target once oldest drops)
      - float required percentage
      - None if not enough scores to form 6 scores
    """
    others = sorted(existing_percents[:WINDOW - 1], reverse=True)
    if len(others) < BEST - 1:
        return None
    if len(others) >= BEST and class_average(others) is not None and class_average(others) >= target_pct:
        return 0.0
    top = sum(others[:BEST - 1])
    return max(0.0, BEST * target_pct - top)


def min_hit_factor(hhf: float, percent: float) -> float:
    """Minimum hit factor to reach a classification percentage."""
    return (hhf * percent) / 100.0


def max_time(points: int, min_hf: float) -> Optional[float]:
    """Slowest time in seconds that still achieves min_hf with given points.

    Rounded down to 0.01 s so the displayed time qualifies.
    """
    if points <= 0 or min_hf <= 0:
        return None
    return int((points / min_hf) * 100 + 1e-9) / 100.0


def hit_combinations(hits: int, steel: int = 0, power_factor: str = "minor") -> List[Dict[str, Any]]:
    """Every way to split the stage's scoring hits into A/C/D/miss with positive points."""
    v = POINTS.get(power_factor, POINTS["minor"])
    paper = hits - steel
    rows = []
    for a in range(hits, -1, -1):
        for c in range(0, min(paper, hits - a) + 1):
            for d in range(0, min(paper - c, hits - a - c) + 1):
                m = hits - a - c - d
                points = a * v["A"] + c * v["C"] + d * v["D"] - m * MISS_PENALTY
                if points > 0:
                    rows.append({"a": a, "c": c, "d": d, "m": m, "points": points})
    rows.sort(key=lambda r: (r["points"], -r["m"], r["a"]), reverse=True)
    return rows


def calculate_next_class_target(
    parsed_data: Dict[str, Any],
    division_key: str,
    hhf: Optional[float] = None,
    rounds: Optional[int] = None,
    steel: int = 0,
    power_factor: str = "minor",
    classifier_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate the values needed to reach the next class for a member and division.

    Args:
        parsed_data: Dict returned by parse_data(html)
        division_key: Division name or ID (e.g. 'Carry Optics' or 'carry-optics')
        hhf: Optional high hit factor of a stage
        rounds: Optional total scoring hits of the stage
        steel: Number of steel targets on the stage
        power_factor: 'minor' or 'major'
        classifier_code: Optional code of the classifier being shot (to exclude earlier attempt)

    Returns:
        Dict with current class, next class, needed percent, needed HF, and combos/times.
    """
    div_id = division_id(division_key)
    divisions = parsed_data.get("divisions", {})
    div_data = divisions.get(div_id)

    if not div_data:
        # Check match_history
        match_hist = parsed_data.get("match_history", {})
        for name, scores in match_hist.items():
            if division_id(name) == div_id:
                div_data = {
                    "name": name,
                    "class": parsed_data.get("classifications", {}).get(name, {}).get("class", "U"),
                    "percent": parsed_data.get("classifications", {}).get(name, {}).get("percent", 0.0),
                    "scores": scores,
                }
                break

    if not div_data:
        return {
            "status": "error",
            "message": f"No data found for division '{division_key}'.",
        }

    raw_scores = div_data.get("scores", [])
    counted = counted_scores(raw_scores)
    percents = [s["p"] for s in counted]

    current_cls = div_data.get("class")
    if current_cls not in [k for k, _ in CLASSES]:
        current_cls = class_for(class_average(percents) or 0.0) if len(percents) >= 5 else "U"

    member_name = parsed_data.get("member", {}).get("name") or parsed_data.get("shooter", {}).get("name", "Member")
    member_num = parsed_data.get("member", {}).get("number") or parsed_data.get("shooter", {}).get("member_number", "")

    # GM Check: there is no class above GM
    if current_cls == "GM":
        return {
            "status": "gm",
            "member_name": member_name,
            "member_number": member_num,
            "division": div_data.get("name", division_key),
            "current_class": "GM",
            "current_percent": div_data.get("percent"),
            "next_class": None,
            "message": f"{member_name} is GM in {div_data.get('name', division_key)}. There is no class above GM.",
        }

    if current_cls == "U" and len(percents) < 5:
        return {
            "status": "unclassed",
            "member_name": member_name,
            "member_number": member_num,
            "division": div_data.get("name", division_key),
            "current_class": "U",
            "scores_count": len(percents),
            "message": f"{member_name} is unclassed with {len(percents)} score(s). Needs 5 scores for an initial class.",
        }

    target = next_class(current_cls)
    if not target:
        return {
            "status": "gm",
            "member_name": member_name,
            "member_number": member_num,
            "division": div_data.get("name", division_key),
            "current_class": current_cls,
            "next_class": None,
            "message": f"No class above {current_cls}.",
        }

    # Exclude earlier attempt of same classifier if specified
    filtered_percents = [s["p"] for s in counted if not (classifier_code and s.get("code") == classifier_code)]
    needed_pct = needed_percent(filtered_percents, target["min"])

    result = {
        "status": "target",
        "member_name": member_name,
        "member_number": member_num,
        "division": div_data.get("name", division_key),
        "current_class": current_cls,
        "current_percent": div_data.get("percent"),
        "next_class": target["id"],
        "target_threshold": target["min"],
        "needed_percent": round(needed_pct, 4) if needed_pct is not None else None,
        "reachable_in_one_run": needed_pct is not None and needed_pct <= MAX_PERCENT,
    }

    if needed_pct is not None and needed_pct > MAX_PERCENT:
        best_possible = class_average([MAX_PERCENT] + filtered_percents)
        result["best_possible_average"] = round(best_possible, 4) if best_possible else None
        result["message"] = (
            f"Cannot reach {target['id']} in a single run: even a max score ({MAX_PERCENT}%) "
            f"brings the average to {result['best_possible_average']}%. More scores needed."
        )

    # Calculate hit factor and times if HHF and rounds are provided
    if hhf and needed_pct is not None and needed_pct <= MAX_PERCENT:
        min_hf = min_hit_factor(hhf, needed_pct)
        result["hhf"] = hhf
        result["needed_hit_factor"] = round(min_hf, 4)

        if rounds:
            combos = hit_combinations(hits=rounds, steel=steel, power_factor=power_factor)
            combos_with_times = []
            for c in combos:
                t = max_time(c["points"], min_hf)
                if t is not None:
                    combos_with_times.append({**c, "max_time": t})
            result["combinations"] = combos_with_times

    return result


# --- Playwright Scraper ---

async def scrape_uspsa_profile(
    member_number: str,
    headless: bool = True,
    timeout: int = 30000,
    url_pattern: str = "https://uspsa.org/classification/{member_number}",
) -> str:
    """Fetch raw HTML for a USPSA member's profile using Playwright."""
    if async_playwright is None:
        raise ImportError(
            "playwright is required to scrape live pages. Install it with: "
            "pip install playwright && playwright install chromium"
        )

    clean_number = member_number.strip().upper()
    url = url_pattern.format(member_number=clean_number)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        # Hide navigator.webdriver flag in headless mode
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_selector("table", timeout=timeout)
            html = await page.content()
            return html
        finally:
            await browser.close()


def parse_data(html: str) -> Dict[str, Any]:
    """Parse USPSA member classification page HTML."""
    if BeautifulSoup is not None:
        return _parse_data_soup(html)
    return _parse_data_stdlib(html)


def _parse_data_soup(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return {
            "success": False,
            "error": "No tables found. Member may not exist or request was blocked by Cloudflare.",
            "member": {},
            "divisions": {},
            "shooter": {},
            "classifications": {},
            "match_history": {},
        }

    shooter_info: Dict[str, Any] = {}
    ro_info: Dict[str, Any] = {}
    classifications: Dict[str, Dict[str, Any]] = {}
    match_history: Dict[str, List[Dict[str, Any]]] = {}

    # 1. Shooter Information
    for table in tables:
        header = table.find("th")
        if header and "Shooter Information" in header.get_text():
            for tr in table.find_all("tr"):
                th = tr.find("th")
                td = tr.find("td")
                if th and td:
                    label = th.get_text(strip=True).rstrip(":")
                    val = td.get_text(strip=True)
                    shooter_info[label] = val
                    if "Joined" in label:
                        shooter_info["joined_iso"] = _parse_iso_date(val)
            break

    if shooter_info:
        shooter_info["name"] = shooter_info.get("Shooter Name")
        shooter_info["member_number"] = shooter_info.get("Member Number")
        shooter_info["joined"] = shooter_info.get("Joined USPSA")
        shooter_info["expires"] = shooter_info.get("Membership Expiry Date")

    # 2. RO Certification
    for table in tables:
        header = table.find("th")
        if header and "RO Certification Info" in header.get_text():
            tbody = table.find("tbody")
            if tbody:
                row_texts = [r.get_text(strip=True) for r in tbody.find_all("tr") if r.get_text(strip=True)]
                ro_info["status"] = " ".join(row_texts) if row_texts else "None"
            nroi_link = soup.find("a", href=re.compile(r"/nroi/workrecords/"))
            if nroi_link:
                ro_info["work_record_url"] = nroi_link.get("href")
            break

    # 3. Classifications summary table
    for table in tables:
        header = table.find("th")
        if header and "Classifications" in header.get_text():
            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                th = tr.find("th")
                tds = tr.find_all("td")
                if th and len(tds) >= 3:
                    div_name = th.get_text(strip=True)
                    cls_text = tds[0].get_text(strip=True).replace("Class:", "").strip()
                    pct_text = tds[1].get_text(strip=True).replace("Pct:", "").strip()
                    high_text = tds[2].get_text(strip=True).replace("High Pct:", "").strip()

                    classifications[div_name] = {
                        "class": cls_text,
                        "percent": _parse_float(pct_text),
                        "high_percent": _parse_float(high_text),
                    }
            break

    # 4. Match history / classifier scores per division
    for table in tables:
        div_link = table.find("a", attrs={"data-division": True})
        if not div_link:
            continue

        raw_div = div_link.get("data-division", "")
        div_name = raw_div.replace("_", " ")

        tbody = table.find("tbody")
        if not tbody:
            continue

        scores: List[Dict[str, Any]] = []
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 8:
                continue

            date_str = tds[0].get_text(strip=True)
            if date_str.lower() == "date":
                continue

            classifier_code = tds[1].get_text(strip=True) or None
            club_cell = tds[2]
            club_name = club_cell.get_text(strip=True)
            club_a = club_cell.find("a")
            club_url = club_a.get("href") if club_a else None

            flag = tds[3].get_text(strip=True) or None
            percent = _parse_float(tds[4].get_text(strip=True))
            hit_factor = _parse_float(tds[5].get_text(strip=True))

            entered_str = tds[6].get_text(strip=True)
            entered = entered_str if entered_str != "-" else None
            source = tds[7].get_text(strip=True) or None

            scores.append({
                "date": _parse_iso_date(date_str) or date_str,
                "raw_date": date_str,
                "code": classifier_code,
                "classifier": classifier_code,
                "club": club_name,
                "club_url": club_url,
                "flag": flag,
                "percent": percent,
                "hf": hit_factor,
                "hit_factor": hit_factor,
                "entered": _parse_iso_date(entered) if entered else entered,
                "source": source,
            })

        match_history[div_name] = scores

    # Build standardized divisions map (keyed by division_id, matching server/uspsa.js and index.html)
    divisions_map: Dict[str, Any] = {}
    for div_name, summary in classifications.items():
        did = division_id(div_name)
        scores = match_history.get(div_name, [])
        divisions_map[did] = {
            "name": div_name,
            "class": summary.get("class"),
            "percent": summary.get("percent"),
            "highPercent": summary.get("high_percent"),
            "scores": scores,
        }

    member_dict = {
        "number": shooter_info.get("Member Number"),
        "name": shooter_info.get("Shooter Name"),
        "joined": _parse_iso_date(shooter_info.get("Joined USPSA")),
        "expires": shooter_info.get("Membership Expiry Date"),
    }

    return {
        "success": True,
        "member": member_dict,
        "divisions": divisions_map,
        "shooter": shooter_info,
        "ro_certification": ro_info,
        "classifications": classifications,
        "match_history": match_history,
    }


def _parse_data_stdlib(html: str) -> Dict[str, Any]:
    """Fallback parser using regex when beautifulsoup4 is not installed."""
    if "<table" not in html.lower():
        return {
            "success": False,
            "error": "No tables found. Member may not exist or request was blocked.",
            "member": {},
            "divisions": {},
            "shooter": {},
            "classifications": {},
            "match_history": {},
        }

    shooter_info: Dict[str, Any] = {}
    ro_info: Dict[str, Any] = {}
    classifications: Dict[str, Dict[str, Any]] = {}
    match_history: Dict[str, List[Dict[str, Any]]] = {}

    # 1. Shooter Information
    m_info = re.search(r'<table[^>]*>[\s\S]*?Shooter Information[\s\S]*?<tbody>([\s\S]*?)</tbody>[\s\S]*?</table>', html, re.I)
    if m_info:
        for row in re.finditer(r'<tr[^>]*>\s*<th[^>]*>([^<]+)</th>\s*<td[^>]*>([^<]+)</td>', m_info.group(1)):
            k = row.group(1).strip().rstrip(":")
            v = row.group(2).strip()
            shooter_info[k] = v
            if "Joined" in k:
                shooter_info["joined_iso"] = _parse_iso_date(v)

    if shooter_info:
        shooter_info["name"] = shooter_info.get("Shooter Name")
        shooter_info["member_number"] = shooter_info.get("Member Number")
        shooter_info["joined"] = shooter_info.get("Joined USPSA")
        shooter_info["expires"] = shooter_info.get("Membership Expiry Date")

    # 2. RO Certification
    m_ro = re.search(r'<table[^>]*>[\s\S]*?RO Certification Info[\s\S]*?<tbody>([\s\S]*?)</tbody>[\s\S]*?</table>', html, re.I)
    if m_ro:
        clean_text = re.sub(r'<[^>]*>', ' ', m_ro.group(1)).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)
        ro_info["status"] = clean_text or "None"
    m_nroi = re.search(r'href="([^"]*?/nroi/workrecords/[^"]*?)"', html)
    if m_nroi:
        ro_info["work_record_url"] = m_nroi.group(1)

    # 3. Classifications
    m_cls = re.search(r'<table[^>]*>[\s\S]*?Classifications[\s\S]*?<tbody>([\s\S]*?)</tbody>[\s\S]*?</table>', html, re.I)
    if m_cls:
        rows = re.finditer(
            r'<th[^>]*>\s*([A-Za-z0-9\s]+?)\s*</th>\s*'
            r'<td[^>]*>\s*Class:\s*([A-Za-z0-9]+)\s*</td>\s*'
            r'<td[^>]*>\s*Pct:\s*([0-9.]+)\s*</td>\s*'
            r'<td[^>]*>\s*High Pct:\s*([0-9.]+)\s*</td>',
            m_cls.group(1), re.I
        )
        for r in rows:
            div = r.group(1).strip()
            classifications[div] = {
                "class": r.group(2).strip(),
                "percent": _parse_float(r.group(3)),
                "high_percent": _parse_float(r.group(4)),
            }

    # 4. Match history by division
    div_blocks = re.finditer(r'data-division="([^"]+)"[\s\S]*?<tbody[^>]*>([\s\S]*?)</tbody>', html)
    for db in div_blocks:
        raw_div = db.group(1)
        div_name = raw_div.replace("_", " ")
        scores: List[Dict[str, Any]] = []
        tbody = db.group(2)
        for tr in re.finditer(r'<tr[^>]*>([\s\S]*?)</tr>', tbody):
            tds = re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr.group(1))
            if len(tds) < 8:
                continue
            texts = [re.sub(r'<[^>]*>', '', c).strip() for c in tds]
            if texts[0].lower() == "date":
                continue

            m_url = re.search(r'href="([^"]+)"', tds[2])
            club_url = m_url.group(1) if m_url else None

            scores.append({
                "date": _parse_iso_date(texts[0]) or texts[0],
                "raw_date": texts[0],
                "code": texts[1] or None,
                "classifier": texts[1] or None,
                "club": texts[2],
                "club_url": club_url,
                "flag": texts[3] or None,
                "percent": _parse_float(texts[4]),
                "hf": _parse_float(texts[5]),
                "hit_factor": _parse_float(texts[5]),
                "entered": _parse_iso_date(texts[6]) if texts[6] != "-" else None,
                "source": texts[7] or None,
            })
        match_history[div_name] = scores

    divisions_map: Dict[str, Any] = {}
    for div_name, summary in classifications.items():
        did = division_id(div_name)
        scores = match_history.get(div_name, [])
        divisions_map[did] = {
            "name": div_name,
            "class": summary.get("class"),
            "percent": summary.get("percent"),
            "highPercent": summary.get("high_percent"),
            "scores": scores,
        }

    member_dict = {
        "number": shooter_info.get("Member Number"),
        "name": shooter_info.get("Shooter Name"),
        "joined": _parse_iso_date(shooter_info.get("Joined USPSA")),
        "expires": shooter_info.get("Membership Expiry Date"),
    }

    return {
        "success": True,
        "member": member_dict,
        "divisions": divisions_map,
        "shooter": shooter_info,
        "ro_certification": ro_info,
        "classifications": classifications,
        "match_history": match_history,
    }


async def main_async(args: argparse.Namespace) -> None:
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        if not args.member_number:
            print("Error: Please provide a member number or an HTML file.", file=sys.stderr)
            sys.exit(1)
        
        # Check cache directory first if not dumping html directly
        cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pages", f"{args.member_number.upper()}.html")
        max_age_sec = (args.cache_hours if getattr(args, "cache_hours", None) is not None else 24) * 3600
        is_fresh = False
        cached_html = None

        if os.path.exists(cache_path) and not getattr(args, "force", False):
            mtime = os.path.getmtime(cache_path)
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_html = f.read()
            if (time.time() - mtime) < max_age_sec:
                is_fresh = True
                html = cached_html

        if not is_fresh:
            if not getattr(args, "dump_html", False):
                print(f"Scraping profile for USPSA member: {args.member_number}...")
            try:
                is_headless = not getattr(args, "headed", False)
                html = await scrape_uspsa_profile(
                    member_number=args.member_number,
                    headless=is_headless,
                    timeout=args.timeout,
                )
                try:
                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                    with open(cache_path, "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception:
                    pass
            except Exception as e:
                if cached_html:
                    if not getattr(args, "dump_html", False):
                        print(f"Scraping failed ({e}); falling back to cached file.", file=sys.stderr)
                    html = cached_html
                else:
                    raise

    if args.dump_html:
        sys.stdout.write(html)
        return

    result = parse_data(html)

    # Perform next class calculation if requested
    target_info = None
    if args.division:
        target_info = calculate_next_class_target(
            parsed_data=result,
            division_key=args.division,
            hhf=args.hhf,
            rounds=args.rounds,
            steel=args.steel,
            power_factor=args.power_factor,
            classifier_code=args.classifier,
        )

    if args.json:
        out = {**result}
        if target_info:
            out["target_calculation"] = target_info
        print(json.dumps(out, indent=2))
        return

    print("Data extracted successfully!\n")
    shooter = result.get("shooter", {})
    print(f"--- Shooter: {shooter.get('name', 'Unknown')} ({shooter.get('member_number', 'N/A')}) ---")
    print(f"Joined: {shooter.get('joined', 'N/A')} | Expiry: {shooter.get('expires', 'N/A')}")
    if result.get("ro_certification", {}).get("status"):
        print(f"RO Status: {result['ro_certification']['status']}")

    print("\n--- Classifications ---")
    for div, stats in result.get("classifications", {}).items():
        print(f"  {div:16}: Class {stats['class']:<2} | Cur: {stats['percent']}% | High: {stats['high_percent']}%")

    if target_info:
        print(f"\n--- Target Calculation ({args.division}) ---")
        status = target_info.get("status")
        if status == "gm":
            print(f"  {target_info['message']}")
        elif status == "unclassed":
            print(f"  {target_info['message']}")
        elif status == "target":
            print(f"  Current Class: {target_info['current_class']} ({target_info['current_percent']}%)")
            print(f"  Target Class : {target_info['next_class']} (needs {target_info['target_threshold']}%)")
            if target_info.get("needed_percent") is not None:
                print(f"  Needed Score : {target_info['needed_percent']}% on next classifier")
            if target_info.get("needed_hit_factor") is not None:
                print(f"  Needed Min HF: {target_info['needed_hit_factor']}")
            if target_info.get("message"):
                print(f"  Note: {target_info['message']}")
            if target_info.get("combinations"):
                print(f"  {len(target_info['combinations'])} hit/time combinations available to make {target_info['next_class']}:")
                top = target_info['combinations'][:5]
                for c in top:
                    print(f"    A: {c['a']:2d} | C: {c['c']:2d} | D: {c['d']:2d} | M: {c['m']:2d} -> Max Time: {c['max_time']:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="USPSA Member Classification Scraper & Target Calculator")
    parser.add_argument("member_number", nargs="?", help="USPSA Member number (e.g. A161327)")
    parser.add_argument("--file", "-f", help="Parse a saved local HTML file instead of scraping")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible headed mode (default: headless)")
    parser.add_argument("--dump-html", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help="Force scrape even if cached file exists")
    parser.add_argument("--cache-hours", type=float, default=24.0, help="Max cache age in hours before re-scraping (default: 24)")
    parser.add_argument("--timeout", type=int, default=30000, help="Navigation timeout in milliseconds")
    parser.add_argument("--json", action="store_true", help="Print output as JSON")
    parser.add_argument("--division", "-d", help="Division to calculate next class target for (e.g. 'Carry Optics')")
    parser.add_argument("--classifier", "-c", help="Classifier code being shot (e.g. '99-11')")
    parser.add_argument("--hhf", type=float, help="High Hit Factor of the classifier")
    parser.add_argument("--rounds", "-r", type=int, help="Scoring hits on the classifier (e.g. 12)")
    parser.add_argument("--steel", type=int, default=0, help="Steel targets count")
    parser.add_argument("--power-factor", "--pf", choices=["minor", "major"], default="minor", help="Power factor")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

