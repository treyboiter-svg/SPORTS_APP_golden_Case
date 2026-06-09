"""
STRENGTH OF SCHEDULE SCRAPER

Scrapes today's games and fetches comprehensive SOS/performance data for each team.

Sources:
- ScoresAndOdds.com: Today's games schedule
- TeamRankings.com: SOS rankings, records, performance metrics

Outputs: sos_data/SOS_LEAGUE_YYYYMMDD.xlsx (one file per sport)
"""

import os
import re
import sys
import time
import json
import argparse
import difflib
import traceback
from datetime import datetime, date as date_type
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import pytz
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════════════════
# FIX 5: NHL city-only → full franchise name normalization
# ═══════════════════════════════════════════════════════════════════════════════
NHL_NAME_MAP = {
    "Washington": "Washington Capitals",
    "Boston": "Boston Bruins",
    "NY Rangers": "New York Rangers",
    "New Jersey": "New Jersey Devils",
    "Philadelphia": "Philadelphia Flyers",
    "Pittsburgh": "Pittsburgh Penguins",
    "Nashville": "Nashville Predators",
    "Buffalo": "Buffalo Sabres",
    "Montreal": "Montreal Canadiens",
    "Los Angeles": "Los Angeles Kings",
    "Vancouver": "Vancouver Canucks",
    "Winnipeg": "Winnipeg Jets",
    "Utah": "Utah Mammoth",
    "Utah Hockey Club": "Utah Mammoth",
    "Utah HC": "Utah Mammoth",
    "Utah Mammoth": "Utah Mammoth",
    "Columbus": "Columbus Blue Jackets",
    "Tampa Bay": "Tampa Bay Lightning",
    "Toronto": "Toronto Maple Leafs",
    "Carolina": "Carolina Hurricanes",
    "Calgary": "Calgary Flames",
    "NY Islanders": "New York Islanders",
    "San Jose": "San Jose Sharks",
    "Ottawa": "Ottawa Senators",
    "Seattle": "Seattle Kraken",
    "Anaheim": "Anaheim Ducks",
    "Chicago": "Chicago Blackhawks",
    "Colorado": "Colorado Avalanche",
    "Dallas": "Dallas Stars",
    "Detroit": "Detroit Red Wings",
    "Edmonton": "Edmonton Oilers",
    "Florida": "Florida Panthers",
    "Minnesota": "Minnesota Wild",
    "Vegas": "Vegas Golden Knights",
    "St. Louis": "St. Louis Blues",
    "St Louis": "St. Louis Blues",
}


NHL_ABBR_MAP = {
    "anaheim ducks": "ana",
    "arizona coyotes": "ari",
    "boston bruins": "bos",
    "buffalo sabres": "buf",
    "calgary flames": "cgy",
    "carolina hurricanes": "car",
    "chicago blackhawks": "chi",
    "colorado avalanche": "col",
    "columbus blue jackets": "cbj",
    "dallas stars": "dal",
    "detroit red wings": "det",
    "edmonton oilers": "edm",
    "florida panthers": "fla",
    "los angeles kings": "lak",
    "minnesota wild": "min",
    "montreal canadiens": "mtl",
    "nashville predators": "nsh",
    "new jersey devils": "njd",
    "new york islanders": "nyi",
    "new york rangers": "nyr",
    "ottawa senators": "ott",
    "philadelphia flyers": "phi",
    "pittsburgh penguins": "pit",
    "san jose sharks": "sjs",
    "seattle kraken": "sea",
    "st louis blues": "stl",
    "tampa bay lightning": "tbl",
    "toronto maple leafs": "tor",
    "utah mammoth": "uta",
    "vancouver canucks": "van",
    "vegas golden knights": "vgk",
    "washington capitals": "wsh",
    "winnipeg jets": "wpg",
}


def _normalize_nhl_name(name: str, sport: str) -> str:
    """If sport is NHL, expand city-only names to full franchise names."""
    if sport.lower() != "nhl":
        return name
    return NHL_NAME_MAP.get(name.strip(), name.strip())


def _nhl_abbrev_candidates(team_name: str) -> List[str]:
    """Return NHL abbreviation candidates (lowercase) for a team label."""
    expanded = clean_team_name(_normalize_nhl_name(team_name, "nhl")).lower().strip()
    cands: List[str] = []
    direct = NHL_ABBR_MAP.get(expanded, "")
    if direct:
        cands.append(direct)
    raw = clean_team_name(team_name).lower().strip()
    if raw and raw != expanded:
        alt = NHL_ABBR_MAP.get(raw, "")
        if alt and alt not in cands:
            cands.append(alt)
    # Handle city-only keys routed through NHL_NAME_MAP.
    mapped = NHL_NAME_MAP.get(team_name.strip(), "")
    if mapped:
        mapped_norm = clean_team_name(mapped).lower().strip()
        mapped_abbr = NHL_ABBR_MAP.get(mapped_norm, "")
        if mapped_abbr and mapped_abbr not in cands:
            cands.append(mapped_abbr)
    return cands
from playwright.sync_api import sync_playwright, Page, Browser, Error as PlaywrightError

# Ensure local imports work even when launched from a different cwd.
_BASE_DIR = Path(__file__).resolve().parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from game_resolver import build_resolvers_from_schedule_dir, make_game_id, write_unresolved_csv, check_unresolved_threshold
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils.dataframe import dataframe_to_rows

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL_SCORES = "https://www.scoresandodds.com"
BASE_URL_RANKINGS = "https://www.teamrankings.com"

SPORTS_CONFIG = {
    "nfl": {
        "scores_path": "/nfl/odds",
        "rankings_path": "/nfl/ranking",
        "sos_path": "/nfl/ranking/schedule-strength-by-other",
        "record_path": "/nfl/trends/win_trends",
        "ppg_path": "/nfl/stat/points-per-game",
        "opp_ppg_path": "/nfl/stat/opponent-points-per-game",
        "home_record_path": "/nfl/trend/win_trends/is_home",
        "away_record_path": "/nfl/trend/win_trends/is_away",
        "last5_path": "/nfl/trends/win_trends/?range=weekly_last_5",
        "ats_path": "/nfl/trends/ats_trends",
    },
    "nba": {
        "scores_path": "/nba/odds",
        "rankings_path": "/nba/ranking",
        "sos_path": "/nba/ranking/schedule-strength-by-other",
        "record_path": "/nba/trends/win_trends",
        "ppg_path": "/nba/stat/points-per-game",
        "opp_ppg_path": "/nba/stat/opponent-points-per-game",
        "home_record_path": "/nba/trend/win_trends/is_home",
        "away_record_path": "/nba/trend/win_trends/is_away",
        "last5_path": "/nba/trends/win_trends/?range=weekly_last_5",
        "ats_path": "/nba/trends/ats_trends",
    },
    "mlb": {
        "scores_path": "/mlb/odds",
        "rankings_path": "/mlb/ranking",
        "sos_path": "/mlb/ranking/schedule-strength-by-other",
        "record_path": "/mlb/trends/win_trends",
        "ppg_path": "/mlb/stat/runs-per-game",
        "opp_ppg_path": "/mlb/stat/opponent-runs-per-game",
        "home_record_path": "/mlb/trend/win_trends/is_home",
        "away_record_path": "/mlb/trend/win_trends/is_away",
        "last5_path": "/mlb/trends/win_trends/?range=weekly_last_5",
        "ats_path": "/mlb/trends/ats_trends",
    },
    "nhl": {
        "scores_path": "/nhl/odds",
        # NHL uses Hockey-Reference instead of TeamRankings (TeamRankings doesn't cover NHL)
        "use_hockey_reference": True,
        "standings_url": "https://www.hockey-reference.com/leagues/NHL_2026_standings.html",
        "stats_url": "https://www.hockey-reference.com/leagues/NHL_2026.html",
    },
    "ncaaf": {
        "scores_path": "/ncaaf/odds",
        "rankings_path": "/college-football/ranking",
        "sos_path": "/college-football/ranking/schedule-strength-by-other",
        "record_path": "/college-football/trends/win_trends",
        "ppg_path": "/college-football/stat/points-per-game",
        "opp_ppg_path": "/college-football/stat/opponent-points-per-game",
        "home_record_path": "/college-football/trend/win_trends/is_home",
        "away_record_path": "/college-football/trend/win_trends/is_away",
        "last5_path": "/college-football/trends/win_trends/?range=weekly_last_5",
        "ats_path": "/college-football/trends/ats_trends",
        "conf_record_path": "/college-football/trends/win_trends/?sc=is_conference",
    },
    "ncaab": {
        "scores_path": "/ncaab/odds",
        "rankings_path": "/ncaa-basketball/ranking",
        "sos_path": "/ncaa-basketball/ranking/schedule-strength-by-other",
        "record_path": "/ncaa-basketball/trends/win_trends",
        "ppg_path": "/ncaa-basketball/stat/points-per-game",
        "opp_ppg_path": "/ncaa-basketball/stat/opponent-points-per-game",
        "home_record_path": "/ncaa-basketball/trend/win_trends/is_home",
        "away_record_path": "/ncaa-basketball/trend/win_trends/is_away",
        "last5_path": "/ncaa-basketball/trends/win_trends/?range=weekly_last_5",
        "ats_path": "/ncaa-basketball/trends/ats_trends",
        "conf_record_path": "/ncaa-basketball/trends/win_trends/?sc=is_conference",
    },
}

HEADLESS = os.getenv("HEADLESS", "1") != "0"
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "0"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.5"))  # Seconds between requests

ET_TZ = pytz.timezone("America/New_York")

# Module-level date override: set via command line, defaults to today (ET)
TARGET_DATE = None  # Set in main() if --date arg provided

UNMATCHED_TEAMS = []
_MLB_TEAM_FORMS = {
    "arizona diamondbacks", "diamondbacks", "d backs", "dbacks",
    "atlanta braves", "braves",
    "baltimore orioles", "orioles",
    "boston red sox", "red sox",
    "chicago cubs", "cubs",
    "chicago white sox", "white sox", "chi sox",
    "cincinnati reds", "reds",
    "cleveland guardians", "guardians",
    "colorado rockies", "rockies",
    "detroit tigers", "tigers",
    "houston astros", "astros",
    "kansas city royals", "royals",
    "los angeles angels", "angels",
    "los angeles dodgers", "dodgers",
    "miami marlins", "marlins",
    "milwaukee brewers", "brewers",
    "minnesota twins", "twins",
    "new york mets", "mets",
    "new york yankees", "yankees",
    "athletics", "oakland athletics",
    "philadelphia phillies", "phillies",
    "pittsburgh pirates", "pirates",
    "san diego padres", "padres",
    "san francisco giants", "giants",
    "seattle mariners", "mariners",
    "st louis cardinals", "st. louis cardinals", "cardinals",
    "tampa bay rays", "rays",
    "texas rangers", "rangers",
    "toronto blue jays", "blue jays",
    "washington nationals", "nationals",
}


def _norm_team_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


_MLB_TEAM_NORMS = {_norm_team_token(v) for v in _MLB_TEAM_FORMS}


def _candidate_matches_mlb_team(tokens) -> bool:
    if not tokens:
        return False
    joined = " ".join(tokens)
    norm_joined = _norm_team_token(joined)
    if norm_joined in _MLB_TEAM_NORMS:
        return True
    if len(tokens) >= 2 and _norm_team_token(" ".join(tokens[-2:])) in _MLB_TEAM_NORMS:
        return True
    if _norm_team_token(tokens[-1]) in _MLB_TEAM_NORMS:
        return True
    return False

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class TeamStats:
    """Comprehensive team statistics and performance data."""
    name: str
    # Record
    wins: int = 0
    losses: int = 0
    ties: int = 0
    win_pct: float = 0.0
    # SOS
    sos_rank: int = 0
    sos_rating: float = 0.0
    # Scoring
    ppg: float = 0.0
    opp_ppg: float = 0.0
    point_diff: float = 0.0
    # Splits
    home_record: str = ""
    away_record: str = ""
    home_win_pct: float = 0.0
    away_win_pct: float = 0.0
    # Recent form
    last5_record: str = ""
    last5_win_pct: float = 0.0
    last10_record: str = ""
    last10_win_pct: float = 0.0
    # Conference (college only)
    conf_record: str = ""
    conf_win_pct: float = 0.0
    # ATS (Against The Spread)
    ats_record: str = ""
    ats_pct: float = 0.0
    # Overall ranking
    power_rank: int = 0


