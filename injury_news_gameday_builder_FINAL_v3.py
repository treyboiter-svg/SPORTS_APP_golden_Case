#!/usr/bin/env python3
"""
injury_news_gameday_builder_FINAL_v3.py

Goal:
- KEEP ESPN as the primary source for schedules, news, and (when possible) injuries.
- ADD supplemental sources (NCAA API, BALLDONTLIE, Sleeper, RapidAPI, Covers, BoydsBets) WITHOUT DROPPING ESPN data.
- FULL DEBUG/DIAGNOSTICS: optional HTTP dumps + per-league diagnostics.
- OUTPUT: one Excel per league ONLY IF there are games for the run date (ET).

Leagues included (and ONLY these):
NFL, NCAAF, NBA, NCAAB (men), MLB, NHL

SECURITY:
- Do NOT hardcode API keys.
- Put keys in api_keys.local.json (same folder) or environment variables:
  APISPORTS_API_KEY
  BALLDONTLIE_API_KEY
  RAPIDAPI_KEY
  RAPIDAPI_HOST
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, date
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

from openpyxl.styles import Font


# -------------------- TIMEZONE --------------------

ET = ZoneInfo("America/New_York")


# -------------------- LOGGING --------------------

logger = logging.getLogger("injury_news_builder")
logger.setLevel(logging.INFO)


def setup_logging(debug: bool) -> Path:
    if logger.handlers:
        return Path("logs")

    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    os.makedirs("logs", exist_ok=True)

    ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    log_path = Path("logs") / f"injury_news_builder_{ts}.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.info("Logging initialized. Log file: %s", str(log_path))
    return Path("logs")


# -------------------- API KEYS LOADING --------------------

def load_keys() -> Dict[str, str]:
    """
    Loads keys from (in this precedence):
    1) environment variables
    2) api_keys.local.json in current folder
    """
    keys: Dict[str, str] = {}
    for k in ["APISPORTS_API_KEY", "BALLDONTLIE_API_KEY", "RAPIDAPI_KEY", "RAPIDAPI_HOST"]:
        v = os.getenv(k)
        if v:
            keys[k] = v.strip()

    p = Path("api_keys.local.json")
    if p.exists():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                for k in ["APISPORTS_API_KEY", "BALLDONTLIE_API_KEY", "RAPIDAPI_KEY", "RAPIDAPI_HOST"]:
                    if k not in keys and obj.get(k):
                        keys[k] = str(obj[k]).strip()
        except Exception as e:
            logger.warning("Failed to read api_keys.local.json: %s", e)

    return keys


# -------------------- HTTP CLIENT WITH OPTIONAL DUMPS --------------------

BASE_HEADERS_JSON = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

BASE_HEADERS_HTML = {
    "User-Agent": BASE_HEADERS_JSON["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _safe_filename(s: str, max_len: int = 140) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:max_len].strip("_") or "resp"


class HttpClient:
    def __init__(self, dump_dir: Optional[Path] = None, timeout: int = 25, retries: int = 3):
        self.s = requests.Session()
        self.dump_dir = dump_dir
        self.timeout = timeout
        self.retries = retries
        self._ssl_strategy_by_host: Dict[str, Any] = {}
        self._ssl_warning_logged_hosts: set[str] = set()
        if dump_dir:
            dump_dir.mkdir(parents=True, exist_ok=True)

    def _get_with_ssl_fallback(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        host = ""
        try:
            from urllib.parse import urlparse
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""

        def _request_with_verify(_verify):
            return self.s.get(url, params=params, headers=headers, timeout=self.timeout, verify=_verify)

        def _request_insecure():
            self._ssl_strategy_by_host[host] = False
            if host not in self._ssl_warning_logged_hosts:
                logger.warning("[HTTP] SSL verify failed for host=%s; using verify=False fallback.", host or url)
                self._ssl_warning_logged_hosts.add(host)
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            return _request_with_verify(False)

        cached_verify = self._ssl_strategy_by_host.get(host, None)
        if cached_verify is not None:
            try:
                return _request_with_verify(cached_verify)
            except requests.exceptions.SSLError:
                # Cached strategy became invalid (host chain changed, stale cert path, etc.).
                return _request_insecure()

        try:
            return self.s.get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.exceptions.SSLError:
            certifi_path = None
            try:
                import certifi  # type: ignore
                certifi_path = certifi.where()
                self._ssl_strategy_by_host[host] = certifi_path
                if host not in self._ssl_warning_logged_hosts:
                    logger.warning("[HTTP] SSL verify failed for host=%s; using certifi bundle.", host or url)
                    self._ssl_warning_logged_hosts.add(host)
                try:
                    return _request_with_verify(certifi_path)
                except requests.exceptions.SSLError:
                    return _request_insecure()
            except Exception:
                return _request_insecure()

    def _dump(self, kind: str, url: str, params: Optional[Dict[str, Any]], status: int, text: str) -> None:
        if not self.dump_dir:
            return

        ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S_%f")
        name = _safe_filename(url)
        fn = self.dump_dir / f"{ts}_{kind}_{status}_{name}.txt"

        payload = {
            "url": url,
            "params": params or {},
            "status": status,
            "text_head": text[:200000],
        }
        fn.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        headers = headers or BASE_HEADERS_JSON

        for attempt in range(1, self.retries + 1):
            try:
                logger.info("[HTTP JSON] GET %s params=%s", url, params)
                r = self._get_with_ssl_fallback(url, params=params, headers=headers)
                self._dump("json", r.url, params, r.status_code, r.text)

                if r.status_code == 429:
                    sleep_for = 1.5 * attempt
                    logger.warning("[HTTP] 429 rate limited; sleep %.1fs", sleep_for)
                    time.sleep(sleep_for)
                    continue
                if r.status_code in (401, 403):
                    logger.warning(
                        "[HTTP JSON] Non-retryable status %s for %s (check API key/plan/access).",
                        r.status_code, url
                    )
                    return None

                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == self.retries:
                    logger.warning("[HTTP JSON] ❌ Failed %s : %s", url, e)
                    return None
                time.sleep(0.5 * attempt)

        return None

    def get_html(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        headers = headers or BASE_HEADERS_HTML

        for attempt in range(1, self.retries + 1):
            try:
                logger.info("[HTTP HTML] GET %s params=%s", url, params)
                r = self._get_with_ssl_fallback(url, params=params, headers=headers)
                self._dump("html", r.url, params, r.status_code, r.text)

                if r.status_code == 429:
                    sleep_for = 1.5 * attempt
                    logger.warning("[HTTP] 429 rate limited; sleep %.1fs", sleep_for)
                    time.sleep(sleep_for)
                    continue
                if r.status_code in (401, 403):
                    logger.warning(
                        "[HTTP HTML] Non-retryable status %s for %s (access blocked/forbidden).",
                        r.status_code, url
                    )
                    return None

                r.raise_for_status()
                return r.text
            except Exception as e:
                if attempt == self.retries:
                    logger.warning("[HTTP HTML] ❌ Failed %s : %s", url, e)
                    return None
                time.sleep(0.5 * attempt)

        return None


# -------------------- LEAGUE CONFIG (ONLY THESE 6) --------------------

@dataclass(frozen=True)
class LeagueCfg:
    key: str
    scoreboard_url: str
    scoreboard_params: Dict[str, Any]
    news_url: str
    injuries_type: str  # "pro_name" or "college_id"
    injuries_base: str
    core_sport: str
    core_league: str


LEAGUES: Dict[str, LeagueCfg] = {
    "NFL": LeagueCfg(
        key="NFL",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        scoreboard_params={},
        news_url="https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        injuries_type="pro_name",
        injuries_base="https://www.espn.com/nfl/team/injuries/_/name/{abbrev}",
        core_sport="football",
        core_league="nfl",
    ),
    "NCAAF": LeagueCfg(
        key="NCAAF",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
        scoreboard_params={"groups": "80"},  # default FBS
        news_url="https://site.api.espn.com/apis/site/v2/sports/football/college-football/news",
        injuries_type="college_id",
        injuries_base="https://www.espn.com/college-football/team/injuries/_/id/{team_id}",
        core_sport="football",
        core_league="college-football",
    ),
    "NBA": LeagueCfg(
        key="NBA",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        scoreboard_params={},
        news_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news",
        injuries_type="pro_name",
        injuries_base="https://www.espn.com/nba/team/injuries/_/name/{abbrev}",
        core_sport="basketball",
        core_league="nba",
    ),
    "NCAAB": LeagueCfg(
        key="NCAAB",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
        scoreboard_params={"groups": "50"},  # D1 Men's (critical!)
        news_url="https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/news",
        injuries_type="college_id",
        injuries_base="https://www.espn.com/mens-college-basketball/team/injuries/_/id/{team_id}",
        core_sport="basketball",
        core_league="mens-college-basketball",
    ),
    "MLB": LeagueCfg(
        key="MLB",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        scoreboard_params={},
        news_url="https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news",
        injuries_type="pro_name",
        injuries_base="https://www.espn.com/mlb/team/injuries/_/name/{abbrev}",
        core_sport="baseball",
        core_league="mlb",
    ),
    "NHL": LeagueCfg(
        key="NHL",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        scoreboard_params={},
        news_url="https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news",
        injuries_type="pro_name",
        injuries_base="https://www.espn.com/nhl/team/injuries/_/name/{abbrev}",
        core_sport="hockey",
        core_league="nhl",
    ),
}

COVERS_INJURY_URLS = {
    "NFL": "https://www.covers.com/sport/football/nfl/injuries",
    "NCAAF": "https://www.covers.com/sport/football/ncaaf/injuries",
    "NBA": "https://www.covers.com/sport/basketball/nba/injuries",
    "NCAAB": "https://www.covers.com/sport/basketball/ncaab/injuries",
    "MLB": "https://www.covers.com/sport/baseball/mlb/injuries",
    "NHL": "https://www.covers.com/sport/hockey/nhl/injuries",
}

# BoydsBets injury pages
BOYDS_INJURY_URLS = {
    "NFL": "https://www.boydsbets.com/nfl-injuries/",
    "NCAAF": "https://www.boydsbets.com/college-football-injuries/",
    "NBA": "https://www.boydsbets.com/nba-injury-reports/",
    "NCAAB": "https://www.boydsbets.com/ncaa-basketball-injuries/",
    "MLB": "https://www.boydsbets.com/mlb-injuries/",
    "NHL": "https://www.boydsbets.com/nhl-injury-report/",
}


# -------------------- HELPERS --------------------

def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def game_key(away: str, home: str) -> str:
    return f"{norm(away)}||{norm(home)}"


def excel_safe(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        if "timestamp" in v:
            try:
                dt = datetime.fromtimestamp(int(v["timestamp"]), tz=ET)
                return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                pass
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple, set)):
        return json.dumps(list(v), ensure_ascii=False)
    return str(v)


# -------------------- TEAM NEWS INTEL (NEW) --------------------

TEAM_NEWS_LIMIT = 60  # fetch more, then filter down

NEGATIVE_KEYWORDS = [
    "power rankings", "straw poll", "draft", "bracketology",
    "top 25", "rankings", "big board"
]

POSITIVE_KEYWORDS = [
    "injury", "out", "questionable", "doubtful", "day-to-day", "injured reserve",
    "trade", "waived", "signed", "suspension", "starting", "starter",
    "lineup", "rotation", "coach", "ruled", "returns", "status"
]


def canonical_url(u: str) -> str:
    return (u or "").strip()


def classify_article(headline: str, summary: str, url: str) -> str:
    h = (headline or "").lower()
    s = (summary or "").lower()
    u = (url or "").lower()
    blob = f"{h} {s} {u}"

    if any(k in blob for k in ["injury", "injured reserve", "questionable", "out", "doubtful", "day-to-day"]):
        return "injury"
    if any(k in blob for k in ["trade", "traded", "waived", "signed", "release", "released", "contract"]):
        return "transaction"
    if any(k in blob for k in ["preview", "brings", "visit", "hosts", "take on", "matchup"]):
        return "preview"
    if any(k in blob for k in ["recap", "beats", "defeat", "win over", "highlights"]):
        return "recap"
    if "video" in blob or "videoclip" in blob:
        return "video"
    if any(k in blob for k in ["power rankings", "straw poll", "big board", "bracketology", "top 25"]):
        return "power_ranking"
    return "analysis"


def relevance_score(team: Dict[str, Any], headline: str, summary: str) -> int:
    team_name = (team.get("displayName") or "").lower()
    team_abbr = (team.get("abbreviation") or "").lower()
    h = (headline or "").lower()
    s = (summary or "").lower()
    blob = f"{h} {s}"

    score = 50
    if team_name and team_name in blob:
        score += 25
    if team_abbr and team_abbr in blob:
        score += 10

    for k in POSITIVE_KEYWORDS:
        if k in blob:
            score += 6
    for k in NEGATIVE_KEYWORDS:
        if k in blob:
            score -= 25

    return max(0, min(100, score))


def dedupe_articles(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        key = canonical_url(r.get("url") or "") or f"{r.get('source')}|{r.get('headline')}|{r.get('published_at')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def cap_by_category(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    caps = {
        "injury": 50,
        "transaction": 25,
        "preview": 10,
        "recap": 10,
        "analysis": 12,
        "video": 8,
        "power_ranking": 2,
    }
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault(r.get("category") or "analysis", []).append(r)

    out: List[Dict[str, Any]] = []
    for cat, items in buckets.items():
        items_sorted = sorted(
            items,
            key=lambda x: (x.get("relevance_score", 0), x.get("published_at") or ""),
            reverse=True,
        )
        out.extend(items_sorted[: caps.get(cat, 10)])

    return sorted(out, key=lambda x: (x.get("relevance_score", 0), x.get("published_at") or ""), reverse=True)


# -------------------- SCHEDULE: ESPN (PAGINATED) --------------------

def fetch_espn_events_paginated(http: HttpClient, cfg: LeagueCfg, run_date: date, include_fcs: bool) -> List[Dict[str, Any]]:
    """
    ESPN scoreboard can be paginated/truncated; page using offset until no new IDs show up.
    For NCAAF: include_fcs also fetches groups=81.
    """
    ymd = run_date.strftime("%Y%m%d")
    base_params = {"dates": ymd, "limit": 300}
    base_params.update(cfg.scoreboard_params or {})

    params_list = [base_params]

    if cfg.key == "NCAAF" and include_fcs:
        params_list = []
        for g in ["80", "81"]:
            p = dict(base_params)
            p["groups"] = g
            params_list.append(p)

    all_events: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for p0 in params_list:
        offset = 0
        for _ in range(200):
            p = dict(p0)
            p["offset"] = offset
            data = http.get_json(cfg.scoreboard_url, params=p) or {}
            events = (data or {}).get("events") or []
            if not events:
                break

            new_count = 0
            for ev in events:
                eid = str((ev or {}).get("id") or "")
                if not eid:
                    continue
                if eid in seen:
                    continue
                seen.add(eid)
                all_events.append(ev)
                new_count += 1

            if new_count == 0:
                break

            offset += len(events)

    logger.info("[%s] ESPN scoreboard events fetched: %d", cfg.key, len(all_events))
    return all_events


def parse_games_from_events(cfg: LeagueCfg, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    games: List[Dict[str, Any]] = []

    for ev in events:
        try:
            comps = (ev or {}).get("competitions") or []
            if not comps:
                continue

            comp = comps[0]
            competitors = (comp or {}).get("competitors") or []
            away = home = None

            for c in competitors:
                side = (c or {}).get("homeAway")
                t = (c or {}).get("team") or {}
                team = {
                    "id": t.get("id"),
                    "abbreviation": t.get("abbreviation") or "",
                    "displayName": t.get("displayName") or t.get("name") or "",
                    "shortDisplayName": t.get("shortDisplayName") or "",
                }
                if side == "away":
                    away = team
                elif side == "home":
                    home = team

            if not away or not home:
                continue

            games.append(
                {
                    "event_id": (ev or {}).get("id"),
                    "date": (ev or {}).get("date"),
                    "name": (ev or {}).get("name") or "",
                    "short_name": (ev or {}).get("shortName") or (ev or {}).get("name") or "",
                    "away_team": away,
                    "home_team": home,
                    "schedule_source": "ESPN",
                }
            )
        except Exception:
            continue

    logger.info("[%s] Games parsed from ESPN events: %d", cfg.key, len(games))
    return games


# -------------------- SCHEDULE BACKUPS --------------------

def fetch_ncaa_api_ncaab(http: HttpClient, run_date: date) -> List[Tuple[str, str, Optional[str], str]]:
    url = (
        f"https://ncaa-api.henrygd.me/scoreboard/basketball-men/d1/"
        f"{run_date.year}/{run_date.month:02d}/{run_date.day:02d}"
    )
    data = http.get_json(url) or {}
    games = (data or {}).get("games") or []
    out: List[Tuple[str, str, Optional[str], str]] = []

    for g in games:
        game = (g or {}).get("game") or {}
        away = ((game.get("away") or {}).get("names") or {}).get("short") or ""
        home = ((game.get("home") or {}).get("names") or {}).get("short") or ""
        gid = str(game.get("gameID") or "")
        ts = game.get("startTimeEpoch")
        iso = None
        if ts:
            try:
                iso = datetime.fromtimestamp(int(ts), tz=ET).isoformat()
            except Exception:
                iso = None

        if away and home:
            out.append((away, home, iso, f"ncaa-{gid or away+'-'+home}"))

    logger.info("[NCAAB] NCAA API backup games: %d", len(out))
    return out


def fetch_balldontlie(http: HttpClient, keys: Dict[str, str], sport: str, run_date: date) -> List[Tuple[str, str, Optional[str], str]]:
    api_key = keys.get("BALLDONTLIE_API_KEY", "")
    if not api_key:
        return []

    base = {
        "nba": "https://api.balldontlie.io/v1",
        "nfl": "https://api.balldontlie.io/nfl/v1",
        "nhl": "https://api.balldontlie.io/nhl/v1",
        "mlb": "https://api.balldontlie.io/mlb/v1",
        "ncaaf": "https://api.balldontlie.io/ncaaf/v1",
        "ncaab": "https://api.balldontlie.io/ncaab/v1",
    }.get(sport)

    if not base:
        return []

    url = f"{base}/games"
    headers = dict(BASE_HEADERS_JSON)
    headers["Authorization"] = api_key

    params = {"dates[]": run_date.isoformat(), "per_page": 100}
    data = http.get_json(url, params=params, headers=headers) or {}
    if not isinstance(data, dict):
        return []

    out: List[Tuple[str, str, Optional[str], str]] = []
    for g in data.get("data") or []:
        away = (
            (((g.get("visitor_team") or g.get("away_team") or {}) or {}).get("full_name") or "")
            or (((g.get("away_team") or {}) or {}).get("name") or "")
        )
        home = (
            (((g.get("home_team") or {}) or {}).get("full_name") or "")
            or (((g.get("home_team") or {}) or {}).get("name") or "")
        )
        gid = str(g.get("id") or "")
        start = g.get("date")
        if away and home:
            out.append((away, home, start, f"bdl-{gid or away+'-'+home}"))

    return out


# -------------------- ESPN TEAMS INDEX (for mapping backup games to ESPN IDs) --------------------

def build_espn_team_index(http: HttpClient, cfg: LeagueCfg) -> Dict[str, Dict[str, Any]]:
    teams_url = cfg.scoreboard_url.replace("/scoreboard", "/teams")
    data = http.get_json(teams_url, params={"limit": 5000}) or {}
    if not isinstance(data, dict):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    sports = data.get("sports") or []
    for sp in sports:
        for lg in (sp or {}).get("leagues") or []:
            for tnode in (lg or {}).get("teams") or []:
                team = (tnode or {}).get("team") or {}
                tid = team.get("id")
                if not tid:
                    continue
                obj = {
                    "id": tid,
                    "abbreviation": team.get("abbreviation") or "",
                    "displayName": team.get("displayName") or team.get("name") or "",
                    "shortDisplayName": team.get("shortDisplayName") or "",
                }
                for k in [obj["abbreviation"], obj["displayName"], obj["shortDisplayName"], team.get("name")]:
                    nk = norm(k or "")
                    if nk:
                        out[nk] = obj

    logger.debug("[%s] ESPN team index size: %d", cfg.key, len(out))
    return out


def match_team(name: str, idx: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    nk = norm(name)
    if nk in idx:
        return idx[nk]
    for k, v in idx.items():
        if nk and (nk in k or k in nk):
            return v
    return None


def merge_backup_games(
    cfg: LeagueCfg,
    espn_games: List[Dict[str, Any]],
    backup_pairs: List[Tuple[str, str, Optional[str], str]],
    team_idx: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out = list(espn_games)
    existing = set(game_key(g["away_team"]["displayName"], g["home_team"]["displayName"]) for g in out)

    added = 0
    for away_name, home_name, start, gid in backup_pairs:
        away = match_team(away_name, team_idx)
        home = match_team(home_name, team_idx)
        if not away or not home:
            continue

        # De-duplicate using canonical ESPN team names, not raw backup labels.
        # Raw labels can differ ("LA Dodgers" vs "Los Angeles Dodgers") and
        # previously caused near-full duplicate slates to be merged in.
        k = game_key(away["displayName"], home["displayName"])
        rk = game_key(home["displayName"], away["displayName"])
        if k in existing or rk in existing:
            continue

        out.append(
            {
                "event_id": f"backup-{gid}",
                "date": start,
                "name": f"{away['displayName']} at {home['displayName']}",
                "short_name": f"{away.get('abbreviation','AWY')} @ {home.get('abbreviation','HOM')}",
                "away_team": away,
                "home_team": home,
                "schedule_source": "BACKUP",
            }
        )
        existing.add(game_key(away["displayName"], home["displayName"]))
        added += 1

    if added:
        logger.info("[%s] Added %d schedule games from backups (ESPN games preserved)", cfg.key, added)
    return out


# -------------------- INJURIES: ESPN CORE JSON (FIRST) --------------------

def espn_core_injuries_url(cfg: LeagueCfg, team_id: str) -> str:
    return f"https://sports.core.api.espn.com/v2/sports/{cfg.core_sport}/leagues/{cfg.core_league}/teams/{team_id}/injuries"


def _core_resolve_ref(http: HttpClient, url: str, cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if url in cache:
        return cache[url]
    data = http.get_json(url)
    cache[url] = data
    if isinstance(data, dict):
        return data
    return None


def fetch_espn_injuries_core(http: HttpClient, cfg: LeagueCfg, team: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    team_id = team.get("id")
    if not team_id:
        return [], "no_team_id"

    url = espn_core_injuries_url(cfg, str(team_id))
    data = http.get_json(url)
    if not isinstance(data, dict):
        return [], "core_no_data"

    items = data.get("items")
    if items is None:
        items = data.get("injuries") or data.get("entries") or []

    if not isinstance(items, list) or len(items) == 0:
        return [], "core_empty"

    ref_cache: Dict[str, Any] = {}
    out: List[Dict[str, Any]] = []

    for it in items:
        try:
            if isinstance(it, dict) and "$ref" in it:
                it = _core_resolve_ref(http, it["$ref"], ref_cache) or {}
            if not isinstance(it, dict):
                continue

            athlete = it.get("athlete") or {}
            if isinstance(athlete, dict) and "$ref" in athlete:
                athlete = _core_resolve_ref(http, athlete["$ref"], ref_cache) or {}

            player = ""
            if isinstance(athlete, dict):
                player = athlete.get("displayName") or athlete.get("fullName") or ""

            pos = ""
            if isinstance(athlete, dict):
                pos = (athlete.get("position") or {}).get("abbreviation") or (athlete.get("position") or {}).get("name") or ""

            status = ""
            st = it.get("status")
            if isinstance(st, dict):
                status = st.get("name") or st.get("type") or ""
            elif isinstance(st, str):
                status = st

            details = it.get("details") or it.get("description") or ""
            if isinstance(details, dict):
                details = details.get("detail") or details.get("type") or json.dumps(details, ensure_ascii=False)

            out.append(
                {
                    "source": "espn_core",
                    "player": player,
                    "pos": pos,
                    "status": status,
                    "details": details,
                    "date": it.get("date") or "",
                    "team": team.get("displayName") or "",
                }
            )
        except Exception:
            continue

    return out, "core_ok"


# -------------------- INJURIES: ESPN HTML (SECOND) --------------------

DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$", re.I)


def _find_nearest_date_for_anchor(a) -> str:
    node = a
    for _ in range(12):
        node = node.previous_sibling
        if node is None:
            break
        if hasattr(node, "get_text"):
            txt = node.get_text(" ", strip=True)
        else:
            txt = str(node).strip()
        if DATE_RE.match(txt or ""):
            return txt
    return ""


def build_injuries_url(cfg: LeagueCfg, team: Dict[str, Any]) -> Optional[str]:
    if cfg.injuries_type == "pro_name":
        ab = (team.get("abbreviation") or "").lower()
        if not ab:
            return None
        return cfg.injuries_base.format(abbrev=ab)
    else:
        tid = team.get("id")
        if not tid:
            return None
        return cfg.injuries_base.format(team_id=tid)


def scrape_injuries_espn_html(http: HttpClient, cfg: LeagueCfg, team: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    url = build_injuries_url(cfg, team)
    if not url:
        return [], "html_no_url"

    html = http.get_html(url)
    if not html:
        return [], "html_no_data"

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    rows_out: List[Dict[str, Any]] = []
    for tbl in tables:
        headers = [th.get_text(" ", strip=True).lower() for th in tbl.find_all("th")]
        if not headers:
            continue
        header_join = " ".join(headers)
        if "name" not in header_join and "player" not in header_join:
            continue

        for tr in tbl.find_all("tr")[1:]:
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < 3:
                continue

            player = tds[0]
            pos = tds[1] if len(tds) > 1 else ""
            status = tds[-1] if len(tds) >= 3 else ""
            details = ""
            if len(tds) >= 4:
                details = " | ".join(tds[2:-1])

            rows_out.append(
                {
                    "source": "espn_html",
                    "player": player,
                    "pos": pos,
                    "status": status,
                    "details": details,
                    "date": "",
                    "team": team.get("displayName") or "",
                    "source_url": url,
                }
            )

    if rows_out:
        return rows_out, "html_table_ok"

    anchors = soup.find_all("a")
    for a in anchors:
        text = a.get_text(" ", strip=True)
        if not text:
            continue
        if "Status" not in text:
            continue

        left, sep, right = text.partition(" Status ")
        if not sep:
            left, _, right = text.partition("Status ")

        left = left.strip()
        right = right.strip()
        if not left:
            continue

        toks = left.split()
        if len(toks) < 2:
            continue

        pos = toks[-1]
        player = " ".join(toks[:-1])
        status = right.split()[0] if right else ""
        details = " ".join(right.split()[1:]) if right and len(right.split()) > 1 else ""

        rows_out.append(
            {
                "source": "espn_html",
                "player": player,
                "pos": pos,
                "status": status,
                "details": details,
                "date": _find_nearest_date_for_anchor(a),
                "team": team.get("displayName") or "",
                "source_url": url,
            }
        )

    return rows_out, ("html_anchor_ok" if rows_out else "html_empty")


# -------------------- INJURIES: COVERS (THIRD) --------------------

def covers_blocked(html: str) -> bool:
    if not html:
        return True
    low = html.lower()
    return ("just a moment" in low) or ("cf-chl" in low) or ("cloudflare" in low and "challenge" in low)


class CoversIndex:
    def __init__(self, league_key: str, url: str):
        self.league_key = league_key
        self.url = url
        self.by_team: Dict[str, List[Dict[str, Any]]] = {}
        self.ok: bool = False
        self.diag: str = "not_loaded"

    def load(self, http: HttpClient) -> None:
        html = http.get_html(self.url)
        if not html:
            self.diag = "no_html"
            return
        if covers_blocked(html):
            self.diag = "blocked"
            return

        try:
            tables = pd.read_html(StringIO(html))
        except Exception as e:
            self.diag = f"read_html_error:{type(e).__name__}"
            return

        best = None
        best_score = -1

        for df in tables:
            cols = [str(c).strip().lower() for c in df.columns]
            score = 0
            if any("player" in c or "name" in c for c in cols):
                score += 2
            if any("team" in c for c in cols):
                score += 3
            if any("status" in c for c in cols):
                score += 1
            if score > best_score:
                best_score = score
                best = df

        if best is None or best_score < 2:
            self.diag = "no_suitable_table"
            return

        best.columns = [str(c).strip().lower() for c in best.columns]
        team_col = next((c for c in best.columns if "team" in c), None)
        player_col = next((c for c in best.columns if "player" in c or "name" in c), None)
        status_col = next((c for c in best.columns if "status" in c), None)
        pos_col = next((c for c in best.columns if "pos" in c), None)
        injury_col = next((c for c in best.columns if "injury" in c), None)
        date_col = next((c for c in best.columns if "date" in c), None)

        if not team_col:
            self.diag = "no_team_column"
            return

        out: Dict[str, List[Dict[str, Any]]] = {}
        for _, row in best.iterrows():
            team = str(row.get(team_col) or "").strip()
            if not team or team.lower() == "team":
                continue

            out.setdefault(norm(team), []).append(
                {
                    "source": "covers",
                    "team": team,
                    "player": str(row.get(player_col) or "").strip() if player_col else "",
                    "pos": str(row.get(pos_col) or "").strip() if pos_col else "",
                    "injury": str(row.get(injury_col) or "").strip() if injury_col else "",
                    "status": str(row.get(status_col) or "").strip() if status_col else "",
                    "date": str(row.get(date_col) or "").strip() if date_col else "",
                    "details": "",
                    "source_url": self.url,
                }
            )

        self.by_team = out
        self.ok = True
        self.diag = f"ok_teams:{len(out)}"

    def match_team(self, team: Dict[str, Any]) -> List[Dict[str, Any]]:
        probes = [
            team.get("displayName") or "",
            team.get("shortDisplayName") or "",
            team.get("abbreviation") or "",
        ]
        for p in probes:
            nk = norm(p)
            if nk and nk in self.by_team:
                return self.by_team[nk]

        nk = norm(team.get("displayName") or "")
        for k, vals in self.by_team.items():
            if nk and (nk in k or k in nk):
                return vals

        return []


# -------------------- INJURIES: BOYDSBETS (FOURTH) --------------------

class BoydsIndex:
    def __init__(self, league_key: str, url: str):
        self.league_key = league_key
        self.url = url
        self.by_team: Dict[str, List[Dict[str, Any]]] = {}
        self.ok: bool = False
        self.diag: str = "not_loaded"

    def load(self, http: HttpClient) -> None:
        html = http.get_html(self.url)
        if not html:
            self.diag = "no_html"
            return

        try:
            tables = pd.read_html(StringIO(html))
        except Exception as e:
            self.diag = f"read_html_error:{type(e).__name__}"
            return

        best = None
        best_score = -1

        for df in tables:
            cols = [str(c).strip().lower() for c in df.columns]
            score = 0
            if any("team" in c for c in cols):
                score += 3
            if any("player" in c or "name" in c for c in cols):
                score += 2
            if any("status" in c for c in cols):
                score += 1
            if any("injury" in c for c in cols):
                score += 1
            if score > best_score:
                best_score = score
                best = df

        if best is None or best_score < 4:
            self.diag = "no_suitable_table"
            return

        best.columns = [str(c).strip().lower() for c in best.columns]
        team_col = next((c for c in best.columns if "team" in c), None)
        player_col = next((c for c in best.columns if "player" in c or "name" in c), None)
        pos_col = next((c for c in best.columns if c in ["pos", "position"] or "pos" in c), None)
        status_col = next((c for c in best.columns if "status" in c), None)
        injury_col = next((c for c in best.columns if "injury" in c), None)
        date_col = next((c for c in best.columns if "date" in c), None)
        impact_col = next((c for c in best.columns if "impact" in c), None)
        note_col = next((c for c in best.columns if "note" in c or "details" in c), None)

        if not team_col or not player_col:
            self.diag = "missing_team_or_player_col"
            return

        out: Dict[str, List[Dict[str, Any]]] = {}
        for _, row in best.iterrows():
            team = str(row.get(team_col) or "").strip()
            player = str(row.get(player_col) or "").strip()
            if not team or team.lower() == "team":
                continue
            if not player or player.lower() == "player":
                continue

            details_bits: List[str] = []
            if impact_col:
                imp = str(row.get(impact_col) or "").strip()
                if imp:
                    details_bits.append(f"Impact: {imp}")
            if note_col:
                nt = str(row.get(note_col) or "").strip()
                if nt:
                    details_bits.append(nt)

            out.setdefault(norm(team), []).append(
                {
                    "source": "boydsbets",
                    "team": team,
                    "player": player,
                    "pos": str(row.get(pos_col) or "").strip() if pos_col else "",
                    "injury": str(row.get(injury_col) or "").strip() if injury_col else "",
                    "status": str(row.get(status_col) or "").strip() if status_col else "",
                    "date": str(row.get(date_col) or "").strip() if date_col else "",
                    "details": " | ".join(details_bits).strip(),
                    "source_url": self.url,
                }
            )

        self.by_team = out
        self.ok = True
        self.diag = f"ok_teams:{len(out)}"

    def match_team(self, team: Dict[str, Any]) -> List[Dict[str, Any]]:
        probes = [
            team.get("displayName") or "",
            team.get("shortDisplayName") or "",
            team.get("abbreviation") or "",
        ]
        for p in probes:
            nk = norm(p)
            if nk and nk in self.by_team:
                return self.by_team[nk]

        nk = norm(team.get("displayName") or "")
        for k, vals in self.by_team.items():
            if nk and (nk in k or k in nk):
                return vals

        return []


# -------------------- INJURIES: SLEEPER (NFL LAST RESORT) --------------------


def scrape_cfbdepth_injuries(http: HttpClient) -> List[Dict[str, Any]]:
    """Scrape CFBDepth.com for comprehensive FCS/FBS injury data"""
    url = "https://www.cfbdepth.com/injury-report/"
    logger.info(f"[HTTP HTML] GET {url} params=None")

    html = http.get_html(url)
    if not html:
        logger.warning("[CFBDEPTH] No HTML returned")
        return []

    try:
        soup = BeautifulSoup(html, 'lxml')
        injuries = []

        table = soup.find('table')
        if not table:
            logger.warning("[CFBDEPTH] No injury table found")
            return []

        rows = table.find_all('tr')[1:]  # Skip header
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 6:
                injuries.append({
                    'source': 'cfbdepth',
                    'team': cols[0].get_text(strip=True),
                    'player': cols[1].get_text(strip=True),
                    'pos': cols[2].get_text(strip=True),
                    'status': cols[3].get_text(strip=True),
                    'injury': cols[4].get_text(strip=True),
                    'details': '',
                    'date': cols[5].get_text(strip=True),
                    'sourceurl': url
                })

        logger.info(f"[CFBDEPTH] Scraped {len(injuries)} injuries")
        return injuries
    except Exception as e:
        logger.error(f"[CFBDEPTH] Error: {e}")
        return []


def scrape_rotowire_injuries(http: HttpClient, league: str) -> List[Dict[str, Any]]:
    """Scrape RotoWire injury news for all leagues"""
    url_map = {
        'NFL': 'https://www.rotowire.com/football/news.php?view=injuries',
        'NCAAF': 'https://www.rotowire.com/cfootball/news.php?view=injuries',
        'NBA': 'https://www.rotowire.com/basketball/news.php?view=injuries',
        'NCAAB': 'https://www.rotowire.com/cbasketball/news.php?view=injuries',
        'NHL': 'https://www.rotowire.com/hockey/news.php?view=injuries'
    }

    if league not in url_map:
        return []

    url = url_map[league]
    logger.info(f"[HTTP HTML] GET {url} params=None")

    html = http.get_html(url)
    if not html:
        logger.warning(f"[{league}][ROTOWIRE] No HTML returned")
        return []

    try:
        soup = BeautifulSoup(html, 'lxml')
        injuries = []

        # RotoWire structure varies - try multiple selectors
        items = soup.find_all('div', class_=['news-update', 'player-news', 'news-item'])

        for item in items:
            try:
                player_elem = item.find(['a', 'span'], class_=['player-name', 'news-player'])
                player = player_elem.get_text(strip=True) if player_elem else ''

                team_elem = item.find('span', class_=['team-name', 'news-team'])
                team = team_elem.get_text(strip=True) if team_elem else ''

                injury_elem = item.find('div', class_=['news-body', 'blurb'])
                injury_text = injury_elem.get_text(strip=True) if injury_elem else ''

                date_elem = item.find('span', class_=['date', 'time'])
                date_text = date_elem.get_text(strip=True) if date_elem else ''

                if player:
                    injuries.append({
                        'source': 'rotowire',
                        'team': team,
                        'player': player,
                        'pos': '',
                        'status': '',
                        'injury': injury_text[:100] if injury_text else '',
                        'details': injury_text,
                        'date': date_text,
                        'sourceurl': url
                    })
            except Exception:
                continue

        if injuries:
            logger.info(f"[{league}][ROTOWIRE] Scraped {len(injuries)} items")
            return injuries

        # Fallback: some layouts expose an HTML table instead of card blocks.
        try:
            tables = pd.read_html(StringIO(html))
        except Exception:
            tables = []
        for df in tables:
            cols = [str(c).strip().lower() for c in df.columns]
            team_col = next((c for c in df.columns if "team" in str(c).strip().lower()), None)
            player_col = next((c for c in df.columns if "player" in str(c).strip().lower() or "name" in str(c).strip().lower()), None)
            status_col = next((c for c in df.columns if "status" in str(c).strip().lower()), None)
            injury_col = next((c for c in df.columns if "injury" in str(c).strip().lower() or "note" in str(c).strip().lower()), None)
            date_col = next((c for c in df.columns if "date" in str(c).strip().lower() or "updated" in str(c).strip().lower()), None)
            if not player_col:
                continue
            for _, row in df.iterrows():
                player = str(row.get(player_col) or "").strip()
                if not player or player.lower() == "player":
                    continue
                injuries.append({
                    "source": "rotowire",
                    "team": str(row.get(team_col) or "").strip() if team_col else "",
                    "player": player,
                    "pos": "",
                    "status": str(row.get(status_col) or "").strip() if status_col else "",
                    "injury": str(row.get(injury_col) or "").strip() if injury_col else "",
                    "details": str(row.get(injury_col) or "").strip() if injury_col else "",
                    "date": str(row.get(date_col) or "").strip() if date_col else "",
                    "sourceurl": url,
                })
            if injuries:
                break

        logger.info(f"[{league}][ROTOWIRE] Scraped {len(injuries)} items")
        return injuries
    except Exception as e:
        logger.error(f"[{league}][ROTOWIRE] Error: {e}")
        return []


def fetch_sleeper_team_injuries_nfl(http: HttpClient, team_abbrev: str, run_date: date) -> List[Dict[str, Any]]:
    if not team_abbrev:
        return []

    cache_dir = Path("cache")
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / f"sleeper_players_nfl_{run_date.strftime('%Y%m%d')}.json"

    data = None
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            data = None

    if data is None:
        url = "https://api.sleeper.app/v1/players/nfl"
        data = http.get_json(url)
        if isinstance(data, dict):
            try:
                cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    if not isinstance(data, dict):
        return []

    ab = team_abbrev.upper()
    out: List[Dict[str, Any]] = []

    for _, p in data.items():
        try:
            if not isinstance(p, dict):
                continue
            if (p.get("team") or "").upper() != ab:
                continue
            st = p.get("injury_status")
            if not st:
                continue
            out.append(
                {
                    "source": "sleeper",
                    "player": p.get("full_name") or "",
                    "pos": p.get("position") or "",
                    "status": st,
                    "details": p.get("injury_notes") or "",
                    "date": p.get("injury_start_date") or "",
                    "team": ab,
                    "injury": "",
                    "source_url": "https://api.sleeper.app/v1/players/nfl",
                }
            )
        except Exception:
            continue

    return out


# -------------------- NEWS: ESPN TEAM NEWS (UPDATED -> TEAM INTEL) --------------------

def fetch_team_news(
    http: HttpClient,
    cfg: LeagueCfg,
    team: Dict[str, Any],
    team_side: str,
    run_date: date,
    limit: int = TEAM_NEWS_LIMIT,
) -> List[Dict[str, Any]]:
    tid = team.get("id")
    if not tid:
        return []

    data = http.get_json(cfg.news_url, params={"team": tid, "limit": limit}) or {}
    if not isinstance(data, dict):
        return []
    articles = data.get("articles") or []
    out: List[Dict[str, Any]] = []

    for a in articles:
        try:
            headline = (a or {}).get("headline") or ""
            summary = (a or {}).get("description") or ""
            published_at = (a or {}).get("published") or ""

            url = ""
            links = (a or {}).get("links") or {}
            if isinstance(links, dict):
                web = links.get("web") or {}
                if isinstance(web, dict):
                    url = web.get("href") or ""

            url = canonical_url(url)
            cat = classify_article(headline, summary, url)
            score = relevance_score(team, headline, summary)

            out.append(
                {
                    "league": cfg.key,
                    "run_date_et": run_date.isoformat(),
                    "team_side": team_side,
                    "team_id": team.get("id"),
                    "team_name": team.get("displayName") or "",
                    "team_abbrev": team.get("abbreviation") or "",
                    "source": "espn",
                    "headline": headline,
                    "summary": summary,
                    "published_at": published_at,
                    "url": url,
                    "category": cat,
                    "relevance_score": score,
                }
            )
        except Exception:
            continue

    out = dedupe_articles(out)
    out = cap_by_category(out)
    return out


# -------------------- RAPIDAPI: LEAGUE NEWS (SUPPLEMENTAL) --------------------

def fetch_rapidapi_league_news(http: HttpClient, keys: Dict[str, str], cfg: LeagueCfg) -> List[Dict[str, Any]]:
    rapid_key = keys.get("RAPIDAPI_KEY", "")
    rapid_host = keys.get("RAPIDAPI_HOST", "").strip()
    if not rapid_key or not rapid_host:
        return []

    path_map = {
        "NFL": "/nfl/news",
        "NCAAF": "/cfb/news",
        "NBA": "/nba/news",
        "NCAAB": "/mbb/news",
        "MLB": "/mlb/news",
        "NHL": "/nhl/news",
    }
    path = path_map.get(cfg.key)
    if not path:
        return []

    url = f"https://{rapid_host}{path}"
    headers = dict(BASE_HEADERS_JSON)
    headers["x-rapidapi-key"] = rapid_key
    headers["x-rapidapi-host"] = rapid_host

    data = http.get_json(url, headers=headers)
    items: Any = []

    if isinstance(data, dict):
        items = data.get("data") or data.get("articles") or data.get("news") or data.get("results") or []
        if isinstance(items, dict):
            items = items.get("items") or items.get("results") or []
    elif isinstance(data, list):
        items = data

    out: List[Dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append(
                {
                    "source": "rapidapi",
                    "headline": it.get("title") or it.get("headline") or "",
                    "description": it.get("description") or it.get("summary") or "",
                    "published": it.get("published") or it.get("date") or "",
                    "link": it.get("url") or it.get("link") or "",
                    "league": cfg.key,
                }
            )

    return out


# -------------------- INJURY PIPELINE WRAPPER (UNION ALL SOURCES) --------------------

INJURY_SOURCE_PRIORITY = {
    "espn_core": 1,
    "espn_html": 1,
    "sleeper": 1,
    "covers": 2,
    "boydsbets": 2,
    "cfbdepth": 2,
    "rotowire": 3,
    "NODATA": 99,
}

_ROTOWIRE_LEAGUE_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _team_probe_keys(team: Dict[str, Any]) -> List[str]:
    probes: List[str] = []
    for raw in (
        team.get("displayName") or "",
        team.get("shortDisplayName") or "",
        team.get("abbreviation") or "",
        team.get("name") or "",
    ):
        nk = norm(str(raw or ""))
        if nk and nk not in probes:
            probes.append(nk)
    return probes


def _rotowire_rows_for_team(http: HttpClient, league_key: str, team: Dict[str, Any]) -> List[Dict[str, Any]]:
    lg = str(league_key or "").upper().strip()
    if not lg:
        return []
    if lg not in _ROTOWIRE_LEAGUE_CACHE:
        _ROTOWIRE_LEAGUE_CACHE[lg] = scrape_rotowire_injuries(http, lg)
    rows = _ROTOWIRE_LEAGUE_CACHE.get(lg) or []
    if not rows:
        return []

    probes = _team_probe_keys(team)
    if not probes:
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        team_txt = norm(str(r.get("team") or ""))
        if not team_txt:
            continue
        if team_txt in probes or any((team_txt in p) or (p in team_txt) for p in probes):
            out.append(r)
    return out


def _inj_sig(r: Dict[str, Any]) -> str:
    keys = ["source", "team", "player", "pos", "status", "injury", "details", "date", "source_url"]
    return "|".join([(str(r.get(k, "")) or "").strip().lower() for k in keys])


def _fold_ascii(txt: str) -> str:
    s = str(txt or "")
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _norm_soft(txt: str) -> str:
    s = _fold_ascii(txt).lower().strip()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_player_name(txt: str) -> str:
    s = _norm_soft(txt)
    # Collapse punctuation variants so "A.J. Minter" and "A J Minter" coalesce.
    toks = s.split()
    if len(toks) >= 3 and len(toks[0]) == 1 and len(toks[1]) == 1:
        toks = [toks[0] + toks[1]] + toks[2:]
    return " ".join(toks)


def _status_bucket(status: str) -> str:
    s = _norm_soft(status)
    if not s:
        return ""
    if "day to day" in s or "day-to-day" in s:
        return "day_to_day"
    if "questionable" in s:
        return "questionable"
    if "doubtful" in s:
        return "doubtful"
    if "out" == s or s.startswith("out "):
        return "out"
    if "injured reserve" in s or s == "ir":
        return "ir"
    if "10 day il" in s or "ten day il" in s:
        return "10_day_il"
    if "15 day il" in s or "fifteen day il" in s:
        return "15_day_il"
    if "60 day il" in s or "sixty day il" in s:
        return "60_day_il"
    return s


def _injury_bucket(injury: str, details: str) -> str:
    base = _norm_soft(injury or details)
    if not base:
        return ""
    for key in ("surgery", "strain", "sprain", "fracture", "inflammation", "soreness", "undisclosed"):
        if key in base:
            return key
    return base[:48]


def _inj_entity_key(r: Dict[str, Any]) -> str:
    team_k = _norm_soft(r.get("team", ""))
    player_k = _norm_player_name(r.get("player", ""))
    status_k = _status_bucket(str(r.get("status", "")))
    injury_k = _injury_bucket(str(r.get("injury", "")), str(r.get("details", "")))
    pos_k = _norm_soft(r.get("pos", ""))
    return "|".join([team_k, player_k, pos_k, status_k, injury_k])


def _inj_info_score(r: Dict[str, Any]) -> int:
    score = 0
    for k in ("pos", "status", "injury", "details", "date", "source_url"):
        if str(r.get(k, "") or "").strip():
            score += 1
    return score


def _inj_sort_key(r: Dict[str, Any]) -> Tuple[int, int, str]:
    src = str(r.get("source", "") or "").strip().lower()
    src_priority = INJURY_SOURCE_PRIORITY.get(src, 9)
    info = _inj_info_score(r)
    date_txt = str(r.get("date", "") or "").strip()
    # Lower priority rank is better; higher info/date is better.
    return (int(100 - src_priority), info, date_txt)


def _dedupe_injury_rows(rows: List[Dict[str, Any]], diag: Dict[str, Any]) -> List[Dict[str, Any]]:
    out_exact: List[Dict[str, Any]] = []
    seen_exact = set()
    exact_dropped = 0
    for r in rows:
        sig = _inj_sig(r)
        if sig in seen_exact:
            exact_dropped += 1
            continue
        seen_exact.add(sig)
        out_exact.append(r)

    merged: Dict[str, Dict[str, Any]] = {}
    passthrough: List[Dict[str, Any]] = []
    merged_dropped = 0
    for r in out_exact:
        # Preserve placeholder rows and records with no player identity.
        if str(r.get("source", "")).upper() == "NO_DATA":
            passthrough.append(r)
            continue
        if not _norm_player_name(str(r.get("player", "") or "")):
            passthrough.append(r)
            continue

        ekey = _inj_entity_key(r)
        if not ekey:
            passthrough.append(r)
            continue

        cur = merged.get(ekey)
        if cur is None:
            merged[ekey] = r
            continue

        if _inj_sort_key(r) > _inj_sort_key(cur):
            merged[ekey] = r
        merged_dropped += 1

    diag["exact_dupes_dropped"] = exact_dropped
    diag["entity_dupes_dropped"] = merged_dropped
    return passthrough + list(merged.values())


def _injury_empty_source_status(diag: Dict[str, Any]) -> str:
    """Separate confirmed clean injury reports from source/parser failure."""
    statuses = [
        str(diag.get("core_status") or "").lower(),
        str(diag.get("html_status") or "").lower(),
    ]
    source_ok = False
    source_unavailable = False
    for st in statuses:
        if st.endswith("_empty") or st in {"core_ok", "html_anchor_ok"}:
            source_ok = True
        if "no_data" in st or "error" in st or "failed" in st or "blocked" in st:
            source_unavailable = True
    for key in ("covers_status", "boyds_status"):
        val = diag.get(key)
        if isinstance(val, dict):
            if val.get("ok") is True:
                source_ok = True
            if val.get("ok") is False and val.get("error"):
                source_unavailable = True
    if source_ok and not source_unavailable:
        return "CONFIRMED_NO_INJURIES"
    if source_ok:
        return "CONFIRMED_NO_INJURIES_PARTIAL_SOURCE"
    return "SOURCE_NO_DATA"


def get_team_injuries(
    http: HttpClient,
    cfg: LeagueCfg,
    team: Dict[str, Any],
    covers: Optional[CoversIndex],
    boyds: Optional[BoydsIndex],
    run_date: date,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    diag: Dict[str, Any] = {
        "team": team.get("displayName"),
        "team_id": team.get("id"),
        "core_status": None,
        "html_status": None,
        "covers_status": (covers.diag if covers else None),
        "boyds_status": (boyds.diag if boyds else None),
        "sleeper_used": False,
        "counts": {},
        "final_count": 0,
    }

    all_rows: List[Dict[str, Any]] = []

    rows_core, st_core = fetch_espn_injuries_core(http, cfg, team)
    diag["core_status"] = st_core
    diag["counts"]["espn_core"] = len(rows_core)
    all_rows.extend(rows_core)

    rows_html, st_html = scrape_injuries_espn_html(http, cfg, team)
    diag["html_status"] = st_html
    diag["counts"]["espn_html"] = len(rows_html)
    all_rows.extend(rows_html)

    if covers and covers.ok:
        rows_cov = covers.match_team(team)
        diag["counts"]["covers"] = len(rows_cov)
        all_rows.extend(rows_cov)
    else:
        diag["counts"]["covers"] = 0

    if boyds and boyds.ok:
        rows_boyds = boyds.match_team(team)
        diag["counts"]["boydsbets"] = len(rows_boyds)
        all_rows.extend(rows_boyds)

    # CFBDepth for NCAAF FCS/FBS coverage
    if cfg.key == 'NCAAF':
        rows_cfbdepth = scrape_cfbdepth_injuries(http)
        diag['counts']['cfbdepth'] = len(rows_cfbdepth)
        all_rows.extend(rows_cfbdepth)
    else:
        diag['counts']['cfbdepth'] = 0

    # RotoWire feed is league-wide; fetch once per league and only keep rows
    # that match this team to avoid N x duplicate pulls/rows.
    rows_rotowire = _rotowire_rows_for_team(http, cfg.key, team)
    diag['counts']['rotowire'] = len(rows_rotowire)
    all_rows.extend(rows_rotowire)


    if cfg.key == "NFL":
        rows_sl = fetch_sleeper_team_injuries_nfl(http, team.get("abbreviation") or "", run_date)
        diag["counts"]["sleeper"] = len(rows_sl)
        if rows_sl:
            diag["sleeper_used"] = True
            all_rows.extend(rows_sl)
    else:
        diag["counts"]["sleeper"] = 0

    out: List[Dict[str, Any]] = _dedupe_injury_rows(all_rows, diag)

    diag["final_count"] = len(out)

    # Avoid silent empty injury sheets, but do not treat confirmed clean reports
    # as source failures. "No injuries" and "no data" are different states.
    if not out:
        empty_status = _injury_empty_source_status(diag)
        out = [{
            "source": empty_status,
            "team": team.get("displayName") or "",
            "player": "",
            "pos": "",
            "status": "",
            "injury": "",
            "details": f"{empty_status}: no player injury rows (core={diag['core_status']} html={diag['html_status']} covers={diag['covers_status']} boyds={diag['boyds_status']})",
            "date": "",
            "source_url": "",
        }]
        diag["final_count"] = 1
        diag["empty_status"] = empty_status

    return out, diag


# -------------------- EXCEL OUTPUT --------------------

def safe_sheet(name: str) -> str:
    bad = '[]:*?/\\'
    for ch in bad:
        name = name.replace(ch, "_")
    name = name.strip()
    return (name[:31] or "Sheet")


def _write_title(ws, row0: int, title: str) -> None:
    cell = ws.cell(row=row0 + 1, column=1, value=title)
    cell.font = Font(bold=True)


def write_workbook(
    out_path: Path,
    cfg: LeagueCfg,
    games: List[Dict[str, Any]],
    game_payloads: List[Dict[str, Any]],
    league_news: List[Dict[str, Any]],
    diagnostics: List[Dict[str, Any]],
    all_game_rows: List[Dict[str, Any]],
    all_injury_rows: List[Dict[str, Any]],
    all_news_rows: List[Dict[str, Any]],
    all_validity_rows: Optional[List[Dict[str, Any]]] = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        pd.DataFrame(diagnostics).to_excel(writer, sheet_name="DIAGNOSTICS", index=False)

        if league_news:
            pd.DataFrame(league_news).to_excel(writer, sheet_name="LEAGUE_NEWS", index=False)

        # Flat, machine-friendly tables
        if all_game_rows:
            pd.DataFrame(all_game_rows).to_excel(writer, sheet_name="GAMES", index=False)

        if all_validity_rows:
            pd.DataFrame(all_validity_rows).to_excel(writer, sheet_name="VALIDITY", index=False)

        if all_injury_rows:
            pd.DataFrame(all_injury_rows).to_excel(writer, sheet_name="INJURIES", index=False)

        if all_news_rows:
            pd.DataFrame(all_news_rows).to_excel(writer, sheet_name="TEAM_NEWS", index=False)

        # Existing per-game matchup tabs
        for payload in game_payloads:
            sheet = safe_sheet(payload["sheet_name"])

            pd.DataFrame([payload["game_info"]]).to_excel(
                writer, sheet_name=sheet, index=False, startrow=0
            )
            ws = writer.sheets[sheet]

            r = 3

            _write_title(ws, r, "AWAY INJURIES")
            pd.DataFrame(payload["away_injuries"]).to_excel(
                writer, sheet_name=sheet, index=False, startrow=r + 1
            )
            r += max(3, len(payload["away_injuries"]) + 4)

            _write_title(ws, r, "HOME INJURIES")
            pd.DataFrame(payload["home_injuries"]).to_excel(
                writer, sheet_name=sheet, index=False, startrow=r + 1
            )
            r += max(3, len(payload["home_injuries"]) + 4)

            _write_title(ws, r, "AWAY TEAM NEWS (INTEL)")
            pd.DataFrame(payload["away_news"]).to_excel(
                writer, sheet_name=sheet, index=False, startrow=r + 1
            )
            r += max(3, len(payload["away_news"]) + 4)

            _write_title(ws, r, "HOME TEAM NEWS (INTEL)")
            pd.DataFrame(payload["home_news"]).to_excel(
                writer, sheet_name=sheet, index=False, startrow=r + 1
            )


# -------------------- MAIN --------------------

def parse_run_date(s: Optional[str]) -> date:
    if not s:
        return datetime.now(ET).date()
    s = s.strip()
    if re.fullmatch(r"\d{8}", s):
        return datetime.strptime(s, "%Y%m%d").date()
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Run date (YYYY-MM-DD or YYYYMMDD). Default: today ET.")
    ap.add_argument("--include-fcs", action="store_true", help="NCAAF: also pull groups=81 (FCS) from ESPN schedule")
    ap.add_argument("--debug", action="store_true", help="Verbose debug logging")
    ap.add_argument("--dump-http", action="store_true", help="Dump raw HTTP responses to ./debug_http/<date>/")
    ap.add_argument("--no-backups", action="store_true", help="Disable backup schedule sources (NCAA API, etc.)")
    ap.add_argument(
        "--use-balldontlie-backup",
        action="store_true",
        help="Enable BallDontLie schedule backups (disabled by default).",
    )
    ap.add_argument(
        "--use-rapidapi-news",
        action="store_true",
        help="Enable RapidAPI league news feed (disabled by default).",
    )
    args = ap.parse_args()

    setup_logging(args.debug)
    keys = load_keys()

    if keys.get("RAPIDAPI_KEY", ""):
        logger.info("RapidAPI key loaded (from env or api_keys.local.json).")
    if keys.get("APISPORTS_API_KEY", ""):
        logger.info("API-SPORTS key loaded (from env or api_keys.local.json).")
    if keys.get("BALLDONTLIE_API_KEY", ""):
        logger.info("BALLDONTLIE key loaded (from env or api_keys.local.json).")
    if not args.use_balldontlie_backup:
        logger.info("BALLDONTLIE schedule backup disabled by default (pass --use-balldontlie-backup to enable).")
    if not args.use_rapidapi_news:
        logger.info("RapidAPI league news disabled by default (pass --use-rapidapi-news to enable).")

    run_date = parse_run_date(args.date)
    logger.info("=== Injury & News Gameday Builder for %s (ET) ===", run_date.isoformat())

    dump_dir = None
    if args.dump_http:
        dump_dir = Path("debug_http") / run_date.strftime("%Y%m%d")

    http = HttpClient(dump_dir=dump_dir)

    out_root = Path.cwd() / "injury_news_output"
    out_root.mkdir(exist_ok=True)
    overall_blocking_validity = False

    for league_key in ["NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL"]:
        cfg = LEAGUES[league_key]
        logger.info("=== Processing league: %s ===", cfg.key)

        # ESPN schedule
        events = fetch_espn_events_paginated(http, cfg, run_date, include_fcs=args.include_fcs)
        espn_games = parse_games_from_events(cfg, events)
        games = espn_games

        # Backups (schedule only) - ESPN preserved
        if not args.no_backups:
            backup_pairs: List[Tuple[str, str, Optional[str], str]] = []
            try:
                if cfg.key == "NCAAB":
                    backup_pairs.extend(fetch_ncaa_api_ncaab(http, run_date))

                sport_map = {
                    "NFL": "nfl",
                    "NBA": "nba",
                    "NHL": "nhl",
                    "MLB": "mlb",
                    "NCAAF": "ncaaf",
                    "NCAAB": "ncaab",
                }
                if args.use_balldontlie_backup:
                    backup_pairs.extend(fetch_balldontlie(http, keys, sport_map[cfg.key], run_date))
            except Exception as e:
                logger.warning("[%s] Backup schedule fetch failed: %s", cfg.key, e)

            if backup_pairs:
                team_idx = build_espn_team_index(http, cfg)
                games = merge_backup_games(cfg, games, backup_pairs, team_idx)

        if not games:
            logger.info("[%s] No games today; skipping workbook", cfg.key)
            continue

        # ── Resolve canonical team names and game_ids from schedule ──────────
        # build_resolvers_from_schedule_dir reads Schedules_LEAGUE_YYYYMMDD.xlsx
        # written by scrapes.py (runs first in pipeline).  Resolver returns the
        # exact canonical away_team / home_team strings and game_id the pipeline
        # uses for every join.  Without this, injury sheets are written with ESPN
        # abbreviation-based names (e.g. "BOS @ MIA") that don't match schedule
        # full names (e.g. "Boston Celtics @ Miami Heat"), so pipeline_orchestrator
        # build_sheet_map_by_game_id() fails to link injury data to games.
        _inj_resolvers: Dict = {}
        try:
            from game_resolver import build_resolvers_from_schedule_dir as _build_resolvers, make_game_id as _make_game_id
            _inj_resolvers = _build_resolvers("stats_output", run_date.isoformat())
        except Exception as _rexc:
            logger.warning("[%s] Could not build schedule resolvers for injury builder: %s", cfg.key, _rexc)

        _inj_resolver = _inj_resolvers.get(cfg.key)

        def _promotable_duplicate_match(_match) -> Optional[Dict[str, str]]:
            """
            Promote high-confidence resolver misses where best/second candidates
            point to the same scheduled game (artificial ambiguity).
            """
            try:
                if not _match:
                    return None
                _conf = float(getattr(_match, "confidence", 0.0) or 0.0)
                if _conf < 0.90:
                    return None
                _diag = getattr(_match, "diagnostics", None)
                if not isinstance(_diag, dict):
                    return None
                _best = _diag.get("best") if isinstance(_diag.get("best"), dict) else {}
                _second = _diag.get("second") if isinstance(_diag.get("second"), dict) else {}
                _best_game = _best.get("game")
                _second_game = _second.get("game")

                def _extract(_g):
                    if _g is None:
                        return "", "", ""
                    if isinstance(_g, dict):
                        return (
                            str(_g.get("game_id") or "").strip(),
                            str(_g.get("away_team") or "").strip(),
                            str(_g.get("home_team") or "").strip(),
                        )
                    return (
                        str(getattr(_g, "game_id", "") or "").strip(),
                        str(getattr(_g, "away_team", "") or "").strip(),
                        str(getattr(_g, "home_team", "") or "").strip(),
                    )

                _best_gid, _best_away, _best_home = _extract(_best_game)
                _second_gid, _, _ = _extract(_second_game)
                if not _best_gid or not _best_away or not _best_home:
                    return None
                if _second_gid and _second_gid != _best_gid:
                    return None
                return {
                    "game_id": _best_gid,
                    "away_team": _best_away,
                    "home_team": _best_home,
                }
            except Exception:
                return None

        for g in games:
            _away_obj = g.get("away_team") or {}
            _home_obj = g.get("home_team") or {}
            _raw_away = _away_obj.get("displayName") or ""
            _raw_home = _home_obj.get("displayName") or ""

            _canon_away = _raw_away
            _canon_home = _raw_home
            _game_id = ""

            if _inj_resolver and _raw_away and _raw_home:
                _match = _inj_resolver.resolve(
                    cfg.key, run_date.isoformat(), _raw_away, _raw_home,
                    raw_time="", raw_venue="",
                )
                if _match.matched and _match.game is not None:
                    _canon_away = _match.game.away_team
                    _canon_home = _match.game.home_team
                    _game_id = _match.game.game_id
                else:
                    _promoted = _promotable_duplicate_match(_match)
                    if _promoted:
                        _canon_away = _promoted["away_team"]
                        _canon_home = _promoted["home_team"]
                        _game_id = _promoted["game_id"]
                        logger.info(
                            "[%s] Injury resolver promoted duplicate match: %s @ %s -> %s @ %s (conf=%.2f)",
                            cfg.key, _raw_away, _raw_home, _canon_away, _canon_home, _match.confidence,
                        )
                    else:
                        try:
                            _game_id = _make_game_id(cfg.key, run_date.isoformat(), _raw_away, _raw_home)
                        except Exception:
                            _game_id = ""
                        logger.warning(
                            "[%s] Injury resolver miss: %s @ %s (conf=%.2f) — using raw names",
                            cfg.key, _raw_away, _raw_home, _match.confidence,
                        )
            elif _raw_away and _raw_home:
                try:
                    _game_id = _make_game_id(cfg.key, run_date.isoformat(), _raw_away, _raw_home)
                except Exception:
                    _game_id = ""

            # Store canonical names and game_id back into the game dict so
            # the payload loop below uses them for game_info and sheet naming.
            g["_canon_away"] = _canon_away
            g["_canon_home"] = _canon_home
            g["_game_id"] = _game_id

        out_path = out_root / f"INJURY_NEWS_{cfg.key}_{run_date.strftime('%Y%m%d')}.xlsx"
        logger.info("[%s] Creating workbook: %s", cfg.key, str(out_path))

        # Covers index (optional)
        covers = None
        c_url = COVERS_INJURY_URLS.get(cfg.key)
        if c_url:
            covers = CoversIndex(cfg.key, c_url)
            covers.load(http)
            logger.info("[%s][COVERS] %s", cfg.key, covers.diag)

        # BoydsBets index (optional)
        boyds = None
        b_url = BOYDS_INJURY_URLS.get(cfg.key)
        if b_url:
            boyds = BoydsIndex(cfg.key, b_url)
            boyds.load(http)
            logger.info("[%s][BOYDS] %s", cfg.key, boyds.diag)

        league_news: List[Dict[str, Any]] = []
        if args.use_rapidapi_news:
            try:
                league_news = fetch_rapidapi_league_news(http, keys, cfg)
            except Exception as e:
                logger.warning("[%s] RapidAPI league news failed: %s", cfg.key, e)

        diagnostics: List[Dict[str, Any]] = []
        payloads: List[Dict[str, Any]] = []
        all_game_rows: List[Dict[str, Any]] = []
        all_injury_rows: List[Dict[str, Any]] = []
        all_news_rows: List[Dict[str, Any]] = []
        all_validity_rows: List[Dict[str, Any]] = []

        injuries_cache: Dict[str, List[Dict[str, Any]]] = {}
        news_cache: Dict[str, List[Dict[str, Any]]] = {}

        def team_cache_key(t: Dict[str, Any]) -> str:
            return f"{cfg.key}:{t.get('id') or t.get('abbreviation') or t.get('displayName')}"

        def _validity_from_rows(rows: List[Dict[str, Any]], diag: Dict[str, Any]) -> str:
            for r in rows or []:
                if str(r.get("player") or "").strip():
                    return "HAS_INJURIES"
            srcs = {str(r.get("source") or "").upper().strip() for r in (rows or [])}
            for state in ("SOURCE_FAILED", "SOURCE_BLOCKED", "SOURCE_NO_DATA", "NO_DATA"):
                if state in srcs:
                    return "SOURCE_NO_DATA" if state == "NO_DATA" else state
            for state in ("CONFIRMED_NO_INJURIES", "CONFIRMED_NO_INJURIES_PARTIAL_SOURCE"):
                if state in srcs:
                    return state
            return str((diag or {}).get("empty_status") or "SOURCE_NO_DATA").upper().strip()

        def _validity_blocking(state: str) -> bool:
            return str(state or "").upper().strip() in {"SOURCE_NO_DATA", "SOURCE_FAILED", "SOURCE_BLOCKED", "NO_DATA", "RESOLVER_MISS"}

        for g in games:
            away = g["away_team"]
            home = g["home_team"]

            sheet_name = g.get("short_name") or f"{away.get('abbreviation','AWY')} @ {home.get('abbreviation','HOM')}"

            a_key = team_cache_key(away)
            h_key = team_cache_key(home)

            # injuries (cached by team id)
            if a_key in injuries_cache:
                away_inj = injuries_cache[a_key]
                a_diag = {"team": away.get("displayName"), "cached": True, "final_count": len(away_inj)}
            else:
                away_inj, a_diag = get_team_injuries(http, cfg, away, covers, boyds, run_date)
                injuries_cache[a_key] = away_inj

            if h_key in injuries_cache:
                home_inj = injuries_cache[h_key]
                h_diag = {"team": home.get("displayName"), "cached": True, "final_count": len(home_inj)}
            else:
                home_inj, h_diag = get_team_injuries(http, cfg, home, covers, boyds, run_date)
                injuries_cache[h_key] = home_inj

            diagnostics.append(
                {
                    "league": cfg.key,
                    "event_id": g.get("event_id"),
                    "game": g.get("name"),
                    "schedule_source": g.get("schedule_source"),
                    "away_team": away.get("displayName"),
                    "away_inj_count": len(away_inj),
                    "away_diag": json.dumps(a_diag, ensure_ascii=False),
                    "home_team": home.get("displayName"),
                    "home_inj_count": len(home_inj),
                    "home_diag": json.dumps(h_diag, ensure_ascii=False),
                }
            )
            _away_validity_state = _validity_from_rows(away_inj, a_diag)
            _home_validity_state = _validity_from_rows(home_inj, h_diag)
            for _side, _team_obj, _team_name, _rows, _diag, _state in [
                ("away", away, g.get("_canon_away") or away.get("displayName"), away_inj, a_diag, _away_validity_state),
                ("home", home, g.get("_canon_home") or home.get("displayName"), home_inj, h_diag, _home_validity_state),
            ]:
                _resolver_status = "RESOLVER_MATCHED" if g.get("_game_id") else "RESOLVER_MISS"
                all_validity_rows.append({
                    "league": cfg.key,
                    "run_date_et": run_date.isoformat(),
                    "event_id": g.get("event_id"),
                    "game_id": g.get("_game_id") or "",
                    "team_side": _side,
                    "team_id": _team_obj.get("id"),
                    "team_name": _team_name,
                    "injury_validity_state": _state,
                    "resolver_status": _resolver_status,
                    "blocking": bool(_validity_blocking(_state) or _resolver_status == "RESOLVER_MISS"),
                    "reason": json.dumps(_diag, ensure_ascii=False),
                })

            # news (cached)
            if a_key in news_cache:
                away_news = news_cache[a_key]
            else:
                away_news = fetch_team_news(http, cfg, away, team_side="away", run_date=run_date, limit=TEAM_NEWS_LIMIT)
                news_cache[a_key] = away_news

            if h_key in news_cache:
                home_news = news_cache[h_key]
            else:
                home_news = fetch_team_news(http, cfg, home, team_side="home", run_date=run_date, limit=TEAM_NEWS_LIMIT)
                news_cache[h_key] = home_news

            payloads.append(
                {
                    "sheet_name": sheet_name,
                    "game_info": {
                        k: excel_safe(v)
                        for k, v in {
                            "league": cfg.key,
                            "event_id": g.get("event_id"),
                            "matchup": g.get("name"),
                            "short_name": g.get("short_name"),
                            "date": g.get("date"),
                            "schedule_source": g.get("schedule_source"),
                            # Use resolver canonical names so pipeline can join
                            # on game_id.  Falls back to ESPN displayName when
                            # resolver was unavailable or missed.
                            "away_team": g.get("_canon_away") or away.get("displayName"),
                            "home_team": g.get("_canon_home") or home.get("displayName"),
                            # game_id MUST be present so build_sheet_map_by_game_id()
                            # in pipeline_orchestrator can key this sheet correctly.
                            "game_id": g.get("_game_id") or "",
                        }.items()
                    },
                    "away_injuries": [{k: excel_safe(v) for k, v in r.items()} for r in away_inj],
                    "home_injuries": [{k: excel_safe(v) for k, v in r.items()} for r in home_inj],
                    "away_news": [{k: excel_safe(v) for k, v in r.items()} for r in away_news],
                    "home_news": [{k: excel_safe(v) for k, v in r.items()} for r in home_news],
                }
            )

            # Normalized game row for flat sheets
            game_row = {
                "league": cfg.key,
                "run_date_et": run_date.isoformat(),
                "event_id": g.get("event_id"),
                "game_id": g.get("_game_id") or "",
                "sheet_name": sheet_name,
                "matchup": g.get("name"),
                "short_name": g.get("short_name"),
                "date": g.get("date"),
                "schedule_source": g.get("schedule_source"),
                "away_team": g.get("_canon_away") or away.get("displayName"),
                "home_team": g.get("_canon_home") or home.get("displayName"),
                "away_team_id": away.get("id"),
                "home_team_id": home.get("id"),
                "away_team_abbrev": away.get("abbreviation"),
                "home_team_abbrev": home.get("abbreviation"),
                "away_inj_count": len(away_inj),
                "home_inj_count": len(home_inj),
            }
            all_game_rows.append({k: excel_safe(v) for k, v in game_row.items()})

            # Normalized injuries with context
            for side, team_obj, team_name, inj_list in [
                ("away", away, g.get("_canon_away") or away.get("displayName"), away_inj),
                ("home", home, g.get("_canon_home") or home.get("displayName"), home_inj),
            ]:
                for r in inj_list:
                    src = r.get("source") or ""
                    flat_inj = {
                        "league": cfg.key,
                        "run_date_et": run_date.isoformat(),
                        "event_id": g.get("event_id"),
                        "game_id": g.get("_game_id") or "",
                        "sheet_name": sheet_name,
                        "team_side": side,
                        "team_id": team_obj.get("id"),
                        "team_abbrev": team_obj.get("abbreviation"),
                        "team_name": team_name,
                        "source": src,
                        "source_team": r.get("team"),
                        "player": r.get("player"),
                        "pos": r.get("pos"),
                        "status": r.get("status"),
                        "injury": r.get("injury"),
                        "details": r.get("details"),
                        "injury_date_raw": r.get("date"),
                        "source_url": r.get("source_url") or r.get("sourceurl") or "",
                        "source_priority": INJURY_SOURCE_PRIORITY.get(str(src), 50),
                    }
                    all_injury_rows.append({k: excel_safe(v) for k, v in flat_inj.items()})

            # Normalized team news with context
            for side, team_obj, team_name, news_list in [
                ("away", away, g.get("_canon_away") or away.get("displayName"), away_news),
                ("home", home, g.get("_canon_home") or home.get("displayName"), home_news),
            ]:
                for r in news_list:
                    flat_news = {
                        "league": r.get("league") or cfg.key,
                        "run_date_et": r.get("run_date_et") or run_date.isoformat(),
                        "team_side": r.get("team_side") or side,
                        "team_id": r.get("team_id") or team_obj.get("id"),
                        "team_name": r.get("team_name") or team_name,
                        "team_abbrev": r.get("team_abbrev") or team_obj.get("abbreviation"),
                        "source": r.get("source"),
                        "headline": r.get("headline"),
                        "summary": r.get("summary"),
                        "published_at": r.get("published_at"),
                        "url": r.get("url"),
                        "category": r.get("category"),
                        "relevance_score": r.get("relevance_score"),
                        "event_id": g.get("event_id"),
                        "game_id": g.get("_game_id") or "",
                        "sheet_name": sheet_name,
                        "matchup": g.get("name"),
                        "short_name": g.get("short_name"),
                    }
                    all_news_rows.append({k: excel_safe(v) for k, v in flat_news.items()})

        write_workbook(out_path, cfg, games, payloads, league_news, diagnostics, all_game_rows, all_injury_rows, all_news_rows, all_validity_rows)
        if any(bool(r.get("blocking")) for r in all_validity_rows):
            overall_blocking_validity = True
            logger.warning("[%s] Blocking injury/news validity rows present.", cfg.key)
        logger.info("[%s] [OK] Workbook written: %s", cfg.key, str(out_path))

    logger.info("=== All leagues done ===")
    return 2 if overall_blocking_validity else 0


if __name__ == "__main__":
    raise SystemExit(main())
