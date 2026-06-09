#!/usr/bin/env python3
"""
Sports Stats Scraper (Windows-safe, NO emojis)

- NHL: MoneyPuck (Playwright) â€” Teams + Goalies, Regular Season + Conditional Playoffs
- NFL/NBA/MLB/NCAAF/NCAAB: TeamRankings (requests)
- Schedules: ScoresAndOdds schedule pages (Playwright)

Outputs per run:
  stats_output/Schedules_LEAGUE_YYYYMMDD.xlsx
  stats_output/RawStats_NHL_YYYYMMDD_regular.xlsx
  stats_output/RawStats_NHL_YYYYMMDD_playoffs.xlsx     (only if playoff threshold met)
  stats_output/RawStats_NHL_Goalies_YYYYMMDD_regular.xlsx
  stats_output/RawStats_NHL_Goalies_YYYYMMDD_playoffs.xlsx  (only if playoff threshold met)
  stats_output/RawStats_LEAGUE_YYYYMMDD.xlsx           (non-NHL leagues)
  stats_output/Matchups_LEAGUE_YYYYMMDD.xlsx           (one sheet per game)
  stats_output/StatsStatus_LEAGUE_YYYYMMDD.json        (audit trail)

FIXES IN THIS VERSION:
  - Ghost row bug eliminated: blank/rank-only rows skipped in MoneyPuck parser
  - Icetime(Minutes) column explicitly dropped â€” always MISSING, no signal
  - Playoff scrape gated behind PLAYOFF_GP_THRESHOLD (default: 2 games)
  - Playoffs selector driven by Playwright before HTML capture
  - Full goalie scrape added (moneypuck.com/goalies.htm) with same season gate
  - create_raw_stats_workbook accepts suffix parameter for multi-file NHL output
  - StatsStatus JSON records full NHL season_type audit trail
  - Date + Time (ET) written to BOTH Away and Home columns
  - All blank/NaN/empty stat values replaced with literal: MISSING_FROM_SOURCE
"""

import os
import re
import time
import json
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from requests.exceptions import SSLError as RequestsSSLError
import urllib3

try:
    import certifi
except Exception:
    certifi = None

# ==============================================================================
# CONFIGURATION
# ==============================================================================