def _team_stats_has_real_data(stats: Optional[TeamStats]) -> bool:
    """True only when a TeamStats object contains scraped values, not placeholders."""
    if stats is None:
        return False
    numeric_fields = (
        "wins", "losses", "ties", "win_pct", "sos_rank", "sos_rating",
        "ppg", "opp_ppg", "point_diff", "home_win_pct", "away_win_pct",
        "last5_win_pct", "last10_win_pct", "conf_win_pct", "ats_pct",
        "power_rank",
    )
    for field_name in numeric_fields:
        try:
            if float(getattr(stats, field_name, 0) or 0) != 0.0:
                return True
        except Exception:
            continue
    text_fields = ("home_record", "away_record", "last5_record", "last10_record", "conf_record", "ats_record")
    return any(bool(str(getattr(stats, field_name, "") or "").strip()) for field_name in text_fields)


@dataclass
class Matchup:
    """A single game matchup with both teams' stats."""
    game_time: str
    away_team: str
    home_team: str
    away_stats: Optional[TeamStats] = None
    home_stats: Optional[TeamStats] = None
    game_id: str = ""
    match_confidence: float = 0.0
    match_method: str = ""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# Common team name mappings (short name -> keywords to match)
# This helps match "Knicks" to "New York Knicks", etc.
TEAM_NAME_MAPPINGS = {
    # ===================================================================
    # NBA - TR uses city-only names: "Detroit", "LA Lakers", "Okla City"
    # ===================================================================
    "knicks": ["new york knicks", "knicks", "ny knicks", "new york"],
    "nets": ["brooklyn nets", "nets", "brooklyn"],
    "celtics": ["boston celtics", "celtics", "boston"],
    "76ers": ["philadelphia 76ers", "76ers", "sixers", "philadelphia"],
    "raptors": ["toronto raptors", "raptors", "toronto"],
    "bulls": ["chicago bulls", "bulls", "chicago"],
    "cavaliers": ["cleveland cavaliers", "cavaliers", "cavs", "cleveland"],
    "pistons": ["detroit pistons", "pistons", "detroit"],
    "pacers": ["indiana pacers", "pacers", "indiana"],
    "bucks": ["milwaukee bucks", "bucks", "milwaukee"],
    "hawks": ["atlanta hawks", "hawks", "atlanta"],
    "hornets": ["charlotte hornets", "hornets", "charlotte"],
    "heat": ["miami heat", "heat", "miami"],
    "magic": ["orlando magic", "magic", "orlando"],
    "wizards": ["washington wizards", "wizards", "washington"],
    "nuggets": ["denver nuggets", "nuggets", "denver"],
    "timberwolves": ["minnesota timberwolves", "timberwolves", "wolves", "minnesota"],
    "thunder": ["oklahoma city thunder", "thunder", "okc", "okla city"],
    "trail blazers": ["portland trail blazers", "trail blazers", "blazers", "portland"],
    "jazz": ["utah jazz", "jazz", "utah"],
    "warriors": ["golden state warriors", "warriors", "golden state"],
    "clippers": ["los angeles clippers", "la clippers", "clippers"],
    "lakers": ["los angeles lakers", "la lakers", "lakers"],
    "suns": ["phoenix suns", "suns", "phoenix"],
    "kings": ["sacramento kings", "kings", "sacramento"],
    "mavericks": ["dallas mavericks", "mavericks", "mavs", "dallas"],
    "rockets": ["houston rockets", "rockets", "houston"],
    "grizzlies": ["memphis grizzlies", "grizzlies", "memphis"],
    "pelicans": ["new orleans pelicans", "pelicans", "new orleans"],
    "spurs": ["san antonio spurs", "spurs", "san antonio"],
    # ===================================================================
    # NHL - TR uses Hockey-Reference; MoneyPuck uses abbreviations
    # ===================================================================
    "blue jackets": ["columbus blue jackets", "blue jackets", "columbus"],
    "devils": ["new jersey devils", "devils", "new jersey"],
    "nhl_rangers": ["new york rangers", "rangers", "ny rangers", "new york rangers"],
    "islanders": ["new york islanders", "islanders", "ny islanders"],
    "flyers": ["philadelphia flyers", "flyers"],
    "penguins": ["pittsburgh penguins", "penguins", "pens", "pittsburgh"],
    "capitals": ["washington capitals", "capitals", "caps"],
    "bruins": ["boston bruins", "bruins"],
    "sabres": ["buffalo sabres", "sabres", "buffalo"],
    "red wings": ["detroit red wings", "red wings"],
    "nhl_panthers": ["florida panthers", "panthers", "florida"],
    "canadiens": ["montreal canadiens", "canadiens", "habs", "montreal"],
    "senators": ["ottawa senators", "senators", "sens", "ottawa"],
    "lightning": ["tampa bay lightning", "lightning", "bolts", "tampa bay"],
    "maple leafs": ["toronto maple leafs", "maple leafs", "leafs"],
    "hurricanes": ["carolina hurricanes", "hurricanes", "canes", "carolina"],
    "blackhawks": ["chicago blackhawks", "blackhawks"],
    "avalanche": ["colorado avalanche", "avalanche", "avs", "colorado"],
    "nhl_stars": ["dallas stars", "stars"],
    "wild": ["minnesota wild", "wild"],
    "predators": ["nashville predators", "predators", "preds", "nashville"],
    "blues": ["st. louis blues", "st louis blues", "blues", "st. louis", "st louis"],
    "nhl_jets": ["winnipeg jets", "jets", "winnipeg"],
    "ducks": ["anaheim ducks", "ducks", "anaheim"],
    "coyotes": ["arizona coyotes", "coyotes", "utah hockey club"],
    "flames": ["calgary flames", "flames", "calgary"],
    "oilers": ["edmonton oilers", "oilers", "edmonton"],
    "sharks": ["san jose sharks", "sharks", "san jose"],
    "canucks": ["vancouver canucks", "canucks", "vancouver"],
    "golden knights": ["vegas golden knights", "golden knights", "knights", "vegas"],
    "kraken": ["seattle kraken", "kraken", "seattle"],
    # ===================================================================
    # NFL - TR uses: "NY Giants", "LA Rams", city-only for most
    # ===================================================================
    "cowboys": ["dallas cowboys", "cowboys"],
    "nfl_giants": ["new york giants", "giants", "ny giants"],
    "eagles": ["philadelphia eagles", "eagles"],
    "commanders": ["washington commanders", "commanders"],
    "bears": ["chicago bears", "bears"],
    "lions": ["detroit lions", "lions"],
    "packers": ["green bay packers", "packers", "green bay"],
    "vikings": ["minnesota vikings", "vikings"],
    "falcons": ["atlanta falcons", "falcons"],
    "saints": ["new orleans saints", "saints"],
    "buccaneers": ["tampa bay buccaneers", "buccaneers", "bucs", "tampa bay"],
    "nfl_cardinals": ["arizona cardinals", "cardinals"],
    "rams": ["los angeles rams", "la rams", "rams"],
    "49ers": ["san francisco 49ers", "49ers", "niners", "san francisco"],
    "seahawks": ["seattle seahawks", "seahawks"],
    "ravens": ["baltimore ravens", "ravens", "baltimore"],
    "bengals": ["cincinnati bengals", "bengals", "cincinnati"],
    "browns": ["cleveland browns", "browns"],
    "steelers": ["pittsburgh steelers", "steelers"],
    "texans": ["houston texans", "texans"],
    "colts": ["indianapolis colts", "colts", "indianapolis"],
    "nfl_jaguars": ["jacksonville jaguars", "jaguars", "jags", "jacksonville"],
    "titans": ["tennessee titans", "titans", "tennessee"],
    "broncos": ["denver broncos", "broncos"],
    "chargers": ["los angeles chargers", "la chargers", "chargers"],
    "raiders": ["las vegas raiders", "raiders", "las vegas"],
    "chiefs": ["kansas city chiefs", "chiefs", "kansas city"],
    "dolphins": ["miami dolphins", "dolphins"],
    "patriots": ["new england patriots", "patriots", "pats", "new england"],
    "bills": ["buffalo bills", "bills"],
    "nfl_jets": ["new york jets", "jets", "ny jets"],
    # ===================================================================
    # MLB - TR uses: "Chi Cubs", "Chi White Sox", "NY Yankees", etc.
    # ===================================================================
    "yankees": ["new york yankees", "yankees", "ny yankees"],
    "mets": ["new york mets", "mets", "ny mets"],
    "red sox": ["boston red sox", "red sox"],
    "blue jays": ["toronto blue jays", "blue jays", "jays", "toronto"],
    "orioles": ["baltimore orioles", "orioles", "os", "baltimore"],
    "rays": ["tampa bay rays", "rays"],
    "white sox": ["chicago white sox", "white sox", "chi white sox"],
    "cubs": ["chicago cubs", "cubs", "chi cubs"],
    "guardians": ["cleveland guardians", "guardians"],
    "mlb_tigers": ["detroit tigers", "tigers"],
    "royals": ["kansas city royals", "royals"],
    "twins": ["minnesota twins", "twins"],
    "astros": ["houston astros", "astros"],
    "angels": ["los angeles angels", "la angels", "angels"],
    "athletics": ["sacramento athletics", "oakland athletics", "athletics", "as", "a's", "oakland", "sacramento"],
    "mariners": ["seattle mariners", "mariners"],
    "mlb_rangers": ["texas rangers", "rangers", "texas"],
    "braves": ["atlanta braves", "braves"],
    "marlins": ["miami marlins", "marlins"],
    "phillies": ["philadelphia phillies", "phillies"],
    "nationals": ["washington nationals", "nationals", "nats"],
    "brewers": ["milwaukee brewers", "brewers"],
    "reds": ["cincinnati reds", "reds"],
    "pirates": ["pittsburgh pirates", "pirates"],
    "diamondbacks": ["arizona diamondbacks", "diamondbacks", "dbacks", "arizona"],
    "rockies": ["colorado rockies", "rockies", "colorado"],
    "dodgers": ["los angeles dodgers", "la dodgers", "dodgers"],
    "padres": ["san diego padres", "padres", "san diego"],
    "mlb_giants": ["san francisco giants", "giants", "sf giants"],
}

