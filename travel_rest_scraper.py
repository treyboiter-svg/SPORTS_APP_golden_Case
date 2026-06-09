"""
Travel/rest loader for per-game context.

Outputs deterministic, numeric fields required by the ingest contract:
- away_rest_days, home_rest_days
- away_games_last_5d, home_games_last_5d
- away_travel_miles, home_travel_miles
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)

_VENUE_FILE = "US_SPORTS_VENUES_MASTER_CORRECTED_V2.json"
_SCHEDULE_FILE_RE = re.compile(r"^Schedules_([A-Z0-9]+)_(\d{8})\.xlsx$")
_GAME_CACHE: Dict[str, List[Tuple[str, str]]] = {}
_VENUE_CACHE: Dict[str, Dict[str, Tuple[float, float]]] = {}


def _to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return datetime.now().date()


def _team_key(name: Any) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.7613
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2.0) ** 2) + math.cos(p1) * math.cos(p2) * (math.sin(dlmb / 2.0) ** 2)
    return 2.0 * r_miles * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _schedule_files(stats_dir: Path, sport: str, game_day: date) -> List[Tuple[date, Path]]:
    out: List[Tuple[date, Path]] = []
    token = str(sport or "").upper().strip()
    for p in stats_dir.glob(f"Schedules_{token}_*.xlsx"):
        m = _SCHEDULE_FILE_RE.match(p.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(2), "%Y%m%d").date()
        except Exception:
            continue
        if d <= game_day:
            out.append((d, p))
    out.sort(key=lambda x: x[0])
    return out


def _read_games(path: Path) -> List[Tuple[str, str]]:
    key = f"{str(path.resolve()).lower()}|{int(path.stat().st_mtime)}"
    cached = _GAME_CACHE.get(key)
    if cached is not None:
        return list(cached)

    try:
        df = pd.read_excel(path, dtype=str)
    except Exception as exc:
        log.warning("[travel_rest] could not read %s: %s", path, exc)
        _GAME_CACHE[key] = []
        return []

    if df is None or df.empty:
        _GAME_CACHE[key] = []
        return []

    cols = [str(c) for c in list(df.columns)]
    away_col = next((c for c in cols if "away" in c.lower()), None)
    home_col = next((c for c in cols if "home" in c.lower()), None)
    if not away_col or not home_col:
        _GAME_CACHE[key] = []
        return []

    games: List[Tuple[str, str]] = []
    for _, row in df.iterrows():
        away = _team_key(row.get(away_col))
        home = _team_key(row.get(home_col))
        if away and home:
            games.append((away, home))
    _GAME_CACHE[key] = games
    return list(games)


def _venue_map(base_dir: Path, sport: str) -> Dict[str, Tuple[float, float]]:
    token = str(sport or "").upper().strip()
    ck = f"{str(base_dir.resolve()).lower()}|{token}"
    cached = _VENUE_CACHE.get(ck)
    if cached is not None:
        return dict(cached)

    out: Dict[str, Tuple[float, float]] = {}
    venue_file = base_dir / _VENUE_FILE
    if not venue_file.exists():
        _VENUE_CACHE[ck] = out
        return out

    try:
        raw = json.loads(venue_file.read_text(encoding="utf-8"))
        rows = raw
        if isinstance(raw, dict):
            # Preserve existing loader behavior from app file.
            first = next(iter(raw.values()), [])
            rows = first if isinstance(first, list) else []
        if not isinstance(rows, list):
            rows = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            lg = str(r.get("league") or "").upper().strip()
            if lg != token:
                continue
            team = _team_key(r.get("team"))
            if not team:
                continue
            try:
                lat = float(r.get("lat"))
                lon = float(r.get("lon"))
            except Exception:
                continue
            out[team] = (lat, lon)
    except Exception as exc:
        log.warning("[travel_rest] venue map load failed: %s", exc)

    _VENUE_CACHE[ck] = out
    return dict(out)


def _team_events(team_key: str, files: List[Tuple[date, Path]]) -> List[Tuple[date, str]]:
    events: List[Tuple[date, str]] = []
    for d, p in files:
        for away, home in _read_games(p):
            if away == team_key or home == team_key:
                # Venue owner is the home team.
                events.append((d, home))
    events.sort(key=lambda x: x[0])
    return events


def _team_metrics(team_name: str, game_day: date, files: List[Tuple[date, Path]], venue_coords: Dict[str, Tuple[float, float]]) -> Tuple[float, float, float]:
    team = _team_key(team_name)
    if not team:
        return (0.0, 0.0, 0.0)

    events = _team_events(team, files)
    prior_days = [d for d, _ in events if d < game_day]
    if prior_days:
        rest_days = float(max(0, (game_day - max(prior_days)).days))
    else:
        # No prior game observed in available schedule horizon.
        rest_days = 7.0

    window_start = game_day - timedelta(days=5)
    games_last_5d = float(sum(1 for d, _ in events if window_start <= d < game_day))

    path_events = [(d, v) for d, v in events if window_start <= d <= game_day]
    miles = 0.0
    for i in range(1, len(path_events)):
        _, prev_home = path_events[i - 1]
        _, curr_home = path_events[i]
        p1 = venue_coords.get(prev_home)
        p2 = venue_coords.get(curr_home)
        if not p1 or not p2:
            continue
        miles += _haversine_miles(p1[0], p1[1], p2[0], p2[1])

    return (rest_days, games_last_5d, round(miles, 2))


def load_travel_rest_for_game(away_team=None, home_team=None, game_date=None, sport=None, **kw):
    game_day = _to_date(game_date)
    sport_up = str(sport or "").upper().strip()
    base_dir = Path(__file__).resolve().parent
    stats_dir = Path(str(kw.get("stats_output_dir") or (base_dir / "stats_output")))
    if not stats_dir.exists():
        return {"available": False, "error": f"stats_output_dir_missing:{stats_dir}"}

    files = _schedule_files(stats_dir, sport_up, game_day)
    if not files:
        return {
            "available": False,
            "error": f"schedule_files_missing:{sport_up}:{game_day.isoformat()}",
            "away_rest_days": 0.0,
            "home_rest_days": 0.0,
            "away_games_last_5d": 0.0,
            "home_games_last_5d": 0.0,
            "away_travel_miles": 0.0,
            "home_travel_miles": 0.0,
        }

    coords = _venue_map(base_dir, sport_up)
    away_rest, away_games_5d, away_miles = _team_metrics(str(away_team or ""), game_day, files, coords)
    home_rest, home_games_5d, home_miles = _team_metrics(str(home_team or ""), game_day, files, coords)

    return {
        "available": True,
        "source": "schedule_derived",
        "away_rest_days": away_rest,
        "home_rest_days": home_rest,
        "away_games_last_5d": away_games_5d,
        "home_games_last_5d": home_games_5d,
        "away_travel_miles": away_miles,
        "home_travel_miles": home_miles,
    }