HEADLESS     = os.getenv("HEADLESS", "1") != "0"
SLOW_MO_MS   = int(os.getenv("SLOW_MO_MS", "0"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

LOG_DIR    = Path("logs")
OUTPUT_DIR = Path("stats_output")
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Minimum playoff games played by BOTH teams before playoff stats are used.
# Below this threshold the scraper uses regular season stats instead.
# Set to 0 to always use playoff stats once playoffs begin.
PLAYOFF_GP_THRESHOLD: int = 2
ALLOW_INSECURE_SSL_FALLBACK: bool = str(os.getenv("OVERLINE_ALLOW_INSECURE_SSL_FALLBACK", "1")).strip().lower() not in {"0", "false", "no", "off"}
REQUEST_TIMEOUT_SEC: int = int(os.getenv("OVERLINE_REQUEST_TIMEOUT_SEC", "30"))

# Columns to silently drop from NHL team stats â€” confirmed always MISSING_FROM_SOURCE
NHL_DROP_COLUMNS = {"Icetime(Minutes)"}

if ALLOW_INSECURE_SSL_FALLBACK:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _safe_requests_get(url: str, league: str, timeout: Optional[int] = None) -> requests.Response:
    """
    Strict-first HTTPS fetch:
    1) default certificate verification
    2) certifi bundle verification (if available)
    3) optional insecure fallback (env-controlled) for broken host CA chains
    """
    _timeout = int(timeout or REQUEST_TIMEOUT_SEC)
    _headers = {"User-Agent": USER_AGENT}
    try:
        return requests.get(url, headers=_headers, timeout=_timeout)
    except RequestsSSLError as e_default:
        _cert_path = certifi.where() if certifi else None
        if _cert_path:
            try:
                log(league, "SSL verification failed with system store; retrying with certifi bundle.", "WARN")
                return requests.get(url, headers=_headers, timeout=_timeout, verify=_cert_path)
            except RequestsSSLError:
                pass
        if ALLOW_INSECURE_SSL_FALLBACK:
            log(league, "SSL verification failed; retrying with verify=False fallback.", "WARN")
            return requests.get(url, headers=_headers, timeout=_timeout, verify=False)
        raise e_default

# ==============================================================================
# SCHEDULE URLS
# ==============================================================================

LEAGUE_URLS = {
    "nfl":   "https://www.scoresandodds.com/nfl/schedule",
    "ncaaf": "https://www.scoresandodds.com/ncaaf/schedule",
    "nba":   "https://www.scoresandodds.com/nba/schedule",
    "ncaab": "https://www.scoresandodds.com/ncaab/schedule",
    "mlb":   "https://www.scoresandodds.com/mlb/schedule",
    "nhl":   "https://www.scoresandodds.com/nhl/schedule",
}

# ==============================================================================
# TEAMRANKINGS STAT URLS (non-NHL)
# ==============================================================================

STATS_URLS: Dict[str, List[str]] = {
    "nfl": [
        "https://www.teamrankings.com/nfl/stat/seconds-per-play",
        "https://www.teamrankings.com/nfl/stat/opponent-seconds-per-play",
        "https://www.teamrankings.com/nfl/stat/points-per-game",
        "https://www.teamrankings.com/nfl/stat/opponent-points-per-game",
        "https://www.teamrankings.com/nfl/stat/red-zone-scoring-pct",
        "https://www.teamrankings.com/nfl/stat/opponent-red-zone-scoring-pct",
        "https://www.teamrankings.com/nfl/stat/yards-per-play",
        "https://www.teamrankings.com/nfl/stat/opponent-yards-per-play",
        "https://www.teamrankings.com/nfl/stat/third-down-conversion-pct",
        "https://www.teamrankings.com/nfl/stat/assisted-tackles-per-game",
        "https://www.teamrankings.com/nfl/stat/opponent-assisted-tackles-per-game",
        "https://www.teamrankings.com/nfl/stat/rushing-play-pct",
        "https://www.teamrankings.com/nfl/stat/yards-per-rush-attempt",
        "https://www.teamrankings.com/nfl/stat/opponent-rushing-play-pct",
        "https://www.teamrankings.com/nfl/stat/opponent-yards-per-rush-attempt",
        "https://www.teamrankings.com/nfl/stat/passing-play-pct",
        "https://www.teamrankings.com/nfl/stat/yards-per-pass-attempt",
        "https://www.teamrankings.com/nfl/stat/completion-pct",
        "https://www.teamrankings.com/nfl/stat/qb-sacked-pct",
        "https://www.teamrankings.com/nfl/stat/opponent-passing-play-pct",
        "https://www.teamrankings.com/nfl/stat/opponent-yards-per-pass-attempt",
        "https://www.teamrankings.com/nfl/stat/opponent-completion-pct",
        "https://www.teamrankings.com/nfl/stat/sack-pct",
        "https://www.teamrankings.com/nfl/stat/field-goal-attempts-per-game",
        "https://www.teamrankings.com/nfl/stat/net-yards-per-punt-attempt",
        "https://www.teamrankings.com/nfl/stat/opponent-field-goal-attempts-per-game",
        "https://www.teamrankings.com/nfl/stat/opponent-net-yards-per-punt-attempt",
        "https://www.teamrankings.com/nfl/stat/turnover-margin-per-game",
        "https://www.teamrankings.com/nfl/stat/penalties-per-play",
        "https://www.teamrankings.com/nfl/stat/opponent-penalties-per-play",
    ],
    "ncaaf": [
        "https://www.teamrankings.com/college-football/stat/points-per-game",
        "https://www.teamrankings.com/college-football/stat/opponent-points-per-game",
        "https://www.teamrankings.com/college-football/stat/seconds-per-play",
        "https://www.teamrankings.com/college-football/stat/opponent-seconds-per-play",
        "https://www.teamrankings.com/college-football/stat/red-zone-scoring-pct",
        "https://www.teamrankings.com/college-football/stat/opponent-red-zone-scoring-pct",
        "https://www.teamrankings.com/college-football/stat/yards-per-play",
        "https://www.teamrankings.com/college-football/stat/opponent-yards-per-play",
        "https://www.teamrankings.com/college-football/stat/third-down-conversion-pct",
        "https://www.teamrankings.com/college-football/stat/opponent-third-down-conversion-pct",
        "https://www.teamrankings.com/college-football/stat/rushing-play-pct",
        "https://www.teamrankings.com/college-football/stat/yards-per-rush-attempt",
        "https://www.teamrankings.com/college-football/stat/opponent-rushing-play-pct",
        "https://www.teamrankings.com/college-football/stat/opponent-yards-per-rush-attempt",
        "https://www.teamrankings.com/college-football/stat/passing-play-pct",
        "https://www.teamrankings.com/college-football/stat/yards-per-pass-attempt",
        "https://www.teamrankings.com/college-football/stat/completion-pct",
        "https://www.teamrankings.com/college-football/stat/qb-sacked-pct",
        "https://www.teamrankings.com/college-football/stat/opponent-passing-play-pct",
        "https://www.teamrankings.com/college-football/stat/opponent-yards-per-pass-attempt",
        "https://www.teamrankings.com/college-football/stat/opponent-completion-pct",
        "https://www.teamrankings.com/college-football/stat/sack-pct",
        "https://www.teamrankings.com/college-football/stat/turnover-margin-per-game",
        "https://www.teamrankings.com/college-football/stat/opponent-turnover-margin-per-game",
        "https://www.teamrankings.com/college-football/stat/penalties-per-play",
        "https://www.teamrankings.com/college-football/stat/opponent-penalties-per-play",
        "https://www.teamrankings.com/college-football/stat/punt-attempts-per-game",
        "https://www.teamrankings.com/college-football/stat/opponent-punt-attempts-per-game",
        "https://www.teamrankings.com/college-football/stat/field-goal-attempts-per-game",
        "https://www.teamrankings.com/college-football/stat/opponent-field-goal-attempts-per-game",
    ],
    "nba": [
        "https://www.teamrankings.com/nba/stat/possessions-per-game",
        "https://www.teamrankings.com/nba/stat/points-per-game",
        "https://www.teamrankings.com/nba/stat/opponent-points-per-game",
        "https://www.teamrankings.com/nba/stat/offensive-efficiency",
        "https://www.teamrankings.com/nba/stat/floor-percentage",
        "https://www.teamrankings.com/nba/stat/defensive-efficiency",
        "https://www.teamrankings.com/nba/stat/opponent-floor-percentage",
        "https://www.teamrankings.com/nba/stat/points-in-paint-per-game",
        "https://www.teamrankings.com/nba/stat/opponent-points-in-paint-per-game",
        "https://www.teamrankings.com/nba/stat/percent-of-points-from-2-pointers",
        "https://www.teamrankings.com/nba/stat/percent-of-points-from-3-pointers",
        "https://www.teamrankings.com/nba/stat/percent-of-points-from-free-throws",
        "https://www.teamrankings.com/nba/stat/opponent-percent-of-points-from-2-pointers",
        "https://www.teamrankings.com/nba/stat/opponent-percent-of-points-from-3-pointers",
        "https://www.teamrankings.com/nba/stat/opponent-percent-of-points-from-free-throws",
        "https://www.teamrankings.com/nba/stat/free-throw-pct",
        "https://www.teamrankings.com/nba/stat/ftm-per-100-possessions",
        "https://www.teamrankings.com/nba/stat/free-throw-rate",
        "https://www.teamrankings.com/nba/stat/opponent-ftm-per-100-possessions",
        "https://www.teamrankings.com/nba/stat/effective-field-goal-pct",
        "https://www.teamrankings.com/nba/stat/opponent-effective-field-goal-pct",
        "https://www.teamrankings.com/nba/stat/total-rebounding-percentage",
        "https://www.teamrankings.com/nba/stat/block-pct",
        "https://www.teamrankings.com/nba/stat/steal-pct",
        "https://www.teamrankings.com/nba/stat/opponent-block-pct",
        "https://www.teamrankings.com/nba/stat/opponent-steal-pct",
        "https://www.teamrankings.com/nba/stat/assist--per--turnover-ratio",
        "https://www.teamrankings.com/nba/stat/opponent-assist--per--turnover-ratio",
        "https://www.teamrankings.com/nba/stat/personal-fouls-per-possession",
        "https://www.teamrankings.com/nba/stat/opponent-personal-fouls-per-possession",
    ],
    "ncaab": [
        "https://www.teamrankings.com/ncaa-basketball/stat/possessions-per-game",
        "https://www.teamrankings.com/ncaa-basketball/stat/points-per-game",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-points-per-game",
        "https://www.teamrankings.com/ncaa-basketball/stat/offensive-efficiency",
        "https://www.teamrankings.com/ncaa-basketball/stat/floor-percentage",
        "https://www.teamrankings.com/ncaa-basketball/stat/defensive-efficiency",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-floor-percentage",
        "https://www.teamrankings.com/ncaa-basketball/stat/percent-of-points-from-2-pointers",
        "https://www.teamrankings.com/ncaa-basketball/stat/percent-of-points-from-3-pointers",
        "https://www.teamrankings.com/ncaa-basketball/stat/percent-of-points-from-free-throws",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-percent-of-points-from-2-pointers",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-percent-of-points-from-3-pointers",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-percent-of-points-from-free-throws",
        "https://www.teamrankings.com/ncaa-basketball/stat/free-throw-pct",
        "https://www.teamrankings.com/ncaa-basketball/stat/ftm-per-100-possessions",
        "https://www.teamrankings.com/ncaa-basketball/stat/free-throw-rate",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-ftm-per-100-possessions",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-free-throw-rate",
        "https://www.teamrankings.com/ncaa-basketball/stat/effective-field-goal-pct",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-effective-field-goal-pct",
        "https://www.teamrankings.com/ncaa-basketball/stat/total-rebounding-percentage",
        "https://www.teamrankings.com/ncaa-basketball/stat/block-pct",
        "https://www.teamrankings.com/ncaa-basketball/stat/steals-perpossession",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-block-pct",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-steals-perpossession",
        "https://www.teamrankings.com/ncaa-basketball/stat/turnovers-per-possession",
        "https://www.teamrankings.com/ncaa-basketball/stat/assist--per--turnover-ratio",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-turnovers-per-possession",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-assist--per--turnover-ratio",
        "https://www.teamrankings.com/ncaa-basketball/stat/personal-fouls-per-possession",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-personal-fouls-per-possession",
        "https://www.teamrankings.com/ncaa-basketball/stat/extra-chances-per-game",
        "https://www.teamrankings.com/ncaa-basketball/stat/opponent-effective-possession-ratio",
    ],
    "mlb": [
        "https://www.teamrankings.com/mlb/stat/runs-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-runs-per-game",
        "https://www.teamrankings.com/mlb/stat/batting-average",
        "https://www.teamrankings.com/mlb/stat/on-base-pct",
        "https://www.teamrankings.com/mlb/stat/slugging-pct",
        "https://www.teamrankings.com/mlb/stat/hits-per-game",
        "https://www.teamrankings.com/mlb/stat/home-runs-per-game",
        "https://www.teamrankings.com/mlb/stat/doubles-per-game",
        "https://www.teamrankings.com/mlb/stat/walks-per-game",
        "https://www.teamrankings.com/mlb/stat/strikeouts-per-game",
        "https://www.teamrankings.com/mlb/stat/stolen-bases-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-batting-average",
        "https://www.teamrankings.com/mlb/stat/opponent-on-base-pct",
        "https://www.teamrankings.com/mlb/stat/opponent-slugging-pct",
        "https://www.teamrankings.com/mlb/stat/opponent-hits-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-home-runs-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-doubles-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-walks-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-strikeouts-per-game",
        "https://www.teamrankings.com/mlb/stat/opponent-stolen-bases-per-game",
    ],
}

# ==============================================================================
# NHL TEAM NAME ALIASES  (MoneyPuck uses abbreviations)
# ==============================================================================

NHL_TEAM_ALIASES: Dict[str, List[str]] = {
    "Anaheim Ducks":         ["ANA", "DUCKS", "ANAHEIM"],
    "Boston Bruins":         ["BOS", "BRUINS", "BOSTON"],
    "Buffalo Sabres":        ["BUF", "SABRES", "BUFFALO"],
    "Calgary Flames":        ["CGY", "CAL", "FLAMES", "CALGARY"],
    "Carolina Hurricanes":   ["CAR", "HURRICANES", "CAROLINA", "CANES"],
    "Chicago Blackhawks":    ["CHI", "BLACKHAWKS", "CHICAGO", "HAWKS"],
    "Colorado Avalanche":    ["COL", "AVALANCHE", "COLORADO", "AVS"],
    "Columbus Blue Jackets": ["CBJ", "COLUMBUS", "BLUE JACKETS"],
    "Dallas Stars":          ["DAL", "STARS", "DALLAS"],
    "Detroit Red Wings":     ["DET", "RED WINGS", "DETROIT"],
    "Edmonton Oilers":       ["EDM", "OILERS", "EDMONTON"],
    "Florida Panthers":      ["FLA", "PANTHERS", "FLORIDA"],
    "Los Angeles Kings":     ["LAK", "LA", "KINGS", "LOS ANGELES"],
    "Minnesota Wild":        ["MIN", "WILD", "MINNESOTA"],
    "Montreal Canadiens":    ["MTL", "MON", "CANADIENS", "MONTREAL", "HABS"],
    "Nashville Predators":   ["NSH", "PREDATORS", "NASHVILLE", "PREDS"],
    "New Jersey Devils":     ["NJD", "NJ", "DEVILS", "NEW JERSEY"],
    "New York Islanders":    ["NYI", "ISLANDERS", "NY ISLANDERS"],
    "New York Rangers":      ["NYR", "RANGERS", "NY RANGERS"],
    "Ottawa Senators":       ["OTT", "SENATORS", "OTTAWA", "SENS"],
    "Philadelphia Flyers":   ["PHI", "FLYERS", "PHILADELPHIA"],
    "Pittsburgh Penguins":   ["PIT", "PENGUINS", "PITTSBURGH", "PENS"],
    "San Jose Sharks":       ["SJS", "SJ", "SHARKS", "SAN JOSE"],
    "Seattle Kraken":        ["SEA", "KRAKEN", "SEATTLE"],
    "St. Louis Blues":       ["STL", "BLUES", "ST LOUIS", "ST. LOUIS"],
    "Tampa Bay Lightning":   ["TBL", "TB", "LIGHTNING", "TAMPA BAY"],
    "Toronto Maple Leafs":   ["TOR", "MAPLE LEAFS", "TORONTO", "LEAFS"],
    "Vancouver Canucks":     ["VAN", "CANUCKS", "VANCOUVER"],
    "Vegas Golden Knights":  ["VGK", "VEGAS", "GOLDEN KNIGHTS"],
    "Washington Capitals":   ["WSH", "WAS", "CAPITALS", "WASHINGTON", "CAPS"],
    "Winnipeg Jets":         ["WPG", "JETS", "WINNIPEG"],
    "Utah Mammoth":          ["UTA", "UTAH", "MAMMOTH"],
}

NHL_ABBREV_TO_FULL: Dict[str, str] = {}
for _full, _aliases in NHL_TEAM_ALIASES.items():
    for _a in _aliases:
        NHL_ABBREV_TO_FULL[_a.upper()] = _full

# ==============================================================================
# CROSS-LEAGUE TEAM ALIASES  (schedule name -> stats source name)
# ==============================================================================

TEAM_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "mlb": {
        "Sacramento": ["Athletics", "Las Vegas Athletics", "Oakland Athletics", "Las Vegas", "Oakland"],
    },
    "nba": {
        "LA Lakers":   ["Lakers", "Los Angeles Lakers"],
        "LA Clippers": ["Clippers", "Los Angeles Clippers"],
        "Golden State": ["Warriors", "Golden State Warriors"],
    },
    "ncaaf": {
        "James Madison": ["JMU", "James Mad"],
        "UCF":           ["Central Florida"],
        "USC":           ["Southern California"],
    },
    "ncaab": {
        "UConn": ["Connecticut"],
        "VCU":   ["Virginia Commonwealth"],
    },
    "nhl": NHL_TEAM_ALIASES,
}

NBA_NICK_TO_CITY: Dict[str, str] = {
    "hawks": "atlanta",
    "celtics": "boston",
    "nets": "brooklyn",
    "hornets": "charlotte",
    "bulls": "chicago",
    "cavaliers": "cleveland",
    "mavericks": "dallas",
    "nuggets": "denver",
    "pistons": "detroit",
    "warriors": "golden state",
    "rockets": "houston",
    "pacers": "indiana",
    "clippers": "la clippers",
    "lakers": "la lakers",
    "grizzlies": "memphis",
    "heat": "miami",
    "bucks": "milwaukee",
    "timberwolves": "minnesota",
    "pelicans": "new orleans",
    "knicks": "new york",
    "thunder": "okla city",
    "magic": "orlando",
    "76ers": "philadelphia",
    "sixers": "philadelphia",
    "suns": "phoenix",
    "trail blazers": "portland",
    "blazers": "portland",
    "kings": "sacramento",
    "spurs": "san antonio",
    "raptors": "toronto",
    "jazz": "utah",
    "wizards": "washington",
}

# ==============================================================================
# LOGGING
# ==============================================================================

def log(league: str, msg: str, level: str = "INFO") -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{league.upper()}] [{level}] {msg}"
    print(line)
    log_file = LOG_DIR / f"{league}_stats.log"
    try:
        log_file.open("a", encoding="utf-8").write(line + "\n")
    except Exception:
        log_file.open("a", encoding="utf-8").write(
            line.encode("utf-8", errors="replace").decode("utf-8") + "\n"
        )