# College team name equivalences (schedule name <-> TeamRankings name)
# Keys and values are both normalized forms
COLLEGE_TEAM_ALIASES: Dict[str, List[str]] = {
    # COMPLETE NCAAB + NCAAF alias coverage
    # Keys = TR canonical key (normalized), Values = SAO/schedule variants
    # ── DIRECTIONAL ──────────────────────────────────────────────────────
    "cs northridge":  ["cal state northridge", "csun"],
    "cs fullerton":   ["cal state fullerton",  "csuf"],
    "cs bakersfield": ["cal state bakersfield","csub"],
    "c michigan":     ["central michigan",    "cmu"],
    "c florida":      ["central florida",     "ucf"],
    "c arkansas":     ["central arkansas",    "uca"],
    "c connecticut":  ["central connecticut", "ccsu", "central conn"],
    "e carolina":     ["east carolina",       "ecu"],
    "e michigan":     ["eastern michigan",    "emu"],
    "e washington":   ["eastern washington",  "ewu"],
    "n illinois":     ["northern illinois",   "niu"],
    "n texas":        ["north texas",         "unt"],
    "n arizona":      ["northern arizona",    "nau"],
    "n colorado":     ["northern colorado",   "unco"],
    "n iowa":         ["northern iowa",       "uni"],
    "n dakota st":    ["north dakota state",  "ndsu"],
    "s alabama":      ["south alabama"],
    "s carolina":     ["south carolina",      "usc gamecocks"],
    "s florida":      ["south florida",       "usf"],
    "s illinois":     ["southern illinois",   "siu"],
    "s mississippi":  ["southern miss",       "southern mississippi", "usm"],
    "s utah":         ["southern utah",       "suu"],
    "s dakota st":    ["south dakota state",  "sdsu"],
    "se missouri st": ["southeast missouri state","semo"],
    "se louisiana":   ["southeastern louisiana","sela"],
    "w carolina":     ["western carolina",    "wcu"],
    "w illinois":     ["western illinois",    "wiu"],
    "w kentucky":     ["western kentucky",    "wku"],
    "w michigan":     ["western michigan",    "wmu"],
    "nw state":       ["northwestern state",  "nwst"],
    # ── STATE SUFFIX ─────────────────────────────────────────────────────
    "alabama st":     ["alabama state"],
    "app state":      ["appalachian state",   "appalachian st"],
    "arizona st":     ["arizona state"],
    "arkansas st":    ["arkansas state",      "a-state"],
    "ball st":        ["ball state"],
    "boise st":       ["boise state"],
    "colorado st":    ["colorado state"],
    "fresno st":      ["fresno state"],
    "georgia st":     ["georgia state"],
    "idaho st":       ["idaho state"],
    "illinois st":    ["illinois state"],
    "indiana st":     ["indiana state"],
    "iowa st":        ["iowa state"],
    "jacksonville st":["jacksonville state", "jsu jacksonville"],
    "jackson st":     ["jackson state",      "jsu jackson"],
    "kansas st":      ["kansas state"],
    "kent st":        ["kent state"],
    "michigan st":    ["michigan state"],
    "mississippi st": ["mississippi state"],
    "montana st":     ["montana state"],
    "morgan st":      ["morgan state"],
    "nc a&t":         ["north carolina a&t", "ncat"],
    "nc state":       ["north carolina state","ncsu"],
    "new mexico st":  ["new mexico state",   "nmsu"],
    "ohio st":        ["ohio state"],
    "oregon st":      ["oregon state"],
    "penn st":        ["penn state"],
    "portland st":    ["portland state"],
    "sacramento st":  ["sacramento state",   "sac state"],
    "san diego st":   ["san diego state",    "sdsu"],
    "san jose st":    ["san jose state",     "sjsu"],
    "tarleton st":    ["tarleton state"],
    "tennessee st":   ["tennessee state"],
    "utah st":        ["utah state"],
    "weber st":       ["weber state"],
    "wichita st":     ["wichita state"],
    "youngstown st":  ["youngstown state"],
    # ── ACRONYMS ─────────────────────────────────────────────────────────
    "byu":            ["brigham young",       "brigham young university"],
    "smu":            ["southern methodist",  "southern methodist university"],
    "tcu":            ["texas christian"],
    "uab":            ["alabama birmingham",  "uab blazers"],
    "ucf":            ["central florida",     "university of central florida"],
    "ucla":           ["california los angeles"],
    "unlv":           ["nevada las vegas"],
    "usc":            ["southern california"],
    "utep":           ["texas el paso",       "texas-el paso"],
    "utsa":           ["ut san antonio",      "texas san antonio"],
    "vmi":            ["virginia military",   "virginia military institute"],
    # ── UNIQUE/SPECIAL ───────────────────────────────────────────────────
    "coastal car":    ["coastal carolina",    "ccu"],
    "florida a&m":    ["famu"],
    "florida intl":   ["florida international","fiu"],
    "fla gulf coast": ["florida gulf coast",  "fgcu"],
    "georgia so":     ["georgia southern"],
    "j madison":      ["james madison",       "jmu"],
    "la tech":        ["louisiana tech",      "louisiana-tech"],
    "little rock":    ["arkansas little rock","ualr"],
    "loyola md":      ["loyola maryland"],
    "middle tenn":    ["middle tennessee",    "mtsu", "middle tennessee state"],
    "old dom":        ["old dominion",        "odu"],
    "prairie view":   ["prairie view a&m",   "pvam"],
    "sf austin":      ["stephen f austin",   "stephen f. austin","sfa"],
    "tenn tech":      ["tennessee tech"],
    "texas a&m-cc":   ["texas a&m corpus christi","tamucc"],
    "texas so":       ["texas southern"],
    "the citadel":    ["citadel"],
    "ut martin":      ["tennessee martin",   "utm"],
    "ul monroe":      ["louisiana monroe",   "ulm"],
    "umass":          ["massachusetts",      "umass amherst"],
    "umbc":           ["maryland baltimore county"],
    "william & mary": ["william and mary",   "w&m"],
    # ── EXISTING ENTRIES (preserved) ─────────────────────────────────────
    "bethune-cookman": ["bethune"],
    "grambling state": ["grambling"],
    "nicholls state":  ["nicholls"],
    "mcneese state":   ["mcneese"],
    "mcneese":         ["mcneese state"],
    "ut rio grande valley": ["ut rio grande"],
    # Miami disambiguation — MUST specify FL/OH or SAO full name to prevent cross-match
    "miami fl":        ["miami", "miami hurricanes", "miami fl", "miami (fl)"],
    "miami oh":        ["miami oh", "miami redhawks", "miami (oh)", "miami ohio"],
    "loyola il":       ["loyola chicago"],
    "george washington": ["g washington"],
    "college of charleston": ["col of charleston"],
    "arkansas little rock": ["arkansas little rock", "ark little rock"],
    "arkansas pine bluff": ["arkansas pine bluff", "ark pine bluff", "ar pine bluff"],
    "detroit mercy":   ["detroit"],
    "detroit-mercy":   ["detroit"],
    "abilene christian": ["abilene christian", "abil christian"],
    "south illinois":  ["south illinois"],
    "long island":     ["liu"],
    "massachusetts lowell": ["umass lowell"],
    "connecticut":     ["uconn"],
    "virginia commonwealth": ["vcu"],
    # New / recently added DI teams
    "lincoln memorial": ["lincoln mem", "lmu lincoln"],
    "queens university": ["queens", "queens nc", "queens (nc)"],
    "st. thomas":      ["st thomas mn", "st thomas (mn)", "thomas"],
    "bellarmine":      ["bellarmine knights"],
    "le moyne":        ["le moyne dolphins"],
    "stonehill":       ["sfb", "stonehill skyhawks"],
    "mercyhurst":      ["mercyhurst lakers"],
    "westcliff":       ["westcliff warriors"],
    # Teams with parenthetical state qualifiers that SAO includes but TR strips
    "pittsburgh":      ["pitt", "pittsburgh panthers"],
    "miami fl":        ["miami hurricanes", "miami fl"],  # intentional dup key — last wins
}