# ==============================================================================
# CELL CLEANING
# ==============================================================================

def clean_cell(v: Any) -> Any:
    """Replace any blank / NaN / None with the sentinel string."""
    if v is None:
        return "MISSING_FROM_SOURCE"
    try:
        if isinstance(v, float) and pd.isna(v):
            return "MISSING_FROM_SOURCE"
    except Exception:
        pass
    s = str(v).strip()
    if s == "" or s.lower() in ("n/a", "na", "nan", "none"):
        return "MISSING_FROM_SOURCE"
    return v

# ==============================================================================
# PLAYWRIGHT HTML FETCH  (generic â€” schedules only)
# ==============================================================================

def fetch_html_playwright(league: str, url: str) -> str:
    log(league, f"Fetching URL: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
        context = browser.new_context(user_agent=USER_AGENT)
        page    = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            html = page.content()
            log(league, f"Fetched HTML ({len(html):,} chars)")
            return html
        finally:
            browser.close()

# ==============================================================================
# SCHEDULE PARSING
# ==============================================================================

def parse_date_str(date_str: str) -> Optional[date]:
    cleaned = " ".join(str(date_str).split())
    for fmt in ("%A, %B %d, %Y", "%A, %b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None

def extract_eastern_time(time_str: str) -> str:
    s = str(time_str or "").strip()
    m = re.search(r"E:\s*([0-9:apmAPM\.]+)", s)
    return m.group(1) if m else s

def _is_late_night_eastern(time_et: str) -> bool:
    """True when the ET game start is 10 PM or later (Pacific-header carry-over guard)."""
    s = str(time_et or "").strip().lower().replace(" ", "")
    if "pm" not in s:
        return False
    m = re.match(r"(\d{1,2})(?::\d{2})?pm", s)
    if not m:
        return False
    hour = int(m.group(1))
    if hour == 12:
        return False
    return hour >= 10

def parse_today_games(league: str, html: str, today: date) -> List[Dict[str, Any]]:
    soup  = BeautifulSoup(html, "lxml")
    games: List[Dict[str, Any]] = []
    table = soup.select_one("table.schedule-container > tbody")
    if not table:
        log(league, "No schedule table found", "WARN")
        return games

    current_date: Optional[date] = None

    for tr in table.find_all("tr", recursive=False):
        classes = tr.get("class", []) or []

        if "schedweek" in classes:
            title_div = tr.select_one("div.schedule-week div.schedule-subhdr.title")
            if not title_div:
                continue
            span_list = title_div.find_all("span")
            if len(span_list) < 2:
                continue
            current_date = parse_date_str(span_list[1].get_text(strip=True))
            continue

        game_div = tr.select_one("div.schedule-game")
        if not game_div or current_date is None:
            continue

        yesterday        = today - timedelta(days=1)
        is_today_header  = (current_date == today)
        is_yest_header   = (current_date == yesterday)

        if not is_today_header and not is_yest_header:
            continue

        if is_yest_header:
            _pre = game_div.select_one("div.schedule-game-col.matchup")
            _raw = ""
            if _pre:
                _spans = _pre.find_all("span")
                if len(_spans) >= 2:
                    _raw = _spans[1].get_text(" ", strip=True)
            if not _is_late_night_eastern(extract_eastern_time(_raw)):
                continue

        rot_away = rot_home = None
        nums_div = game_div.select_one("div.schedule-game-col.nums")
        if nums_div:
            ns = nums_div.find_all("span")
            if len(ns) >= 2:
                rot_away = ns[0].get_text(strip=True) or None
                rot_home = ns[1].get_text(strip=True) or None

        matchup_div = game_div.select_one("div.schedule-game-col.matchup")
        if not matchup_div:
            continue
        spans = matchup_div.find_all("span")
        if len(spans) < 3:
            continue

        away_team = spans[0].get_text(strip=True)
        time_raw  = spans[1].get_text(" ", strip=True)
        home_team = spans[-1].get_text(strip=True)
        if not away_team or not home_team:
            continue

        games.append({
            "date":         today.isoformat(),
            "time_eastern": extract_eastern_time(time_raw),
            "away_team":    away_team,
            "home_team":    home_team,
            "rot_away":     rot_away,
            "rot_home":     rot_home,
            "league":       league.upper(),
        })

    log(league, f"Parsed {len(games)} games for {today.isoformat()}")
    return games


def fallback_games_from_odds(league: str, today: date) -> List[Dict[str, Any]]:
    """
    Fallback slate resolver:
    Use the existing odds scraper when schedule-page parsing yields zero games.
    This preserves ingest continuity when schedule markup changes for a league/day.
    """
    games: List[Dict[str, Any]] = []
    try:
        import odds_scraper  # local project module
    except Exception as e:
        log(league, f"[fallback] odds scraper import failed: {e}", "WARN")
        return games

    try:
        scraped, _count = odds_scraper.scrape_sport(str(league).upper())
    except Exception as e:
        log(league, f"[fallback] odds scrape failed: {e}", "WARN")
        return games

    try:
        odds_dir = os.path.join(os.path.dirname(__file__), "odds_data")
        saved_path = odds_scraper.save_excel(scraped, str(league).upper(), odds_dir)
    except Exception as e:
        log(league, f"[fallback] odds save failed: {e}", "WARN")
        return games

    if not saved_path or not os.path.exists(str(saved_path)):
        log(league, "[fallback] odds workbook not produced", "WARN")
        return games

    try:
        odds_df = pd.read_excel(str(saved_path))
    except Exception as e:
        log(league, f"[fallback] odds workbook read failed: {e}", "WARN")
        return games

    def _has_value(v: Any) -> bool:
        if v is None:
            return False
        s = str(v).strip().lower()
        return s not in {"", "nan", "none", "null"}

    for _, _row in odds_df.iterrows():
        try:
            row = _row.to_dict() if hasattr(_row, "to_dict") else dict(_row)
            row_date_raw = str(row.get("Date", "") or row.get("date", "") or "").strip()
            row_date = None
            if row_date_raw:
                try:
                    row_date = datetime.fromisoformat(row_date_raw).date()
                except Exception:
                    # tolerate YYYYMMDD or mixed date formats
                    try:
                        row_date = datetime.strptime(row_date_raw, "%Y%m%d").date()
                    except Exception:
                        row_date = None
            if row_date is None:
                try:
                    row_time = str(row.get("Time", "") or "").strip()
                    row_date = datetime.strptime(row_time.split()[0], "%m/%d").date().replace(year=today.year)
                except Exception:
                    row_date = None
            if row_date is not None and row_date != today:
                continue

            away_team = str(
                row.get("Away_Team", "")
                or row.get("Away", "")
                or row.get("away_team", "")
                or ""
            ).strip()
            home_team = str(
                row.get("Home_Team", "")
                or row.get("Home", "")
                or row.get("home_team", "")
                or ""
            ).strip()
            time_eastern = str(row.get("Time", "") or row.get("time_eastern", "") or "").strip()
            if not away_team or not home_team:
                continue
            # Keep team/time slate rows even when market fields are blank.
            # Stats ingestion/marrying must still execute for real games.
            has_market = any(
                _has_value(row.get(k))
                for k in (
                    "Away_ML", "Home_ML",
                    "Total", "OU_Line", "ou_line", "market_total",
                    "Away_Spread", "Home_Spread",
                )
            )
            games.append(
                {
                    "date": today.isoformat(),
                    "time_eastern": time_eastern,
                    "away_team": away_team,
                    "home_team": home_team,
                    "rot_away": None,
                    "rot_home": None,
                    "league": str(league).upper(),
                    "has_market": bool(has_market),
                }
            )
        except Exception:
            continue

    log(league, f"[fallback] odds-based slate recovered {len(games)} game(s) for {today.isoformat()}")
    return games

# ==============================================================================
# TEAMRANKINGS STATS  (NFL / NBA / MLB / NCAAF / NCAAB)
# ==============================================================================

def scrape_teamrankings_stat(url: str, league: str) -> pd.Series:
    try:
        resp = _safe_requests_get(url, league, timeout=REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        soup  = BeautifulSoup(resp.text, "lxml")
        table = soup.select_one("table.tr-table")
        if not table:
            log(league, f"No stats table at {url}", "WARN")
            return pd.Series(dtype=object)
        stat_data: Dict[str, str] = {}
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            team  = cells[1].get_text(strip=True)
            value = cells[2].get_text(strip=True)
            if team:
                stat_data[team] = value
        return pd.Series(stat_data)
    except Exception as e:
        log(league, f"ERROR scrape_teamrankings_stat: {e}", "ERROR")
        return pd.Series(dtype=object)

# ==============================================================================
# MONEYPUCK â€” SHARED PLAYWRIGHT HELPER
# ==============================================================================

def _moneypuck_select_season_type(page: Any, season_type: str) -> None:
    """
    Interact with MoneyPuck dropdowns to select season (2025-2026) and
    situation type (Playoffs or Regular Season) before capturing HTML.

    season_type: "regular" -> selects "Regular Season"
                 "playoffs" -> selects "Playoffs"
    """
    label_map = {
        "regular":  "Regular Season",
        "playoffs": "Playoffs",
    }
    target_label = label_map.get(season_type.lower(), "Regular Season")

    try:
        selects = page.query_selector_all("select")
        for sel in selects:
            options = sel.evaluate("el => [...el.options].map(o => o.text.trim())")
            if target_label in options:
                sel.select_option(label=target_label)
                log("nhl", f"Dropdown set to: {target_label}")
                time.sleep(2)
                # Wait for table to re-render after selection
                try:
                    page.wait_for_function(
                        "() => document.querySelector('table') !== null",
                        timeout=8000
                    )
                except Exception:
                    pass
                time.sleep(1)
                return
        log("nhl", f"WARNING: Could not find dropdown with option '{target_label}'", "WARN")
    except Exception as e:
        log("nhl", f"WARNING: Dropdown selection failed: {e}", "WARN")

# ==============================================================================
# MONEYPUCK â€” NHL TEAM STATS
# ==============================================================================

def _parse_moneypuck_table(
    html: str,
    table_id: str,
    label: str,
    index_is_team: bool = True,
) -> pd.DataFrame:
    """
    Generic MoneyPuck HTML table parser.

    Handles the ghost-row bug: MoneyPuck renders two <tr> elements per team â€”
    one real data row and one hidden expandable row. The hidden row has an
    empty or rank-only first cell. We skip those rows explicitly.

    index_is_team:
      True  -> first column after rank is the team abbreviation (teams table)
      False -> first column is goalie name (goalies table)
    """
    soup  = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"id": table_id})
    if not table:
        log("nhl", f"ERROR: #{table_id} not found in HTML", "ERROR")
        return pd.DataFrame()

    all_rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        all_rows.append([c.get_text(strip=True) for c in cells])

    if len(all_rows) < 2:
        log("nhl", f"ERROR: Not enough rows in #{table_id}", "ERROR")
        return pd.DataFrame()

    headers   = all_rows[0]
    data_rows = all_rows[1:]

    fixed_rows: List[List[str]] = []
    for r in data_rows:
        first = r[0].strip() if r else ""
        if not first:
            continue
        if len(r) <= 3 and first.isdigit():
            continue
        if (
            len(r) >= len(headers) + 3
            and str(r[1]).strip().isdigit()
            and str(r[2]).strip() == ""
            and re.match(r"^\d+", first)
        ):
            r = r[3:]
        elif not first.isdigit():
            continue
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[: len(headers)]
        fixed_rows.append(r)

    if not fixed_rows:
        log("nhl", f"WARNING: No data rows found in #{table_id} after ghost-row filter", "WARN")
        return pd.DataFrame()

    df = pd.DataFrame(fixed_rows, columns=headers)

    # Drop the leading rank column (always col 0 â€” pure integers)
    if df.columns[0].strip() == "" or df.iloc[:, 0].str.isdigit().all():
        df = df.iloc[:, 1:]

    # Set index to entity column.
    if not df.empty:
        idx_col = df.columns[0]
        if index_is_team and "Team" in df.columns:
            idx_col = "Team"
        df = df.set_index(idx_col)

    if index_is_team:
        # Convert abbreviations -> full team names
        new_index = []
        for abbrev in df.index:
            clean = re.sub(r"^\d+", "", str(abbrev).strip()).strip()
            new_index.append(NHL_ABBREV_TO_FULL.get(clean.upper(), clean))
        df.index = new_index

    # Drop explicitly unwanted columns
    cols_to_drop = [c for c in df.columns if c in NHL_DROP_COLUMNS]
    if cols_to_drop:
        df.drop(columns=cols_to_drop, inplace=True)
        log("nhl", f"Dropped columns: {cols_to_drop}")

    df = df.replace("", pd.NA).fillna("MISSING_FROM_SOURCE")
    return df


def scrape_moneypuck_nhl_teams(season_type: str = "regular") -> pd.DataFrame:
    """
    Scrape moneypuck.com/teams.htm for the requested season_type.
    Returns a DataFrame indexed by full team name.
    season_type: "regular" | "playoffs"
    """
    url   = "https://moneypuck.com/teams.htm"
    label = season_type.upper()
    log("nhl", f"Scraping NHL team stats [{label}]: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
            context = browser.new_context(user_agent=USER_AGENT)
            page    = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("table#teamsTable", timeout=15000)
                time.sleep(2)
                _moneypuck_select_season_type(page, season_type)
                page.wait_for_selector("table#teamsTable", timeout=10000)
                time.sleep(2)
                html = page.content()
            finally:
                browser.close()

        df = _parse_moneypuck_table(html, "teamsTable", label, index_is_team=True)
        log("nhl", f"NHL team stats [{label}]: {len(df)} teams x {len(df.columns)} cols")
        return df

    except Exception as e:
        log("nhl", f"ERROR scraping NHL teams [{label}]: {e}", "ERROR")
        traceback.print_exc()
        return pd.DataFrame()


# ==============================================================================
# MONEYPUCK â€” NHL GOALIE STATS
# ==============================================================================

def scrape_moneypuck_nhl_goalies(season_type: str = "regular") -> pd.DataFrame:
    """
    Scrape moneypuck.com/goalies.htm for the requested season_type.
    Returns a DataFrame indexed by goalie name with team column intact.
    season_type: "regular" | "playoffs"
    """
    url   = "https://moneypuck.com/goalies.htm"
    label = season_type.upper()
    log("nhl", f"Scraping NHL goalie stats [{label}]: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
            context = browser.new_context(user_agent=USER_AGENT)
            page    = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # MoneyPuck goalies table may have a different ID â€” try both known IDs
                for tbl_id in ("goaliesTable", "playerTable", "skaterTable"):
                    try:
                        page.wait_for_selector(f"table#{tbl_id}", timeout=8000)
                        found_table_id = tbl_id
                        break
                    except Exception:
                        continue
                else:
                    # Fallback: wait for any table
                    page.wait_for_selector("table", timeout=15000)
                    found_table_id = None
                time.sleep(2)
                _moneypuck_select_season_type(page, season_type)
                time.sleep(2)
                html = page.content()
            finally:
                browser.close()

        # Detect actual table ID from HTML if fallback was used
        if found_table_id is None:
            soup = BeautifulSoup(html, "lxml")
            tbl  = soup.find("table")
            found_table_id = tbl.get("id", "goaliesTable") if tbl else "goaliesTable"
            log("nhl", f"Goalie table ID detected as: #{found_table_id}", "WARN")

        df = _parse_moneypuck_table(html, found_table_id, label, index_is_team=False)
        log("nhl", f"NHL goalie stats [{label}]: {len(df)} goalies x {len(df.columns)} cols")
        return df

    except Exception as e:
        log("nhl", f"ERROR scraping NHL goalies [{label}]: {e}", "ERROR")
        traceback.print_exc()
        return pd.DataFrame()

# ==============================================================================
# PLAYOFF ELIGIBILITY CHECK
# ==============================================================================

def _get_team_playoff_gp(team_name: str, playoff_teams_df: pd.DataFrame) -> int:
    """
    Read the GamesPlayed value from a MoneyPuck playoffs DataFrame for a team.
    Returns 0 if not found or if the value is MISSING_FROM_SOURCE.
    """
    if playoff_teams_df is None or playoff_teams_df.empty:
        return 0
    row = find_team_stats(team_name, playoff_teams_df, "nhl")
    if row is None:
        return 0
    gp_val = row.get("GamesPlayed", "0")
    try:
        return int(str(gp_val).strip())
    except (ValueError, TypeError):
        return 0


def determine_nhl_season_mode(
    games: List[Dict[str, Any]],
    playoff_teams_df: pd.DataFrame,
) -> Tuple[str, Dict[str, int]]:
    """
    Decide whether today needs regular, playoff, or both stat sets.

    Returns:
        mode (str): "regular" | "playoffs" | "both"
        gp_map (dict): {team_name: playoff_gp} for all teams playing today
    """
    if not games:
        return "regular", {}

    gp_map: Dict[str, int] = {}
    for g in games:
        for team in (g["away_team"], g["home_team"]):
            if team not in gp_map:
                gp_map[team] = _get_team_playoff_gp(team, playoff_teams_df)

    teams_qualifying = {t for t, gp in gp_map.items() if gp >= PLAYOFF_GP_THRESHOLD}

    if not teams_qualifying:
        return "regular", gp_map

    all_teams = set(gp_map.keys())
    if all_teams == teams_qualifying:
        return "playoffs", gp_map

    return "both", gp_map

# ==============================================================================
# CROSS-LEAGUE STAT DISPATCH
# ==============================================================================

def get_all_stats_for_league(league: str) -> pd.DataFrame:
    """For non-NHL leagues only. NHL is handled separately in run_nhl()."""
    log(league, "Fetching TeamRankings stats...")
    stat_urls = STATS_URLS.get(league, [])
    all_stats: Dict[str, pd.Series] = {}

    for idx, url in enumerate(stat_urls, 1):
        stat_name = url.split("/stat/")[-1]
        log(league, f"[{idx}/{len(stat_urls)}] {stat_name}")
        s = scrape_teamrankings_stat(url, league)
        if not s.empty:
            all_stats[stat_name] = s
        time.sleep(0.5)

    if not all_stats:
        log(league, "No stats scraped", "WARN")
        return pd.DataFrame()

    df = pd.DataFrame(all_stats)
    df = df.replace("", pd.NA).fillna("MISSING_FROM_SOURCE")
    log(league, f"{len(df)} teams x {len(df.columns)} stats")
    return df

# ==============================================================================
# TEAM NAME MATCHING
# ==============================================================================

def normalize_team_name(name: str) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_team_stats(
    team_name: str,
    stats_df: pd.DataFrame,
    league: str,
) -> Optional[pd.Series]:
    if stats_df is None or stats_df.empty:
        return None

    target = normalize_team_name(team_name)

    for idx in stats_df.index:
        if normalize_team_name(str(idx)) == target:
            return stats_df.loc[idx]

    if league == "nba":
        city_target = NBA_NICK_TO_CITY.get(target, "")
        if city_target:
            for idx in stats_df.index:
                if normalize_team_name(str(idx)) == city_target:
                    return stats_df.loc[idx]

    aliases = TEAM_ALIASES.get(league, {})
    for full_name, alias_list in aliases.items():
        if team_name == full_name or team_name in alias_list:
            full_norm = normalize_team_name(full_name)
            for idx in stats_df.index:
                idxn = normalize_team_name(str(idx))
                if idxn == full_norm or full_norm in idxn:
                    return stats_df.loc[idx]

    tset = set(target.split())
    best, best_score = None, 0
    for idx in stats_df.index:
        iset  = set(normalize_team_name(str(idx)).split())
        score = len(tset & iset)
        if score > best_score:
            best_score = score
            best       = idx

    if best is not None and best_score >= 1:
        return stats_df.loc[best]

    return None

# ==============================================================================
# WORKBOOK HELPERS
# ==============================================================================

def sanitize_sheet_name(name: str) -> str:
    name = re.sub(r"[\\/*\[\]:?]", "", name)
    return name[:31]


def unique_sheet_name(base: str, used: set[str]) -> str:
    """Return an Excel-safe unique sheet name (handles 31-char collisions)."""
    clean = sanitize_sheet_name(base) or "Sheet"
    if clean not in used:
        used.add(clean)
        return clean
    i = 2
    while True:
        suffix = f"_{i}"
        cand = f"{clean[:31 - len(suffix)]}{suffix}"
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def _write_stats_status_marker(
    league: str,
    today: date,
    status: str,
    *,
    games: int = 0,
    teams: int = 0,
    stats_rows: int = 0,
    schedules_file: str = "",
    rawstats_file: str = "",
    matchups_file: str = "",
    error: str = "",
    note: str = "",
) -> None:
    marker  = OUTPUT_DIR / f"StatsStatus_{league.upper()}_{today.strftime('%Y%m%d')}.json"
    payload = {
        "league":         league.upper(),
        "date":           today.isoformat(),
        "status":         status,
        "games_found":    int(games),
        "teams_found":    int(teams),
        "stats_rows":     int(stats_rows),
        "schedules_file": schedules_file,
        "rawstats_file":  rawstats_file,
        "matchups_file":  matchups_file,
        "error":          error,
        "note":           note,
        "updated_at":     datetime.now().isoformat(),
    }
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_schedules_workbook(
    league: str,
    games: List[Dict[str, Any]],
    today: date,
) -> Optional[Path]:
    if not games:
        return None
    filename = OUTPUT_DIR / f"Schedules_{league.upper()}_{today.strftime('%Y%m%d')}.xlsx"
    rows = []
    for i, g in enumerate(games, 1):
        rows.append({
            "Game #":    i,
            "Date":      g.get("date", ""),
            "Time (ET)": g.get("time_eastern", ""),
            "Away":      g.get("away_team", ""),
            "Home":      g.get("home_team", ""),
            "Away Rot":  g.get("rot_away", ""),
            "Home Rot":  g.get("rot_home", ""),
        })
    pd.DataFrame(rows).to_excel(filename, index=False, sheet_name="Schedule")
    log(league, f"Schedules workbook: {filename}")
    return filename


def create_raw_stats_workbook(
    league: str,
    stats_df: pd.DataFrame,
    today: date,
    suffix: str = "",
) -> Optional[Path]:
    """
    suffix: optional string appended before .xlsx
    e.g. suffix="regular"  -> RawStats_NHL_20260508_regular.xlsx
         suffix="playoffs" -> RawStats_NHL_20260508_playoffs.xlsx
         suffix="goalies_playoffs" -> RawStats_NHL_Goalies_20260508_playoffs.xlsx
    """
    if stats_df is None or stats_df.empty:
        return None
    date_str  = today.strftime("%Y%m%d")
    suf_part  = f"_{suffix}" if suffix else ""
    filename  = OUTPUT_DIR / f"RawStats_{league.upper()}_{date_str}{suf_part}.xlsx"
    export = stats_df.reset_index()
    export = export.rename(columns={export.columns[0]: "Team"})
    export.to_excel(filename, index=False, sheet_name="AllStats")
    log(league, f"RawStats workbook: {filename}")
    return filename


def create_matchups_workbook(
    league: str,
    games: List[Dict[str, Any]],
    stats_df: pd.DataFrame,
    today: date,
    *,
    playoff_df: Optional[pd.DataFrame] = None,
    goalies_df: Optional[pd.DataFrame] = None,
    gp_map: Optional[Dict[str, int]] = None,
) -> Optional[Path]:
    """
    Build the per-game matchup workbook.

    For NHL:
      - Selects playoff stats if BOTH teams have >= PLAYOFF_GP_THRESHOLD playoff games.
      - Falls back to regular season stats otherwise.
      - Appends goalie stats as a separate section when available.
      - Records which stat source was used in the matchup sheet.
    """
    if not games or (stats_df is None or stats_df.empty):
        log(league, "No games or no stats â€” skipping matchups workbook", "WARN")
        return None

    filename = OUTPUT_DIR / f"Matchups_{league.upper()}_{today.strftime('%Y%m%d')}.xlsx"
    gp_map   = gp_map or {}

    with pd.ExcelWriter(filename, engine="xlsxwriter") as writer:
        used_sheet_names: set[str] = set()
        for g in games:
            away_name = g["away_team"]
            home_name = g["home_team"]

            # ---- Choose stat source for this specific matchup (NHL only) ----
            active_df    = stats_df
            source_label = "REGULAR_SEASON"

            if league == "nhl" and playoff_df is not None and not playoff_df.empty:
                away_gp = gp_map.get(away_name, 0)
                home_gp = gp_map.get(home_name, 0)
                if away_gp >= PLAYOFF_GP_THRESHOLD and home_gp >= PLAYOFF_GP_THRESHOLD:
                    active_df    = playoff_df
                    source_label = f"PLAYOFFS (away GP={away_gp}, home GP={home_gp})"
                else:
                    source_label = (
                        f"REGULAR_SEASON "
                        f"(playoff GP thin: away={away_gp}, home={home_gp}, "
                        f"threshold={PLAYOFF_GP_THRESHOLD})"
                    )

            away_stats = find_team_stats(away_name, active_df, league)
            home_stats = find_team_stats(home_name, active_df, league)

            matchup_rows: List[Dict[str, Any]] = []

            # Metadata rows â€” written to BOTH team columns
            dval = clean_cell(g.get("date", ""))
            tval = clean_cell(g.get("time_eastern", ""))
            matchup_rows.append({"Stat": "Date",         away_name: dval, home_name: dval})
            matchup_rows.append({"Stat": "Time (ET)",    away_name: tval, home_name: tval})
            matchup_rows.append({"Stat": "STATS_SOURCE", away_name: source_label, home_name: source_label})

            # Team stats rows
            all_stats: set = set()
            if away_stats is not None:
                all_stats.update(away_stats.index.tolist())
            if home_stats is not None:
                all_stats.update(home_stats.index.tolist())

            if not all_stats:
                matchup_rows.append({"Stat": "NO STATS", away_name: "FAILED", home_name: "FAILED"})
            else:
                for stat in sorted(map(str, all_stats)):
                    av = away_stats.get(stat, "MISSING_FROM_SOURCE") if away_stats is not None else "MISSING_FROM_SOURCE"
                    hv = home_stats.get(stat, "MISSING_FROM_SOURCE") if home_stats is not None else "MISSING_FROM_SOURCE"
                    matchup_rows.append({"Stat": stat, away_name: clean_cell(av), home_name: clean_cell(hv)})

            # Goalie stats section (NHL only)
            if league == "nhl" and goalies_df is not None and not goalies_df.empty:
                matchup_rows.append({"Stat": "--- GOALIE STATS ---", away_name: "", home_name: ""})
                # Filter goalies by team abbreviation column if present
                away_abbrev = None
                home_abbrev = None
                for abbrev, full in NHL_ABBREV_TO_FULL.items():
                    if full == away_name:
                        away_abbrev = abbrev
                    if full == home_name:
                        home_abbrev = abbrev

                team_col = None
                for col in goalies_df.columns:
                    if col.strip().lower() in ("team", "tm"):
                        team_col = col
                        break

                for goalie_name, goalie_row in goalies_df.iterrows():
                    if team_col:
                        team_val = str(goalie_row.get(team_col, "")).strip().upper()
                        is_away = away_abbrev and team_val == away_abbrev.upper()
                        is_home = home_abbrev and team_val == home_abbrev.upper()
                        if not is_away and not is_home:
                            continue
                    else:
                        # No team column â€” include all and let the model sort it
                        is_away = is_home = True

                    for stat, val in goalie_row.items():
                        row_key = f"  {goalie_name} | {stat}"
                        if is_away:
                            matchup_rows.append({"Stat": row_key, away_name: clean_cell(val), home_name: ""})
                        elif is_home:
                            matchup_rows.append({"Stat": row_key, away_name: "", home_name: clean_cell(val)})

            # Coverage summary
            data_rows = [
                r for r in matchup_rows
                if str(r.get("Stat", "")).strip() not in
                   ("Date", "Time (ET)", "STATS_SOURCE", "NO STATS", "--- GOALIE STATS ---")
                and not str(r.get("Stat", "")).startswith("  ")
            ]
            total   = len(data_rows)
            missing = sum(
                1 for r in data_rows
                if r.get(away_name) == "MISSING_FROM_SOURCE"
                or r.get(home_name) == "MISSING_FROM_SOURCE"
            )
            coverage = f"{total - missing}/{total}" if total else "0/0"
            matchup_rows.append({"Stat": "STATS_COVERAGE", away_name: coverage, home_name: coverage})

            sheet = unique_sheet_name(f"{league.upper()}_{away_name}@{home_name}", used_sheet_names)
            pd.DataFrame(matchup_rows).to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.sheets[sheet]
            ws.set_column("A:A", 50)
            ws.set_column("B:Z", 24)

    log(league, f"Matchups workbook: {filename}")
    return filename


def validate_matchups_workbook(path: Optional[Path]) -> Dict[str, Any]:
    """
    Enforce per-game stats mapping contract from the produced matchup workbook.
    A game fails if:
      - NO STATS row is FAILED, or
      - STATS_COVERAGE is 0/0.
    """
    out: Dict[str, Any] = {"games": 0, "failed_games": 0, "failed_sheets": []}
    if path is None or not path.exists():
        out["failed_games"] = 1
        out["failed_sheets"] = ["<workbook_missing>"]
        return out
    try:
        xls = pd.ExcelFile(path)
    except Exception:
        out["failed_games"] = 1
        out["failed_sheets"] = ["<workbook_unreadable>"]
        return out

    fails: List[str] = []
    for sheet in xls.sheet_names:
        out["games"] += 1
        try:
            df = pd.read_excel(path, sheet_name=sheet)
        except Exception:
            fails.append(sheet)
            continue
        if df is None or df.empty or len(df.columns) < 3:
            fails.append(sheet)
            continue
        stat_col = str(df.columns[0])
        away_col = str(df.columns[1])
        home_col = str(df.columns[2])

        # Hard fail if explicit no-stats marker indicates failed mapping.
        no_stats = df[df[stat_col].astype(str).str.strip().str.upper() == "NO STATS"]
        if not no_stats.empty:
            av = str(no_stats.iloc[0].get(away_col, "") or "").strip().upper()
            hv = str(no_stats.iloc[0].get(home_col, "") or "").strip().upper()
            if av == "FAILED" or hv == "FAILED":
                fails.append(sheet)
                continue

        # Hard fail if coverage is zero.
        cov = df[df[stat_col].astype(str).str.strip().str.upper() == "STATS_COVERAGE"]
        if not cov.empty:
            cv = str(cov.iloc[0].get(away_col, "") or "").strip()
            m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", cv)
            if m:
                num = int(m.group(1))
                den = int(m.group(2))
                if den == 0 or num == 0:
                    fails.append(sheet)
                    continue
    out["failed_sheets"] = fails
    out["failed_games"] = len(fails)
    return out

# ==============================================================================
# NHL ORCHESTRATOR
# ==============================================================================

def run_nhl(games: List[Dict[str, Any]], today: date) -> None:
    """
    Full NHL scrape pipeline with smart playoff gating.

    Step 1: Always scrape regular season team stats (baseline).
    Step 2: Quick playoff GP check using a lightweight MoneyPuck playoffs scrape.
    Step 3: If any matchup has BOTH teams >= PLAYOFF_GP_THRESHOLD playoff GP:
              - Scrape full playoff team stats
              - Scrape goalie stats for the appropriate season type
            Else:
              - Scrape regular season goalie stats only
    Step 4: Build matchups workbook â€” each game uses the correct stat source.
    Step 5: Write StatsStatus JSON with full audit trail.
    """
    log("nhl", "=" * 60)
    log("nhl", "NHL PIPELINE START")

    schedules_path   = None
    regular_path     = None
    playoffs_path    = None
    goalies_path     = None
    matchups_path    = None
    season_mode      = "regular"
    gp_map: Dict[str, int] = {}
    playoff_df: Optional[pd.DataFrame]  = None
    goalies_df: Optional[pd.DataFrame]  = None

    try:
        # ---- Step 1: Regular season team stats (always) ----
        log("nhl", "Step 1/5: Regular season team stats")
        regular_df = scrape_moneypuck_nhl_teams(season_type="regular")
        regular_path = create_raw_stats_workbook("nhl", regular_df, today, suffix="regular")

        # ---- Step 2: Playoff GP eligibility check ----
        log("nhl", "Step 2/5: Checking playoff GP eligibility")
        # We do a lightweight MoneyPuck playoffs scrape just for GamesPlayed.
        # This is fast because we only need one column â€” but we store the full
        # result so we avoid a second scrape if playoffs are confirmed.
        playoff_check_df = scrape_moneypuck_nhl_teams(season_type="playoffs")
        season_mode, gp_map = determine_nhl_season_mode(games, playoff_check_df)
        log("nhl", f"Season mode: {season_mode} | GP map: {gp_map}")

        # ---- Step 3: Conditional playoff + goalie scrapes ----
        if season_mode in ("playoffs", "both"):
            log("nhl", "Step 3/5: Playoff threshold met â€” saving playoff team stats")
            playoff_df   = playoff_check_df  # already scraped â€” reuse it
            playoffs_path = create_raw_stats_workbook("nhl", playoff_df, today, suffix="playoffs")

            log("nhl", "Step 3b/5: Scraping playoff goalie stats")
            goalies_df   = scrape_moneypuck_nhl_goalies(season_type="playoffs")
            goalies_path = create_raw_stats_workbook("nhl", goalies_df, today, suffix="goalies_playoffs")
        else:
            log("nhl", "Step 3/5: Playoff threshold NOT met â€” scraping regular goalie stats")
            goalies_df   = scrape_moneypuck_nhl_goalies(season_type="regular")
            goalies_path = create_raw_stats_workbook("nhl", goalies_df, today, suffix="goalies_regular")

        # ---- Step 4: Schedule + matchups workbooks ----
        log("nhl", "Step 4/5: Building schedule + matchups workbooks")
        schedules_path = create_schedules_workbook("nhl", games, today)
        matchups_path  = create_matchups_workbook(
            "nhl", games, regular_df, today,
            playoff_df=playoff_df,
            goalies_df=goalies_df,
            gp_map=gp_map,
        )

        # ---- Step 5: Status marker ----
        all_teams = set()
        for g in games:
            all_teams.add(g["away_team"])
            all_teams.add(g["home_team"])

        note = (
            f"season_mode={season_mode} | "
            f"playoff_GP_threshold={PLAYOFF_GP_THRESHOLD} | "
            f"playoff_scrape={'YES' if playoff_df is not None else 'SKIPPED'} | "
            f"goalie_scrape={'YES' if goalies_df is not None else 'SKIPPED'} | "
            f"gp_map={gp_map}"
        )
        _audit = validate_matchups_workbook(matchups_path)
        _ready = bool(matchups_path) and int(_audit.get("failed_games", 0)) == 0
        _write_stats_status_marker(
            "nhl", today,
            "READY" if _ready else "FAILED",
            games=len(games),
            teams=len(all_teams),
            stats_rows=len(regular_df) if not regular_df.empty else 0,
            schedules_file=schedules_path.name if schedules_path else "",
            rawstats_file=regular_path.name if regular_path else "",
            matchups_file=matchups_path.name if matchups_path else "",
            note=(
                f"{note} | contract_games={_audit.get('games', 0)} "
                f"| contract_failed={_audit.get('failed_games', 0)} "
                f"| failed_sheets={_audit.get('failed_sheets', [])}"
            ),
            error="" if _ready else f"Stats mapping contract failed: {_audit.get('failed_sheets', [])}",
        )
        log("nhl", "Step 5/5: Status marker written")

    except Exception as e:
        err_text = f"{type(e).__name__}: {e}"
        log("nhl", f"FATAL ERROR: {err_text}", "ERROR")
        for ln in traceback.format_exc().strip().splitlines():
            log("nhl", ln, "ERROR")
        _write_stats_status_marker(
            "nhl", today, "FAILED",
            games=len(games),
            schedules_file=schedules_path.name if schedules_path else "",
            rawstats_file=regular_path.name if regular_path else "",
            matchups_file=matchups_path.name if matchups_path else "",
            error=err_text,
        )

    log("nhl", "NHL PIPELINE DONE")

# ==============================================================================
# MAIN
# ==============================================================================

def main() -> None:
    today = date.today()

    print("\n" + "=" * 78)
    print("SPORTS STATS SCRAPER")
    print(f"  NHL  -> MoneyPuck (Playwright) | Teams + Goalies | Regular + Conditional Playoffs")
    print(f"  Other -> TeamRankings (requests)")
    print(f"  Date  -> {today.isoformat()}")
    print(f"  Playoff GP Threshold -> {PLAYOFF_GP_THRESHOLD} games")
    print("=" * 78 + "\n")

    for league in LEAGUE_URLS.keys():
        log(league, "-" * 60)
        log(league, "START")

        schedules_path = None
        rawstats_path  = None
        matchups_path  = None

        try:
            schedule_url = LEAGUE_URLS[league]
            html         = fetch_html_playwright(league, schedule_url)
            games        = parse_today_games(league, html, today)

            if not games:
                games = fallback_games_from_odds(league, today)

            if not games:
                log(league, "No games today")
                _write_stats_status_marker(
                    league, today, "NO_GAMES",
                    games=0,
                    note="No slate for target date.",
                )
                log(league, "DONE")
                continue

            # NHL has its own dedicated orchestrator
            if league == "nhl":
                run_nhl(games, today)
                log(league, "DONE")
                continue

            # All other leagues
            stats_df = get_all_stats_for_league(league)

            schedules_path = create_schedules_workbook(league, games, today)
            rawstats_path  = create_raw_stats_workbook(league, stats_df, today)
            matchups_path  = create_matchups_workbook(league, games, stats_df, today)

            all_teams = set()
            for g in games:
                all_teams.add(g.get("away_team", ""))
                all_teams.add(g.get("home_team", ""))

            _audit = validate_matchups_workbook(matchups_path)
            _ready = bool(rawstats_path) and bool(matchups_path) and int(_audit.get("failed_games", 0)) == 0
            _write_stats_status_marker(
                league, today,
                "READY" if _ready else "FAILED",
                games=len(games),
                teams=len(all_teams),
                stats_rows=len(stats_df) if isinstance(stats_df, pd.DataFrame) else 0,
                schedules_file=schedules_path.name if schedules_path else "",
                rawstats_file=rawstats_path.name if rawstats_path else "",
                matchups_file=matchups_path.name if matchups_path else "",
                note=(
                    f"contract_games={_audit.get('games', 0)} "
                    f"| contract_failed={_audit.get('failed_games', 0)} "
                    f"| failed_sheets={_audit.get('failed_sheets', [])}"
                ),
                error="" if _ready else (
                    "RawStats/Matchups missing or stats mapping contract failed: "
                    f"{_audit.get('failed_sheets', [])}"
                ),
            )

        except Exception as e:
            err_text = f"{type(e).__name__}: {e}"
            log(league, f"FATAL ERROR: {err_text}", "ERROR")
            for ln in traceback.format_exc().strip().splitlines():
                log(league, ln, "ERROR")
            _write_stats_status_marker(
                league, today, "FAILED",
                games=0,
                schedules_file=schedules_path.name if schedules_path else "",
                rawstats_file=rawstats_path.name if rawstats_path else "",
                matchups_file=matchups_path.name if matchups_path else "",
                error=err_text,
            )

        log(league, "DONE")
        time.sleep(2)

    print("\n" + "=" * 78)
    print("ALL DONE")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