def clean_team_name(raw: str, sport: str = "") -> str:
    """Clean and normalize team names."""
    s = (raw or "").strip()
    # SAO often concatenates pitcher text into team labels on odds pages.
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    # Remove trailing records like "10-5" or rankings like "#5"
    s = re.sub(r"\s*#?\d{1,3}(?:-\d{1,3}){0,2}-?\s*$", "", s)
    # MLB odds rows append probable starters ("Team Pitcher R/L" or "Team Pitcher RHP/LHP").
    # Trim obvious trailing pitcher fragments first, then fall back to token checks.
    if str(sport or "").lower() == "mlb":
        s = re.sub(
            r"\s+[A-Z][A-Za-z\.'\-]+(?:\s+[A-Z][A-Za-z\.'\-]+)?\s+(?:R|L|RHP|LHP)\s*$",
            "",
            s,
            flags=re.IGNORECASE,
        )
        toks = s.split()
        if len(toks) >= 3 and toks[-1].upper() in {"L", "R", "LHP", "RHP"}:
            candidates = []
            if len(toks) >= 3:
                candidates.append(toks[:-2])
            if len(toks) >= 4:
                candidates.append(toks[:-3])
            for cand in candidates:
                if _candidate_matches_mlb_team(cand):
                    s = " ".join(cand)
                    break
    s = re.sub(r"\s+\d+$", "", s)
    s = re.sub(r"^#\d+\s+", "", s)
    s = re.sub(r"[^A-Za-z0-9\.\-'& ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_team_name_from_cell(team_cell, sport: str = "") -> str:
    """Extract team name without pitcher child spans from a SAO team cell."""
    if team_cell is None:
        return ""
    name_span = team_cell.find("span", class_="team-name")
    if name_span is None:
        return clean_team_name(team_cell.get_text(" ", strip=True), sport=sport)

    direct_text = [
        t.strip()
        for t in name_span.find_all(string=True, recursive=False)
        if str(t).strip()
    ]
    raw_name = " ".join(direct_text) if direct_text else name_span.get_text(" ", strip=True)
    return clean_team_name(raw_name, sport=sport)


def _schedule_path_for_sport(sport: str) -> Path:
    ymd = (TARGET_DATE or datetime.now(ET_TZ).date()).strftime("%Y%m%d")
    return _BASE_DIR / "stats_output" / f"Schedules_{sport.upper()}_{ymd}.xlsx"


def _stats_status_for_sport(sport: str) -> str:
    ymd = (TARGET_DATE or datetime.now(ET_TZ).date()).strftime("%Y%m%d")
    marker = _BASE_DIR / "stats_output" / f"StatsStatus_{sport.upper()}_{ymd}.json"
    if not marker.exists():
        return ""
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(payload.get("status", "") or "").strip().upper()


def _load_matchups_from_schedule_workbook(sport: str) -> List[Matchup]:
    """Prefer clean schedule workbook names from scrapes.py for deterministic joins."""
    stats_status = _stats_status_for_sport(sport)
    if stats_status == "NO_GAMES":
        print(f"  Stats marker gate for {sport.upper()}: NO_GAMES (skipping schedule workbook reuse)")
        return []

    path = _schedule_path_for_sport(sport)
    if not path.exists():
        return []

    try:
        df = pd.read_excel(path)
    except Exception as exc:
        print(f"  WARN: Could not read schedule workbook {path.name}: {exc}")
        return []

    needed = {"Away", "Home"}
    if not needed.issubset(set(df.columns)):
        print(f"  WARN: Schedule workbook missing expected columns: {path.name}")
        return []

    out: List[Matchup] = []
    for _, row in df.iterrows():
        away = clean_team_name(str(row.get("Away", "") or ""), sport=sport)
        home = clean_team_name(str(row.get("Home", "") or ""), sport=sport)
        if not away or not home:
            continue

        time_val = str(row.get("Time (ET)", "") or "").strip()
        time_display = time_val
        if TARGET_DATE:
            time_display = f"{TARGET_DATE.month}/{TARGET_DATE.day} {time_val}".strip()

        out.append(
            Matchup(
                game_time=time_display,
                away_team=_normalize_nhl_name(away, sport),
                home_team=_normalize_nhl_name(home, sport),
            )
        )

    if out:
        print(f"  Using schedule workbook for {sport.upper()}: {path.name} ({len(out)} games)")
    return out


def _write_sos_status_marker(
    sport: str,
    status: str,
    *,
    output_file: Optional[str] = None,
    games: int = 0,
    matched: int = 0,
    error: str = "",
    note: str = "",
) -> None:
    target = TARGET_DATE or datetime.now(ET_TZ).date()
    ymd = target.strftime("%Y%m%d")
    out_dir = _BASE_DIR / "sos_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    marker_path = out_dir / f"SOSStatus_{sport.upper()}_{ymd}.json"

    payload = {
        "league": sport.upper(),
        "date": target.isoformat(),
        "status": status,  # READY | PARTIAL_READY | NO_GAMES | ERROR
        "games_found": int(games),
        "games_matched": int(matched),
        "output_file": output_file or "",
        "error": error,
        "note": note,
        "updated_at": datetime.now(ET_TZ).isoformat(),
    }
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def normalize_team_for_matching(name: str, sport: str = "") -> str:
    """Normalize team name for matching - collapses directional variants to root.
    
    V13: Also generates TR-style contracted forms since TeamRankings uses
    abbreviated names (CS Fullerton not Cal State Fullerton, UCSB not UC Santa Barbara).
    """
    s = clean_team_name(name).lower()
    s = s.replace(".", "")
    is_pro = sport.lower() in ("nba", "nfl", "mlb", "nhl") if sport else False
    
    # === V13: TR-STYLE CONTRACTIONS (algorithmically collapse to TR format) ===
    # These are pattern rules, not dictionary entries per SKILL.md
    if not is_pro:
        # Cal State X -> CS X (TR uses "CS Fullerton" not "Cal State Fullerton")
        s = re.sub(r"\bcal\s*state\b", "cs", s)
        s = re.sub(r"\bcalifornia\s*state\b", "cs", s)
        # UC Santa Barbara -> UCSB (special case - TR concatenates)
        s = re.sub(r"\buc\s+santa\s+barbara\b", "ucsb", s)
        # Appalachian State -> App State (TR truncates)
        s = re.sub(r"\bappalachian\s+state\b", "app state", s)
        s = re.sub(r"\bappalachian\s+st\b", "app state", s)
        # Florida International -> Florida Intl (TR abbreviates)
        s = re.sub(r"\bflorida\s+international\b", "florida intl", s)
        s = re.sub(r"\binternational\b", "intl", s)
        # Tennessee-Martin / Tennessee Martin -> UT Martin (TR uses UT prefix)
        s = re.sub(r"\btennessee[-\s]martin\b", "ut martin", s)
        # Fairleigh Dickinson / FDU -> F Dickinson (TR abbreviates first name)
        s = re.sub(r"\bfairleigh\s+dickinson\b", "f dickinson", s)
        s = re.sub(r"\bfdu\b", "f dickinson", s)
        # Chicago State -> Chicago St (TR truncates State)
        s = re.sub(r"\bchicago\s+state\b", "chicago st", s)
    # League-specific abbreviation rules
    if is_pro:
        s = re.sub(r"\bst\b", "saint", s)
        s = re.sub(r"\bsf\b", "san francisco", s)
        s = re.sub(r"\bchi\b", "chicago", s)
        s = re.sub(r"\bny\b", "new york", s)
        s = re.sub(r"\bla\b", "los angeles", s)
    else:
        s = re.sub(r"\bst\b", "state", s)
        s = re.sub(r"\bsf\b", "stephen f", s)
        s = re.sub(r"\bu\b", "university", s)
        s = re.sub(r"\b(university|univ|college)\b", "", s)
    # === DIRECTIONAL: compound directionals first ===
    s = re.sub(r"\b(southeastern)\b", "southeast", s)
    s = re.sub(r"\bse(?=\s)", "southeast", s)
    s = re.sub(r"\b(southwestern)\b", "southwest", s)
    s = re.sub(r"\bsw(?=\s)", "southwest", s)
    s = re.sub(r"\b(northwestern)\b", "northwest", s)
    s = re.sub(r"\bnw(?=\s)", "northwest", s)
    s = re.sub(r"\b(northeastern)\b", "northeast", s)
    s = re.sub(r"\bne(?=\s)", "northeast", s)
    # Simple directionals (AFTER compound to avoid double-expansion)
    s = re.sub(r"\b(southern|south|so)\b", "south", s)
    s = re.sub(r"\bs(?=\s)", "south", s)
    s = re.sub(r"\b(northern|north)\b", "north", s)
    s = re.sub(r"\bn(?=\s)", "north", s)
    s = re.sub(r"\b(eastern|east)\b", "east", s)
    s = re.sub(r"\be(?=\s)", "east", s)
    s = re.sub(r"\b(western|west)\b", "west", s)
    s = re.sub(r"\bw(?=\s)", "west", s)
    s = re.sub(r"\bc(?=\s)", "central", s)
    # UNC / NC -> "north carolina"
    s = re.sub(r"\bunc\b", "north carolina", s)
    s = re.sub(r"\bnc\b", "north carolina", s)
    # TR abbreviation expansions (verified against actual TR team list)
    s = re.sub(r"\bar\b", "arkansas", s)          # AR-Pine Bluff
    s = re.sub(r"\bark\b", "arkansas", s)         # Ark. (backup)
    s = re.sub(r"\bill\b", "illinois", s)          # Ill. (backup)
    s = re.sub(r"\bchr\b", "christian", s)         # Chr. (backup)
    s = re.sub(r"\bhou\b", "houston", s)           # Hou Christian (actual TR)
    s = re.sub(r"\bcc\b", "corpus christi", s)     # Texas A&M-CC
    s = re.sub(r"\bval\b", "valley", s)            # Val. (backup)
    s = re.sub(r"\bmiss\b", "mississippi", s)      # Miss Valley St (actual TR)
    s = re.sub(r"\btenn\b", "tennessee", s)        # Tenn Tech (actual TR)
    s = re.sub(r"\bcar\b", "carolina", s)          # Coastal Car, W Carolina (actual TR)
    s = re.sub(r"\bokla\b", "oklahoma", s)         # Okla City (NBA)
    s = re.sub(r"\babl\b", "abilene", s)           # Abl Christian (actual TR)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_team_keywords(team_name: str, sport: str = "") -> List[str]:
    """Get keywords for team matching -- NO single-word additions to prevent pollution."""
    normalized = normalize_team_for_matching(team_name, sport)
    keywords = [normalized]

    # Also add the raw cleaned lowercase (before normalize transforms)
    raw_clean = clean_team_name(team_name).lower().strip()
    if raw_clean and raw_clean != normalized:
        keywords.append(raw_clean)

    # Check if this team has pro-league mappings (NBA/NFL/NHL/MLB only)
    for key, aliases in TEAM_NAME_MAPPINGS.items():
        if normalized in aliases or key == normalized:
            keywords.extend(aliases)
            keywords.append(key)
            break
        for alias in aliases:
            if alias == normalized or normalized == alias:
                keywords.extend(aliases)
                keywords.append(key)
                break

    # DO NOT add individual words -- this caused cross-contamination
    # e.g., adding "arkansas" for "Central Arkansas" would pollute the data dict

    return list(set(kw for kw in keywords if kw))


def is_today_game(game_time_str: str) -> bool:
    """Check if a game is scheduled for the target date (today or override)."""
    try:
        target = TARGET_DATE or datetime.now(ET_TZ).date()
        s = (game_time_str or "").strip().lower()
        if "today" in s:
            # "today" only valid if TARGET_DATE is actually today
            if TARGET_DATE is None or TARGET_DATE == datetime.now(ET_TZ).date():
                return True
            return False
        m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", s)
        if m:
            mm = int(m.group(1))
            dd = int(m.group(2))
            return (mm == target.month) and (dd == target.day)
        # If no date specified and has time format, assume target date
        if re.search(r"\d{1,2}:\d{2}", s):
            return True
        return False
    except Exception:
        return False


def parse_record(record_str: str) -> Tuple[int, int, int, float]:
    """Parse a record string like '10-5' or '10-5-1' into (W, L, T, pct)."""
    try:
        record_str = (record_str or "").strip()
        # Match patterns like "10-5", "10-5-1", "10 - 5"
        m = re.search(r"(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?", record_str)
        if m:
            w = int(m.group(1))
            l = int(m.group(2))
            t = int(m.group(3)) if m.group(3) else 0
            total = w + l + t
            pct = w / total if total > 0 else 0.0
            return w, l, t, pct
    except Exception:
        pass
    return 0, 0, 0, 0.0


def parse_percentage(pct_str: str) -> float:
    """Parse a percentage string like '65.5%' or '.655' into a float."""
    try:
        pct_str = (pct_str or "").strip().replace("%", "")
        val = float(pct_str)
        # If it's already a decimal (less than 1), return as-is
        if val <= 1.0:
            return val
        # Otherwise convert from percentage
        return val / 100.0
    except Exception:
        return 0.0


def parse_float(val_str: str) -> float:
    """Parse a float value, handling various formats."""
    try:
        val_str = (val_str or "").strip()
        val_str = re.sub(r"[^\d.\-]", "", val_str)
        return float(val_str) if val_str else 0.0
    except Exception:
        return 0.0


def parse_rank(rank_str: str) -> int:
    """Parse a rank string like '#5' or '5' into an integer."""
    try:
        rank_str = (rank_str or "").strip()
        m = re.search(r"(\d+)", rank_str)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


# ============================================================================
# SCRAPING: TODAY'S GAMES
# ============================================================================

def scrape_todays_games(page: Page, sport: str) -> List[Matchup]:
    """Scrape today's games from ScoresAndOdds."""
    config = SPORTS_CONFIG[sport]
    url = f"{BASE_URL_SCORES}{config['scores_path']}"
    print(f"  Loading games from {url}")
    
    matchups = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Find the odds table - try multiple selectors
        tbody = None
        for prefix in ["odds-table-spread--", "odds-table-moneyline--", "odds-table-"]:
            tbody = soup.find("tbody", id=lambda x: x and prefix in str(x))
            if tbody:
                break
        
        if not tbody:
            # Fallback: look for game rows directly
            game_rows = soup.find_all("tr", class_=lambda x: x and "game" in str(x).lower())
            if not game_rows:
                print(f"  No games table found for {sport}")
                return []
        else:
            game_rows = tbody.find_all("tr", recursive=False)
        
        current_time = ""
        teams_buffer = []
        
        for row in game_rows:
            # Check for time cell
            time_cell = row.find("td", class_="game-time")
            if time_cell:
                # Save previous matchup if complete
                if len(teams_buffer) >= 2:
                    if is_today_game(current_time):
                        matchups.append(Matchup(
                            game_time=current_time,
                            away_team=_normalize_nhl_name(teams_buffer[0], sport),
                            home_team=_normalize_nhl_name(teams_buffer[1], sport)
                        ))
                current_time = time_cell.get_text(strip=True)
                teams_buffer = []
            
            # Check for team cell
            team_cell = row.find("td", class_="game-team")
            if team_cell:
                team_name = _extract_team_name_from_cell(team_cell, sport=sport)
                if team_name:
                    teams_buffer.append(team_name)
        
        # Don't forget the last matchup
        if len(teams_buffer) >= 2 and is_today_game(current_time):
            matchups.append(Matchup(
                game_time=current_time,
                away_team=_normalize_nhl_name(teams_buffer[0], sport),
                home_team=_normalize_nhl_name(teams_buffer[1], sport)
            ))
        
    except Exception as e:
        print(f"  Error scraping games for {sport}: {e}")
    
    return matchups


# ============================================================================
# SCRAPING: TEAM RANKINGS DATA
# ============================================================================

def scrape_rankings_table(page: Page, url: str, sport: str) -> Dict[str, Dict]:
    """Generic scraper for TeamRankings tables. Returns dict keyed by normalized team name."""
    data = {}
    try:
        # Block redirects to non-TeamRankings domains (ad/malware protection)
        def handle_request(route):
            request_url = route.request.url
            # Allow TeamRankings and common CDNs
            allowed_domains = ["teamrankings.com", "googletagmanager.com", "google-analytics.com", 
                             "googleapis.com", "gstatic.com", "cloudflare.com"]
            try:
                if any(domain in request_url for domain in allowed_domains):
                    route.continue_()
                else:
                    # Block suspicious redirects
                    route.abort()
            except PlaywrightError as e:
                # Playwright can race-close routes; ignore already-handled routes.
                if "already handled" not in str(e).lower():
                    raise
        
        # Set up request interception
        page.route("**/*", handle_request)
        
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        
        # Remove route handler after page load
        page.unroute("**/*")
        
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Find the data table
        table = soup.find("table", class_="tr-table")
        if not table:
            table = soup.find("table", class_="datatable")
        if not table:
            tables = soup.find_all("table")
            table = tables[0] if tables else None
        
        if not table:
            return data
        
        # Get headers
        headers = []
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                for th in header_row.find_all(["th", "td"]):
                    headers.append(th.get_text(strip=True).lower())
        
        # Get data rows
        tbody = table.find("tbody") or table
        for row in tbody.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            
            # First cell is usually rank or team
            team_cell = None
            for cell in cells:
                text = cell.get_text(strip=True)
                # Look for team name (not a number, not empty)
                if text and not re.sub(r"[^A-Za-z0-9]", "", text).isdigit():
                    team_cell = cell
                    break
            
            if not team_cell:
                continue
            
            team_name = clean_team_name(team_cell.get_text(strip=True))
            normalized = normalize_team_for_matching(team_name, sport)
            
            if not normalized:
                continue
            
            row_data = {"original_name": team_name}
            for idx, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                if idx < len(headers):
                    row_data[headers[idx]] = cell_text
                row_data[f"col_{idx}"] = cell_text
            
            # Store under normalized name ONLY - no keyword pollution
            data[normalized] = row_data
            
            # Also store under raw cleaned name if different
            raw_clean = clean_team_name(team_name).lower().strip()
            if raw_clean and raw_clean != normalized and raw_clean not in data:
                data[raw_clean] = row_data
            
            # For PRO sports, also store under nickname keywords from TEAM_NAME_MAPPINGS
            # This lets "Pistons" find "Detroit Pistons", "Nets" find "Brooklyn Nets", etc.
            # Safe because pro team nicknames are unique (no collisions like college names)
            for mapping_key, mapping_aliases in TEAM_NAME_MAPPINGS.items():
                all_variants = [mapping_key] + mapping_aliases
                norm_variants = [normalize_team_for_matching(v, sport) for v in all_variants]
                if normalized in norm_variants or raw_clean in [v.lower().strip() for v in all_variants]:
                    for variant in all_variants:
                        v_lower = variant.lower().strip()
                        if v_lower and v_lower not in data:
                            data[v_lower] = row_data
                    break
        
    except Exception as e:
        print(f"    Error scraping {url}: {e}")
        # Try to unroute on error
        try:
            page.unroute("**/*")
        except:
            pass
    
    time.sleep(REQUEST_DELAY)
    # Debug: show how many unique teams were scraped from this page
    unique_originals = set(v.get("original_name", "") for v in data.values() if isinstance(v, dict))
    print(f"      Scraped {len(unique_originals)} unique teams, {len(data)} total keys from {url.split('/')[-1]}")
    if len(unique_originals) < 5:
        print(f"      [WARN] Very few teams scraped - page may not have loaded. Keys: {list(data.keys())[:10]}")
    return data


# Words too generic to drive a match on their own
_SOS_GENERIC_WORDS = frozenset({
    "state", "a", "m", "the", "of",
    "north", "south", "east", "west", "central", "southern",
    "northern", "eastern", "western", "southeastern", "southwestern",
    "northeastern", "northwestern", "new", "texas", "carolina",
    "florida", "alabama", "mississippi", "virginia", "california",
})


_SOS_MANUAL_ALIASES = {
    # ── ABBREVIATIONS (algorithm can't derive these) ──────────────────────
    "uic":                  "illinois chicago",
    "fgcu":                 "florida gulf coast",
    "florida gulf coast":   "florida gulf coast",
    "fla gulf coast":       "florida gulf coast",
    "fl gulf coast":        "florida gulf coast",
    "ucf":                  "central florida",
    "usc":                  "southern california",
    "utep":                 "texas el paso",
    "utsa":                 "texas san antonio",
    "uab":                  "alabama birmingham",
    "umbc":                 "maryland baltimore county",
    "uncw":                 "north carolina wilmington",
    "unc":                  "north carolina",
    "lsu":                  "louisiana state",
    "smu":                  "southern methodist",
    "tcu":                  "texas christian",
    "vcu":                  "virginia commonwealth",
    "byu":                  "brigham young",
    "unlv":                 "nevada las vegas",
    "umass":                "massachusetts",
    "cofc":                 "college of charleston",
    "col of charleston":    "college of charleston",
    "ualr":                 "little rock",
    "ark little rock":      "little rock",
    "sfb":                  "stonehill",
    "liu":                  "long island",
    "njit":                 "new jersey tech",
    "ipfw":                 "purdue fort wayne",
    "iupui":                "purdue fort wayne",
    "purdue fort wayne":    "purdue fort wayne",
    "nku":                  "northern kentucky",
    "siue":                 "southern illinois edwardsville",
    "siu edwardsville":     "southern illinois edwardsville",
    "csun":                 "cs northridge",
    "csuf":                 "cs fullerton",
    "csub":                 "cs bakersfield",
    "ucd":                  "uc davis",
    "ucr":                  "uc riverside",
    "ucsd":                 "uc san diego",
    "ucsb":                 "uc santa barbara",
    # ── ATHLETICS RELOCATION — TR uses "Sacramento" as of 2025-26 ────────
    "athletics":            "sacramento",
    "oakland athletics":    "sacramento",
    "oakland":              "sacramento",
    "sacramento athletics": "sacramento",
    "las vegas athletics":  "sacramento",
    "sac athletics":        "sacramento",
    # ── NHL RELOCATION — Utah Mammoth (was Coyotes / Utah HC) ────────────
    "utah hockey club":     "utah mammoth",
    "utah hc":              "utah mammoth",
    # ── PRO CITY-ONLY ALIASES (TR drops mascot for these) ────────────────
    "indiana pacers":       "indiana",
    "oklahoma city thunder":"okla city",
    "portland trail blazers": "portland",
    "golden state warriors":"golden state",
    # ── NCAAB / NCAAF ALIASES NOT DERIVABLE ALGORITHMICALLY ──────────────
    "queens":               "queens university",    # disambiguation: Queens NC
    "queens nc":            "queens university",
    "queens (nc)":          "queens university",
    "st. thomas":           "st thomas",
    "st thomas mn":         "st thomas",
    "st thomas (mn)":       "st thomas",
    "lincoln mem":          "lincoln memorial",
    "bellarmine knights":   "bellarmine",
    "le moyne dolphins":    "le moyne",
    "mercyhurst lakers":    "mercyhurst",
    "stonehill skyhawks":   "stonehill",
    "pitt":                 "pittsburgh",
    "miami hurricanes":     "miami fl",
    "miami redhawks":       "miami oh",
    "miami (fl)":           "miami fl",
    "miami (oh)":           "miami oh",
    "miami ohio":           "miami oh",
}


def find_team_in_data(
    team_name: str,
    data: Dict[str, Dict],
    sport: str = "",
    report_failure: bool = True,
) -> Optional[Dict]:
    """
    Find a team in scraped data using scored matching with anti-contamination guards.

    Tiers:
      0. Manual alias lookup (non-derivable abbreviations)
      1. Exact normalized match
      2. Exact keyword match
      2b. Containment match (pro sports only - safe because city names are unique per league)
      3. College team alias lookup
      4. Scored word-overlap (requires >50% coverage, generic-only blocked)
    """
    if not data:
        return None

    # -- Tier 0: Manual alias lookup (before any fuzzy) --
    _alias_key = normalize_team_for_matching(team_name, sport)
    # Also try raw lowercase for alias lookup
    _alias_raw = team_name.lower().strip()
    _canonical = _SOS_MANUAL_ALIASES.get(_alias_key) or _SOS_MANUAL_ALIASES.get(_alias_raw)
    if _canonical:
        # Try multiple forms to find in data dict
        _canon_norm = normalize_team_for_matching(_canonical, sport)
        if _canon_norm in data:
            return data[_canon_norm]
        # Also try the canonical string directly (data keys may be raw-lowered)
        if _canonical in data:
            return data[_canonical]
        # Containment: look for data keys that contain or are contained by canonical
        for dk, dv in data.items():
            if _canonical in dk or dk in _canonical:
                return dv
            if _canon_norm in dk or dk in _canon_norm:
                return dv

    is_pro = sport.lower() in ("nba", "nfl", "mlb", "nhl") if sport else False
    normalized = normalize_team_for_matching(team_name, sport)
    keywords = get_team_keywords(team_name, sport)

    # -- Tier 1: exact normalized match --
    if normalized in data:
        return data[normalized]

    # -- Tier 2: exact keyword match --
    for keyword in keywords:
        if keyword in data:
            return data[keyword]

    # -- Tier 2a: NHL abbreviation bridge (e.g., "edmonton oilers" -> "edm") --
    if sport.lower() == "nhl":
        for abbr in _nhl_abbrev_candidates(team_name):
            if abbr in data:
                return data[abbr]

    # -- Tier 2b: containment match (pro sports ONLY) --
    # TR uses city-only ("Detroit"), schedule uses full ("Detroit Pistons")
    # Safe for pro because city names are unique within each league
    # NOT safe for college (Indiana != Indiana State)
    if is_pro:
        target_words = set(normalized.split())
        for key in data:
            key_words = set(key.split())
            # Either data key is subset of target, or target is subset of data key
            if key_words and target_words and (key_words <= target_words or target_words <= key_words):
                return data[key]

    # -- Tier 3: college team alias lookup --
    for alias_key, alias_variants in COLLEGE_TEAM_ALIASES.items():
        norm_alias_key = normalize_team_for_matching(alias_key, sport)
        all_alias_norms = [normalize_team_for_matching(v, sport) for v in alias_variants]
        if normalized == norm_alias_key or normalized in all_alias_norms:
            # Try each variant against data keys - both normalized and raw
            for variant in [alias_key] + alias_variants:
                norm_v = normalize_team_for_matching(variant, sport)
                if norm_v in data:
                    return data[norm_v]
                # Also try raw lowercase (data dict stores both normalized and raw)
                raw_v = variant.lower().strip()
                if raw_v in data:
                    return data[raw_v]

    # -- Tier 3.5: Mascot-drop (SAO includes mascot, TR typically does not) --
    # "Bradley Braves" → try "Bradley"; "North Texas Mean Green" → try "North Texas"
    # Only apply when name has ≥ 2 words and the result has ≥ 1 word
    _words = normalized.split()
    if len(_words) >= 2:
        _no_mascot = " ".join(_words[:-1])
        if _no_mascot in data:
            return data[_no_mascot]
        # Also run keywords on the mascot-stripped form
        _nm_kw = get_team_keywords(_no_mascot, sport)
        for _kw in _nm_kw:
            if _kw in data:
                return data[_kw]

    # -- Tier 4: scored word-overlap (BEST match, not FIRST) --
    # Ties broken by secondary difflib score for determinism
    tset = set(normalized.split())
    t_meaningful = tset - _SOS_GENERIC_WORDS

    best_key = None
    best_score = 0.0
    best_fuzzy_tiebreak = 0.0

    for key, val in data.items():
        kset = set(key.split())
        overlap = tset & kset
        if not overlap:
            continue

        meaningful_overlap = overlap - _SOS_GENERIC_WORDS

        # BLOCK: if only generic words overlap (e.g. just "state"), reject
        if not meaningful_overlap:
            continue

        # Score = proportion of words covered
        denom = max(len(tset), len(kset))
        score = len(overlap) / denom if denom > 0 else 0

        # Boost for meaningful word coverage
        if t_meaningful:
            m_ratio = len(meaningful_overlap) / len(t_meaningful)
            score = (score + m_ratio) / 2.0

        # Secondary tie-break via difflib (deterministic when primary scores tie)
        fuzzy_tb = difflib.SequenceMatcher(None, normalized, key).ratio()

        if score > best_score or (score == best_score and fuzzy_tb > best_fuzzy_tiebreak):
            best_score = score
            best_key = key
            best_fuzzy_tiebreak = fuzzy_tb

    # Also check original_name field in data values
    if best_score < 0.50:
        for key, val in data.items():
            original = normalize_team_for_matching(val.get("original_name", ""), sport)
            if not original:
                continue

            oset = set(original.split())
            overlap = tset & oset
            if not overlap:
                continue

            meaningful_overlap = overlap - _SOS_GENERIC_WORDS
            if not meaningful_overlap:
                continue

            denom = max(len(tset), len(oset))
            score = len(overlap) / denom if denom > 0 else 0
            if t_meaningful:
                m_ratio = len(meaningful_overlap) / len(t_meaningful)
                score = (score + m_ratio) / 2.0

            fuzzy_tb = difflib.SequenceMatcher(None, normalized, key).ratio()
            if score > best_score or (score == best_score and fuzzy_tb > best_fuzzy_tiebreak):
                best_score = score
                best_key = key
                best_fuzzy_tiebreak = fuzzy_tb

    if best_key is not None and best_score >= 0.50:
        return data[best_key]

    # === V13 TIER 5: FUZZY MATCHING WITH DIFFLIB ===
    # When all structured matching fails, use character-level fuzzy matching
    # This catches abbreviation variants we didn't explicitly code
    best_fuzzy = None
    best_fuzzy_score = 0.0
    best_fuzzy_key = None
    
    for key, val in data.items():
        # Use SequenceMatcher for fuzzy comparison
        score = difflib.SequenceMatcher(None, normalized, key).ratio()
        
        # Also try against original_name if present
        orig = val.get("original_name", "")
        if orig:
            orig_norm = normalize_team_for_matching(orig, sport)
            orig_score = difflib.SequenceMatcher(None, normalized, orig_norm).ratio()
            score = max(score, orig_score)
        
        if score > best_fuzzy_score:
            best_fuzzy_score = score
            best_fuzzy = val
            best_fuzzy_key = key
    
    # Accept fuzzy match if score >= 0.82 (high confidence only — prevents contamination)
    if best_fuzzy_score >= 0.82:
        print(f"    [V13 FUZZY] '{team_name}' -> '{best_fuzzy_key}' (score={best_fuzzy_score:.2f})")
        return best_fuzzy
    
    # === V13 TIER 6: REPORT FAILURE FOR LIVE FETCH ===
    # At this point we've exhausted all matching - log for potential live fetch
    if report_failure:
        print(f"    [V13 MATCH FAIL] '{team_name}' (normalized: '{normalized}') - NO MATCH FOUND")
        print(f"        Best fuzzy candidate: '{best_fuzzy_key}' (score={best_fuzzy_score:.2f})")

        # Store failed team for batch recovery attempt
        if not hasattr(find_team_in_data, '_failed_teams'):
            find_team_in_data._failed_teams = []
        find_team_in_data._failed_teams.append({
            'schedule_name': team_name,
            'normalized': normalized,
            'best_candidate': best_fuzzy_key,
            'best_score': best_fuzzy_score
        })

        UNMATCHED_TEAMS.append({
            "raw_team": team_name,
            "sport": sport,
            "date": (TARGET_DATE or datetime.now(ET_TZ).date()).isoformat(),
        })
    return None




def fetch_team_stats_live(team_name: str, sport: str = "ncaab") -> Optional[Dict]:
    """
    V13: LIVE FETCH - When matching fails, directly scrape TeamRankings for the team.
    This is the NUCLEAR option - makes HTTP request for each failed team.
    """
    import requests
    
    # Normalize team name for URL
    url_name = team_name.lower().strip()
    url_name = re.sub(r'[^a-z0-9]+', '-', url_name).strip('-')
    
    # Try multiple URL patterns that TeamRankings might use
    url_patterns = [
        f"https://www.teamrankings.com/ncaa-basketball/team/{url_name}/stats",
        f"https://www.teamrankings.com/ncaa-basketball/team/{url_name}",
    ]
    
    # Also try common abbreviations
    abbrev_map = {
        'cal state': 'cs',
        'california state': 'cs', 
        'uc ': 'uc-',
        'florida international': 'florida-intl',
        'appalachian state': 'app-state',
        'tennessee-martin': 'ut-martin',
        'fairleigh dickinson': 'f-dickinson',
        'chicago state': 'chicago-st',
    }
    
    for full, abbrev in abbrev_map.items():
        if full in url_name:
            alt_name = url_name.replace(full.replace(' ', '-'), abbrev)
            url_patterns.append(f"https://www.teamrankings.com/ncaa-basketball/team/{alt_name}/stats")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for url in url_patterns:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Extract PPG from team page
                stats = {}
                for row in soup.select('table tr'):
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                        
                        try:
                            if 'points per game' in label or label == 'ppg':
                                stats['ppg'] = float(value)
                            elif 'opponent points' in label or 'opp ppg' in label:
                                stats['opp_ppg'] = float(value)
                        except:
                            pass
                
                if stats.get('ppg', 0) > 0:
                    print(f"    [V13 LIVE FETCH SUCCESS] '{team_name}' -> PPG={stats.get('ppg')}")
                    return {
                        'ppg': stats.get('ppg', 0),
                        'opp_ppg': stats.get('opp_ppg', 0),
                        'original_name': team_name,
                        'source': 'live_fetch'
                    }
        except Exception as e:
            continue
    
    print(f"    [V13 LIVE FETCH FAILED] '{team_name}' - could not retrieve from TeamRankings")
    return None


def scrape_nhl_from_hockey_reference(page: Page, team_names: List[str]) -> Dict[str, TeamStats]:
    """Scrape NHL team stats from Hockey-Reference.com standings page."""
    team_stats = {}
    
    # Initialize stats for all teams
    for name in team_names:
        team_stats[name] = TeamStats(name=name)
    
    print(f"  Scraping team data from Hockey-Reference...")
    
    config = SPORTS_CONFIG["nhl"]
    standings_url = config["standings_url"]
    
    try:
        print(f"    - Loading standings from {standings_url}...")
        page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Hockey-Reference has multiple tables - find standings tables
        # They typically have class="stats_table" and contain team records
        all_data = {}
        
        for table in soup.find_all("table", class_="stats_table"):
            tbody = table.find("tbody")
            if not tbody:
                continue
            
            for row in tbody.find_all("tr"):
                # Skip header rows within tbody
                if row.get("class") and "thead" in row.get("class", []):
                    continue
                
                cells = row.find_all(["td", "th"])
                if len(cells) < 5:
                    continue
                
                # First cell is usually team name
                team_cell = row.find("th", {"data-stat": "team_name"}) or cells[0]
                team_link = team_cell.find("a")
                if team_link:
                    team_name = clean_team_name(team_link.get_text(strip=True))
                else:
                    team_name = clean_team_name(team_cell.get_text(strip=True))
                
                if not team_name:
                    continue
                
                normalized = normalize_team_for_matching(team_name, "nhl")
                
                # Extract data by data-stat attribute or position
                row_data = {"original_name": team_name}
                for idx, cell in enumerate(cells):
                    stat = cell.get("data-stat", "")
                    val = cell.get_text(strip=True)
                    if stat:
                        row_data[stat] = val
                    # Also store by position for fallback
                    row_data[f"col_{idx}"] = val
                
                all_data[normalized] = row_data
                
                # Also store under raw cleaned name if different
                raw_clean = clean_team_name(team_name).lower().strip()
                if raw_clean and raw_clean != normalized and raw_clean not in all_data:
                    all_data[raw_clean] = row_data
                # Store three-letter team code if Hockey-Reference exposes it in team href.
                if team_link and team_link.get("href"):
                    _m = re.search(r"/teams/([A-Z]{2,3})/", str(team_link.get("href") or ""))
                    if _m:
                        all_data[_m.group(1).lower()] = row_data
        
        # Match teams and populate stats
        matched = 0
        for name, stats in team_stats.items():
            team_data = find_team_in_data(name, all_data, "nhl")
            if team_data:
                matched += 1
                
                # Parse wins, losses, OT losses
                wins = int(team_data.get("wins", team_data.get("col_1", "0")) or 0)
                losses = int(team_data.get("losses", team_data.get("col_2", "0")) or 0)
                ot_losses = int(team_data.get("losses_ot", team_data.get("col_3", "0")) or 0)
                
                stats.wins = wins
                stats.losses = losses
                stats.ties = ot_losses  # OT losses stored as ties for display
                
                total = wins + losses + ot_losses
                if total > 0:
                    # NHL points percentage: (Wins + 0.5*OTL) / Games
                    stats.win_pct = (wins + 0.5 * ot_losses) / total
                
                # Goals for/against
                gf = parse_float(team_data.get("goals", team_data.get("goals_for", team_data.get("col_5", "0"))))
                ga = parse_float(team_data.get("goals_against", team_data.get("opp_goals", team_data.get("col_6", "0"))))
                games = total if total > 0 else 1
                
                stats.ppg = round(gf / games, 2) if gf > 0 else 0
                stats.opp_ppg = round(ga / games, 2) if ga > 0 else 0
                stats.point_diff = round(stats.ppg - stats.opp_ppg, 2)
                
                # SOS - Hockey-Reference shows SOS in some views
                sos = team_data.get("strength_of_schedule", team_data.get("sos", ""))
                if sos:
                    stats.sos_rating = parse_float(sos)
                
                # Home/Away records if available
                home_rec = team_data.get("home_record", "")
                away_rec = team_data.get("away_record", "")
                if home_rec:
                    stats.home_record = home_rec
                    w, l, t, pct = parse_record(home_rec)
                    stats.home_win_pct = pct
                if away_rec:
                    stats.away_record = away_rec
                    w, l, t, pct = parse_record(away_rec)
                    stats.away_win_pct = pct
        
        print(f"      Matched {matched}/{len(team_stats)} teams from standings")
        
        # Try to get additional stats from the season summary page
        stats_url = config.get("stats_url")
        if stats_url:
            print(f"    - Loading team stats...")
            time.sleep(REQUEST_DELAY)
            page.goto(stats_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            
            # Look for team stats table
            stats_table = soup.find("table", id="team_stats") or soup.find("table", class_="stats_table")
            if stats_table:
                tbody = stats_table.find("tbody")
                if tbody:
                    stats_data: Dict[str, Dict[str, str]] = {}
                    for row in tbody.find_all("tr"):
                        cells = row.find_all(["td", "th"])
                        if len(cells) < 3:
                            continue
                        
                        team_cell = row.find("th", {"data-stat": "team_name"}) or cells[0]
                        team_link = team_cell.find("a")
                        team_name = clean_team_name((team_link or team_cell).get_text(strip=True))
                        if not team_name:
                            continue

                        row_data = {"original_name": team_name}
                        for idx, cell in enumerate(cells):
                            stat = cell.get("data-stat", "")
                            val = cell.get_text(strip=True)
                            if stat:
                                row_data[stat] = val
                            row_data[f"col_{idx}"] = val

                        norm_name = normalize_team_for_matching(team_name, "nhl")
                        stats_data[norm_name] = row_data

                        raw_name = clean_team_name(team_name).lower().strip()
                        if raw_name and raw_name not in stats_data:
                            stats_data[raw_name] = row_data
                        if team_link and team_link.get("href"):
                            _m = re.search(r"/teams/([A-Z]{2,3})/", str(team_link.get("href") or ""))
                            if _m:
                                stats_data[_m.group(1).lower()] = row_data

                    for name, stats in team_stats.items():
                        # Supplemental table is optional. Avoid escalating false hard-fail logs here.
                        team_data = find_team_in_data(name, stats_data, "nhl", report_failure=False)
                        if not team_data:
                            continue

                        ppg_val = parse_float(
                            team_data.get("goals_per_game", team_data.get("goals_pct", ""))
                        )
                        if ppg_val > 0:
                            stats.ppg = ppg_val

                        opp_ppg_val = parse_float(team_data.get("opp_goals_per_game", ""))
                        if opp_ppg_val > 0:
                            stats.opp_ppg = opp_ppg_val
        
        # Calculate rankings based on points
        sorted_teams = sorted(
            [(n, s) for n, s in team_stats.items() if s.wins > 0],
            key=lambda x: (x[1].wins * 2 + x[1].ties, x[1].point_diff),
            reverse=True
        )
        for rank, (name, stats) in enumerate(sorted_teams, 1):
            stats.power_rank = rank
            if stats.sos_rank == 0:
                stats.sos_rank = rank  # Use power rank as SOS proxy if not available
        
    except Exception as e:
        print(f"    Error scraping NHL data: {e}")
    
    return team_stats


def scrape_all_team_data(page: Page, sport: str, team_names: List[str]) -> Dict[str, TeamStats]:
    """Scrape all relevant data for teams playing today."""
    config = SPORTS_CONFIG[sport]
    
    # NHL uses Hockey-Reference instead of TeamRankings
    if config.get("use_hockey_reference"):
        return scrape_nhl_from_hockey_reference(page, team_names)
    
    team_stats = {}
    
    print(f"  Scraping team data from TeamRankings...")
    
    # Initialize stats for all teams
    for name in team_names:
        team_stats[name] = TeamStats(name=name)
    
    # 1. SOS Rankings
    print(f"    - Strength of Schedule...")
    sos_url = f"{BASE_URL_RANKINGS}{config['sos_path']}"
    sos_data = scrape_rankings_table(page, sos_url, sport)
    
    matched = 0
    unmatched = []
    for name, stats in team_stats.items():
        team_data = find_team_in_data(name, sos_data, sport)
        if team_data:
            matched += 1
            # SOS rank is usually first column, rating might be in another
            stats.sos_rank = parse_rank(
                team_data.get("rank")
                or team_data.get("#")
                or team_data.get("col_0")
                or ""
            )
            stats.sos_rating = parse_float(
                team_data.get("rating")
                or team_data.get("schedule strength")
                or team_data.get("other sos")
                or team_data.get("col_2")
                or team_data.get("col_3")
                or ""
            )
            if stats.sos_rank == 0:
                # Try other columns
                for key in ["rank", "#", "col_1"]:
                    r = parse_rank(team_data.get(key, ""))
                    if r > 0:
                        stats.sos_rank = r
                        break
                if stats.sos_rank == 0:
                    print(f"      [WARN] {name}: found in data but SOS rank=0. Columns: {list(team_data.keys())[:8]}")
        else:
            unmatched.append(name)
    print(f"      Matched {matched}/{len(team_stats)} teams")
    if unmatched:
        print(f"      [WARN] Unmatched teams: {unmatched[:10]}")
    
    # 2. Overall Record / Win Trends
    print(f"    - Win/Loss Records...")
    record_url = f"{BASE_URL_RANKINGS}{config['record_path']}"
    record_data = scrape_rankings_table(page, record_url, sport)
    
    matched = 0
    records_found = 0
    for name, stats in team_stats.items():
        team_data = find_team_in_data(name, record_data, sport)
        if team_data:
            matched += 1
            # Look for record in various columns - win_trends page has it in col_1 (Win-Loss Record)
            # Headers on TeamRankings are like: "Team", "Win-Loss Record", "Win %", "MOV", "ATS +/-"
            for key in ["win-loss record", "win-loss", "record", "col_1", "col_2", "col_3", "w-l", "w-l-t"]:
                record_str = team_data.get(key, "")
                if re.search(r"\d+-\d+", record_str):
                    w, l, t, pct = parse_record(record_str)
                    if w > 0 or l > 0:  # Valid record found
                        stats.wins, stats.losses, stats.ties, stats.win_pct = w, l, t, pct
                        records_found += 1
                        break
            # Win percentage might be in a separate column (col_2 = "Win %")
            if stats.win_pct == 0:
                for key in ["win %", "win%", "pct", "col_2", "col_3"]:
                    pct_str = team_data.get(key, "")
                    if pct_str:
                        stats.win_pct = parse_percentage(pct_str)
                        if stats.win_pct > 0:
                            break
    print(f"      Matched {matched}/{len(team_stats)} teams, {records_found} records parsed")
    
    # Fallback: If records weren't found, try the standings page
    if records_found < len(team_stats) // 2:
        print(f"    - Trying standings page for records...")
        standings_path = config.get('record_path', '').replace('/trends/win_trends', '/standings/')
        if '/nba/' in standings_path:
            standings_url = f"{BASE_URL_RANKINGS}/nba/standings/"
        elif '/ncaa-basketball/' in config.get('record_path', ''):
            standings_url = f"{BASE_URL_RANKINGS}/ncb/standings/"
        elif '/college-football/' in config.get('record_path', ''):
            standings_url = f"{BASE_URL_RANKINGS}/ncf/standings/"
        elif '/nfl/' in config.get('record_path', ''):
            standings_url = f"{BASE_URL_RANKINGS}/nfl/standings/"
        elif '/mlb/' in config.get('record_path', ''):
            standings_url = f"{BASE_URL_RANKINGS}/mlb/standings/"
        else:
            standings_url = None
        
        if standings_url:
            standings_data = scrape_rankings_table(page, standings_url, sport)
            for name, stats in team_stats.items():
                if stats.wins == 0 and stats.losses == 0:
                    team_data = find_team_in_data(name, standings_data, sport)
                    if team_data:
                        # Standings usually have W and L in separate columns
                        for w_key in ["w", "wins", "col_1", "col_2"]:
                            w_val = team_data.get(w_key, "")
                            if w_val and w_val.isdigit():
                                stats.wins = int(w_val)
                                break
                        for l_key in ["l", "losses", "col_2", "col_3"]:
                            l_val = team_data.get(l_key, "")
                            if l_val and l_val.isdigit():
                                stats.losses = int(l_val)
                                break
                        if stats.wins + stats.losses > 0:
                            stats.win_pct = stats.wins / (stats.wins + stats.losses)
    
    # 3. Points Per Game
    print(f"    - Points/Goals Per Game...")
    ppg_url = f"{BASE_URL_RANKINGS}{config['ppg_path']}"
    ppg_data = scrape_rankings_table(page, ppg_url, sport)
    
    matched = 0
    live_fetched = 0
    _live_data_cache: Dict[str, Dict] = {}  # keyed by schedule team name; used in OppPPG section
    for name, stats in team_stats.items():
        team_data = find_team_in_data(name, ppg_data, sport)
        
        # V13: LIVE FETCH FALLBACK when matching fails
        if not team_data and sport.lower() in ("ncaab", "ncaaf"):
            team_data = fetch_team_stats_live(name, sport)
            if team_data:
                live_fetched += 1
                _live_data_cache[name] = team_data  # cache so OppPPG loop can reuse
        
        if team_data:
            matched += 1
            # Check for direct ppg field first (from live fetch)
            if team_data.get('ppg', 0) > 0:
                stats.ppg = team_data['ppg']
            else:
                for key in ["points per game", "ppg", "avg", "col_2", "col_3", "2024", "2025", "2026"]:
                    val = team_data.get(key, "")
                    if val and parse_float(val) > 0:
                        stats.ppg = parse_float(val)
                        break
            # If live fetch also returned opp_ppg, set it now so OppPPG loop can skip this team
            if team_data.get('opp_ppg', 0) > 0:
                stats.opp_ppg = team_data['opp_ppg']
    if live_fetched > 0:
        print(f"      Matched {matched}/{len(team_stats)} teams ({live_fetched} via live fetch)")
    else:
        print(f"      Matched {matched}/{len(team_stats)} teams")
    
    # 4. Opponent Points Per Game
    print(f"    - Opponent Points/Goals Per Game...")
    opp_ppg_url = f"{BASE_URL_RANKINGS}{config['opp_ppg_path']}"
    opp_ppg_data = scrape_rankings_table(page, opp_ppg_url, sport)
    
    matched = 0
    for name, stats in team_stats.items():
        # Skip teams whose opp_ppg was already populated from live fetch
        if stats.opp_ppg > 0:
            matched += 1
            stats.point_diff = round(stats.ppg - stats.opp_ppg, 1)
            continue

        team_data = find_team_in_data(name, opp_ppg_data, sport)
        
        # Use live-fetched data if we cached it during the PPG section
        if not team_data:
            team_data = _live_data_cache.get(name)
        
        if team_data:
            matched += 1
            if team_data.get('opp_ppg', 0) > 0:
                stats.opp_ppg = team_data['opp_ppg']
            else:
                for key in ["opponent points per game", "opp ppg", "avg", "col_2", "col_3", "2024", "2025", "2026"]:
                    val = team_data.get(key, "")
                    if val and parse_float(val) > 0:
                        stats.opp_ppg = parse_float(val)
                        break
        # Calculate point differential
        stats.point_diff = round(stats.ppg - stats.opp_ppg, 1)
    print(f"      Matched {matched}/{len(team_stats)} teams")
    
    # 5. Conference Record (college sports only)
    if "conf_record_path" in config:
        print(f"    - Conference Records...")
        conf_url = f"{BASE_URL_RANKINGS}{config['conf_record_path']}"
        conf_data = scrape_rankings_table(page, conf_url, sport)
        
        matched = 0
        records_found = 0
        for name, stats in team_stats.items():
            team_data = find_team_in_data(name, conf_data, sport)
            if team_data:
                matched += 1
                # Conference trends page has record in col_1 (Win-Loss Record column)
                for key in ["win-loss record", "record", "col_1", "col_2", "col_3", "conf", "conference"]:
                    record_str = team_data.get(key, "")
                    if re.search(r"\d+-\d+", record_str):
                        w, l, t, pct = parse_record(record_str)
                        if w > 0 or l > 0:
                            stats.conf_record = record_str
                            stats.conf_win_pct = pct
                            records_found += 1
                            break
        print(f"      Matched {matched}/{len(team_stats)} teams, {records_found} records parsed")
    
    # 6. Power Rankings
    print(f"    - Power Rankings...")
    rank_url = f"{BASE_URL_RANKINGS}{config['rankings_path']}/predictive-by-other"
    rank_data = scrape_rankings_table(page, rank_url, sport)
    
    matched = 0
    for name, stats in team_stats.items():
        team_data = find_team_in_data(name, rank_data, sport)
        if team_data:
            matched += 1
            stats.power_rank = parse_rank(team_data.get("col_0", team_data.get("rank", "")))
            if stats.power_rank == 0:
                for key in ["rank", "col_1"]:
                    r = parse_rank(team_data.get(key, ""))
                    if r > 0:
                        stats.power_rank = r
                        break
    print(f"      Matched {matched}/{len(team_stats)} teams")
    
    # -- CROSS-CONTAMINATION VALIDATION --
    # Detect if multiple teams ended up with identical stat profiles
    from collections import Counter
    profiles = {}
    for name, stats in team_stats.items():
        # Create a fingerprint from key metrics
        if stats.sos_rank > 0 or stats.ppg > 0:
            fp = (stats.wins, stats.losses, stats.sos_rank, round(stats.ppg, 1), round(stats.point_diff, 1))
            profiles.setdefault(fp, []).append(name)
    
    contaminated = False
    for fp, teams in profiles.items():
        if len(teams) > 1 and fp[2] > 0:  # Multiple teams, non-zero SOS
            contaminated = True
            print(f"    [CONTAMINATION WARNING] {len(teams)} teams share identical profile "
                  f"(W-L={fp[0]}-{fp[1]}, SOS={fp[2]}, PPG={fp[3]}, Diff={fp[4]}): {teams}")
    
    if not contaminated:
        print(f"    [VALIDATION OK] No cross-contamination detected across {len(team_stats)} teams")
    
    return team_stats


# ============================================================================
# SOS INTEGRITY + UNMATCHED TEAMS LOGGING
# ============================================================================

def write_sos_integrity(matchups, sport: str):
    import json
    from pathlib import Path
    ymd = (TARGET_DATE or datetime.now(ET_TZ).date()).strftime("%Y%m%d")
    sos_dir = Path("sos_data")
    sos_dir.mkdir(exist_ok=True)

    num_schedule_games = len(matchups)
    num_sos_games = len([
        m for m in matchups
        if m.away_stats is not None and m.home_stats is not None
    ])
    integrity = {
        "num_schedule_games": int(num_schedule_games),
        "num_sos_games": int(num_sos_games),
        "coverage_ratio": float(num_sos_games) / max(1, num_schedule_games),
    }
    (sos_dir / f"SOSIntegrity_{sport.upper()}_{ymd}.json").write_text(
        json.dumps(integrity, indent=2),
        encoding="utf-8",
    )


def write_unmatched_teams_log(sport: str):
    if not UNMATCHED_TEAMS:
        return
    import json
    from pathlib import Path
    import pandas as pd
    ymd = (TARGET_DATE or datetime.now(ET_TZ).date()).strftime("%Y%m%d")
    outdir = Path("sos_unresolved")
    outdir.mkdir(exist_ok=True)
    pd.DataFrame(UNMATCHED_TEAMS).to_csv(
        outdir / f"SOS_UnmatchedTeams_{sport.upper()}_{ymd}.csv",
        index=False,
    )


# ============================================================================
# EXCEL OUTPUT
# ============================================================================

def create_matchup_excel(matchups: List[Matchup], sport: str, output_dir: str) -> Optional[str]:
    """Create a professional Excel file with side-by-side matchup comparisons."""
    if not matchups:
        return None

    date_str = (TARGET_DATE or datetime.now(ET_TZ).date()).strftime("%Y-%m-%d")
    resolver = None
    try:
        resolvers = build_resolvers_from_schedule_dir(str(_BASE_DIR / "stats_output"), date_str)
        resolver = resolvers.get(sport.upper())
        if resolver:
            print(f"  SOS resolver: {sport.upper()} {len(resolver.games)} games")
        else:
            print(f"  SOS resolver missing for {sport.upper()} on {date_str}")
    except Exception as e:
        print(f"  SOS resolver unavailable: {e}")

    # game_id_unresolved: resolver could not correlate to a Schedules entry.
    # DOES NOT mean SOS stats are missing — stats attach via m.away_stats/home_stats
    # before this function is called. Log for diagnostics only. Never crash on this.
    game_id_unresolved: List[Dict[str, Any]] = []

    for m in matchups:
        if resolver:
            match = resolver.resolve(
                sport.upper(),
                date_str,
                m.away_team,
                m.home_team,
                m.game_time,
            )
            if match.matched and match.game is not None:
                m.game_id = match.game.game_id
                m.match_confidence = match.confidence
                m.match_method = match.method
                # Enforce resolver canonical names so the SOS Excel is written
                # with the exact same team names the pipeline uses for joining.
                # Without this, TR/SAO raw names leak into the output and cause
                # find_matching_sos_row() misses even when data is present.
                m.away_team = match.game.away_team
                m.home_team = match.game.home_team
            else:
                m.game_id = make_game_id(sport.upper(), date_str, m.away_team, m.home_team)
                m.match_confidence = match.confidence
                m.match_method = "synthetic_id_only"
                game_id_unresolved.append({
                    "raw_away": m.away_team,
                    "raw_home": m.home_team,
                    "raw_time": m.game_time,
                    "raw_venue": "",
                    "league": sport.upper(),
                    "date": date_str,
                    "confidence": match.confidence,
                    "method": match.method,
                    "diagnostics": match.diagnostics,
                })
        else:
            m.game_id = make_game_id(sport.upper(), date_str, m.away_team, m.home_team)
            m.match_confidence = 0.0
            m.match_method = "synthetic_no_resolver"

    if game_id_unresolved:
        write_unresolved_csv(game_id_unresolved, sport.upper(), "sos_gameid", date_str)
        print(f"  [DIAG] {len(game_id_unresolved)}/{len(matchups)} games assigned synthetic "
              f"game_ids (Schedules resolver mismatch). SOS stats unaffected.")

    # Real data-gap check: games where SOS stats are actually missing.
    # This — not game_id resolver failures — is what check_unresolved_threshold must measure.
    stats_missing = [
        m for m in matchups
        if not _team_stats_has_real_data(m.away_stats) or not _team_stats_has_real_data(m.home_stats)
    ]
    for m in stats_missing:
        print(f"  [ERROR] SOS DATA GAP — no stats for {m.away_team} @ {m.home_team}")

    check_unresolved_threshold(
        unresolved_count=len(stats_missing),
        total_count=len(matchups),
        league=sport.upper(),
        source_name="SOS",
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Matchup Comparisons"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="1F4E79")
    subheader_fill = PatternFill("solid", fgColor="2E75B6")
    away_fill = PatternFill("solid", fgColor="FFF2CC")
    home_fill = PatternFill("solid", fgColor="E2EFDA")
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    ws.merge_cells("A1:F1")
    ws["A1"] = (
        f"{sport.upper()} - Strength of Schedule Report - "
        f"{(TARGET_DATE or datetime.now(ET_TZ).date()).strftime('%B %d, %Y')}"
    )
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = center_align

    row = 3

    for matchup in matchups:
        away = matchup.away_stats or TeamStats(name=matchup.away_team)
        home = matchup.home_stats or TeamStats(name=matchup.home_team)

        ws.merge_cells(f"A{row}:F{row}")
        ws[f"A{row}"] = f"{matchup.game_time} - {matchup.away_team} @ {matchup.home_team}"
        ws[f"A{row}"].font = Font(bold=True, size=12)
        ws[f"A{row}"].fill = header_fill
        ws[f"A{row}"].font = Font(bold=True, color="FFFFFF", size=12)
        ws[f"A{row}"].alignment = center_align
        row += 1

        ws[f"A{row}"] = "Metric"
        ws[f"B{row}"] = matchup.away_team
        ws[f"C{row}"] = matchup.home_team
        ws[f"D{row}"] = "Advantage"
        ws[f"E{row}"] = "game_id"
        ws[f"F{row}"] = "match_method"

        for col in "ABCDEF":
            ws[f"{col}{row}"].font = header_font
            ws[f"{col}{row}"].fill = subheader_fill
            ws[f"{col}{row}"].alignment = center_align
            ws[f"{col}{row}"].border = thin_border
        row += 1

        metrics = [
            ("Wins", away.wins, home.wins),
            ("Losses", away.losses, home.losses),
            ("SOS Rank", away.sos_rank, home.sos_rank),
            ("PPG", away.ppg, home.ppg),
            ("Opponent PPG", away.opp_ppg, home.opp_ppg),
            ("Point Diff", away.point_diff, home.point_diff),
            ("Power Rank", away.power_rank, home.power_rank),
        ]

        for metric_name, away_val, home_val in metrics:
            ws[f"A{row}"] = metric_name
            ws[f"B{row}"] = away_val
            ws[f"C{row}"] = home_val

            if metric_name in {"Losses", "SOS Rank", "Opponent PPG", "Power Rank"}:
                if away_val < home_val:
                    adv = matchup.away_team
                elif home_val < away_val:
                    adv = matchup.home_team
                else:
                    adv = "Even"
            else:
                if away_val > home_val:
                    adv = matchup.away_team
                elif home_val > away_val:
                    adv = matchup.home_team
                else:
                    adv = "Even"

            ws[f"D{row}"] = adv
            ws[f"E{row}"] = matchup.game_id
            ws[f"F{row}"] = matchup.match_method

            for col in "ABCDEF":
                ws[f"{col}{row}"].border = thin_border
                ws[f"{col}{row}"].alignment = center_align
            ws[f"B{row}"].fill = away_fill
            ws[f"C{row}"].fill = home_fill
            row += 1

        row += 1

    widths = {"A": 22, "B": 20, "C": 20, "D": 20, "E": 34, "F": 22}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    ymd = date_str.replace("-", "")
    out_path = os.path.join(output_dir, f"SOS_{sport.upper()}_{ymd}.xlsx")
    wb.save(out_path)
    print(f"  Wrote: {out_path}")
    return out_path

# ============================================================================
# MAIN
# ============================================================================

def scrape_sport(sport: str, browser: Browser) -> Tuple[List[Matchup], int]:
    """Scrape all data for a single sport."""
    print(f"\n{'='*60}")
    print(f"{sport.upper()} - Scraping Strength of Schedule Data")
    print(f"{'='*60}")
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
        java_script_enabled=True,
    )
    
    # Block known ad/malware domains at the context level
    def block_bad_domains(route):
        url = route.request.url.lower()
        blocked_patterns = [
            "endpointwipe", "doubleclick", "adservice", "adsystem",
            "popads", "popcash", "propellerads", "mgid", "taboola",
            "outbrain", "exoclick", "trafficjunky"
        ]
        try:
            if any(pattern in url for pattern in blocked_patterns):
                route.abort()
            else:
                route.continue_()
        except PlaywrightError as e:
            if "already handled" not in str(e).lower():
                raise
    
    context.route("**/*", block_bad_domains)
    page = context.new_page()
    
    try:
        # 1. Get today's games (prefer clean schedule workbook names if available)
        matchups = _load_matchups_from_schedule_workbook(sport)
        if not matchups:
            matchups = scrape_todays_games(page, sport)
        print(f"  Found {len(matchups)} games for today")
        
        if not matchups:
            return [], 0
        
        # 2. Get unique teams
        teams = set()
        for m in matchups:
            teams.add(m.away_team)
            teams.add(m.home_team)
        print(f"  Teams playing: {len(teams)}")
        
        # 3. Scrape stats for all teams
        team_stats = scrape_all_team_data(page, sport, list(teams))
        
        # 4. Attach stats to matchups
        matched_count = 0
        for m in matchups:
            m.away_stats = team_stats.get(m.away_team)
            m.home_stats = team_stats.get(m.home_team)
            if _team_stats_has_real_data(m.away_stats) and _team_stats_has_real_data(m.home_stats):
                matched_count += 1
        
        print(f"  Successfully matched data for {matched_count}/{len(matchups)} games")
        
        return matchups, matched_count
        
    finally:
        context.close()


def _parse_cli_args() -> Tuple[Optional[date_type], List[str]]:
    parser = argparse.ArgumentParser(description="SOS scraper")
    parser.add_argument("--date", dest="date_override", help="Target date (YYYY-MM-DD)")
    parser.add_argument("--sport", action="append", dest="sports", help="Single sport key (repeatable)")
    parser.add_argument("--sports", dest="sports_csv", help="Comma-separated sport keys")
    parser.add_argument("positional_date", nargs="?", help="Legacy date arg (YYYY-MM-DD)")
    args = parser.parse_args()

    raw_date = args.date_override or args.positional_date
    target_date = None
    if raw_date:
        try:
            target_date = date_type.fromisoformat(raw_date)
        except ValueError:
            print(f"ERROR: Invalid date format '{raw_date}'. Use YYYY-MM-DD.")
            sys.exit(1)

    selected: List[str] = []
    if args.sports:
        selected.extend(args.sports)
    if args.sports_csv:
        selected.extend([s.strip() for s in args.sports_csv.split(",") if s.strip()])
    if not selected:
        selected = list(SPORTS_CONFIG.keys())

    normalized: List[str] = []
    for sport in selected:
        key = str(sport or "").strip().lower()
        if key not in SPORTS_CONFIG:
            print(f"ERROR: Unsupported sport '{sport}'. Valid: {', '.join(SPORTS_CONFIG.keys())}")
            sys.exit(1)
        if key not in normalized:
            normalized.append(key)

    return target_date, normalized


def main():
    global TARGET_DATE
    TARGET_DATE, sports_to_run = _parse_cli_args()

    if TARGET_DATE:
        print(f"[DATE OVERRIDE] Using date: {TARGET_DATE.isoformat()}")

    output_dir = str(_BASE_DIR / "sos_data")
    os.makedirs(output_dir, exist_ok=True)

    target_str = (TARGET_DATE or datetime.now(ET_TZ).date()).strftime("%B %d, %Y")
    print("=" * 70)
    print("STRENGTH OF SCHEDULE SCRAPER")
    print(f"Date: {target_str}")
    print(f"Sports: {', '.join(s.upper() for s in sports_to_run)}")
    print("=" * 70)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
            try:
                for sport in sports_to_run:
                    out_file = ""
                    games_found = 0
                    games_matched = 0
                    status = "ERROR"
                    err_msg = ""
                    note_msg = ""

                    try:
                        matchups, games_matched = scrape_sport(sport, browser)
                        games_found = len(matchups)
                        if matchups:
                            out_file = create_matchup_excel(matchups, sport, output_dir) or ""
                            write_sos_integrity(matchups, sport)
                            write_unmatched_teams_log(sport)
                            if not out_file:
                                status = "ERROR"
                                err_msg = "Workbook creation returned empty path."
                            elif games_matched >= games_found:
                                status = "READY"
                            elif games_matched > 0:
                                status = "PARTIAL_READY"
                                note_msg = f"Partial coverage: matched {games_matched}/{games_found} games."
                            else:
                                status = "ERROR"
                                err_msg = f"Matched 0/{games_found} games."
                        else:
                            print(f"  No games found for {sport.upper()} today.")
                            status = "NO_GAMES"
                            note_msg = "No games found for target date."
                    except Exception as exc:
                        status = "ERROR"
                        err_msg = f"{type(exc).__name__}: {exc}"
                        print(f"  ERROR {sport.upper()}: {err_msg}")
                        print(traceback.format_exc())
                    finally:
                        _write_sos_status_marker(
                            sport,
                            status,
                            output_file=out_file,
                            games=games_found,
                            matched=games_matched,
                            error=err_msg,
                            note=note_msg,
                        )
            finally:
                browser.close()
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        print(f"FATAL: Unable to initialize Playwright/browser: {err_msg}")
        print(traceback.format_exc())
        for sport in sports_to_run:
            _write_sos_status_marker(
                sport,
                "ERROR",
                games=0,
                matched=0,
                error=err_msg,
                note="Playwright bootstrap failure before league scrape started.",
            )
        raise

    print("\n" + "=" * 70)
    print("SCRAPING COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
