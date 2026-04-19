# air_density_full_app_PATCHED_v8.py
# ============================================================
# v8 â€” MATCHUP DETAIL POPUP
#APP
# NEW: Double-click any game row â†’ opens a full Matchup Detail
#      window showing:
#        â€¢ Game time + all odds (spread / total / moneyline)
#        â€¢ Home venue â€” name, city, elevation, surface, roof, orientation
#        â€¢ Away venue â€” name, elevation (their home park for reference)
#        â€¢ Elevation delta â€” how much higher/lower the game venue is
#          vs where the away team normally plays
#        â€¢ Live weather at the home venue
#        â€¢ Full physics output â€” air density, density altitude,
#          headwind, crosswind
#        â€¢ "Load HOME/AWAY â†’ Physics Model" buttons inside the popup
#
# INTERACTION CHANGES:
#   Double-click row  â†’ Open Matchup Detail popup (NEW)
#   Right-click row   â†’ Context menu:
#                         â€¢ Open Matchup Detail
#                         â€¢ Load HOME â†’ Physics Model
#                         â€¢ Load AWAY â†’ Physics Model
#   "Load Selected" button â†’ loads HOME team into Physics Model (unchanged)
# ============================================================

import tkinter as tk
from tkinter import ttk
import pandas as pd
import requests
import math
import json
import logging
import traceback
import threading
import os
import re
import queue
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Default to hidden scraper browsers unless user explicitly opts out (HEADLESS=0).
os.environ.setdefault("HEADLESS", "1")

# â”€â”€ Arsenal engine (optional) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from arsenal_engine import (
        get_todays_arsenal, load_cached_arsenal,
        find_pitcher_for_team, get_pitcher_rows,
        check_starter_changes, patch_arsenal_with_new_pitcher,
        PYBASEBALL_AVAILABLE,
    )
    ARSENAL_AVAILABLE = True
except Exception as _ars_err:
    ARSENAL_AVAILABLE    = False
    PYBASEBALL_AVAILABLE = False
    _arsenal_import_error = str(_ars_err)

try:
    from odds_scraper import scrape_sport, save_excel
    SCRAPER_AVAILABLE = True
except Exception as _scraper_err:
    SCRAPER_AVAILABLE = False
    _scraper_import_error = str(_scraper_err)
# â”€â”€ Stats + SOS integration (scrapes.py + sos_scraper.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from stats_sos_integration import (
        render_stats_sos_block  as _render_stats_sos_block,
        get_stats_for_matchup   as _get_stats_for_matchup,
        get_sos_from_file       as _get_sos_from_file,
        get_stats_sos_model_signal as _get_stats_sos_model_signal,
        add_stats_fetch_button  as _add_stats_fetch_button,
        invalidate_stats_cache  as _invalidate_stats_cache,
        invalidate_sos_cache    as _invalidate_sos_cache,
        get_league_readiness    as _get_stats_sos_league_readiness,
        get_all_league_readiness as _get_stats_sos_all_readiness,
    )
    STATS_SOS_AVAILABLE = True
except Exception as _sts_err:
    STATS_SOS_AVAILABLE = False
    def _render_stats_sos_block(*a, **kw): pass
    def _get_stats_for_matchup(*a, **kw): return {"away": None, "home": None, "source": "unavailable", "error": str(_sts_err)}
    def _get_sos_from_file(*a, **kw): return {"away": None, "home": None, "source": "no_file", "error": "stats_sos_integration.py not found"}
    def _get_stats_sos_model_signal(*a, **kw): return {"score": 0.0, "coverage": 0.0, "factors": []}
    def _add_stats_fetch_button(*a, **kw): pass
    def _invalidate_stats_cache(*a, **kw): pass
    def _invalidate_sos_cache(*a, **kw): pass
    def _get_stats_sos_league_readiness(*a, **kw): return {"readiness_state": "BLOCKED", "stats_state": "STATS_BLOCKED", "sos_state": "SOS_BLOCKED"}
    def _get_stats_sos_all_readiness(*a, **kw): return {}
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# =========================
# CONFIG
# =========================
def _load_openweather_api_key() -> str:
    for _env_key in ("OWM_API_KEY", "OPENWEATHER_API_KEY"):
        _k = str(os.environ.get(_env_key, "") or "").strip()
        if _k:
            return _k
    _base = Path(__file__).resolve().parent
    _candidates = [
        _base / "owm_api_key.txt",
        _base / "openweather_api_key.txt",
        _base / "odds_data" / "owm_api_key.txt",
        _base / "odds_data" / "openweather_api_key.txt",
    ]
    for _p in _candidates:
        try:
            if _p.exists():
                _txt = _p.read_text(encoding="utf-8")
                for _line in _txt.splitlines():
                    _v = str(_line or "").strip()
                    if not _v or _v.startswith("#"):
                        continue
                    if "<" in _v and ">" in _v:
                        continue
                    return _v
        except Exception:
            continue
    return ""

SCRIPT_DIR = Path(__file__).resolve().parent
OPENWEATHER_API_KEY = _load_openweather_api_key()
OPENWEATHER_KEY_FILE = str(SCRIPT_DIR / "openweather_api_key.txt")
_USER_HOME = Path.home()
_BRAND_ICON_CANDIDATES = [
    _USER_HOME / "Downloads" / "IMG_0336.PNG",
    _USER_HOME / "Downloads" / "img_0336.png",
    _USER_HOME / "Downloads" / "IMG_0036.PNG",
    _USER_HOME / "Downloads" / "img_0036.png",
    _USER_HOME / "Downloads" / "Gradient Hexagon Logo Design.png",
    _USER_HOME / "Downloads" / "Modern _OE_ Logo with Gradient Design.png",
    _USER_HOME / "Downloads" / "Modern Overline Edge Logo Design.png",
    _USER_HOME / "Downloads" / "logo.png",
]
_BRAND_LOCKUP_CANDIDATES = [
    _USER_HOME / "Downloads" / "IMG_0335.PNG",
    _USER_HOME / "Downloads" / "img_0335.png",
    _USER_HOME / "Downloads" / "ChatGPT Image Apr 16, 2026, 11_20_59 PM.png",
    _USER_HOME / "Downloads" / "ChatGPT Image Apr 16, 2026, 11_20_40 PM.png",
    _USER_HOME / "Downloads" / "ChatGPT Image Apr 16, 2026, 11_20_07 PM.png",
    _USER_HOME / "Downloads" / "logo.png",
]
_APP_ICON_CANDIDATES = [
    _USER_HOME / "Downloads" / "IMG_0336.PNG",
    _USER_HOME / "Downloads" / "img_0336.png",
    _USER_HOME / "Downloads" / "IMG_0036.PNG",
    _USER_HOME / "Downloads" / "img_0036.png",
]
_SPLASH_LOGO_CANDIDATES = [
    _USER_HOME / "Downloads" / "IMG_0336.PNG",
    _USER_HOME / "Downloads" / "img_0336.png",
    _USER_HOME / "Downloads" / "logo.png",
]
def _ensure_openweather_key_file_hint():
    try:
        _p = Path(OPENWEATHER_KEY_FILE)
        if _p.exists():
            return
        _p.write_text(
            "# OpenWeather API key (single line)\n"
            "# Example: abcdef1234567890\n"
            "# This file is read when OPENWEATHER_API_KEY / OWM_API_KEY env vars are not set.\n",
            encoding="utf-8",
        )
    except Exception:
        pass

_ensure_openweather_key_file_hint()
VENUE_FILE          = SCRIPT_DIR / "US_SPORTS_VENUES_MASTER_CORRECTED_V2.json"
# Absolute path â€” always resolves to the folder where this script lives,
# regardless of what working directory you run from.
ODDS_DIR       = str(SCRIPT_DIR / "odds_data")
AUDIT_LOG_FILE = os.path.join(ODDS_DIR, "model_audit_log.json")
_PRIMARY_INJURY_DIR = SCRIPT_DIR / "injury_news_output"
_LEGACY_INJURY_DIR = Path(ODDS_DIR) / "injury_news_output"
_CWD_INJURY_DIR = Path.cwd() / "injury_news_output"

def _injury_news_output_dir() -> Path:
    """Resolve the active injury/news output directory."""
    token = datetime.now().strftime("%Y%m%d")
    candidates = []
    for _p in (_PRIMARY_INJURY_DIR, _LEGACY_INJURY_DIR, _CWD_INJURY_DIR):
        try:
            _r = _p.resolve()
        except Exception:
            _r = _p
        if all(str(_r) != str(_e) for _e in candidates):
            candidates.append(_r)

    for _p in candidates:
        try:
            if _p.exists() and any(_p.glob(f"INJURY_NEWS_*_{token}.xlsx")):
                return _p
        except Exception:
            continue
    for _p in candidates:
        try:
            if _p.exists():
                return _p
        except Exception:
            continue
    return candidates[0] if candidates else _PRIMARY_INJURY_DIR

def _injury_news_file_path(sport: str, token=None) -> Path:
    _tok = token or datetime.now().strftime("%Y%m%d")
    return _injury_news_output_dir() / f"INJURY_NEWS_{str(sport).upper()}_{_tok}.xlsx"

def _injury_news_has_required_sheets(path: Path) -> bool:
    try:
        xl = pd.ExcelFile(path)
        sheets = {str(s).strip().upper() for s in (xl.sheet_names or [])}
        return "INJURIES" in sheets and "TEAM_NEWS" in sheets
    except Exception:
        return False
# â”€â”€ CRE Integration (Circadian Rhythm Effect) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from cre_integration import get_cre_for_game, apply_cre_to_model, cre_display_block
    _CRE_AVAILABLE = True
except ImportError:
    _CRE_AVAILABLE = False
    def get_cre_for_game(*a, **k): return None
    def apply_cre_to_model(ou, side, conf, rec, league, rho_pct=None):
        return {"final_ou_lean": ou, "final_side_lean": side,
                "final_confidence": conf, "cre_contributed": False,
                "cre_summary": "CRE module not installed.", "compound_signal": False,
                "cre_weight_applied": 0.0, "away_severity": "N/A",
                "home_severity": "N/A", "cre_ou_lean": "NEUTRAL",
                "cre_side_lean": "NEUTRAL", "notes": ""}
    def cre_display_block(*a, **k): return ""
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

LEAGUE_MAP = {
    "MLB":   "mlb",
    "NBA":   "nba",
    "NFL":   "nfl",
    "NHL":   "nhl",
    "NCAAB": "ncaab",
    "NCAAF": "ncaaf",
}

_STATS_SOS_LEAGUES = ("MLB", "NBA", "NHL", "NFL", "NCAAB", "NCAAF")
_STATUS_READYNESS_ALLOWED = {"READY", "PARTIAL_READY", "STATS_READY", "SOS_READY", "NO_GAMES", "BLOCKED"}
_MLB_CITY_STARTER_FALLBACK = {
    # Only include cities that map unambiguously to one MLB franchise.
    "washington": "nationals",
    "pittsburgh": "pirates",
    "baltimore": "orioles",
    "cleveland": "guardians",
    "cincinnati": "reds",
    "milwaukee": "brewers",
    "minnesota": "twins",
    "detroit": "tigers",
    "seattle": "mariners",
    "miami": "marlins",
    "tampa bay": "rays",
    "toronto": "blue jays",
    "st louis": "cardinals",
    "san diego": "padres",
    "san francisco": "giants",
    "oakland": "athletics",
    "sacramento": "athletics",
    "colorado": "rockies",
    "arizona": "diamondbacks",
}

_VENUE_LEAGUE_ALIASES = {
    "MLB":   {"MLB"},
    "NBA":   {"NBA"},
    "NFL":   {"NFL"},
    "NHL":   {"NHL"},
    "NCAAB": {"NCAAB", "NCAA D1 MBB"},
    "NCAAF": {"NCAAF", "NCAA FBS"},
}

# =========================
# FILE LOGGING
# =========================
LOG_FILE = "sports_physics_engine.log"
logging.basicConfig(
    filename=LOG_FILE, level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

_gui_ready = False
_LOG_UI_QUEUE = queue.Queue(maxsize=20000)
_LOG_QUEUE_DROPPED = 0
_LOG_PUMP_STARTED = False
_DETAIL_POPUP_DEFAULT_HEAVY = False
_DETAIL_POPUP_FAST_RENDER = True
_DETAIL_POPUP_DEBOUNCE_SEC = 0.65
_LAST_MATCHUP_OPEN_TS = 0.0
_DETAIL_WINDOW_OPENING = False
_LOG_TAG_COLORS_CONFIGURED = set()
_LOG_MAX_LINES_PER_TAB = 2500
_LOG_PROGRESS_THROTTLE_SEC = 0.60
_DETAIL_HEAVY_CACHE = {}
_DETAIL_HEAVY_CACHE_LOCK = threading.Lock()
_DETAIL_HEAVY_CACHE_MAX = 96

# Daily startup orchestration ledger:
# tracks which heavy startup scrapers completed for today's date so
# first app-open runs full refresh, while subsequent opens skip redundant jobs.
_STARTUP_TASK_STATE_FILE = Path(ODDS_DIR) / "startup_data" / "startup_task_state.json"
_STARTUP_TASK_STATE_LOCK = threading.Lock()


def _startup_task_today_token() -> str:
    return datetime.now().strftime("%Y%m%d")


def _startup_task_state_read_nolock() -> dict:
    today = _startup_task_today_token()
    state = {}
    try:
        if _STARTUP_TASK_STATE_FILE.exists():
            state = json.loads(_STARTUP_TASK_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    if not isinstance(state, dict) or str(state.get("date_token", "")) != today:
        state = {
            "date_token": today,
            "first_opened_at": datetime.now().astimezone().isoformat(),
            "tasks": {},
        }
    if not isinstance(state.get("tasks"), dict):
        state["tasks"] = {}
    return state


def _startup_task_state_write_nolock(state: dict) -> None:
    _tmp = None
    try:
        _STARTUP_TASK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _tmp = _STARTUP_TASK_STATE_FILE.with_suffix(".tmp")
        _tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(str(_tmp), str(_STARTUP_TASK_STATE_FILE))
    except Exception:
        try:
            if _tmp is not None and _tmp.exists():
                _tmp.unlink()
        except Exception:
            pass


def _startup_task_should_run(task_name: str):
    with _STARTUP_TASK_STATE_LOCK:
        state = _startup_task_state_read_nolock()
        rec = dict(state.get("tasks", {}).get(task_name, {}) or {})
        status = str(rec.get("status", "")).lower().strip()
        should_run = status != "success"
        return should_run, rec


def _startup_task_mark(task_name: str, status: str, **extra):
    with _STARTUP_TASK_STATE_LOCK:
        state = _startup_task_state_read_nolock()
        tasks = state.setdefault("tasks", {})
        rec = dict(tasks.get(task_name, {}) or {})
        rec.update(extra or {})
        rec["status"] = str(status or "").lower().strip()
        rec["updated_at"] = datetime.now().astimezone().isoformat()
        tasks[task_name] = rec
        _startup_task_state_write_nolock(state)
        return rec

# â”€â”€ Arsenal globals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_starters_df      = None
_arsenal_df       = None
_arsenal_fetching = False   # True while background fetch is running
_arsenal_progress = ""      # e.g. "[12/30] Max Fried (Yankees)"

def log(msg, level="info"):
    global _LOG_QUEUE_DROPPED
    def _sanitize_ui_text(s):
        s = str(s)
        # Attempt to repair common mojibake sequences first.
        try:
            if any(tok in s for tok in ("\u00e2", "\u00c3", "\u00f0", "\u00c2", "\u00d0\u00b2", "\u00ce")):
                s_fixed = s.encode("latin1", "ignore").decode("utf-8", "ignore")
                if s_fixed:
                    s = s_fixed
        except Exception:
            pass
        fixes = {
            "â”€": "-",
            "â•": "=",
            "â€”": "-",
            "â†’": "->",
            "âœ…": "[OK]",
            "âš ": "[WARN]",
            "â³": "[PENDING]",
            "âš™": "[RUN]",
            "âŒ": "[ERROR]",
            "â–¶": "Run",
            # Legacy mojibake fallbacks seen in historical logs.
            "\u00e2\u0161 ": "[WARN] ",
            "\u00e2\u0161\u00a0": "[WARN]",
            "\u00e2\u0153\u2026": "[OK]",
            "\u00e2\u008f\u00b3": "[PENDING]",
            "\u00e2\u0161\u2122": "[RUN]",
            "\u00e2\u009d\u0152": "[ERROR]",
            "\u00e2\u2020\u2019": "->",
            "\u00e2\u20ac\u201d": "-",
            "\u00e2\u2013\u00b6": "Run",
        }
        for bad, good in fixes.items():
            s = s.replace(bad, good)
        return s
    try:
        getattr(logging, level)(msg)
    except Exception:
        logging.info(str(msg))
    if not _gui_ready:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        _LOG_UI_QUEUE.put_nowait((ts, str(level), _sanitize_ui_text(msg)))
    except Exception:
        _LOG_QUEUE_DROPPED += 1


_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def _is_dead_loopback_proxy(value: str) -> bool:
    s = str(value or "").strip().lower()
    if not s:
        return False
    return (":9" in s) and any(tok in s for tok in ("127.0.0.1", "localhost", "::1"))


def _strip_dead_loopback_proxies(env_obj: dict) -> list:
    removed = []
    for k in _PROXY_ENV_KEYS:
        if k in env_obj and _is_dead_loopback_proxy(env_obj.get(k)):
            env_obj.pop(k, None)
            removed.append(k)
    if removed:
        # Preserve loopback bypass for local tooling.
        env_obj.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
        env_obj.setdefault("no_proxy", env_obj.get("NO_PROXY", "localhost,127.0.0.1,::1"))
    return removed


def _runtime_env_copy() -> dict:
    env = dict(os.environ)
    _strip_dead_loopback_proxies(env)
    return env


_removed_proxy_keys = _strip_dead_loopback_proxies(os.environ)
if _removed_proxy_keys:
    log(
        "Startup network hygiene: removed dead loopback proxy env vars "
        f"({', '.join(sorted(set(_removed_proxy_keys)))}) so live data fetches can run.",
        "warning",
    )


def _drain_log_queue():
    global _LOG_QUEUE_DROPPED
    if not _gui_ready:
        root.after(140, _drain_log_queue)
        return
    _processed = 0
    _touched_boxes = set()
    while _processed < 80:
        try:
            ts, level, msg = _LOG_UI_QUEUE.get_nowait()
        except Exception:
            break
        if level == "error":
            _append_tab(err_box, ts, "ERROR", msg, _UI["danger"], autoscroll=False)
            _touched_boxes.add(err_box)
        elif level == "warning":
            _append_tab(data_box, ts, "WARN", msg, _UI["warning"], autoscroll=False)
            _touched_boxes.add(data_box)
        else:
            color = _UI["success"] if level == "info" else _UI["text_muted"]
            _append_tab(
                run_box,
                ts,
                "INFO" if level == "info" else "DEBUG",
                msg,
                color,
                autoscroll=False,
            )
            _touched_boxes.add(run_box)
        _processed += 1
    if _LOG_QUEUE_DROPPED > 0:
        _append_tab(
            data_box,
            datetime.now().strftime("%H:%M:%S"),
            "WARN",
            f"Log overload: dropped {_LOG_QUEUE_DROPPED} UI lines (file log preserved).",
            _UI["warning"],
            autoscroll=False,
        )
        _touched_boxes.add(data_box)
        _LOG_QUEUE_DROPPED = 0
        _processed += 1
    if _touched_boxes:
        for _box in _touched_boxes:
            try:
                _box.see(tk.END)
            except Exception:
                pass
    if _processed:
        _update_tab_badges()
    root.after(120, _drain_log_queue)


def _start_log_pump():
    global _LOG_PUMP_STARTED
    if _LOG_PUMP_STARTED:
        return
    _LOG_PUMP_STARTED = True
    root.after(80, _drain_log_queue)

def _append_tab(box, ts, tag, msg, color, autoscroll=True):
    box.config(state=tk.NORMAL)
    if color not in _LOG_TAG_COLORS_CONFIGURED:
        box.tag_config(color, foreground=color)
        _LOG_TAG_COLORS_CONFIGURED.add(color)
    box.insert(tk.END, f"{ts} [{tag}]  {msg}\n", color)
    try:
        _lines = max(int(box.index("end-1c").split(".")[0]) - 1, 0)
        if _lines > _LOG_MAX_LINES_PER_TAB:
            _drop = _lines - _LOG_MAX_LINES_PER_TAB
            box.delete("1.0", f"{_drop + 1}.0")
    except Exception:
        pass
    if autoscroll:
        box.see(tk.END)
    box.config(state=tk.DISABLED)

def _update_tab_badges():
    try:
        e = max(int(err_box.index("end-1c").split(".")[0]) - 1, 0)
        w = max(int(data_box.index("end-1c").split(".")[0]) - 1, 0)
        diag_tabs.tab(1, text=f"  Errors ({e})  ")
        diag_tabs.tab(2, text=f"  Data Health ({w})  ")
    except Exception:
        pass

# =========================
# LOAD VENUE DATA
# =========================
startup_warnings = []

try:
    with open(VENUE_FILE, "r") as f:
        data = json.load(f)
    if isinstance(data, dict):
        keys = list(data.keys())
        data = data[keys[0]]
        startup_warnings.append(f"JSON wrapped in key '{keys[0]}' â€” auto-unwrapped.")
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError("Venue JSON must be a non-empty list.")
    df = pd.DataFrame(data)
    for col in ["lat", "lon", "elevation", "orientation_deg"]:
        if col not in df.columns:
            df[col] = float("nan")
            startup_warnings.append(f"Column '{col}' missing -> left as missing (NaN).")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["league", "team", "venue"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
        else:
            startup_warnings.append(f"Column '{col}' missing from JSON.")
except FileNotFoundError:
    raise SystemExit(f"[FATAL] Venue file not found: {VENUE_FILE}")
except json.JSONDecodeError as e:
    raise SystemExit(f"[FATAL] Venue JSON malformed: {e}")
except Exception as e:
    raise SystemExit(f"[FATAL] Could not load venue data: {e}")

# =========================
# HELPERS
# =========================
def get_teams(league):
    return sorted(df[df["league"] == league]["team"].dropna().unique())

def _normalize_league_tag(league):
    lg = str(league or "").strip()
    if not lg:
        return ""
    up = lg.upper()
    for canonical, aliases in _VENUE_LEAGUE_ALIASES.items():
        if up == canonical or up in {a.upper() for a in aliases}:
            return canonical
    return up

def _same_league_tag(row_league, preferred_league):
    if not preferred_league:
        return True
    return _normalize_league_tag(row_league) == _normalize_league_tag(preferred_league)

def get_row(team, preferred_league=None):
    rows = df[df["team"] == team]
    if preferred_league:
        rows = rows[rows["league"].apply(lambda lg: _same_league_tag(lg, preferred_league))]
    return rows.iloc[0] if not rows.empty else None

def safe(row, col):
    return row[col] if row is not None and col in row.index and pd.notna(row[col]) else ""

def safe_float(val, default=0.0, label="value"):
    _missing = False
    if val is None:
        _missing = True
    elif isinstance(val, str):
        _v = val.strip()
        _missing = (_v == "" or _v.upper() in {"N/A", "NA", "NONE", "NULL"})
    else:
        try:
            _missing = bool(pd.isna(val))
        except Exception:
            _missing = False
    if _missing:
        if default is None:
            return None
        log(f"Missing {label} -> using default {default}", "warning")
        return default
    try:
        _f = float(val)
        if not math.isfinite(_f):
            raise ValueError("non-finite float")
        return _f
    except (ValueError, TypeError):
        if default is None:
            return None
        log(f"Non-numeric {label} '{val}' -> using default {default}", "warning")
        return default
# =========================
# PITCHER STRIPPER â€” v7 FIXED
# =========================
_PITCHER_CAMEL = re.compile(
    r'(?<=[a-z])([A-Z][a-zA-Z\-\']*(?::\s+[A-Za-z][a-zA-Z\-\']*)*\s+[LR])\s*$'
)
_PITCHER_SPACE = re.compile(r'\s+[A-Z][a-zA-Z\-\']+\s+[LR]\s*$')
_TEAM_PREFIXES_SORTED = tuple(
    sorted((str(t) for t in df["team"].dropna().unique().tolist()), key=len, reverse=True)
)
_TEAM_LOWER_SET = {str(t).lower() for t in _TEAM_PREFIXES_SORTED}
_KNOWN_TEAM_PREFIXES_SORTED = tuple(sorted([
    "blue jays","red sox","white sox","trail blazers","golden knights",
    "maple leafs","blue jackets","red wings","timberwolves","diamondbacks",
    "guardians","nationals","mariners","brewers","athletics","cardinals",
    "dodgers","phillies","rangers","rockies","padres","marlins","orioles",
    "braves","astros","giants","pirates","royals","tigers","angels","twins",
    "yankees","mets","cubs","rays","reds",
    "celtics","lakers","warriors","bucks","suns","nets","bulls","heat",
    "knicks","mavericks","nuggets","clippers","spurs","rockets","hawks",
    "sixers","raptors","cavaliers","grizzlies","pelicans","wizards","magic",
    "pacers","pistons","thunder","jazz","hornets","kings","blazers",
    "penguins","capitals","lightning","bruins","avalanche","flyers","stars",
    "hurricanes","predators","blues","flames","oilers","canucks","ducks",
    "canadiens","senators","sabres","sharks","blackhawks","wild","coyotes",
    "islanders","devils","panthers","kraken",
    "chiefs","eagles","49ers","ravens","cowboys","bills","bengals","rams",
    "chargers","dolphins","raiders","broncos","packers","bears","vikings",
    "lions","seahawks","saints","buccaneers","falcons","panthers","giants",
    "commanders","patriots","jets","colts","titans","texans","jaguars",
    "steelers","browns","raiders",
], key=len, reverse=True))

def _strip_pitcher(name: str) -> str:
    """Clean team names that may have a pitcher last name appended.
    Handles:  'Angels L'  'AngelsKlassen'  'Rangersde' 'Angels Klassen L'
    Strategy: venue-prefix match first â†’ regex â†’ CamelCase split â†’ original.
    """
    if not name:
        return name
    # â”€â”€ Step 0: Direct venue-prefix match (fastest, handles ALL suffix types) â”€â”€
    # Finds the longest known venue-DB team name that is a prefix of this string.
    # Works for CamelCase ("AngelsKlassen") AND lowercase particles ("Rangersde").
    # Use venue DataFrame (df from US_SPORTS_VENUES_MASTER_CORRECTED_V2.json)
    # sorted longest-first for greedy match â€” handles "Rangersde", "AngelsKlassen" etc.
    # â”€â”€ Step 0a: venue-DB prefix match â”€â”€
    try:
        raw_l = name.lower()
        for team in _TEAM_PREFIXES_SORTED:
            tl = str(team).lower()
            if raw_l.startswith(tl) and len(name) > len(tl):
                return name[:len(tl)]  # always return â€” suffix is always pitcher
    except Exception:
        pass
    # â”€â”€ Step 0b: hardcoded known-team fallback (handles Rangers, Red Sox, etc.) â”€â”€
    try:
        raw_l = name.lower()
        for _kn in _KNOWN_TEAM_PREFIXES_SORTED:
            if raw_l.startswith(_kn) and len(name) > len(_kn):
                return name[:len(_kn)]
    except Exception:
        pass

    # Try existing regex patterns first (handles trailing handedness)
    cleaned = _PITCHER_CAMEL.sub("", name).strip()
    if cleaned and cleaned != name:
        return cleaned
    cleaned2 = _PITCHER_SPACE.sub("", name).strip()
    if cleaned2 and cleaned2 != name:
        return cleaned2
    # CamelCase fallback: "AngelsKlassen" â†’ split on internal capitals
    # and keep the longest prefix that matches a known venue-db team
    camel_parts = re.findall(r"[A-Z][a-z0-9]*", name)
    if len(camel_parts) >= 2:           # must have at least 2 CamelCase words
        for take in range(len(camel_parts)-1, 0, -1):
            candidate = "".join(camel_parts[:take])
            if candidate.lower() in _TEAM_LOWER_SET:
                return candidate
    # Strip trailing seed/score numbers ("UConn 7"â†’"UConn", "Michigan 3"â†’"Michigan")
    import re as _re_sp
    name = _re_sp.sub(r'\s+\d{1,3}$', '', name.strip()).strip()
    return name

# =========================
# WEATHER
# =========================

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ESPN LIVE VENUE + GAME CONTEXT RESOLVER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
_espn_venue_cache = {}
ESPN_SPORT_MAP = {
    "MLB":   ("baseball",    "mlb",                      "limit=300"),
    "NBA":   ("basketball",  "nba",                      "limit=200"),
    "NHL":   ("hockey",      "nhl",                      "limit=200"),
    "NFL":   ("football",    "nfl",                      "limit=200"),
    "NCAAB": ("basketball",  "mens-college-basketball",  "limit=500&groups=50"),
    "NCAAF": ("football",    "college-football",         "limit=500"),
}
_CTX_EMOJI = {"championship":"ðŸ†","final":"ðŸ†","finals":"ðŸ†","playoff":"ðŸ¥Š","playoffs":"ðŸ¥Š",
              "postseason":"Ã°Å¸Â¥Å ","tournament":"Ã°Å¸Å½â€œ","semifinal":"Ã°Å¸Â¥Ë†","quarterfinal":"Ã°Å¸Â¥â€°",
              "wild card":"ðŸƒ","wildcard":"ðŸƒ","bowl":"ðŸˆ","super bowl":"ðŸˆ",
              "stanley cup":"ðŸ’","elite eight":"ðŸŽ“","final four":"ðŸŽ“",
              "sweet sixteen":"Ã°Å¸Å½â€œ","first round":"Ã°Å¸Å½â€œ","second round":"Ã°Å¸Å½â€œ",
              "third round":"Ã°Å¸Å½â€œ","game 7":"Ã°Å¸â€Â¥","game 6":"Ã°Å¸â€Â¥","series":"Ã°Å¸Å½Â¯"}
def _ctx_emoji(t):
    t=t.lower()
    for k,e in _CTX_EMOJI.items():
        if k in t: return e
    return "âš¡"
def _resolve_game_venue(sport, away_team, home_team, game_date_str):
    key=(sport,away_team.lower(),home_team.lower(),game_date_str)
    if key in _espn_venue_cache: return _espn_venue_cache[key]
    if sport not in ESPN_SPORT_MAP: _espn_venue_cache[key]=None; return None
    try:
        import urllib.request as _ur, json as _j, time as _t
        sp,lg,params=ESPN_SPORT_MAP[sport]
        url=(f"https://site.api.espn.com/apis/site/v2/sports/{sp}/{lg}/scoreboard"
             f"?dates={game_date_str.replace('-','')}&{params}")
        _t.sleep(0.25)
        with _ur.urlopen(url,timeout=9) as r: data=_j.loads(r.read())
        def _nm(n1,n2):
            n1=n1.lower().strip(); n2=n2.lower().strip()
            return n1 in n2 or n2 in n1 or n1.split()[-1]==n2.split()[-1]
        for event in data.get("events",[]):
            comp=(event.get("competitions") or [{}])[0]
            ea=eh=""
            for c in comp.get("competitors",[]):
                nm=c.get("team",{}).get("displayName","")
                if c.get("homeAway")=="away": ea=nm
                else: eh=nm
            if not (_nm(away_team,ea) and _nm(home_team,eh)): continue
            v=comp.get("venue",{}); addr=v.get("address",{})
            vname=v.get("fullName",""); city=addr.get("city",""); state=addr.get("state","")
            indoor=bool(v.get("indoor",False)); neutral=bool(comp.get("neutralSite",False))
            lat=lon=elev=None
            loc=v.get("location",{})
            if loc:
                lat=loc.get("latitude") or loc.get("lat")
                lon=loc.get("longitude") or loc.get("lon") or loc.get("lng")
            if (lat is None or lon is None) and (vname or city):
                for _gq in ([f"{vname} {city} {state}"] if vname else []) + ([f"{city} {state} USA"] if city else []):
                    try:
                        _gq2=_gq.strip().replace(" ","+")
                        _req=__import__("urllib.request",fromlist=["Request"]).Request(
                            f"https://nominatim.openstreetmap.org/search?q={_gq2}&format=json&limit=1",
                            headers={"User-Agent":"AirDensityApp/1.0"})
                        with _ur.urlopen(_req, timeout=7) as _gr:
                            _rs=(_j.loads(_gr.read()) or [{}])[0]
                        if _rs.get("lat") and _rs.get("lon"):
                            lat=float(_rs["lat"]); lon=float(_rs["lon"]); break
                    except Exception: pass
                if not (lat and lon) and city:
                    try:
                        _gq3=f"{city} {state} USA".replace(" ","+")
                        with _ur.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?name={_gq3}&count=1&format=json",timeout=6) as _gr2:
                            _rs2=(_j.loads(_gr2.read()).get("results") or [{}])[0]
                        lat=_rs2.get("latitude"); lon=_rs2.get("longitude")
                        if _rs2.get("elevation"): elev=_rs2["elevation"]*3.28084
                    except Exception: pass
            if elev is None and lat and lon:
                try:
                    with _ur.urlopen(f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}",timeout=6) as er:
                        em=(_j.loads(er.read()).get("results") or [{}])[0].get("elevation")
                    if em is not None: elev=em*3.28084
                except Exception: pass
            gctx=""; gemoji=""; series_sum=""
            for note in comp.get("notes",[]):
                nh=note.get("headline","").strip()
                if nh: gctx=nh; gemoji=_ctx_emoji(nh); break
            stype=event.get("season",{}).get("type",2)
            if not gctx and stype==3: gctx="POSTSEASON"; gemoji="Ã°Å¸Â¥Å "
            sr=comp.get("series",{})
            if sr: series_sum=sr.get("summary","") or sr.get("title","")
            result={"venue_name":vname,"city":city,"state":state,
                    "lat":float(lat) if lat is not None else None,
                    "lon":float(lon) if lon is not None else None,
                    "indoor":indoor,"elevation":float(elev) if elev is not None else None,
                    "neutral_site":neutral,"game_context":gctx,"ctx_emoji":gemoji,
                    "series_summary":series_sum,"season_type":stype,"source":"ESPN"}
            _espn_venue_cache[key]=result
            log(f"ESPN venue: {vname}, {city} {state}{' [NEUTRAL]' if neutral else ''}{' | '+gctx if gctx else ''}","info")
            return result
    except Exception as ex:
        log(f"ESPN venue lookup failed ({away_team}@{home_team}): {ex}","warning")
    _espn_venue_cache[key]=None; return None

_weather_fallback      = None   # No fallback â€” missing weather = no physics analysis
_weather_used_fallback = False
_weather_source_label  = "âœ” Live (current)"
_weather_key_missing_logged = False
_weather_auth_block_until = 0.0
_weather_auth_error_logged = False
_weather_auth_block_seconds = 900
_weather_cache_lock = threading.Lock()
_weather_state_lock = threading.Lock()
_weather_current_cache = {}
_weather_forecast_cache = {}
_weather_current_ttl_sec = 180
_weather_forecast_ttl_sec = 900
_weather_key_refresh_interval_sec = 15
_weather_last_key_refresh_ts = 0.0


def _wx_cache_key(lat, lon):
    try:
        return (round(float(lat), 4), round(float(lon), 4))
    except Exception:
        return (str(lat), str(lon))


def _wx_cache_get(store: dict, key, ttl_sec: int):
    now_ts = time.time()
    with _weather_cache_lock:
        rec = store.get(key)
        if not rec:
            return False, None
        age = now_ts - float(rec.get("ts", 0.0))
        if age > max(1, int(ttl_sec)):
            store.pop(key, None)
            return False, None
        return True, rec.get("value")


def _wx_cache_put(store: dict, key, value):
    with _weather_cache_lock:
        store[key] = {"ts": time.time(), "value": value}


def _refresh_openweather_api_key_runtime(force: bool = False) -> str:
    """Allow live key rotation without app restart."""
    global OPENWEATHER_API_KEY, _weather_last_key_refresh_ts
    global _weather_auth_block_until, _weather_auth_error_logged, _weather_key_missing_logged
    now_ts = time.time()
    old_key = ""
    new_key = ""
    with _weather_state_lock:
        if (not force) and (now_ts - float(_weather_last_key_refresh_ts) < float(_weather_key_refresh_interval_sec)):
            return str(OPENWEATHER_API_KEY or "").strip()
        _weather_last_key_refresh_ts = now_ts
        old_key = str(OPENWEATHER_API_KEY or "").strip()
        new_key = str(_load_openweather_api_key() or "").strip()
        if new_key == old_key:
            return new_key
        OPENWEATHER_API_KEY = new_key
        _weather_auth_block_until = 0.0
        _weather_auth_error_logged = False
        _weather_key_missing_logged = False
    with _weather_cache_lock:
        _weather_current_cache.clear()
        _weather_forecast_cache.clear()
    if new_key:
        log("OpenWeather key refreshed at runtime; weather auth backoff reset.", "info")
    else:
        log("OpenWeather key removed at runtime.", "warning")
    return new_key


def _openweather_is_auth_blocked() -> bool:
    global _weather_auth_error_logged
    now_ts = time.time()
    with _weather_state_lock:
        blocked = bool(_weather_auth_block_until and now_ts < _weather_auth_block_until)
        if blocked and not _weather_auth_error_logged:
            wait_sec = max(1, int(_weather_auth_block_until - now_ts))
            log(
                "OpenWeather calls suppressed after 401 Unauthorized. "
                f"Retrying automatically in ~{wait_sec}s; key updates are picked up without restart.",
                "warning",
            )
            _weather_auth_error_logged = True
        return blocked


def _mark_openweather_401(context_label: str) -> None:
    global _weather_auth_block_until, _weather_auth_error_logged
    with _weather_state_lock:
        _weather_auth_block_until = time.time() + float(_weather_auth_block_seconds)
        _weather_auth_error_logged = True
    log(
        f"{context_label} API rejected OPENWEATHER_API_KEY/OWM_API_KEY (401 Unauthorized). "
        f"Set a valid key in env var or file: {OPENWEATHER_KEY_FILE}",
        "error",
    )


def _clear_openweather_auth_backoff() -> None:
    global _weather_auth_block_until, _weather_auth_error_logged
    with _weather_state_lock:
        _weather_auth_block_until = 0.0
        _weather_auth_error_logged = False

def get_weather(lat, lon):
    global _weather_used_fallback, _weather_source_label, _weather_key_missing_logged
    _weather_used_fallback = False
    _weather_source_label = "[OK] Live (current)"
    _refresh_openweather_api_key_runtime()
    if not OPENWEATHER_API_KEY:
        if not _weather_key_missing_logged:
            log(
                f"No OpenWeather API key configured. Set OPENWEATHER_API_KEY (or OWM_API_KEY) "
                f"or create this file with your key: {OPENWEATHER_KEY_FILE}",
                "warning",
            )
            _weather_key_missing_logged = True
        _weather_source_label = "[WARN] Weather unavailable (no API key)"
        return None
    if _openweather_is_auth_blocked():
        _weather_source_label = "[WARN] Weather unavailable (invalid OWM key)"
        return None
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (ValueError, TypeError):
        log(f"Invalid lat/lon - cannot fetch weather.", "error")
        _weather_source_label = "[WARN] Weather unavailable"
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        log("Invalid lat/lon (non-finite) - cannot fetch weather.", "error")
        _weather_source_label = "[WARN] Weather unavailable"
        return None
    _ckey = _wx_cache_key(lat_f, lon_f)
    _cached_ok, _cached_val = _wx_cache_get(_weather_current_cache, _ckey, _weather_current_ttl_sec)
    if _cached_ok and isinstance(_cached_val, dict):
        _weather_source_label = "[OK] Cached (recent current)"
        return dict(_cached_val)
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat_f,
        "lon": lon_f,
        "appid": OPENWEATHER_API_KEY,
        "units": "imperial",
    }
    try:
        t0  = datetime.now()
        r   = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        d   = r.json()
        ms  = int((datetime.now() - t0).total_seconds() * 1000)
        main = d.get("main", {})
        wind = d.get("wind", {})
        if not main:
            _weather_source_label = "[WARN] Weather unavailable"
            return None
        _t  = main.get("temp")
        _h  = main.get("humidity")
        _p  = main.get("pressure")
        _ws = wind.get("speed") if wind else None
        _wd = wind.get("deg")   if wind else None
        # If any critical field is missing, weather is unusable
        if _t is None or _h is None or _p is None:
            log("Weather API returned incomplete data (missing temp/humidity/pressure) - analysis suppressed.", "warning")
            return None
        result = {
            "temp":       float(_t),
            "humidity":   float(_h),
            "pressure":   float(_p) * 0.02953,
            "wind_speed": float(_ws) if _ws is not None else None,
            "wind_dir":   float(_wd) if _wd is not None else None,
        }
        _clear_openweather_auth_backoff()
        _wx_cache_put(_weather_current_cache, _ckey, result)
        log(f"Weather OK ({ms}ms)", "debug")
        return result
    except requests.HTTPError as e:
        _code = None
        try:
            _code = e.response.status_code
        except Exception:
            _code = None
        if _code == 401:
            _weather_source_label = "[WARN] Weather unavailable (OWM 401 Unauthorized)"
            _mark_openweather_401("Weather")
            return None
        log(f"Weather API HTTP error: {e}", "error")
    except Exception as e:
        log(f"Weather API error: {e}", "error")
    _weather_source_label = "[WARN] Weather unavailable"
    return None


# =========================
# GAME-TIME WEATHER FORECAST
# =========================
def _parse_game_time(game_time_str):
    """Parse strings like '4/5 1:35PM', '04/05 13:35', 'Apr 5 1:35PM' into datetime.
    Always injects the current year into the format string to avoid the Python 3.14+
    DeprecationWarning about year-less date parsing."""
    if not game_time_str or str(game_time_str).strip() in ["", "nan", "None"]:
        return None
    s = str(game_time_str).strip()
    yr  = datetime.now().year
    ys  = str(yr)                  # e.g. "2026"

    # Each entry: (format_string, string_to_parse)
    # Year-less formats: prepend the year so strptime never guesses
    candidates = [
        ("%Y-%m-%d %H:%M",    s),                  # already has year
        ("%Y %m/%d %I:%M%p",  ys + " " + s),
        ("%Y %m/%d %I:%M %p", ys + " " + s),
        ("%Y %m/%d %H:%M",    ys + " " + s),
        ("%Y %b %d %I:%M%p",  ys + " " + s),
        ("%Y %b %d %I:%M %p", ys + " " + s),
        ("%Y %B %d %I:%M%p",  ys + " " + s),
        ("%Y %B %d %I:%M %p", ys + " " + s),
    ]
    for fmt, target in candidates:
        try:
            return datetime.strptime(target, fmt)
        except ValueError:
            continue
    return None


def _venue_zoneinfo_from_lon(lon):
    """Best-effort venue timezone from longitude for US sports venues."""
    try:
        tz_label, _ = _lon_to_tz(lon)
    except Exception:
        tz_label = "ET"
    tz_name = {
        "ET": "America/New_York",
        "CT": "America/Chicago",
        "MT": "America/Denver",
        "PT": "America/Los_Angeles",
    }.get(tz_label, "America/New_York")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/New_York")


def get_weather_at_gametime(lat, lon, game_time_str):
    """Fetch the OWM 3-hour forecast closest to game time.
    Falls back to current-conditions get_weather() if game time cannot be parsed
    or if the game is already in progress / past.
    Sets globals _weather_used_fallback and _weather_source_label."""
    global _weather_used_fallback, _weather_source_label, _weather_key_missing_logged
    _weather_used_fallback = False
    _refresh_openweather_api_key_runtime()
    if not OPENWEATHER_API_KEY:
        if not _weather_key_missing_logged:
            log(
                f"No OpenWeather API key configured. Set OPENWEATHER_API_KEY (or OWM_API_KEY) "
                f"or create this file with your key: {OPENWEATHER_KEY_FILE}",
                "warning",
            )
            _weather_key_missing_logged = True
        _weather_source_label = "[WARN] Weather unavailable (no API key)"
        return None
    if _openweather_is_auth_blocked():
        _weather_source_label = "[WARN] Weather unavailable (invalid OWM key)"
        return None

    try:
        lat_f, lon_f = float(lat), float(lon)
    except (ValueError, TypeError):
        log("Invalid lat/lon for forecast fetch.", "error")
        _weather_source_label = "[WARN] Weather unavailable"
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        log("Invalid lat/lon (non-finite) for forecast fetch.", "error")
        _weather_source_label = "[WARN] Weather unavailable"
        return None

    game_dt = _parse_game_time(game_time_str)
    if game_dt is None:
        _weather_source_label = "[OK] Live (current - game time unparseable)"
        return get_weather(lat, lon)

    venue_tz = _venue_zoneinfo_from_lon(lon_f)
    if game_dt.tzinfo is None:
        game_dt_local = game_dt.replace(tzinfo=venue_tz)
    else:
        game_dt_local = game_dt.astimezone(venue_tz)
    game_dt_utc = game_dt_local.astimezone(timezone.utc)

    _fkey = (_wx_cache_key(lat_f, lon_f), str(game_time_str or "").strip().lower())
    _cached_ok, _cached_val = _wx_cache_get(_weather_forecast_cache, _fkey, _weather_forecast_ttl_sec)
    if _cached_ok and isinstance(_cached_val, dict):
        _weather_source_label = "[OK] Cached (recent forecast)"
        return dict(_cached_val)

    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "lat": lat_f,
        "lon": lon_f,
        "appid": OPENWEATHER_API_KEY,
        "units": "imperial",
        "cnt": 40,
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        forecasts = r.json().get("list", [])
        if not forecasts:
            raise ValueError("Empty forecast list")

        best = min(forecasts, key=lambda f: abs(f["dt"] - game_dt_utc.timestamp()))
        forecast_dt_utc   = datetime.fromtimestamp(best["dt"], tz=timezone.utc)
        forecast_dt_local = forecast_dt_utc.astimezone(venue_tz)
        delta_hrs         = abs((forecast_dt_utc - game_dt_utc).total_seconds()) / 3600
        main         = best.get("main", {})
        wind         = best.get("wind", {})

        _t  = main.get("temp")
        _h  = main.get("humidity")
        _p  = main.get("pressure")
        _ws = wind.get("speed") if wind else None
        _wd = wind.get("deg")   if wind else None
        if _t is None or _h is None or _p is None:
            log("Forecast API returned incomplete data - analysis suppressed.", "warning")
            return None
        result = {
            "temp":       float(_t),
            "humidity":   float(_h),
            "pressure":   float(_p) * 0.02953,
            "wind_speed": float(_ws) if _ws is not None else None,
            "wind_dir":   float(_wd) if _wd is not None else None,
        }
        _clear_openweather_auth_backoff()
        _wx_cache_put(_weather_forecast_cache, _fkey, result)
        _weather_source_label = (
            f"[OK] Forecast  {forecast_dt_local.strftime('%m/%d %I:%M %p %Z')}  "
            f"(+/-{delta_hrs:.0f}h of gametime)"
        )
        log(f"Gametime forecast fetched - {_weather_source_label}", "info")
        return result

    except Exception as e:
        _code = None
        try:
            _code = e.response.status_code if hasattr(e, "response") and e.response is not None else None
        except Exception:
            _code = None
        if _code == 401:
            _weather_source_label = "[WARN] Forecast unavailable (OWM 401 Unauthorized)"
            _mark_openweather_401("Forecast")
            return None
        log(f"Forecast API error: {e} - falling back to current conditions.", "warning")
        _weather_source_label = "[WARN] Forecast failed - Live (current)"
        return get_weather(lat, lon)


# =========================
# PHYSICS
# =========================
def air_density(temp_f, pressure_inhg, humidity):
    temp_c      = (temp_f - 32) * 5.0 / 9.0
    temp_k      = temp_c + 273.15
    pressure_pa = pressure_inhg * 3386.39
    es  = 6.1078 * 10 ** ((7.5 * temp_c) / (237.3 + temp_c))
    e   = (humidity / 100.0) * es * 100.0
    Rd, Rv = 287.05, 461.5
    rho = ((pressure_pa - e) / (Rd * temp_k)) + (e / (Rv * temp_k))
    return rho * 0.062428

def density_altitude(temp_f, elevation_ft, pressure_inhg=None, humidity=None):
    """
    Compute density altitude from actual air density when pressure/humidity exist.
    Falls back to a temperature-elevation approximation only when full weather
    inputs are unavailable.
    """
    elevation_ft = safe_float(elevation_ft, 0.0, "elevation_ft")
    temp_f = safe_float(temp_f, 59.0, "temp_f")
    p = safe_float(pressure_inhg, None, "pressure_inhg")
    h = safe_float(humidity, None, "humidity")
    if p is not None and h is not None:
        try:
            # Convert measured density to equivalent standard-atmosphere altitude.
            rho_meas = air_density(temp_f, p, h) / 0.0624279606  # lb/ft^3 -> kg/m^3
            if rho_meas > 0:
                T0 = 288.15
                L = 0.0065
                g = 9.80665
                M = 0.0289644
                R = 8.3144598
                rho0 = 1.225
                expn = 1.0 / ((g * M) / (R * L) - 1.0)
                ratio = max(1e-6, min(2.0, rho_meas / rho0))
                h_m = (T0 / L) * (1.0 - (ratio ** expn))
                return h_m * 3.280839895
        except Exception:
            pass
    standard_temp = 59.0 - 0.00356 * elevation_ft
    return elevation_ft + (120.0 * (temp_f - standard_temp))

def wind_components(speed, direction, orientation_deg):
    speed           = safe_float(speed,           0.0, "wind_speed")
    direction       = safe_float(direction,        0.0, "wind_dir")
    orientation_deg = safe_float(orientation_deg, 0.0, "orientation_deg")
    # OWM direction is where wind comes FROM; convert to the travel vector.
    theta = math.radians((direction - orientation_deg + 180.0) % 360.0)
    return round(speed * math.cos(theta), 2), round(speed * math.sin(theta), 2)

# =========================
# MATCHUPS â€” RAW FALLBACK DF
# =========================
def _build_display_df_from_raw(raw_data: dict, sport_key: str) -> pd.DataFrame:
    def _first_val(game, team_idx, field):
        try:
            books = game["teams"][team_idx].get("books", [])
            return next((b[field] for b in books if field in b), "")
        except (IndexError, KeyError):
            return ""

    def _norm(name):
        s = re.sub(r"\s+", " ", str(name or "").strip().lower())
        return re.sub(r"[^\w\s]", "", s).strip()

    spread_map    = {}
    total_map     = {}
    moneyline_map = {}

    for g in raw_data.get("spread", []):
        if len(g.get("teams", [])) < 2:
            continue
        ar = _strip_pitcher(g["teams"][0].get("name", ""))
        hr = _strip_pitcher(g["teams"][1].get("name", ""))
        k  = (_norm(ar), _norm(hr))
        spread_map[k] = {"Time": g.get("time",""), "Away_Team": ar, "Home_Team": hr,
                         "Away_Spread": _first_val(g, 0, "value"),
                         "Home_Spread": _first_val(g, 1, "value")}

    for g in raw_data.get("total", []):
        if len(g.get("teams", [])) < 2:
            continue
        ar = _strip_pitcher(g["teams"][0].get("name", ""))
        hr = _strip_pitcher(g["teams"][1].get("name", ""))
        k  = (_norm(ar), _norm(hr))
        total_map[k] = {"Total": _first_val(g, 0, "value")}

    for g in raw_data.get("moneyline", []):
        if len(g.get("teams", [])) < 2:
            continue
        ar = _strip_pitcher(g["teams"][0].get("name", ""))
        hr = _strip_pitcher(g["teams"][1].get("name", ""))
        k  = (_norm(ar), _norm(hr))
        moneyline_map[k] = {"Away_ML": _first_val(g, 0, "moneyline"),
                             "Home_ML": _first_val(g, 1, "moneyline")}

    all_keys = set(spread_map) | set(total_map) | set(moneyline_map)
    rows = []
    for k in all_keys:
        sp  = spread_map.get(k, {})
        tot = total_map.get(k, {})
        ml  = moneyline_map.get(k, {})
        ref = sp or tot or ml
        rows.append({
            "Time": ref.get("Time",""), "Away_Team": ref.get("Away_Team", k[0]),
            "Home_Team": ref.get("Home_Team", k[1]),
            "Away_Spread": sp.get("Away_Spread",""), "Home_Spread": sp.get("Home_Spread",""),
            "Total": tot.get("Total",""),
            "Away_ML": ml.get("Away_ML",""), "Home_ML": ml.get("Home_ML",""),
            "match_method": "resolver_bypassed",
        })

    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values("Time").reset_index(drop=True)
    log(f"Fallback display df built â€” {len(result)} games, resolver bypassed.", "info")
    return result

# =========================
# 4-TIER FUZZY TEAM MATCHER
# =========================
def _find_team_fuzzy(raw_name: str, preferred_league=None):
    if not raw_name or not raw_name.strip():
        return None, None
    name = _strip_pitcher(raw_name.strip())
    def _search(frame):
        if frame.empty:
            return None, None
        r = get_row(name, preferred_league=preferred_league)
        if r is not None and frame is not None and _same_league_tag(safe(r, "league"), preferred_league):
            return name, str(safe(r, "league"))

        mask = frame["team"].str.lower() == name.lower()
        if mask.any():
            return str(frame.loc[mask, "team"].iloc[0]), str(frame.loc[mask, "league"].iloc[0])

        mask = frame["team"].str.lower().str.contains(re.escape(name.lower()), regex=True, na=False)
        if mask.sum() == 1:
            return str(frame.loc[mask, "team"].iloc[0]), str(frame.loc[mask, "league"].iloc[0])
        if mask.sum() > 1:
            cands = frame.loc[mask].copy()
            cands["_l"] = cands["team"].str.len()
            best = cands.nsmallest(1, "_l").iloc[0]
            return str(best["team"]), str(best["league"])

        for _, row in frame.iterrows():
            vname = str(row["team"]).lower()
            if vname and vname in name.lower():
                return str(row["team"]), str(row["league"])
        return None, None

    scoped_df = df[df["league"].apply(lambda lg: _same_league_tag(lg, preferred_league))] if preferred_league else df
    team, league = _search(scoped_df)
    if team or not preferred_league:
        return team, league
    return _search(df)


def _detail_heavy_cache_key(sport, away_clean, home_clean, game_time):
    return (
        datetime.now().strftime("%Y%m%d"),
        str(sport or "").upper().strip(),
        str(away_clean or "").strip().lower(),
        str(home_clean or "").strip().lower(),
        str(game_time or "").strip(),
    )


def _detail_heavy_cache_get(cache_key):
    with _DETAIL_HEAVY_CACHE_LOCK:
        entry = _DETAIL_HEAVY_CACHE.get(cache_key)
        if not isinstance(entry, dict):
            return None
        return dict(entry)


def _detail_heavy_cache_put(cache_key, payload):
    if not isinstance(payload, dict):
        return
    with _DETAIL_HEAVY_CACHE_LOCK:
        _DETAIL_HEAVY_CACHE[cache_key] = dict(payload)
        if len(_DETAIL_HEAVY_CACHE) > _DETAIL_HEAVY_CACHE_MAX:
            _oldest = next(iter(_DETAIL_HEAVY_CACHE.keys()))
            if _oldest != cache_key:
                _DETAIL_HEAVY_CACHE.pop(_oldest, None)


def _build_heavy_detail_context(
    sport,
    game_time,
    away_clean,
    home_clean,
    away_row,
    home_row,
):
    _ctx = {}
    _sport_up = str(sport or "").upper().strip()

    if _sport_up == "MLB":
        try:
            _ctx["mlb_db"] = _mlb_db_lookup(home_clean, away_clean)
        except Exception as _e_mlb:
            log(f"[detail] mlb_db preload failed: {_e_mlb}", "warning")
            _ctx["mlb_db"] = None

    try:
        _ctx["inj_data"] = _inj_news_lookup(_sport_up, away_clean, home_clean)
    except Exception as _e_inj:
        log(f"[detail] injury/news preload failed: {_e_inj}", "warning")
        _ctx["inj_data"] = None

    try:
        _gd_match = re.search(r"(\d{1,2})/(\d{1,2})", str(game_time))
        if _gd_match:
            _gdate = f"{datetime.now().year}-{int(_gd_match.group(1)):02d}-{int(_gd_match.group(2)):02d}"
        else:
            _gdate = str(datetime.now().date())
    except Exception:
        _gdate = str(datetime.now().date())

    try:
        _ctx["circ"] = _circ_analysis(
            game_time,
            home_row,
            away_row,
            _sport_up,
            away_team=away_clean,
            home_team=home_clean,
            game_date=_gdate,
        )
    except Exception as _e_circ:
        log(f"[detail] circadian preload failed: {_e_circ}", "warning")
        _ctx["circ"] = {"available": False, "reason": f"circadian preload failed: {_e_circ}"}

    _ctx["rr"] = None
    if _REF_ENGINE_OK and _rse_mod:
        try:
            from datetime import date as _date_ref2
            _ctx["rr"] = _rse_mod.get_ref_signal(_sport_up, away_clean, home_clean, _date_ref2.today())
        except Exception as _e_ref:
            log(f"[detail] officials preload failed: {_e_ref}", "warning")

    _ctx["loaded_at"] = datetime.now().astimezone().isoformat()
    return _ctx


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MATCHUP DETAIL POPUP  â† NEW IN v8
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_DETAIL_TEXT_WIDGETS = []

def _detail_palette():
    return {
        "bg": _UI.get("bg_surface", "#ffffff"),
        "fg": _UI.get("text_primary", "#132235"),
        "header": _UI.get("text_primary", "#132235"),
        "section": _UI.get("accent", "#274f7f"),
        "label": _UI.get("text_muted", "#6a7b8f"),
        "value": _UI.get("text_primary", "#132235"),
        "good": _UI.get("success", "#1f6a45"),
        "warn": _UI.get("danger", "#8f2d2d"),
        "sep": _UI.get("border", "#cfd7e2"),
        "na": _UI.get("text_muted", "#6a7b8f"),
        "odds_pos": _UI.get("success", "#1f6a45"),
        "odds_neg": _UI.get("danger", "#8f2d2d"),
        "odds_ev": _UI.get("text_muted", "#6a7b8f"),
    }

def _style_detail_text_widget(txt_widget):
    _p = _detail_palette()
    try:
        txt_widget.configure(
            bg=_p["bg"],
            fg=_p["fg"],
            insertbackground=_p["fg"],
            relief="flat",
            padx=12,
            pady=10,
        )
    except Exception:
        pass
    txt_widget.tag_config("header",   foreground=_p["header"], font=("Consolas", 12, "bold"))
    txt_widget.tag_config("section",  foreground=_p["section"], font=("Consolas", 10, "bold"))
    txt_widget.tag_config("label",    foreground=_p["label"])
    txt_widget.tag_config("value",    foreground=_p["value"])
    txt_widget.tag_config("good",     foreground=_p["good"])
    txt_widget.tag_config("warn",     foreground=_p["warn"])
    txt_widget.tag_config("sep",      foreground=_p["sep"])
    txt_widget.tag_config("na",       foreground=_p["na"])
    txt_widget.tag_config("odds_pos", foreground=_p["odds_pos"])
    txt_widget.tag_config("odds_neg", foreground=_p["odds_neg"])
    txt_widget.tag_config("odds_ev",  foreground=_p["odds_ev"])

def _open_matchup_detail(row_vals, sport="MLB", status_callback=None):
    """
    Opens a full Matchup Detail popup for the selected game row.
    row_vals = (time, away_team, home_team, away_spread, home_spread,
                total, away_ml, home_ml)
    """
    game_time   = row_vals[0]
    away_raw    = row_vals[1]
    home_raw    = row_vals[2]
    away_spread = row_vals[3]
    home_spread = row_vals[4]
    total       = row_vals[5]
    away_ml     = row_vals[6]
    home_ml     = row_vals[7]

    away_clean  = _strip_pitcher(str(away_raw))
    home_clean  = _strip_pitcher(str(home_raw))

    # Look up both teams in venue db
    away_team_db, away_league = _find_team_fuzzy(away_clean, preferred_league=sport)
    home_team_db, home_league = _find_team_fuzzy(home_clean, preferred_league=sport)

    away_row = get_row(away_team_db, preferred_league=sport) if away_team_db else None
    home_row = get_row(home_team_db, preferred_league=sport) if home_team_db else None

    # â”€â”€ Build window â”€â”€
    win = tk.Toplevel(root)
    win.title(f"Matchup Intelligence | {away_clean} at {home_clean} | {game_time}")
    win.minsize(680, 680)
    win.resizable(True, True)
    try:
        win.configure(bg=_UI.get("bg_app", "#f3f5f8"))
    except Exception:
        pass
    detail_status_var = tk.StringVar(value="")

    btn_frame = ttk.Frame(win, style="Card.TFrame")
    btn_frame.pack(fill=tk.X, padx=8, pady=(8, 0))

    def _load_home():
        if home_team_db:
            win.destroy()
            _send_team_to_physics(home_team_db, preferred_league=sport)
        else:
            detail_status_var.set(f"'{home_clean}' not found in venue db.")

    def _load_away():
        if away_team_db:
            win.destroy()
            _send_team_to_physics(away_team_db, preferred_league=sport)
        else:
            detail_status_var.set(f"'{away_clean}' not found in venue db.")

    ttk.Button(btn_frame, text=f"Analyze HOME ({home_clean})",
               command=_load_home).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_frame, text=f"Analyze AWAY ({away_clean})",
               command=_load_away).pack(side=tk.LEFT)

    refresh_btn = ttk.Button(btn_frame, text="Refresh Weather")
    refresh_btn.pack(side=tk.RIGHT)

    _deep_btn = ttk.Button(
        btn_frame,
        text="Reload Full Detail",
    )
    _deep_btn.pack(side=tk.RIGHT, padx=(0, 6))
    ttk.Label(win, textvariable=detail_status_var, style="Subtle.TLabel").pack(
        fill=tk.X, padx=8, pady=(4, 0)
    )


    txt_frame = ttk.Frame(win, style="Card.TFrame")
    txt_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    sc  = ttk.Scrollbar(txt_frame, orient=tk.VERTICAL)
    txt = tk.Text(
        txt_frame,
        font=("Consolas", 10),
        wrap=tk.WORD,
        yscrollcommand=sc.set,
        state=tk.NORMAL,
        bg=_UI.get("bg_surface", "#ffffff"),
        fg=_UI.get("text_primary", "#132235"),
        insertbackground=_UI.get("text_primary", "#132235"),
        relief="flat",
        padx=12,
        pady=10,
    )
    _install_text_sanitizer(txt)
    sc.config(command=txt.yview)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sc.pack(side=tk.RIGHT, fill=tk.Y)
    _style_detail_text_widget(txt)
    try:
        _DETAIL_TEXT_WIDGETS.append(txt)
        win.bind(
            "<Destroy>",
            lambda _e, _t=txt: (_DETAIL_TEXT_WIDGETS.remove(_t) if _t in _DETAIL_TEXT_WIDGETS else None),
            add="+",
        )
    except Exception:
        pass
    _status_cb = status_callback if callable(status_callback) else (lambda _m: detail_status_var.set(str(_m)))
    _detail_state = {
        "weather": None,
        "espn_venue": None,
        "heavy_ctx": None,
        "deep_loading": False,
        "deep_loaded": False,
    }
    _cache_key = _detail_heavy_cache_key(sport, away_clean, home_clean, game_time)
    _cached_ctx = _detail_heavy_cache_get(_cache_key)
    if _cached_ctx:
        _detail_state["heavy_ctx"] = _cached_ctx
        _detail_state["deep_loaded"] = True

    # â”€â”€ Stats & SOS fetch button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if STATS_SOS_AVAILABLE:
        _add_stats_fetch_button(
            btn_frame, win, txt, sport,
            away_clean, home_clean,
            status_callback=_status_cb,
        )

    def _render_from_state(render_heavy=False):
        _ctx = _detail_state.get("heavy_ctx") if render_heavy else None
        _render_detail(
            txt, home_row, away_row, away_clean, home_clean,
            game_time, away_spread, home_spread, total,
            away_ml, home_ml, away_team_db, home_team_db,
            weather=_detail_state.get("weather"), sport=sport,
            espn_venue=_detail_state.get("espn_venue"),
            render_heavy=bool(render_heavy),
            heavy_ctx=_ctx,
        )

    def _auto_load_deep(force_refresh=False):
        if _detail_state.get("deep_loading"):
            detail_status_var.set("Full detail already loading...")
            return
        if _detail_state.get("deep_loaded") and not force_refresh:
            try:
                if win.winfo_exists():
                    _render_from_state(render_heavy=True)
                    detail_status_var.set("Full detail loaded.")
            except Exception:
                pass
            return

        _detail_state["deep_loading"] = True
        detail_status_var.set("Auto-loading full detail (injury/news + lineup + context)...")

        def _worker():
            try:
                _ctx = _build_heavy_detail_context(
                    sport=sport,
                    game_time=game_time,
                    away_clean=away_clean,
                    home_clean=home_clean,
                    away_row=away_row,
                    home_row=home_row,
                )
                _detail_heavy_cache_put(_cache_key, _ctx)

                def _apply():
                    try:
                        if win.winfo_exists():
                            _detail_state["heavy_ctx"] = _ctx
                            _detail_state["deep_loaded"] = True
                            _render_from_state(render_heavy=True)
                            detail_status_var.set("Full detail loaded.")
                    except Exception:
                        pass
                    finally:
                        _detail_state["deep_loading"] = False

                root.after(0, _apply)
            except Exception as _e_deep:
                log(f"[detail] deep preload failed: {_e_deep}", "warning")

                def _deep_err():
                    _detail_state["deep_loading"] = False
                    detail_status_var.set(f"Deep detail load failed: {_e_deep}")

                root.after(0, _deep_err)

        threading.Thread(target=_worker, daemon=True).start()

    _deep_btn.configure(command=lambda: _auto_load_deep(force_refresh=True))

    # Initial render â€” defer one tick so popup paints before heavy text assembly.
    detail_status_var.set("Rendering quick view...")

    def _render_initial():
        try:
            if win.winfo_exists():
                _render_from_state(render_heavy=False)
                detail_status_var.set("Quick view ready. Weather/context loading...")
        except Exception:
            pass

    try:
        win.after(10, _render_initial)
    except Exception:
        _render_initial()

    # Fetch ESPN venue + weather in background together â€” one re-render when both ready
    def _safe_render_update(_wx_val, _ev_val):
        try:
            if win.winfo_exists():
                _detail_state["weather"] = _wx_val
                _detail_state["espn_venue"] = _ev_val
                _render_from_state(render_heavy=bool(_detail_state.get("deep_loaded")))
                if _detail_state.get("deep_loaded"):
                    detail_status_var.set("Live weather/context loaded (full detail active).")
                else:
                    detail_status_var.set("Live weather/context loaded. Full detail auto-loading...")
        except Exception:
            pass

    refresh_btn.configure(
        command=lambda: _refresh_detail(
            txt, home_row, away_row, away_clean, home_clean,
            game_time, away_spread, home_spread, total,
            away_ml, home_ml, away_team_db, home_team_db,
            sport=sport,
            render_heavy=bool(_detail_state.get("deep_loaded")),
            heavy_ctx=_detail_state.get("heavy_ctx"),
            status_var=detail_status_var,
        )
    )

    def _fetch_and_update():
        # 1. Resolve ESPN venue (authoritative lat/lon/indoor/context)
        _ev = None
        try:
            from datetime import datetime as _dt2
            _gd=game_time.split()[0]; _gm,_gday=_gd.split("/")
            _gds=f"{_dt2.now().year}-{int(_gm):02d}-{int(_gday):02d}"
        except Exception:
            from datetime import datetime as _dt2; _gds=_dt2.now().strftime("%Y-%m-%d")
        try: _ev=_resolve_game_venue(sport,away_clean,home_clean,_gds)
        except Exception: pass
        # 2. Use ESPN lat/lon when available (correct for neutral-site games)
        wx = None
        _lat = (_ev["lat"] if _ev and _ev.get("lat") is not None
                else (safe(home_row,"lat") if home_row is not None else ""))
        _lon = (_ev["lon"] if _ev and _ev.get("lon") is not None
                else (safe(home_row,"lon") if home_row is not None else ""))
        if _lat not in ("",None) and _lon not in ("",None):
            wx = get_weather_at_gametime(_lat, _lon, game_time)
        try:
            root.after(0, lambda: _safe_render_update(wx, _ev))
        except Exception:
            pass

    threading.Thread(target=_fetch_and_update, daemon=True).start()
    win.after(60, lambda: _auto_load_deep(force_refresh=False))


def _refresh_detail(txt, home_row, away_row, away_clean, home_clean,
                    game_time, away_spread, home_spread, total,
                    away_ml, home_ml, away_team_db, home_team_db, sport="MLB",
                    render_heavy=False, heavy_ctx=None, status_var=None):
    _render_detail(txt, home_row, away_row, away_clean, home_clean,
                   game_time, away_spread, home_spread, total,
                   away_ml, home_ml, away_team_db, home_team_db,
                   weather=None, sport=sport, espn_venue=None,
                   render_heavy=bool(render_heavy), heavy_ctx=heavy_ctx)
    if status_var is not None:
        try:
            status_var.set("Refreshing weather/context...")
        except Exception:
            pass

    def _fetch():
        _ev = None
        try:
            from datetime import datetime as _dt2
            _gd=game_time.split()[0]; _gm,_gday=_gd.split("/")
            _gds=f"{_dt2.now().year}-{int(_gm):02d}-{int(_gday):02d}"
        except Exception:
            from datetime import datetime as _dt2; _gds=_dt2.now().strftime("%Y-%m-%d")
        try: _ev=_resolve_game_venue(sport,away_clean,home_clean,_gds)
        except Exception: pass
        wx = None
        _lat=(_ev["lat"] if _ev and _ev.get("lat") is not None else (safe(home_row,"lat") if home_row is not None else ""))
        _lon=(_ev["lon"] if _ev and _ev.get("lon") is not None else (safe(home_row,"lon") if home_row is not None else ""))
        if _lat not in ("",None) and _lon not in ("",None):
            wx = get_weather_at_gametime(_lat, _lon, game_time)
        def _render_refresh_if_alive():
            try:
                if txt.winfo_exists():
                    _render_detail(txt, home_row, away_row, away_clean, home_clean,
                                   game_time, away_spread, home_spread, total,
                                   away_ml, home_ml, away_team_db, home_team_db,
                                   weather=wx, sport=sport, espn_venue=_ev,
                                   render_heavy=bool(render_heavy), heavy_ctx=heavy_ctx)
                    if status_var is not None:
                        try:
                            if render_heavy:
                                status_var.set("Weather/context refreshed (full detail active).")
                            else:
                                status_var.set("Weather/context refreshed.")
                        except Exception:
                            pass
            except Exception:
                pass
        try:
            root.after(0, _render_refresh_if_alive)
        except Exception:
            pass

    threading.Thread(target=_fetch, daemon=True).start()


def _clean_display_text(text):
    s = str(text)
    try:
        if any(tok in s for tok in ("\u00e2", "\u00c3", "\u00f0", "\u00c2", "\u00d0\u00b2", "\u00ce", "\u00cf")):
            s_fixed = s.encode("latin1", "ignore").decode("utf-8", "ignore")
            if s_fixed:
                s = s_fixed
    except Exception:
        pass
    fixes = {
        "â”€": "-",
        "â•": "=",
        "â€“": "-",
        "â€”": "-",
        "â†’": "->",
        "â†": "<-",
        "âœ…": "[OK]",
        "âš ": "[WARN]",
        "â³": "[PENDING]",
        "âš™": "[RUN]",
        "âŒ": "[ERROR]",
        "â–¸": ">",
        "â–¶": "Run",
        "\u00c2\u00b0": " deg",
        "\u00c2\u00b1": "+/-",
        "Â±": "+/-",
        "ÃŽâ€Vert": "DeltaVert",
        "ÃŽâ€Horiz": "DeltaHoriz",
        "ÃŽâ€": "Delta",
        "TempÃŽâ€": "TempDelta",
        "PressÃŽâ€": "PressDelta",
        "ÃŽâ€v": "DeltaV",
        "Ï": "rho",
        "ÏÎ”": "rhoDelta",
        "Ï€": "pi",
        "lb/ftÂ³": "lb/ft^3",
        "Â°F": " F",
        "°F": " F",
        "Â°": " deg",
        "Â³": "^3",
        "Ã—": "x",
        "âˆ": "~",
        "â‰¥": ">=",
        "â‰¤": "<=",
        "ρ": "rho",
        "ΔVert": "DeltaVert",
        "ΔHoriz": "DeltaHoriz",
        "Δ": "Delta",
        "°": " deg",
        "→": "->",
        "←": "<-",
        "—": "-",
        "–": "-",
        "−": "-",
        "▸": ">",
        "▶": "Run",
        # Legacy mojibake fallbacks seen in historical logs.
        "\u00e2\u0161 ": "[WARN] ",
        "\u00e2\u0161\u00a0": "[WARN]",
        "\u00e2\u0153\u2026": "[OK]",
        "\u00e2\u008f\u00b3": "[PENDING]",
        "\u00e2\u0161\u2122": "[RUN]",
        "\u00e2\u009d\u0152": "[ERROR]",
        "\u00e2\u2020\u2019": "->",
        "\u00e2\u20ac\u201d": "-",
        "\u00e2\u2013\u00b6": "Run",
        "\u00c3\u201a\u00b0": " deg",
        "\u00c3\u017d\u00e2\u20ac\u009dVert": "DeltaVert",
        "\u00c3\u017d\u00e2\u20ac\u009dHoriz": "DeltaHoriz",
        "\u00c3\u017d\u00e2\u20ac\u009d": "Delta",
    }
    for bad, good in fixes.items():
        s = s.replace(bad, good)
    return s


def _install_text_sanitizer(widget):
    """Patch a Tk Text widget so every inserted string is display-sanitized."""
    try:
        _raw_insert = widget.insert
        def _insert(index, chars, *args):
            try:
                _clean = _clean_display_text(chars)
            except Exception:
                _clean = str(chars)
            return _raw_insert(index, _clean, *args)
        widget.insert = _insert
    except Exception:
        pass
    return widget


def _w(txt, text, tag="value"):
    txt.insert(tk.END, _clean_display_text(text), tag)

def _sep(txt, char="-", width=58):
    c = _clean_display_text(char)
    if not c:
        c = "-"
    txt.insert(tk.END, c[0] * width + "\n", "sep")

def _fmt_odds(val):
    s = str(val).strip()
    if not s or s in ["nan", "NaN", "None", ""]:
        return ("N/A", "na")
    if s.lower() == "even":
        return ("EVEN", "odds_ev")
    try:
        n = float(s)
        return (s, "odds_pos" if n >= 0 else "odds_neg")
    except ValueError:
        return (s, "value")

def _render_detail(txt, home_row, away_row, away_clean, home_clean,
                   game_time, away_spread, home_spread, total,
                   away_ml, home_ml, away_team_db, home_team_db,
                   weather, sport="MLB", espn_venue=None, render_heavy=False, heavy_ctx=None):
    txt.config(state=tk.NORMAL)
    txt.delete(1.0, tk.END)

    # ESPN venue passed in from caller (resolved in background thread with weather)
    _espn_v = espn_venue


    cross = 0.0  # safe default â€” overwritten by physics block when weather available
    W = 58
    h_surface = "N/A"
    h_detail = ""
    h_lat = ""
    h_lon = ""

    # â”€â”€ HEADER â”€â”€
    _sep(txt, "â•", W)
    header = f"  {away_clean}  @  {home_clean}"
    _w(txt, header + "\n", "header")
    _w(txt, f"  Game Time: {game_time}\n", "label")
    _sep(txt, "â•", W)

    # â”€â”€ ODDS â”€â”€
    _w(txt, "\n  ODDS\n", "section")
    _sep(txt, "â”€", W)

    # Spread
    txt.insert(tk.END, f"  {'Spread':<14}", "label")
    asp, atag = _fmt_odds(away_spread)
    hsp, htag = _fmt_odds(home_spread)
    _w(txt, f"{away_clean:<22}", "label")
    _w(txt, f"{asp:<10}", atag)
    _w(txt, f"  {home_clean:<22}", "label")
    _w(txt, f"{hsp}\n", htag)

    # Total
    txt.insert(tk.END, f"  {'Total (O/U)':<14}", "label")
    tv, ttag = _fmt_odds(total)
    _w(txt, f"{tv}\n", ttag)

    # Moneyline
    txt.insert(tk.END, f"  {'Moneyline':<14}", "label")
    aml, amtag = _fmt_odds(away_ml)
    hml, hmtag = _fmt_odds(home_ml)
    _w(txt, f"{away_clean:<22}", "label")
    _w(txt, f"{aml:<10}", amtag)
    _w(txt, f"  {home_clean:<22}", "label")
    _w(txt, f"{hml}\n", hmtag)

    # â”€â”€ HOME VENUE â”€â”€
    # â”€â”€ Game Context Banner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _gctx  =(_espn_v or {}).get("game_context","")
    _gemoji=(_espn_v or {}).get("ctx_emoji","")
    _series=(_espn_v or {}).get("series_summary","")
    _neut  =(_espn_v or {}).get("neutral_site",False)
    _evn   =(_espn_v or {}).get("venue_name","")
    _ecity =(_espn_v or {}).get("city",""); _estat=(_espn_v or {}).get("state","")
    if _gctx or _neut:
        _sep(txt,"â˜…",W)
        _bl=f"  {_gemoji}  {_gctx.upper()}" if _gctx else "  âš¡  SPECIAL GAME"
        if _neut:  _bl+="  |  â˜… NEUTRAL SITE"
        if _evn:   _bl+=f"  â€”  {_evn}"
        if _ecity: _bl+=f", {_ecity}"
        if _estat: _bl+=f" {_estat}"
        _w(txt,_bl.strip()+"\n","section")
        if _series: _w(txt,f"  Series: {_series}\n","warn")
        _sep(txt,"â˜…",W)
        _w(txt,"\n","value")


    _neut_label = (_espn_v or {}).get("neutral_site", False)
    if _neut_label and (_espn_v or {}).get("venue_name"):
        _gvn = _espn_v["venue_name"]
        _gc  = _espn_v.get("city",""); _gs = _espn_v.get("state","")
        _gloc = f", {_gc} {_gs}".rstrip() if _gc else ""
        _w(txt, f"\n  GAME VENUE  â€”  {_gvn}{_gloc}\n", "section")
    else:
        _w(txt, f"\n  HOME VENUE  â€”  {home_clean}\n", "section")
    _sep(txt, "â”€", W)

    if home_row is not None:
        h_venue   = safe(home_row, "venue")        or "N/A"
        h_elev    = safe(home_row, "elevation")
        h_elev_f  = safe_float(h_elev, None, "home_elevation") if h_elev not in ("","N/A",None) else None
        h_surface = safe(home_row, "surface_type") or "N/A"
        h_detail  = safe(home_row, "surface_detail")
        h_roof    = safe(home_row, "roof_type")    or "N/A"
        h_orient  = safe(home_row, "orientation_deg")
        h_olabel  = safe(home_row, "orientation_label") or ""
        h_lat     = safe(home_row, "lat")
        h_lon     = safe(home_row, "lon")
        # ESPN actual venue â€” overrides h_* vars directly (key-name-independent)
        if _espn_v:
            if _espn_v.get("venue_name"):            h_venue  = _espn_v["venue_name"]
            if _espn_v.get("lat")  is not None:      h_lat    = _espn_v["lat"]
            if _espn_v.get("lon")  is not None:      h_lon    = _espn_v["lon"]
            if _espn_v.get("elevation") is not None: h_elev_f = float(_espn_v["elevation"])
            if _espn_v["indoor"]:                    h_roof   = "closed"
            elif _espn_v.get("neutral_site"):        h_roof   = "open"
        # Sport surface FACTS â€” these are known truths, not defaults
        if sport in {"NBA","NCAAB"}:
            h_surface, h_detail = "Hardwood Court", "Maple/parquet flooring"
        elif sport == "NHL":
            h_surface, h_detail = "Ice Surface", "Regulation ice"

        surf_str = f"{h_surface} ({h_detail})" if h_detail else h_surface
        elev_str = f"{int(h_elev_f):,} ft" if h_elev_f is not None else "N/A"
        orient_str = (f"{h_orient}Â°  {h_olabel}") if h_orient != "" else "N/A"
        _ev_lat = (_espn_v or {}).get("lat")
        _ev_lon = (_espn_v or {}).get("lon")
        _ev_neu = (_espn_v or {}).get("neutral_site", False)
        _ev_city= (_espn_v or {}).get("city","")
        _ev_st  = (_espn_v or {}).get("state","")
        if _ev_lat is not None and _ev_lon is not None:
            coord_str = f"{round(float(_ev_lat),4)}, {round(float(_ev_lon),4)}"
        elif _ev_neu and _ev_city:
            coord_str = f"{_ev_city}, {_ev_st}  (geocoding pending)" if _ev_st else f"{_ev_city}  (geocoding pending)"
        elif h_lat not in ("",None) and h_lon not in ("",None):
            try: coord_str = f"{round(float(h_lat),4)}, {round(float(h_lon),4)}"
            except: coord_str = "N/A"
        else:
            coord_str = "N/A"

        for lbl, val in [
            ("Venue",       h_venue),
            ("Coordinates", coord_str),
            ("Elevation",   elev_str),
            ("Surface",     surf_str),
            ("Roof",        h_roof),
            ("Orientation", orient_str),
        ]:
            txt.insert(tk.END, f"  {lbl:<16}", "label")
            _w(txt, f"{val}\n")
    else:
        if home_team_db:
            _w(txt, f"  '{home_clean}' found as '{home_team_db}' but venue data incomplete.\n", "warn")
        else:
            _w(txt, f"  '{home_clean}' not found in venue database.\n", "warn")
        h_elev_f = None
        h_roof   = ""
        h_orient = ""

    # â”€â”€ AWAY VENUE (reference) â”€â”€
    _w(txt, f"\n  AWAY TEAM HOME VENUE  â€”  {away_clean}\n", "section")
    _sep(txt, "â”€", W)

    if away_row is not None:
        a_venue  = safe(away_row, "venue")     or "N/A"
        a_elev   = safe(away_row, "elevation")
        a_elev_f = safe_float(a_elev, 0.0, "away_elevation") if a_elev != "" else None
        a_surface = safe(away_row, "surface_type") or "N/A"
        a_roof    = safe(away_row, "roof_type")    or "N/A"
        if sport in {"NBA","NCAAB"}:  a_surface = "Hardwood Court"
        elif sport == "NHL":                  a_surface = "Ice Surface"

        a_elev_str = f"{int(a_elev_f):,} ft" if a_elev_f is not None else "N/A"
        for lbl, val in [
            ("Venue",    a_venue),
            ("Elevation", a_elev_str),
            ("Surface",  a_surface),
        ]:
            txt.insert(tk.END, f"  {lbl:<16}", "label")
            _w(txt, f"{val}\n")
    else:
        _w(txt, f"  '{away_clean}' not found in venue database.\n", "warn")
        a_elev_f = None



    # â”€â”€ PITCHING MATCHUP & ENVIRONMENTAL ASSESSMENT â”€â”€
    SECTION_LABELS = {
        "MLB":   "PITCHING MATCHUP  +  ENVIRONMENTAL ASSESSMENT",
        "NHL":   "GOALTENDER MATCHUP  +  ENVIRONMENTAL ASSESSMENT",
        "NBA":   "SCORING ENVIRONMENT ASSESSMENT",
        "NFL":   "PASSING / KICKING ENVIRONMENT ASSESSMENT",
        "NCAAB": "SCORING ENVIRONMENT ASSESSMENT",
        "NCAAF": "PASSING / KICKING ENVIRONMENT ASSESSMENT",
    }
    # is_indoor: elevation+pressure apply everywhere; ONLY wind is suppressed indoors
    INDOOR_SPORTS = {"NBA", "NCAAB", "NHL"}
    try:
        _h_roof = str(home_row.get("roof_type","") if isinstance(home_row,dict)
                      else (home_row["roof_type"] if home_row is not None and
                            hasattr(home_row,"index") and "roof_type" in home_row.index
                            else "")).lower()
    except Exception:
        _h_roof = ""
    # is_indoor resolution â€” priority order:
    # 1. ESPN live indoor flag (ground truth, includes neutral-site venues)
    # 2. Explicit roof_type from venue DB ("open" = outdoor, "dome/closed" = indoor)
    # 3. Sport-based fact (NBA/NHL are always played indoors â€” not a default, a fact)
    # 4. Retractable roof: UNKNOWN until ESPN resolves it â€” treated as outdoor
    #    (conservative: better to undercount wind suppression than fabricate it)
    _espn_indoor_flag = (_espn_v.get("indoor") if isinstance(_espn_v, dict) else None)
    if _espn_indoor_flag is not None:
        is_indoor = bool(_espn_indoor_flag)   # ESPN is authoritative
    else:
        _explicitly_outdoor = _h_roof in ("open","open_air","outdoor")
        _explicitly_indoor  = _h_roof in ("dome","dome_fixed","closed","retractable closed")
        _always_indoor_sport = sport in {"NBA","NHL"}   # factual, not a default
        is_indoor = _explicitly_indoor or (_always_indoor_sport and not _explicitly_outdoor)

    _w(txt, f"\n  {SECTION_LABELS.get(sport, 'ENVIRONMENTAL ASSESSMENT')}\n", "section")
    _sep(txt, "â”€", W)
# Deep-context layers auto-load in background after first render to
# keep click-path responsiveness high without requiring extra user action.
    _ctx = dict(heavy_ctx or {}) if isinstance(heavy_ctx, dict) else {}
    _mlb_db = (_ctx.get("mlb_db") if render_heavy else None)
    if _mlb_db is None and (sport == "MLB" and render_heavy):
        _mlb_db = _mlb_db_lookup(home_clean, away_clean)
    _inj_data = (_ctx.get("inj_data") if render_heavy else None)
    if _inj_data is None and render_heavy:
        _inj_data = _inj_news_lookup(sport, away_clean, home_clean)
    if render_heavy:
        _circ = _ctx.get("circ")
        if _circ is None:
            try:
                import re as _re2
                _gd_m = _re2.search(r'(\d{1,2})/(\d{1,2})', str(game_time))
                _gdate = (f"{datetime.now().year}-{int(_gd_m.group(1)):02d}-{int(_gd_m.group(2)):02d}"
                          if _gd_m else str(datetime.now().date()))
            except Exception:
                _gdate = str(datetime.now().date())
            _circ = _circ_analysis(game_time, home_row, away_row, sport,
                                   away_team=away_clean, home_team=home_clean,
                                   game_date=_gdate)
        _rr = _ctx.get("rr")
        if _rr is None and _REF_ENGINE_OK and _rse_mod:
            try:
                from datetime import date as _date_ref2
                _rr = _rse_mod.get_ref_signal(sport, away_clean, home_clean,
                                              _date_ref2.today())
            except Exception:
                _rr = None
    else:
        _circ = {"available": False, "reason": "Auto-loading full detail in background."}
        _rr = None

    # Safe defaults â€” these get real values later inside the physics block.
    # Defining them here ensures they are always bound even on weather=None renders.
    rho   = 0.0
    da    = None
    head  = 0.0
    cross = 0.0
    h_elev_use = h_elev_f if h_elev_f is not None else None
    _wx_ready  = (weather is not None and weather != "error")
    if _wx_ready:
        try:
            h_orient_f = safe_float(
                h_orient if home_row is not None and h_orient != "" else 0.0,
                0.0, "orientation")
            wind_eff_p = weather["wind_speed"]
            if str(h_roof if home_row is not None else "").lower() in ["closed","dome"]:
                wind_eff_p = 0.0
            rho   = air_density(weather["temp"], weather["pressure"], weather["humidity"])
            da    = density_altitude(weather["temp"], h_elev_use, weather["pressure"], weather["humidity"]) if h_elev_use is not None else None
            head, cross = wind_components(wind_eff_p, weather["wind_dir"], h_orient_f)
        except Exception:
            rho = 0.0
            da = None
            head = 0.0
            cross = 0.0

    # Standard atmosphere density at a given elevation (pitcher HOME baseline)
    def _std_rho_at_elev(elev_ft):
        """Dry-air standard density at elevation â€” the expected baseline
        for a pitcher who trains/pitches at that park."""
        import math
        elev_m = max(0.0, elev_ft) * 0.3048
        T = 288.15 - 0.0065 * elev_m        # K
        P = 101325 * (T / 288.15) ** 5.2561 # Pa
        rho_kgm3 = P * 0.0289644 / (8.31446 * T)
        return rho_kgm3 * 0.0624279606       # â†’ lb/ftÂ³

    # Home pitcher: today's weather at home vs STANDARD at same elevation
    #   (pure weather deviation â€” park doesn't change for them)
    # Away pitcher: today's game-venue density vs STANDARD at THEIR home elevation
    #   (full delta â€” captures both elevation AND weather change)
    if _wx_ready and rho and h_elev_use is not None:
        _home_baseline_rho = _std_rho_at_elev(h_elev_use)
        _away_baseline_rho = _std_rho_at_elev(a_elev_f if a_elev_f is not None else h_elev_use)
        _ars_pct_home = ((rho - _home_baseline_rho) / _home_baseline_rho * 100
                         if _home_baseline_rho else 0.0)
        _ars_pct_away = ((rho - _away_baseline_rho) / _away_baseline_rho * 100
                         if _away_baseline_rho else 0.0)
    else:
        _ars_pct_home = _ars_pct_away = None

    # Keep legacy _ars_pct for any remaining references
    _ars_pct   = _ars_pct_home  # used as fallback
    _ars_head  = head  if _wx_ready else None
    _ars_cross = cross if _wx_ready else None
    hw = _ars_head

    PITCH_LABELS = {
        "FF": "4-Seam FB", "SI": "Sinker",    "FC": "Cutter",
        "CU": "Curveball", "KC": "Knkl-Curve","SL": "Slider",
        "ST": "Sweeper",   "SV": "Slurve",    "CH": "Changeup",
        "FS": "Splitter",  "FO": "Forkball",  "EP": "Eephus",
        "UN": "Unknown",   "PO": "Pitchout",
    }
    # Spin-sensitivity weight (0=none, 1=full) â€” how much air density affects movement

    def _render_mlb_pitcher_context(side_key, pitcher_name, base_net_score, rho_pct):
        if sport != "MLB" or not _mlb_db:
            return base_net_score

        sp = (_mlb_db.get(f"{side_key}_sp") or {})
        opp_tm = (_mlb_db.get("away_team_st" if side_key == "home" else "home_team_st") or {})
        catcher = (_mlb_db.get(f"{side_key}_catcher") or {})
        own_state = (_circ.get(f"{side_key}_state") or {}) if isinstance(_circ, dict) else {}
        opp_state = (_circ.get("away_state" if side_key == "home" else "home_state") or {}) if isinstance(_circ, dict) else {}

        if not any([sp, opp_tm, catcher, own_state]):
            return base_net_score

        def _f(v):
            try:
                if v is None or str(v).strip() in ("", "None", "nan", "â€”"):
                    return None
                return float(v)
            except Exception:
                return None

        context_score = 0.0
        surface_l = str(h_surface or "").lower()
        _w(txt, "\n  Cumulative Pitcher Context\n", "section")
        _w(txt, "  " + "â”€" * 50 + "\n", "sep")
        env_tag = "warn" if base_net_score > 0.3 else "good" if base_net_score < -0.3 else "value"
        if base_net_score > 0.3:
            env_note = "weather/air-density baseline already leans favorable"
        elif base_net_score < -0.3:
            env_note = "weather/air-density baseline already leans unfavorable"
        else:
            env_note = "weather/air-density baseline is close to neutral"
        _w(txt, f"  â–¸ Environment baseline: {env_note} ({base_net_score:+.2f}).\n", env_tag)

        throws = str(sp.get("throws") or "").strip().upper()[:1]
        split_key = "ops_vs_lhp" if throws == "L" else "ops_vs_rhp" if throws == "R" else None
        split_val = _f(opp_tm.get(split_key)) if split_key else None
        opp_ops = _f(opp_tm.get("ops"))
        opp_xwoba = _f(opp_tm.get("xwoba"))
        opp_hh = _f(opp_tm.get("hard_hit_pct"))
        offense_ref = split_val if split_val is not None else opp_ops
        off_note = "opponent profile incomplete"
        off_tag = "value"
        if offense_ref is not None:
            if offense_ref >= 0.760:
                context_score -= 0.55
                off_note = "dangerous opposing offense"
                off_tag = "good"
            elif offense_ref >= 0.720:
                context_score -= 0.30
                off_note = "above-average opposing offense"
                off_tag = "good"
            elif offense_ref <= 0.660:
                context_score += 0.35
                off_note = "soft opposing offense"
                off_tag = "warn"
            elif offense_ref <= 0.690:
                context_score += 0.15
                off_note = "below-average opposing offense"
                off_tag = "warn"
            else:
                off_note = "middle-of-pack opposing offense"
        if opp_xwoba is not None:
            if opp_xwoba >= 0.330:
                context_score -= 0.12
            elif opp_xwoba <= 0.305:
                context_score += 0.08
        if opp_hh is not None:
            if opp_hh >= 38.0:
                context_score -= 0.08
            elif opp_hh <= 31.0:
                context_score += 0.05
        split_lbl = ("vs LHP" if split_key == "ops_vs_lhp" else
                     "vs RHP" if split_key == "ops_vs_rhp" else "overall")
        split_txt = f"{offense_ref:.3f}" if offense_ref is not None else "â€”"
        xwoba_txt = f"{opp_xwoba:.3f}" if opp_xwoba is not None else "â€”"
        hh_txt = f"{opp_hh:.1f}%" if opp_hh is not None else "â€”"
        _w(txt, f"  â–¸ Opponent attack: {split_lbl} OPS {split_txt} | xwOBA {xwoba_txt} | HH% {hh_txt} â€” {off_note}.\n", off_tag)

        gb = _f(sp.get("gb_pct"))
        fb = _f(sp.get("fb_pct"))
        dens_sens = _f(sp.get("density_sensitivity"))
        fit_note = None
        fit_tag = "value"
        if gb is not None and gb >= 48.0 and (rho_pct or 0) > 0.8:
            context_score += 0.20
            fit_note = f"{gb:.1f}% GB profile pairs well with dense air"
            fit_tag = "warn"
        elif fb is not None and fb >= 36.0 and hw is not None and hw < -3.0:
            context_score += 0.16
            fit_note = f"{fb:.1f}% FB profile gets carry protection from the headwind"
            fit_tag = "warn"
        elif fb is not None and fb >= 34.0 and (((rho_pct or 0) < -0.8) or (hw is not None and hw > 3.0)):
            context_score -= 0.24
            fit_note = f"{fb:.1f}% FB profile is exposed by tonight's carry conditions"
            fit_tag = "good"
        elif gb is not None and "grass" in surface_l:
            context_score += 0.08
            fit_note = f"{gb:.1f}% ground-ball lean fits the grass surface"
            fit_tag = "warn"
        if dens_sens is not None and rho_pct is not None:
            if dens_sens >= 0.68 and rho_pct > 0.8:
                context_score += 0.12
            elif dens_sens >= 0.68 and rho_pct < -0.8:
                context_score -= 0.12
        if fit_note:
            _w(txt, f"  â–¸ Batted-ball fit: {fit_note}.\n", fit_tag)

        impact = _f(catcher.get("catcher_impact_score"))
        catcher_name = catcher.get("catcher_name") or "Catcher"
        if impact is not None:
            if impact >= 0.65:
                context_score += 0.18
                ck_note = "strong receiving/blocking support"
                ck_tag = "warn"
            elif impact <= 0.35:
                context_score -= 0.18
                ck_note = "catching layer works against run prevention"
                ck_tag = "good"
            else:
                ck_note = "neutral catcher support"
                ck_tag = "value"
            _w(txt, f"  â–¸ Catcher support: {catcher_name} impact {impact:.2f} â€” {ck_note}.\n", ck_tag)

        era = _f(sp.get("era"))
        era3 = _f(sp.get("era_last3"))
        avg_pc3 = _f(sp.get("avg_pc_last3"))
        avg_ip3 = _f(sp.get("avg_ip_last3"))
        recent_bits = []
        recent_tag = "value"
        if era3 is not None:
            recent_bits.append(f"last-3 ERA {era3:.2f}")
            if era3 <= 3.20:
                context_score += 0.16
                recent_tag = "warn"
            elif era3 >= 4.80:
                context_score -= 0.16
                recent_tag = "good"
        elif era is not None:
            recent_bits.append(f"season ERA {era:.2f}")
        if avg_pc3 is not None:
            recent_bits.append(f"{avg_pc3:.0f} avg pitches")
            if avg_pc3 < 75:
                context_score -= 0.06
                recent_tag = "good"
        if avg_ip3 is not None:
            recent_bits.append(f"{avg_ip3:.1f} avg IP")
        if recent_bits:
            _w(txt, f"  â–¸ Form/workload: {', '.join(recent_bits)}.\n", recent_tag)

        own_risk = _f(own_state.get("risk_score")) or 0.0
        opp_risk = _f(opp_state.get("risk_score")) or 0.0
        risk_diff = opp_risk - own_risk
        if abs(risk_diff) >= 1.0:
            if risk_diff > 0:
                context_score += 0.15
                circ_note = "opposing offense carries the heavier travel/circadian tax"
                circ_tag = "warn"
            else:
                context_score -= 0.15
                circ_note = "pitcher side is more taxed by travel/circadian load"
                circ_tag = "good"
            _w(txt, f"  â–¸ Travel/body-clock: {circ_note} ({own_risk:.1f} vs {opp_risk:.1f}).\n", circ_tag)

        if _rr and sport == "MLB" and _rr.get("ump_name"):
            sc = (_rr.get("scorecard") or
                  (_rse_mod._get_ump_scorecard(_rr["ump_name"])
                   if hasattr(_rse_mod, "_get_ump_scorecard") else None))
            if sc:
                ump_name = _rr.get("ump_name") or "Umpire"
                aae = _f(sc.get("aae"))
                kpg = _f(sc.get("k_per_game"))
                if aae is not None and aae >= 1.5:
                    context_score += 0.12
                    ump_note = "tighter strike-zone profile supports pitchers"
                    ump_tag = "warn"
                elif aae is not None and aae <= -1.5:
                    context_score -= 0.12
                    ump_note = "looser zone profile can inflate contact/run scoring"
                    ump_tag = "good"
                elif kpg is not None and kpg >= 18.0:
                    context_score += 0.08
                    ump_note = "high strikeout game history is pitcher-friendly"
                    ump_tag = "warn"
                elif kpg is not None and kpg <= 13.0:
                    context_score -= 0.08
                    ump_note = "low strikeout game history trims the pitcher margin"
                    ump_tag = "good"
                else:
                    ump_note = "umpire profile looks neutral"
                    ump_tag = "value"
                _w(txt, f"  â–¸ Umpire layer: {ump_name} â€” {ump_note}.\n", ump_tag)

        overall_score = base_net_score + context_score
        ctx_tag = "warn" if context_score > 0.15 else "good" if context_score < -0.15 else "value"
        _w(txt, f"  â–¸ Context add-on only: {context_score:+.2f} versus the environment-only baseline.\n", ctx_tag)
        verdict_tag = "warn" if overall_score > 0.55 else "good" if overall_score < -0.55 else "value"
        if overall_score > 0.55:
            verdict = "combined pitcher outlook is favorable"
        elif overall_score < -0.55:
            verdict = "combined pitcher outlook is challenging"
        else:
            verdict = "combined pitcher outlook is mixed"
        _w(txt, f"  {'âœ…' if overall_score > 0.55 else 'âš ' if overall_score < -0.55 else 'âž¡'} COMBINED PITCHER OUTLOOK: {verdict} ({overall_score:+.2f}).\n", verdict_tag)
        return overall_score

    def _norm_team_token(value):
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip())

    def _find_pitcher_for_team_safe(team_name, starters_df, game_time_hint=None):
        """
        Starter resolver with city-name fallback.
        Handles odds feeds that use city-only labels (e.g., "Washington", "Pittsburgh").
        """
        try:
            p = find_pitcher_for_team(team_name, starters_df, game_time_hint=game_time_hint)
            if p:
                return p
        except Exception:
            pass

        try:
            if starters_df is None or getattr(starters_df, "empty", True) or "team" not in starters_df.columns:
                return None
            target = _norm_team_token(team_name)
            if not target:
                return None

            teams = [str(t) for t in starters_df["team"].dropna().astype(str).tolist()]
            if not teams:
                return None

            city_hint = _MLB_CITY_STARTER_FALLBACK.get(target, "")
            candidate_teams = []
            for raw_team in teams:
                norm_team = _norm_team_token(raw_team)
                if not norm_team:
                    continue
                if target == norm_team or target in norm_team or norm_team.startswith(target + " "):
                    candidate_teams.append(raw_team)
                    continue
                if city_hint and city_hint in norm_team:
                    candidate_teams.append(raw_team)

            # De-dup while preserving order.
            _seen = set()
            candidate_teams = [t for t in candidate_teams if not (_norm_team_token(t) in _seen or _seen.add(_norm_team_token(t)))]

            for candidate in candidate_teams:
                try:
                    p = find_pitcher_for_team(candidate, starters_df, game_time_hint=game_time_hint)
                    if p:
                        return p
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _render_pitcher_full(side_key, side_label, team_name, rho_pct, hw, cw,
                         baseline_label="home baseline"):
        """Render arsenal card + per-pitch env analysis + net assessment."""
        pitcher_info = None
        rows_df      = pd.DataFrame()

        if ARSENAL_AVAILABLE and _starters_df is not None and _arsenal_df is not None:
            pitcher_info = _find_pitcher_for_team_safe(team_name, _starters_df, game_time_hint=game_time)
            if pitcher_info:
                rows_df = get_pitcher_rows(pitcher_info["name"], _arsenal_df)

        _w(txt, f"  {side_label}\n", "label")

        if pitcher_info is None:
            if not ARSENAL_AVAILABLE:
                _w(txt, "  [WARN] arsenal_engine.py not found in script folder.\n", "na")
            elif _starters_df is None or (hasattr(_starters_df,"empty") and _starters_df.empty):
                if _arsenal_fetching:
                    prog = _arsenal_progress or "starting..."
                    _w(txt, f"  [RUN] Arsenal fetch in progress: {prog}\n", "warn")
                    _w(txt,  "     Check the Pitcher Arsenal tab for live progress.\n", "warn")
                else:
                    _w(txt, "  [RUN] Starters not loaded - check Pitcher Arsenal tab.\n", "warn")
            else:
                n_st = len(_starters_df)
                teams_in = ", ".join(_starters_df["team"].str.split().str[-1].unique()[:6])
                _w(txt, f"  No starter matched for '{team_name}'.\n", "na")
                _w(txt, f"  ({n_st} starters loaded: {teams_in}...)\n", "na")
            return 0

        _w(txt, f"  {'Starter':<14} {pitcher_info['name']}  ({pitcher_info['team']})\n", "value")

        if rows_df.empty:
            n_ars = len(_arsenal_df) if _arsenal_df is not None and not (hasattr(_arsenal_df,"empty") and _arsenal_df.empty) else 0
            if n_ars == 0:
                if _arsenal_fetching:
                    prog = _arsenal_progress or "starting..."
                    _w(txt, f"  [RUN] Fetch in progress: {prog}\n", "warn")
                    _w(txt,  "     Arsenal will populate when complete - re-open this popup then.\n", "warn")
                else:
                    _w(txt, "  [RUN] Arsenal not loaded - click Fetch in the Pitcher Arsenal tab.\n", "warn")
            else:
                _w(txt, f"  No 2025 Statcast data for {pitcher_info['name']}\n", "na")
                _w(txt, f"  (Arsenal has {n_ars} rows for {_arsenal_df['name'].nunique()} pitchers â€” this pitcher had no qualifying 2025 appearances)\n", "na")
            return 0

        # add Usage % if missing
        if "Usage %" not in rows_df.columns and "Total Pitches" in rows_df.columns:
            total = rows_df["Total Pitches"].sum()
            rows_df = rows_df.copy()
            rows_df["Usage %"] = (rows_df["Total Pitches"] / total * 100).round(1) if total else 0.0

        rows_df = rows_df.sort_values("Usage %", ascending=False) if "Usage %" in rows_df.columns else rows_df

        # â”€â”€ Arsenal table â”€â”€
        # â”€â”€ Pitcher's OWN spin reference from Baseball Savant â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Weighted average across all pitch types by usage% â€” purely self-referential
        try:
            _u = pd.to_numeric(rows_df.get("Total Pitches", rows_df.get("Usage %")), errors="coerce").fillna(1)
            _s = pd.to_numeric(rows_df["Spin Rate (RPM)"], errors="coerce").fillna(0)
            pitcher_own_avg_spin = float((_s * _u).sum() / _u.sum()) if _u.sum() > 0 else 0
        except Exception:
            pitcher_own_avg_spin = 0

        _w(txt, f"\n  {'Pitch':<10}{'Velo':>7}{'Spin':>9}{'Sp/Own':>8}{'H.Mov\"':>9}{'V.Mov\"':>8}{'Usage':>7}\n", "label")
        _w(txt, "  " + "â”€" * 50 + "\n", "sep")

        for _, pr in rows_df.iterrows():
            pt   = str(pr.get("Pitch Type", "->->"))
            velo = pr.get("Velocity (MPH)", float("nan"))
            spin = pr.get("Spin Rate (RPM)", float("nan"))
            hm   = pr.get("Horiz Mov (in)", float("nan"))
            vm   = pr.get("Vert Mov (in)", float("nan"))
            use  = pr.get("Usage %", 0.0)
            try:    velo_s = f"{float(velo):.1f}"
            except: velo_s = "N/A"
            try:    spin_s = f"{int(round(float(spin))):,}"
            except: spin_s = "N/A"
            try:    hm_s   = f"{float(hm):+.1f}"
            except: hm_s   = "N/A"
            try:    vm_s   = f"{float(vm):+.1f}"
            except: vm_s   = "N/A"
            try:    use_s  = f"{float(use):.1f}%"
            except: use_s  = "->"
            tag  = "value" if float(use) >= 20 else "label" if float(use) >= 10 else "na"
            # Sp/Own = this pitch spin vs pitcher's OWN weighted-average from Baseball Savant
            try:
                if pitcher_own_avg_spin > 0 and spin > 50:
                    _own_r = (spin / pitcher_own_avg_spin - 1) * 100
                    spin_vs = f"{_own_r:+.0f}%"
                else:
                    spin_vs = "â€”"
            except Exception:
                spin_vs = "â€”"
            _w(txt, f"  {pt:<10}{velo_s:>7}{spin_s:>9}{spin_vs:>8}{hm_s:>9}{vm_s:>8}{use_s:>7}\n", tag)

        # â”€â”€ Per-pitch environmental adjustments â”€â”€
        if rho_pct is None:
            _w(txt, "\n  â³ Environmental adjustments pending weather data.\n", "warn")
            return 0

        _w(txt, f"\n  Per-Pitch Movement Adjustments  (Ï {rho_pct:+.1f}% vs {baseline_label})\n", "label")
        _w(txt, f"  {'Pitch':<10}{'ÃŽâ€Vert\"':>8}{'ÃŽâ€Horiz\"':>9}{'Sens':>7}  Note\n", "label")
        _w(txt, "  " + "â”€" * 56 + "\n", "sep")

        weighted_impact = 0.0   # + = denser air helping pitcher this pitch
        total_weight    = 0.0
        pitches         = []    # list of pitch dicts used in net assessment
        _drag_ctx_map   = {}    # pitch_type â†’ drag physics context

        for _, pr in rows_df.iterrows():
            pt   = str(pr.get("Pitch Type", "->->"))
            hm   = pr.get("Horiz Mov (in)")
            vm   = pr.get("Vert Mov (in)")
            spin = pr.get("Spin Rate (RPM)")
            use  = pr.get("Usage %")
            # pd.isna catches float NaN, None, numpy NaN â€” all forms of missing
            def _pf(v):
                try:
                    if v is None: return None
                    if str(v).strip().lower() in ("","nan","none","n/a"): return None
                    f = float(v)
                    return None if f != f else f  # f!=f is True only for NaN
                except Exception: return None
            hm=_pf(hm); vm=_pf(vm); spin=_pf(spin)
            use_v=_pf(use); use=use_v if use_v is not None else 0.0
            if hm is None or vm is None or spin is None:
                log(f"Pitch {pt} skipped â€” missing data ({pitcher_info['name']})", "debug")
                continue

            # â”€â”€ Spin sensitivity from THIS PITCHER's own Savant spin data â”€â”€â”€â”€â”€â”€
            # spin_factor = how this pitch's RPM compares to pitcher's OWN average
            # (computed above from Savant, no league numbers involved)
            # Base pitch-type Magnus fraction (how spin-driven this pitch design is)
            # Ã— individual spin_factor from their OWN arsenal = effective sensitivity
            # â”€â”€ Pure spin-rate physics â€” NO hardcoded pitch-type assumptions â”€â”€
            # Magnus force âˆ spin rate. The fraction of movement that is
            # Magnus-driven = spin / (spin + K) where K=1000 RPM represents
            # the baseline non-Magnus contribution (seam drag, gravity, release).
            # This is a PHYSICAL CONSTANT â€” not a league average.
            # A 3,200 RPM CU and a 2,100 RPM CU now correctly differ.
            # A 1,500 RPM CH and a 2,500 RPM SL correctly differ.
            # Only the pitcher's OWN Baseball Savant spin rate drives this.
            # Pitch-type-specific K: higher K = less Magnus-driven = less air sensitive
            _PT_K = {"FF":700,"SI":750,"FC":900,"SL":950,"ST":900,
                     "CU":1200,"KC":1200,"CH":1600,"FS":1500,"FO":1500}
            K_non_magnus = float(_PT_K.get(pt.upper(), 1000))
            if spin > 50:
                sens = min(0.95, spin / (spin + K_non_magnus))
            else:
                sens = 0.50

            # â”€â”€ CORRECT movement delta formula â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # pfx_x / pfx_z ALREADY encode this pitcher's actual spin rate.
            # Magnus force âˆ Ï Ã— Ï‰ Ã— v â€” since Ï‰ and v are fixed for this
            # pitcher, movement scales linearly with Ï.
            # Î”movement = season_movement Ã— (Î”Ï / Ï_baseline) Ã— spin_type_sens
            # rho_pct = (Ï_today - Ï_baseline) / Ï_baseline Ã— 100
            # where Ï_baseline = standard density at THIS PITCHER's home elevation
            # â†’ result is how much their own pitch moves MORE/LESS vs home norms
            d_vm  = vm * (rho_pct / 100.0) * sens
            d_hm  = hm * (rho_pct / 100.0) * sens

            # â”€â”€ Dual-path impact model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # PATH 1 â€” Magnus (spin-driven): applies to high-spin pitches
            #   sens â‰¥ 0.65 â†’ movement scales directly with Ï
            # PATH 2 â€” Drag/Tumble (low-spin): applies to FS, CH, FO etc.
            #   Dense air = MORE drag = ball decelerates later = more late break
            #   Tailwind  = lower ÃŽâ€v vs air = LESS tumble (flat landing)
            #   Headwind  = higher ÃŽâ€v vs air = MORE tumble (sharper late break)
            mag_chg     = abs(d_vm) + abs(d_hm)   # Magnus component
            _is_low_spin = (sens < 0.62)            # FS, CH, FO, knuckleball range

            if _is_low_spin:
                # Drag-tumble bonus: dense air amplifies late break
                # Formula: |movement| Ã— Î”Ï% Ã— drag_fraction Ã— empirical_scale
                # drag_fraction = (1 - sens): how much movement is drag-driven
                _drag_frac   = max(0.0, 1.0 - sens)
                _tumble_mag  = (abs(vm) + abs(hm)) * 0.5   # avg movement magnitude
                _drag_bonus  = _tumble_mag * (rho_pct / 100.0) * _drag_frac * 0.9
                # Wind modulation: tailwind reduces, headwind enhances tumble
                # hw > 0 = tailwind (ball â†’ same direction as pitch travel)
                _hw_val      = hw if hw is not None else 0.0
                _wind_mod    = -(_hw_val * 0.015 * _drag_frac)  # ~1.5%/mph for low-spin
                _net_drag    = _drag_bonus + _wind_mod
                # Total impact: Magnus path + drag path
                # Both favorable (dense air good for movement) but DIFFERENT magnitudes
                pitch_impact = (mag_chg + max(0.0, _net_drag)) * (1 if rho_pct > 0 else -1)
                # Store drag context for note generation
                _drag_context = {
                    "drag_bonus":  _drag_bonus,
                    "wind_mod":    _wind_mod,
                    "net_drag":    _net_drag,
                    "hw":          _hw_val,
                    "is_low_spin": True,
                    "drag_frac":   _drag_frac,
                }
            else:
                # High-spin Magnus path â€” standard formula
                pitch_impact  = mag_chg * (1 if rho_pct > 0 else -1)
                _drag_context = {"is_low_spin": False}

            weighted_impact += pitch_impact * (use / 100.0)
            total_weight    += use / 100.0
            _drag_ctx_map[pt] = _drag_context   # store per pitch for note rendering

            # Pitch-type-specific note based on movement direction + magnitude
            def _pitch_note(pt, dv, dh, pct, sn, drag_ctx=None):
                if abs(pct) < 0.3: return "Neutral conditions â€” standard air"
                dc = drag_ctx or {}
                if dc.get("is_low_spin") and abs(pct) >= 0.3:
                    _db = dc.get("drag_bonus", 0.0)
                    _wm = dc.get("wind_mod", 0.0)
                    _hw = dc.get("hw", 0.0)
                    _sgn = "+" if pct > 0 else "âˆ’"
                    if _db > 0.03 and pct > 0:
                        _note = f"[{_sgn}drag] Tumble/sink amplified by dense air (+{_db:.2f}\")"
                    elif pct < 0:
                        _note = f"[{_sgn}drag] Tumble reduced â€” thin air lowers late break"
                    else:
                        _note = "[drag] Minimal late-break change"
                    if _hw > 2.0 and _wm < -0.02:
                        _note += f" | tailwind flattens tumble ({_wm:+.2f}\" net)"
                    elif _hw < -2.0 and _wm > 0.02:
                        _note += f" | headwind sharpens tumble ({_wm:+.2f}\" net)"
                    return _note
                if sn < 0.50:
                    return "Low-spin/velo pitch â€” air density has minor effect"
                if abs(dv) < 0.04 and abs(dh) < 0.04:
                    return "Change <0.04\" in all directions â€” negligible"
                p = pt.upper()
                sign = "+" if pct > 0 else "âˆ’"
                # Describe movement in pitch-type language
                if p in ("FF",):
                    mv = f"{abs(dv):.2f}\" {'more' if dv>0 else 'less'} rise/hop"
                elif p in ("SI",):
                    mv = f"{abs(dv):.2f}\" {'more' if dv>0 else 'less'} sink, {abs(dh):.2f}\" {'more' if abs(dh)>0.03 else '~same'} arm-side"
                elif p in ("CU","KC"):
                    mv = f"{abs(dv):.2f}\" {'sharper' if dv<0 else 'flatter'} downward break"
                elif p in ("SL","ST"):
                    mv = f"{abs(dh):.2f}\" {'more' if (dh>0 if p=='ST' else dh<0) else 'less'} lateral sweep"
                elif p in ("FC",):
                    mv = f"{abs(dv):.2f}\" {'more' if dv>0 else 'less'} cut action"
                elif p in ("SV",):
                    mv = f"{abs(dv):.2f}\" vert + {abs(dh):.2f}\" lateral combined"
                else:
                    mv = f"ÃŽâ€Vert={dv:+.2f}\" ÃŽâ€Horiz={dh:+.2f}\""
                return f"[{sign}air] {mv}"
            note = _pitch_note(pt, d_vm, d_hm, rho_pct, sens, drag_ctx=_drag_context)

            sens_lbl = f"{int(sens*100)}%"
            d_vm_s   = f"{d_vm:+.2f}" if abs(d_vm) >= 0.02 else " ~0.00"
            d_hm_s   = f"{d_hm:+.2f}" if abs(d_hm) >= 0.02 else " ~0.00"
            tag = "warn" if rho_pct > 0 else "good" if rho_pct < 0 else "value"
            _w(txt, f"  {pt:<10}{d_vm_s:>8}{d_hm_s:>9}{sens_lbl:>7}  {note}\n", tag)
            pitches.append({"pitch_type":pt,"spin":spin,"usage":use,"dv":d_vm,"dh":d_hm})

        # â”€â”€ Net pitcher assessment â”€â”€
        avg_impact = weighted_impact / total_weight if total_weight else 0.0

        _w(txt, "\n  Net Pitcher Assessment\n", "section")
        _w(txt, "  " + "â”€" * 50 + "\n", "sep")
        _by_use = sorted(pitches, key=lambda p: p.get("usage",0), reverse=True)
        _top1   = _by_use[0] if _by_use else {}
        _wt_sp  = (sum(p.get("spin",0)*p.get("usage",0) for p in pitches)
                   / max(sum(p.get("usage",0) for p in pitches), 1))
        def _td(p): return abs(p.get("dv",0)) + abs(p.get("dh",0))
        _max_p  = max(pitches, key=_td) if pitches else {}
        if abs(rho_pct) < 0.3:
            _w(txt, "  \u25b8 Air density: NEUTRAL â€” no meaningful movement deviation.\n", "value")
        else:
            _dw  = "DENSER" if rho_pct > 0 else "THINNER"
            _col = "warn" if rho_pct > 0 else "good"
            _w(txt, f"  \u25b8 Air is {abs(rho_pct):.1f}% {_dw}:\n", _col)
            _p1n=_top1.get("pitch_type",""); _p1u=_top1.get("usage",0)
            _p1s=_top1.get("spin",0); _p1v=_top1.get("dv",0); _p1h=_top1.get("dh",0)
            if _p1n:
                _p1si = int(round(_p1s))
                _slbl = "high-spin" if _p1si>=2300 else "low-spin"
                _ms   = (f"{_p1v:+.2f}\u201d vert/{_p1h:+.2f}\u201d horiz"
                         if abs(_p1v)+abs(_p1h)>0.04 else "negligible change")
                _w(txt, f"    Primary: {_p1n} ({_p1u:.0f}% usage, {_slbl} {_p1si:,} rpm) \u2192 {_ms}\n", _col)
            _mpn = _max_p.get("pitch_type","")
            # If primary pitch has low sensitivity (<0.60), redirect attention to most-impacted
            _p1_pitch_sens = min(0.95, (_top1.get("spin",2000)) / ((_top1.get("spin",2000)) + 1000))
            _primary_low_sens = _p1_pitch_sens < 0.60
            if _mpn and _mpn!=_p1n and _td(_max_p)>0.08:
                _mv=_max_p.get("dv",0); _mh=_max_p.get("dh",0); _mu=_max_p.get("usage",0)
                prefix = "Primary impact" if _primary_low_sens else "Most affected"
                _w(txt, f"    {prefix}: {_mpn} ({_mu:.0f}%) \u0394Vert={_mv:+.2f}\u201d \u0394Horiz={_mh:+.2f}\u201d\n", _col)
            if _primary_low_sens and _mpn and _mpn != _p1n:
                _w(txt, f"    Note: {_p1n} is primary by usage but low-spin ({int(round(_top1.get('spin',0))):,} rpm) â€” {_mpn} is the meaningful movement pitch.\n", "na")
            if _wt_sp>=2300:
                _w(txt, f"    Spin-dominant ({_wt_sp:.0f} rpm avg) â€” {'benefits significantly' if rho_pct>0 else 'disproportionately hurt'} by {_dw.lower()} air.\n", _col)
            else:
                _w(txt, f"    Seam/sink-dominant ({_wt_sp:.0f} rpm avg) â€” air density effect modest on this arsenal.\n", _col)
        if hw is not None:
            if abs(hw)<1.5:   _w(txt, "  \u25b8 Wind: negligible â€” no material carry effect.\n", "value")
            elif hw<0:        _w(txt, f"  \u25b8 Wind: {abs(hw):.1f} mph HEADWIND â€” batted balls lose carry. FAVORABLE for pitcher.\n", "warn")
            else:             _w(txt, f"  \u25b8 Wind: {hw:.1f} mph TAILWIND â€” batted balls carry further. UNFAVORABLE.\n", "good")
        wind_factor = (-hw*0.5) if hw is not None else 0.0
        net_score   = avg_impact + wind_factor
        _w(txt, "\n", "value")
        _pn = _top1.get("pitch_type","primary pitch")
        # Dynamic net explanation â€” never contradicts the movement table
        _is_dense = rho_pct > 0
        _is_tail  = hw is not None and hw >  1.5
        _is_head  = hw is not None and hw < -1.5
        if net_score > 0.3:
            _w(txt, "  \u2705 NET: ENVIRONMENT FAVORS THIS PITCHER\n", "warn")
            if _is_dense and _is_head:
                _exp = f"Dense air boosts {_pn} movement AND headwind suppresses carry â€” stacks in pitcher's favor."
            elif _is_dense:
                _exp = f"Dense air enhances {_pn} movement{(' + headwind' if _is_head else '')} â€” favorable conditions."
            else:
                _exp = f"Environment favors pitcher â€” headwind limits batted ball carry."
            _w(txt, f"     {_exp}\n", "warn")
        elif net_score < -0.3:
            _w(txt, "  \u26a0 NET: ENVIRONMENT WORKS AGAINST THIS PITCHER\n", "good")
            if _is_dense and _is_tail:
                _exp = (f"Dense air DOES enhance {_pn} movement, but {hw:.1f} mph tailwind "
                        f"overpowers â€” batted ball carry elevated despite improved pitch movement.")
            elif not _is_dense:
                _exp = f"Thin air reduces {_pn} movement{(' + tailwind' if _is_tail else '')} â€” pitches easier to square up."
            else:
                _exp = f"Net environment unfavorable â€” {_pn} impacted{(' + tailwind' if _is_tail else '')}."
            _w(txt, f"     {_exp}\n", "good")
        else:
            _w(txt, "  \u27a1 NET: MIXED / NEUTRAL environment for this pitcher.\n", "value")
            if _is_dense and _is_tail:
                _w(txt, f"     Dense air movement boost largely offset by {hw:.1f} mph tailwind carry â€” effects cancel.\n", "value")
            else:
                _w(txt, "     Competing effects largely cancel â€” matchup and command factors dominate.\n", "value")
        return _render_mlb_pitcher_context(side_key, pitcher_info["name"], net_score, rho_pct)

    if sport == "MLB":
        if (not render_heavy) and _DETAIL_POPUP_FAST_RENDER:
            _w(
                txt,
                "  Pitching context is auto-loading in background for full per-pitch movement,\n"
                "  matchup context, and combined pitcher outlook scoring.\n",
                "warn",
            )
            home_net = 0
            away_net = 0
        else:
            try:
                home_net = _render_pitcher_full(
                    "home",
                    f"HOME STARTER  â€”  {home_clean}", home_clean,
                    _ars_pct_home,
                    _ars_head, _ars_cross,
                    baseline_label=f"home park ({int(h_elev_use):,} ft std)")
            except Exception as _pe:
                log(f"Home pitcher render error: {_pe}", "error")
                _w(txt, f"  âš  Home pitcher render error: {_pe}\n", "warn")
                home_net = 0
            _w(txt, "\n", "value")
            try:
                away_net = _render_pitcher_full(
                    "away",
                    f"AWAY STARTER  â€”  {away_clean}", away_clean,
                    _ars_pct_away,
                    _ars_head, _ars_cross,
                    baseline_label=f"away home ({int(a_elev_f):,} ft std)" if a_elev_f else "away home std")
            except Exception as _pe:
                log(f"Away pitcher render error: {_pe}", "error")
                _w(txt, f"  âš  Away pitcher render error: {_pe}\n", "warn")
                away_net = 0

            # Pitching-environment edge summary
            if _ars_pct is not None and isinstance(home_net, (int, float)) and isinstance(away_net, (int, float)):
                _w(txt, "\n  PITCHING EDGE / GAME CONTEXT\n", "section")
                _sep(txt, "â”€", W)
                diff = home_net - away_net
                if abs(diff) < 0.3:
                    both_pos = home_net > 0.3 and away_net > 0.3
                    both_neg = home_net < -0.3 and away_net < -0.3
                    if both_pos:
                        _w(txt, "  Both starters grade well once environment and matchup context are blended.\n", "warn")
                        _w(txt, "  No meaningful differential edge from the full pitching setup.\n", "warn")
                    elif both_neg:
                        _w(txt, "  Both starters grade poorly once environment and matchup context are blended.\n", "good")
                        _neg_env = ("tailwind carry overpowers both arsenals" if (hw is not None and hw > 1.5)
                                   else "thin air reduces movement for both" if (rho_pct is not None and rho_pct < 0)
                                   else "net conditions unfavorable for both starters")
                        _w(txt, f"  {_neg_env.capitalize()} â€” offense favored.\n", "good")
                    else:
                        _w(txt, "  Full pitching context is essentially neutral on both sides.\n", "value")
                elif diff > 0:
                    _w(txt, f"  Overall pitching context FAVORS the {home_clean} starter more tonight.\n", "warn")
                else:
                    _w(txt, f"  Overall pitching context FAVORS the {away_clean} starter more tonight.\n", "warn")

    else:
        # Non-MLB: sport-appropriate matchup context
        _w(txt, f"\n  HOME: {home_clean}  |  AWAY: {away_clean}\n", "label")
        SPORT_MATCHUP_NOTE = {
            "NHL":   "(Goaltender data not integrated â€” full physics analysis follows)",
            "NBA":   "(Player/lineup data not integrated â€” elevation/density analysis follows)",
            "NFL":   "(QB/kicker data not integrated â€” wind/density analysis follows)",
            "NCAAB": "(Roster data not integrated â€” venue physics analysis follows)",
            "NCAAF": "(Roster data not integrated â€” wind/density analysis follows)",
        }
        _w(txt, f"  {SPORT_MATCHUP_NOTE.get(sport, '(Matchup data pending for this sport.)')}\n", "na")
        home_net = 0
        away_net = 0

    # â”€â”€ ENVIRONMENT ANALYSIS (unified) â”€â”€
        # â”€â”€ WEATHER â”€â”€

    # Keep click-path responsive: deep injury/lineup rendering is opt-in.
    if render_heavy:
        _render_injury_news_section(txt, _inj_data, away_clean, home_clean, sport, W)
        _render_lineup_section(txt, away_clean, home_clean, sport, W)
    else:
        _w(txt, "\n  INJURIES & LINEUP INTEL\n", "section")
        _sep(txt, "â”€", W)
        _w(
            txt,
            "  Auto-loading full injury/news/lineup intelligence in background.\n",
            "warn",
        )
    # â”€â”€ Referee / Umpire section â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if _REF_ENGINE_OK and _rse_mod:
        try:
            if _rr and (_rr.get("ref_names") or _rr.get("ump_name")):
                _w(txt, "\n  OFFICIALS\n", "section")
                _sep(txt, "â”€", W)
                # Names
                for nm in (_rr.get("ref_names") or []):
                    _w(txt, f"  {nm}\n", "na")
                # MLB ump stats
                if sport == "MLB" and _rr.get("ump_name"):
                    sc = (_rr.get("scorecard") or
                          (_rse_mod._get_ump_scorecard(_rr["ump_name"])
                           if hasattr(_rse_mod,"_get_ump_scorecard") else None))
                    _ump_conf = _rr.get("ump_confidence","->")
                    _ump_src  = _rr.get("ump_source","->")
                    _conf_badge = "âœ… CONFIRMED" if _ump_conf=="CONFIRMED" else "~ PREDICTED (series rotation)"
                    _w(txt, f"  Source:  {_conf_badge}  [{_ump_src}]\n", "na")
                    if sc and sc.get("games_total",0) >= 50:
                        _aae  = sc.get("aae",0.0) or 0.0
                        _rpg  = sc.get("runs_per_game",0.0) or 0.0
                        _kpg  = sc.get("k_per_game",0.0) or 0.0
                        _bbpg = sc.get("bb_per_game",0.0) or 0.0
                        _fav  = sc.get("favor_home",0.0) or 0.0
                        _games= sc.get("games_total",0)
                        _aae_tag = "warn" if abs(_aae)>=1.5 else "na"
                        _w(txt, f"  AAE       ", "na")
                        _w(txt, f"{_aae:+.2f} pct pts  ", _aae_tag)
                        _zone_lbl = "TIGHT ZONEâ†’UNDER" if _aae>=1.5 else "LOOSE ZONEâ†’OVER" if _aae<=-1.5 else "avg zone"
                        _w(txt, f"{_zone_lbl}\n", _aae_tag)
                        _w(txt, f"  RPG       {_rpg:.2f}  K/G {_kpg:.2f}  BB/G {_bbpg:.2f}\n", "na")
                        _w(txt, f"  Favor     {_fav:+.3f} (>0=home, <0=away)  Games {_games}\n", "na")
                # OU + side signal
                if _rr.get("ou_signal","NEUTRAL") != "NEUTRAL":
                    _sig_tag = "warn" if _rr["ou_signal"]=="OVER" else "good"
                    _w(txt, f"  Signal:   {_rr['ou_signal']}  ({_rr.get('detail','')[:80]})\n", _sig_tag)
                if _rr.get("side_signal","NEUTRAL") != "NEUTRAL":
                    _w(txt, f"  Side:     {_rr['side_signal']}\n", "value")
                _sep(txt, "â”€", W)
        except Exception: pass

    # â”€â”€ MLB pre-game DB stats (pitcher stats, team offense, catchers) â”€â”€â”€â”€â”€â”€â”€
    if sport == "MLB":
        if _mlb_db is not None:
            _w(txt, "\n  MLB PRE-GAME DATA  (mlb_pregame.db)\n", "section")
            _sep(txt, "â”€", W)
            # Never perform synchronous RotoWire fetches in the UI thread.
            _rw_rec_db = None
            _render_mlb_db_section(txt, _mlb_db, away_clean, home_clean, W, rw_rec=_rw_rec_db)
        else:
            _w(txt, "\n  MLB PRE-GAME DATA\n", "section")
            _sep(txt, "â”€", W)
            if render_heavy:
                _w(txt, "  âš™  Auto-boot running â€” stats will populate momentarily.\n"
                        "     Close and re-open this popup once the Run Log shows âœ….\n", "warn")
            else:
                _w(txt, "  â³  Auto-loading full MLB DB context in background.\n", "na")
    _wx_label = ("WEATHER @ GAME VENUE"
                 if (_espn_v or {}).get("neutral_site")
                 else "WEATHER @ HOME VENUE")
    _w(txt, f"\n  {_wx_label}\n", "section")
    _sep(txt, "â”€", W)
    _w(txt, "  â˜… Station data primary â€” all physics derived from live measured conditions.\n", "na")

    if weather is None:
        _w(txt, "  â³  Fetching live weather...\n", "warn")
    elif weather == "error":
        _w(txt, "  âš   Weather fetch failed â€” check API key / connection.\n", "warn")
    else:
        wx_src = _weather_source_label
        txt.insert(tk.END, f"  {'Source':<16}", "label")
        _w(txt, f"{wx_src}\n", "warn" if _weather_used_fallback else "good")

        for lbl, val in [
            ("Temperature",  f"{weather['temp']} Â°F"),
            ("Humidity",     f"{weather['humidity']}%"),
            ("Pressure",     f"{round(weather['pressure'], 2)} inHg"),
            ("Wind", (f"{weather['wind_speed']} mph  @  {weather['wind_dir']}Â°"
                     if weather.get('wind_dir') is not None
                     else f"{weather['wind_speed']} mph (direction N/A)")),
        ]:
            txt.insert(tk.END, f"  {lbl:<16}", "label")
            _w(txt, f"{val}\n")

        # â”€â”€ PHYSICS â”€â”€
        _ph_label = ("PHYSICS @ GAME VENUE"
                     if (_espn_v or {}).get("neutral_site")
                     else "PHYSICS @ HOME VENUE")
        _w(txt, f"\n  {_ph_label}\n", "section")
        _sep(txt, "â”€", W)
        _w(txt, "  â˜… Vector math applied to station pressure / temp / humidity / wind bearing.\n", "na")

        h_elev_use = h_elev_f if h_elev_f is not None else None
        h_orient_f = safe_float(h_orient if home_row is not None and h_orient != "" else 0.0,
                                0.0, "orientation")

        # Zero wind if indoor/dome
        wind_eff = weather["wind_speed"]
        roof_note = ""
        if str(h_roof if home_row is not None else "").lower() in ["closed", "dome"]:
            wind_eff = 0.0
            roof_note = "  (zeroed â€” dome/closed roof)"

        try:
            rho   = air_density(weather["temp"], weather["pressure"], weather["humidity"])
            da    = density_altitude(weather["temp"], h_elev_use, weather["pressure"], weather["humidity"]) if h_elev_use is not None else None
            head, cross = wind_components(wind_eff, weather["wind_dir"], h_orient_f)
        except Exception as ex:
            rho = 0.0
            da = None
            head = 0.0
            cross = 0.0
            _w(txt, f"  Physics calc error: {ex}\n", "warn")

        for lbl, val in [
            ("Air Density",       f"{round(rho, 5)} lb/ftÂ³"),
            ("Density Altitude",  (f"{round(da):,} ft" if da is not None else "N/A (missing elevation)")),
            ("Headwind",          f"{head} mph{roof_note}"),
            ("Crosswind",         f"{cross} mph"),
        ]:
            txt.insert(tk.END, f"  {lbl:<20}", "label")
            _w(txt, f"{val}\n")
    _w(txt, "\n  ENVIRONMENT ANALYSIS\n", "section")
    _sep(txt, "â”€", W)

    # Guard: physics vars only exist when weather was available
    if weather is None:
        _w(txt, "  â³ Pending forecast â€” analysis will populate after weather loads.\n", "warn")
        _sep(txt, "â•", W)
        txt.config(state=tk.DISABLED)
        txt.see("1.0")
        return
    if weather == "error":
        _w(txt, "  âš  Weather fetch failed â€” environment analysis unavailable.\n", "warn")
        _sep(txt, "â•", W)
        txt.config(state=tk.DISABLED)
        txt.see("1.0")
        return

    std_rho = 0.07647  # lb/ftÂ³ â€” standard: 59Â°F, sea level, 50% RH, 29.92 inHg
    pct = ((rho - std_rho) / std_rho) * 100 if rho is not None else None

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # ENVIRONMENT ANALYSIS â€” all language is sport-aware, no MLB bleed
    # All sports get full physics: density, pressure, elevation, wind (if outdoor)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _OBJ = {"MLB":"batted ball","NHL":"puck","NBA":"shot/ball",
             "NFL":"football","NCAAB":"ball","NCAAF":"football"}.get(sport,"projectile")

    _THIN_MSG = {
        "MLB":   "Ball carries FARTHER â€” thin/warm air reduces drag on batted balls.",
        "NHL":   "Puck drag reduced â€” thin air aids shot velocity and carry on passes/shots.",
        "NBA":   "Shot arcs extend marginally. Elevation fatigue opens late-period scoring.",
        "NFL":   "Kick range and passing carry extended. Deep routes and field goals aided.",
        "NCAAB": "Altitude reduces aerodynamic drag on the ball. Second-half fatigue opens scoring.",
        "NCAAF": "Kick distance and deep pass carry extended at elevation or in thin air.",
    }.get(sport, "Projectile carries farther in thin air.")

    _DENSE_MSG = {
        "MLB":   "Ball carries SHORTER â€” dense/cold air increases drag on batted balls.",
        "NHL":   "Puck drag increased â€” dense air slows shots and suppresses puck velocity.",
        "NBA":   "Shot resistance marginally increased. Dense cold air may stiffen play.",
        "NFL":   "Kick distance and passing carry suppressed. Run-heavy offense may be favored.",
        "NCAAB": "Dense air adds aerodynamic resistance. Cold, heavy air may tighten play.",
        "NCAAF": "Dense air limits kicking game and deep passing. Conservative offense expected.",
    }.get(sport, "Projectile carries shorter in dense air.")

    _HW_MSG = {
        "MLB":   "Headwind blowing IN â€” fly balls suppressed, warning-track outs likely. Pitcher-favoring.",
        "NHL":   "Headwind suppresses dump-in puck carry and perimeter shot velocity.",
        "NBA":   "Headwind (outdoor/open-roof) reduces ball carry. Rare but real.",
        "NFL":   "Headwind suppresses kick distance and deep passing game. Run game favored.",
        "NCAAB": "Headwind (open-roof venue) adds resistance. Scoring pace may tighten.",
        "NCAAF": "Headwind suppresses kicking game and deep routes. Conservative offense.",
    }.get(sport, "Headwind suppresses projectile carry.")

    _TW_MSG = {
        "MLB":   "Tailwind blowing OUT â€” fly balls carry further, home run risk elevated. Offense-favoring.",
        "NHL":   "Tailwind aids puck carry on dump-ins and outlet passes.",
        "NBA":   "Tailwind (outdoor/open-roof) aids ball carry.",
        "NFL":   "Tailwind boosts kick distance and deep passing game.",
        "NCAAB": "Tailwind (open-roof venue) aids ball carry.",
        "NCAAF": "Tailwind boosts kicking distance and deep routes.",
    }.get(sport, "Tailwind boosts projectile carry.")

    _AWAY_DOWN_MSG = {
        "MLB":   "Away team used to THINNER air â€” today's denser air suppresses their expected ball carry and power output. Away pitchers gain marginal extra resistance.",
        "NHL":   "Away team used to THINNER air â€” today's denser air marginally suppresses skating pace and shot carry vs their home norm.",
        "NBA":   "Away team used to THINNER air â€” denser conditions may suppress their shooting rhythm and fatigue advantage.",
        "NFL":   "Away team used to THINNER air â€” kick range and deep passing may be suppressed vs their home norm.",
        "NCAAB": "Away team stepping DOWN into denser air â€” their conditioning advantage may be reduced vs their elevation-accustomed norm.",
        "NCAAF": "Away team used to THINNER air â€” kicking game and deep passing suppressed vs their norm.",
    }.get(sport, "Away team faces denser air than their home norm.")

    _AWAY_UP_MSG = {
        "MLB":   "Away team stepping UP into THINNER air vs their home â€” extra ball carry relative to their norm. Away pitchers lose some pitch movement.",
        "NHL":   "Away team stepping UP into THINNER air â€” puck carry aided, skating pace marginally boosted vs their norm.",
        "NBA":   "Away team stepping UP into THINNER air â€” shot carry aided relative to their home norm. Altitude fatigue is a real factor.",
        "NFL":   "Away team in THINNER air â€” kick range and passing carry extended vs their norm.",
        "NCAAB": "Away team in THINNER air â€” scoring pace may elevate relative to their home norm. Elevation fatigue favors home team in late game.",
        "NCAAF": "Away team in THINNER air â€” kicking game and deep passing aided vs their norm.",
    }.get(sport, "Away team faces thinner air than their home norm.")

    if pct is not None:
        _w(txt, "  [1] Air Density vs. Standard Baseline\n", "section")
        _w(txt, f"      Standard = 0.07647 lb/ft\u00b3  (59\u00b0F \u00b7 sea level \u00b7 50% RH \u00b7 29.92 inHg)\n", "label")
        _w(txt, f"      Measured = {round(rho,5)} lb/ft\u00b3  ", "value")
        if abs(pct) < 0.5:
            _w(txt, "(\u2248 standard â€” neutral conditions)\n", "value")
            air_verdict = "neutral"
        elif pct < 0:
            _w(txt, f"({abs(pct):.1f}% THINNER than standard)\n", "warn")
            _w(txt, f"      \u2192 {_THIN_MSG}\n", "warn")
            _w(txt, f"        Driven by: temp={weather['temp']:.0f}\u00b0F, humidity={weather['humidity']}%, elevation={int(h_elev_use):,}ft.\n", "warn")
            _w(txt,  "        Water vapor displaces O\u2082/N\u2082 â€” reduces overall air density.\n", "warn")
            air_verdict = "carry+"
        else:
            _w(txt, f"({pct:.1f}% DENSER than standard)\n", "good")
            _w(txt, f"      \u2192 {_DENSE_MSG}\n", "good")
            _w(txt, f"        Cool/dry/high-pressure conditions increase aerodynamic drag on {_OBJ}s.\n", "good")
            air_verdict = "carry-"
        _w(txt, "\n", "value")

        if a_elev_f is not None:
            _is_neut_elev = (_espn_v or {}).get("neutral_site", False)
            _w(txt, "  [2] Elevation Adjustment\n", "section")
            if _is_neut_elev:
                _gvn2 = (_espn_v or {}).get("venue_name", "Game Venue")
                _w(txt, f"      â˜… NEUTRAL SITE â€” both teams away from home.\n", "warn")
                _w(txt, f"      Game Venue: {int(h_elev_use):,} ft  ({_gvn2})\n", "value")
                _d_away = int(h_elev_use) - int(a_elev_f)
                _d_tag_a = "warn" if abs(_d_away) > 200 else "value"
                _w(txt, f"      {away_clean} home: {int(a_elev_f):,} ft  â†’  {abs(_d_away):,} ft {'higher' if _d_away > 0 else 'lower'} than neutral venue\n", _d_tag_a)
                if home_row is not None:
                    _h_home_e = safe_float(safe(home_row, "elevation"), None, "he")
                    if _h_home_e is not None:
                        _d_home = int(h_elev_use) - int(_h_home_e)
                        _d_tag_h = "warn" if abs(_d_home) > 200 else "value"
                        _w(txt, f"      {home_clean} home: {int(_h_home_e):,} ft  â†’  {abs(_d_home):,} ft {'higher' if _d_home > 0 else 'lower'} than neutral venue\n", _d_tag_h)
                _max_d = max(abs(_d_away), abs(int(h_elev_use) - int(safe_float(safe(home_row,"elevation") if home_row is not None else "",0,"") or h_elev_use)))
                if _max_d < 100:
                    _w(txt, "      Elevation near both teams' norms â€” no material adjustment.\n", "value")
                else:
                    _pct_e = abs(_d_away) / 1000 * 0.8
                    _w(txt, f"      Effect: ~{_pct_e:.1f}% air density shift from away home norm.\n", "warn")
            else:
                _w(txt, "      Away Team Perspective\n", "label")
                delta = int(h_elev_use) - int(a_elev_f)
                _dir  = "HIGHER" if delta > 0 else "LOWER"
                _w(txt, f"      Home: {int(h_elev_use):,} ft  |  Away Home: {int(a_elev_f):,} ft  ({delta:+,} ft {_dir} than away norm)\n", "value")
                if abs(delta) < 100:
                    _w(txt,  "      Elevation difference is negligible â€” no meaningful adjustment.\n", "value")
                elif delta > 0:
                    _pct_e2 = abs(delta) / 1000 * 0.8
                    _w(txt, f"      Elevation-only effect: ~{_pct_e2:.1f}% thinner air at home vs away norm.\n", "warn")
                    _w(txt, f"      {_AWAY_UP_MSG}\n", "warn")
                else:
                    _w(txt, f"      Away team stepping DOWN {abs(delta):,} ft from their home elevation.\n", "good")
                    _w(txt, f"      {_AWAY_DOWN_MSG}\n", "good")
            _w(txt, "\n", "value")

        _w(txt, "  [3] Wind Effect\n", "section")
        if is_indoor:
            _w(txt, "      Indoor/closed-roof venue â€” wind is climate-controlled.\n", "value")
            _w(txt, "      Wind excluded from scoring model. Density + elevation apply at full weight.\n", "value")
            wind_verdict = "neutral"
        elif abs(head) < 2:
            _w(txt, f"      Effectively calm ({head:.1f} mph at plate).\n", "value")
            _w(txt,  "      No meaningful wind influence on carry in either direction.\n", "value")
            wind_verdict = "neutral"
        elif head < 0:
            _w(txt, f"      {abs(head):.1f} mph HEADWIND â€” blowing IN toward play.\n", "good")
            _w(txt, f"      \u2192 {_HW_MSG}\n", "good")
            wind_verdict = "carry-"
        else:
            _w(txt, f"      {head:.1f} mph TAILWIND â€” blowing OUT away from play.\n", "warn")
            _w(txt, f"      \u2192 {_TW_MSG}\n", "warn")
            wind_verdict = "carry+"
        if not is_indoor and abs(cross) >= 2:
            _cdir = "right-to-left" if cross < 0 else "left-to-right"
            _w(txt, f"      Crosswind: {abs(cross):.1f} mph {_cdir} â€” affects trajectory and carry direction.\n", "value")
        _w(txt, "\n", "value")
    else:
        air_verdict  = None
        wind_verdict = None

    # â”€â”€ NET VERDICT â”€â”€
    _w(txt, "\n  NET VERDICT\n", "section")
    _sep(txt, "â”€", W)
    _w(txt, "  â˜… Verdict derived solely from station data + vector physics. No scraped data involved.\n", "na")

    if pct is None or rho is None:
        # No real physics data â€” never show a verdict based on missing data
        _w(txt, "  \u23f3  Weather data pending â€” NET VERDICT will populate once live conditions are loaded.\n", "na")
        _w(txt, "  Physics requires: temperature, pressure, humidity, wind speed/direction.\n", "na")
    else:
        # Load adaptive model weights â€” tuned from graded pick history
        import json as _json_mw
        _MW_PATH = os.path.join(ODDS_DIR, "model_weights.json")
        try:
            with open(_MW_PATH) as _mwf: _mw = _json_mw.load(_mwf)
        except Exception: _mw = {}
        def _w8(k): return float(_mw.get(sport, {}).get(k, 1.0))

        # Full physics every sport â€” wind zeroed for confirmed indoor only
        carry_score = -pct * _w8("air_density")
        wind_score  = (head * _w8("headwind")) if not is_indoor else 0.0
        net         = carry_score + wind_score

        # Sport-specific labels and descriptions
        _O_LBL = {"MLB":"OFFENSE-FRIENDLY","NHL":"HIGH-SCORING LEAN","NBA":"HIGH-SCORING LEAN",
                   "NFL":"OFFENSE-FRIENDLY","NCAAB":"HIGH-SCORING LEAN","NCAAF":"OFFENSE-FRIENDLY"}.get(sport,"OFFENSE-FRIENDLY")
        _U_LBL = {"MLB":"PITCHER-FRIENDLY","NHL":"LOW-SCORING LEAN","NBA":"LOW-SCORING LEAN",
                   "NFL":"DEFENSE-FRIENDLY","NCAAB":"LOW-SCORING LEAN","NCAAF":"DEFENSE-FRIENDLY"}.get(sport,"DEFENSE-FRIENDLY")
        _O_MSG = {"MLB":"Thin air and/or tailwind boost ball carry. Power offense aided.",
                  "NHL":"Lower air density and/or tailwind aid puck carry. High-scoring environment.",
                  "NBA":"Thinner air extends shot arcs. Elevation fatigue opens late-period scoring.",
                  "NFL":"Thin air extends kick range and passing carry. Passing/FG game aided.",
                  "NCAAB":"Altitude reduces drag and opens scoring. Fatigue advantage to home team.",
                  "NCAAF":"Thin air aids kicking game and deep routes. OVER lean."}.get(sport,"")
        _U_MSG = {"MLB":"Dense air and/or headwind suppress carry. Pitcher-friendly, fly balls die.",
                  "NHL":"Dense air increases puck drag. Headwind limits zone entry carry. UNDER lean.",
                  "NBA":"Dense air adds shot resistance marginally. Low-energy cold environment.",
                  "NFL":"Dense air suppresses kick distance and passing carry. Run game favored.",
                  "NCAAB":"Dense air adds resistance. Cold/heavy air tightens play.",
                  "NCAAF":"Dense air limits kicking and deep passing. Conservative offense."}.get(sport,"")

        mw_active = [f"{k}={_w8(k):.2f}" for k in ["air_density","headwind","elevation"]
                     if abs(_w8(k)-1.0) > 0.02]
        if mw_active:
            _w(txt, f"  [Adaptive weights active: {', '.join(mw_active)}]\n", "na")
        if is_indoor:
            _w(txt, "  [Indoor venue: ambient wind suppressed in scoring model â€” elevation/density full weight]\n", "na")

        if net > 4:
            _w(txt, f"  {_O_LBL} environment.\n", "warn")
            _w(txt, f"  {_O_MSG}\n", "warn")
            _w(txt, "  Environmental lean: OVER (all else equal).\n", "warn")
        elif net < -4:
            _w(txt, f"  {_U_LBL} environment.\n", "good")
            _w(txt, f"  {_U_MSG}\n", "good")
            _w(txt, "  Environmental lean: UNDER (all else equal).\n", "good")
        else:
            pos_f, neg_f = [], []
            if air_verdict == "carry+":             pos_f.append(f"thin air ({abs(pct):.1f}% below standard)")
            if air_verdict == "carry-":             neg_f.append(f"dense air (+{pct:.1f}% above standard)")
            if wind_verdict == "carry+" and not is_indoor: pos_f.append(f"{head:.1f} mph tailwind")
            if wind_verdict == "carry-" and not is_indoor: neg_f.append(f"{abs(head):.1f} mph headwind")
            if not pos_f and not neg_f:
                _w(txt, "  NEUTRAL â€” no dominant environmental factor today.\n", "value")
                _w(txt, f"  Air density {abs(pct):.1f}% from standard, wind {abs(head):.1f} mph â€” within neutral range.\n", "value")
            else:
                _w(txt, "  MIXED â€” competing factors partially offset each other.\n", "value")
                if pos_f: _w(txt, f"  Offense-favoring: {', '.join(pos_f)}.\n", "warn")
                if neg_f: _w(txt, f"  Defense-favoring: {', '.join(neg_f)}.\n", "good")



    # â”€â”€ CIRCADIAN section render â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _render_circadian_section(txt, _circ, away_clean, home_clean, sport, W)

    # â”€â”€ DATA SOURCE COMPARISON  (Our Physics vs RotoWire) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # This section NEVER feeds the model. It is a sanity-check display only.
    # Our numbers = ground truth. RotoWire = reference for pattern-spotting.
    if sport == "MLB" and render_heavy:
        try:
            import importlib.util as _ilu
            _rw_path = os.path.join(ODDS_DIR, "rotowire_lineup_scraper.py")
            _rw_spec = _ilu.spec_from_file_location("rotowire_lineup_scraper", _rw_path)
            _rw_mod  = _ilu.module_from_spec(_rw_spec)
            _rw_spec.loader.exec_module(_rw_mod)
            _rw_rec  = _rw_mod.get_lineup_for_teams(away_clean, home_clean)
        except Exception:
            _rw_rec = None

        _w(txt, "\n  DATA SOURCE COMPARISON\n", "section")
        _sep(txt, "â”€", W)
        _w(txt, "  â˜… OUR STATION DATA IS PRIMARY â€” ALWAYS. "
                "RotoWire = reference/sanity-check only. Never touches model.\n", "warn")
        _w(txt, "\n", "na")

        # â”€â”€ Column headers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _w(txt, f"  {'FACTOR':<22}  {'OUR CALCULATION':<26}  {'ROTOWIRE':<20}  STATUS\n", "label")
        _w(txt, "  " + "â”€" * 78 + "\n", "sep")

        def _cmp_row(label, our_val, rw_val, agree_fn=None, our_tag="value"):
            """Print one comparison row with agreement/contrast tag."""
            our_str = str(our_val) if our_val not in (None, "", "N/A") else "â€”"
            rw_str  = str(rw_val)  if rw_val  not in (None, "", "N/A") else "â€”"
            if our_str == "â€”" or rw_str == "â€”":
                status, stag = "NO DATA", "na"
            elif agree_fn is None:
                status, stag = "â€”", "na"
            elif agree_fn(our_val, rw_val):
                status, stag = "âœ… CONSISTENT", "good"
            else:
                status, stag = "âš   CONTRAST", "warn"
            txt.insert(tk.END, f"  {label:<22}  ", "label")
            _w(txt,            f"{our_str:<26}  ", our_tag)
            _w(txt,            f"{rw_str:<20}  ")
            _w(txt, f"{status}\n", stag)

        # â”€â”€ Wind direction sanity check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Translate our head/cross into a cardinal label to compare with RW text
        def _our_wind_label(head_mph, cross_mph, is_dome):
            if is_dome:               return "DOME (suppressed)"
            if weather is None or weather == "error": return "â€”"
            if abs(head_mph) < 1.5 and abs(cross_mph) < 1.5:
                return "Calm (<1.5 mph)"
            if abs(head_mph) >= abs(cross_mph):
                return "INTO (headwind)" if head_mph < 0 else "OUT (tailwind)"
            else:
                return "CROSSWIND"

        def _rw_wind_agree(our_label, rw_dir):
            if not our_label or not rw_dir or our_label == "â€”": return None
            our_l = our_label.upper()
            rw_d  = str(rw_dir).upper().replace("-","").replace(" ","")
            # Map RotoWire direction strings to our label categories
            rw_is_out = any(x in rw_d for x in ("OUT","OUTFIELD"))
            rw_is_in  = any(x in rw_d for x in ("IN","INFIELD")) and "OUT" not in rw_d
            rw_is_x   = any(x in rw_d for x in ("LR","RL","LEFT","RIGHT","CROSS"))
            if "DOME" in our_l:          return True   # dome is dome â€” consistent by definition
            if "CALM" in our_l:          return True   # calm = direction irrelevant
            if rw_is_out and "OUT"  in our_l: return True
            if rw_is_in  and "INTO" in our_l: return True
            if rw_is_x   and "CROSS" in our_l: return True
            return False

        _rw_dir   = _rw_rec.get("wind_direction") if _rw_rec else None
        _rw_wspd  = _rw_rec.get("wind_speed")     if _rw_rec else None
        _our_wlbl = _our_wind_label(head if weather not in (None,"error") else 0,
                                     cross if weather not in (None,"error") else 0,
                                     is_indoor)

        our_wind_str = (f"{head:+.1f} mph headwind  {abs(cross):.1f} mph cross"
                        if weather not in (None,"error") and not is_indoor
                        else ("Dome â€” suppressed" if is_indoor else "â€”"))
        rw_wind_str  = (f"{_rw_wspd} mph {_rw_dir}" if _rw_wspd and _rw_dir
                        else (_rw_dir or "â€”"))

        _cmp_row("Wind Direction",
                 _our_wlbl, _rw_dir,
                 agree_fn=lambda o, r: _rw_wind_agree(o, r),
                 our_tag="value")
        _cmp_row("Wind Speed",
                 f"{weather['wind_speed']} mph @ {weather.get('wind_dir','')}Â°" if weather not in (None,"error") else "â€”",
                 f"{_rw_wspd} mph" if _rw_wspd else "â€”",
                 agree_fn=None)   # not comparable â€” different sources, display only

        # â”€â”€ Dome / indoor status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _rw_dome = _rw_rec.get("venue_type","") if _rw_rec else ""
        our_dome_str = "Dome / Indoor" if is_indoor else "Outdoor"
        rw_dome_str  = _rw_dome or "â€”"
        _cmp_row("Venue Type",
                 our_dome_str, rw_dome_str,
                 agree_fn=lambda o, r: ("Dome" in (r or "")) == ("Indoor" in (o or "") or "Dome" in (o or "")))

        # â”€â”€ Lineup status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _rw_both = _rw_rec.get("both_confirmed", 0) if _rw_rec else 0
        _rw_a_st = _rw_rec.get("away_lineup_status","->") if _rw_rec else "->"
        _rw_h_st = _rw_rec.get("home_lineup_status","->") if _rw_rec else "->"
        _rw_lu_str = (f"âœ… Both Confirmed" if _rw_both
                      else f"A:{_rw_a_st[:4]}  H:{_rw_h_st[:4]}")
        _cmp_row("Lineup Status", "MLB API + RotoWire gate", _rw_lu_str, agree_fn=None)

        # â”€â”€ Catchers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _rw_ac = _rw_rec.get("away_catcher","->") if _rw_rec else "->"
        _rw_hc = _rw_rec.get("home_catcher","->") if _rw_rec else "->"
        _cmp_row("Away Catcher",  "From MLB boxscore", _rw_ac or "â€”", agree_fn=None)
        _cmp_row("Home Catcher",  "From MLB boxscore", _rw_hc or "â€”", agree_fn=None)

        # â”€â”€ O/U line â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _rw_ou = _rw_rec.get("ou_line") if _rw_rec else None
        _cmp_row("O/U Line", total or "â€”", f"{_rw_ou}" if _rw_ou else "â€”", agree_fn=None)

        # â”€â”€ Umpire â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Umpire is RotoWire-exclusive data â€” not in our stack yet
        _rw_ump  = _rw_rec.get("umpire_name") if _rw_rec else None
        _rw_rpg  = _rw_rec.get("umpire_rpg")  if _rw_rec else None
        _rw_kpg  = _rw_rec.get("umpire_kpg")  if _rw_rec else None
        if _rw_ump:
            _w(txt, "\n  UMPIRE DATA  (RotoWire â€” additional context for O/U)\n", "section")
            _sep(txt, "â”€", W)
            txt.insert(tk.END, f"  {'Umpire':<22}", "label")
            _w(txt, f"{_rw_ump}\n", "value")
            if _rw_rpg is not None:
                rpg_tag = "warn" if _rw_rpg > 10.5 else "good" if _rw_rpg < 8.5 else "value"
                txt.insert(tk.END, f"  {'Runs/Game called':<22}", "label")
                _w(txt, f"{_rw_rpg}  ", rpg_tag)
                note = ("HIGH â€” umpire calls a big zone, run scoring elevated" if _rw_rpg > 10.5
                        else "LOW â€” tight zone, pitching-friendly game called" if _rw_rpg < 8.5
                        else "AVERAGE â€” neutral run environment")
                _w(txt, f"({note})\n", rpg_tag)
            if _rw_kpg is not None:
                kpg_tag = "good" if _rw_kpg > 18 else "warn" if _rw_kpg < 13 else "value"
                txt.insert(tk.END, f"  {'Strikeouts/Game':<22}", "label")
                _w(txt, f"{_rw_kpg}  ", kpg_tag)
                k_note = ("HIGH K/G â€” this umpire calls strikes, pitcher K% gets boost" if _rw_kpg > 18
                          else "LOW K/G â€” liberal ball calls, walk rates may rise" if _rw_kpg < 13
                          else "AVERAGE K/G â€” standard game called")
                _w(txt, f"({k_note})\n", kpg_tag)

        _w(txt, "\n", "na")
        _sep(txt, "â”€", W)
        _w(txt, "  â˜…  CONTRAST rows = investigate, not override.\n", "warn")
        _w(txt, "  â˜…  OUR STATION DATA IS PRIMARY â€” ALWAYS.\n", "warn")
        _w(txt, "     Physics calc never reads RotoWire wind, dome, or any scraped field.\n", "na")
    elif sport == "MLB":
        _w(txt, "\n  DATA SOURCE COMPARISON\n", "section")
        _sep(txt, "â”€", W)
        _w(txt, "  â³ Auto-loading full source-comparison panel in background.\n", "na")

    # â”€â”€ Stats + SOS section (appended last â€” toggled via Fetch button) â”€â”€â”€â”€â”€â”€
    if STATS_SOS_AVAILABLE and render_heavy:
        _render_stats_sos_block(txt, sport, away_clean, home_clean)
    elif STATS_SOS_AVAILABLE:
        _w(txt, "\n  TEAM STATS + SOS INTEGRATION\n", "section")
        _sep(txt, "=", W)
        _w(txt, "  â³ Auto-loading full stats/SOS panel in background.\n", "na")

    txt.config(state=tk.DISABLED)
    txt.see("1.0")



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MLB PRE-GAME DB READER  â€”  reads mlb_pregame.db for detail popup
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _mlb_db_lookup(home_team, away_team, game_date=None):
    """
    Pulls pitcher stats, team offense, and catcher data from mlb_pregame.db.
    Returns dict with keys: home_sp, away_sp, home_team, away_team,
                             home_catcher, away_catcher, matchup
    Returns None if DB not found or no data for today.
    """
    import sqlite3 as _sq3
    from datetime import date as _date
    db_path = os.path.join(ODDS_DIR, "mlb_pregame.db")
    if not os.path.exists(db_path):
        return None
    gd = game_date or str(_date.today())
    try:
        con = _sq3.connect(db_path)
        con.row_factory = _sq3.Row
        def _fuzz(name, col):
            # fuzzy match: any word >=4 chars from name appears in col value
            parts = [p for p in (name or "").split() if len(p) >= 4]
            if not parts: return "1=0"
            return " OR ".join([f"LOWER({col}) LIKE '%{p.lower()}%'" for p in parts])

        def _query_team(name):
            q = f"""SELECT * FROM team_stats
                    WHERE ({_fuzz(name,'team_name')})
                    ORDER BY
                      ((ops IS NOT NULL) +
                       (xwoba IS NOT NULL) +
                       (hard_hit_pct IS NOT NULL) +
                       (barrel_pct IS NOT NULL) +
                       (ops_vs_rhp IS NOT NULL) +
                       (ops_vs_lhp IS NOT NULL) +
                       (runs_last14 IS NOT NULL) +
                       (ops_last14 IS NOT NULL) +
                       (bullpen_era_7d IS NOT NULL) +
                       (bullpen_ip_3d IS NOT NULL)) DESC,
                      fetched_date DESC, id DESC LIMIT 1"""
            row = con.execute(q).fetchone()
            return dict(row) if row else {}

        def _query_sp(name, expected_team=None):
            if not name:
                return {}
            team_clause = f" AND ({_fuzz(expected_team,'team_name')})" if expected_team else ""
            q = f"""SELECT * FROM starter_stats
                    WHERE ({_fuzz(name,'player_name')}){team_clause}
                    ORDER BY
                      ((CASE WHEN throws IS NOT NULL AND TRIM(throws) <> '' THEN 1 ELSE 0 END) +
                       (xera IS NOT NULL) +
                       (whiff_pct IS NOT NULL) +
                       (hard_hit_pct IS NOT NULL) +
                       (barrel_pct IS NOT NULL) +
                       (avg_velo IS NOT NULL) +
                       (avg_spin IS NOT NULL) +
                       (era_last3 IS NOT NULL) +
                       (avg_pc_last3 IS NOT NULL) +
                       (density_sensitivity IS NOT NULL) +
                       (xwoba_against IS NOT NULL)) DESC,
                      fetched_date DESC, id DESC LIMIT 1"""
            row = con.execute(q).fetchone()
            if not row and expected_team:
                q2 = f"""SELECT * FROM starter_stats
                         WHERE ({_fuzz(name,'player_name')})
                         ORDER BY fetched_date DESC, id DESC LIMIT 1"""
                row = con.execute(q2).fetchone()
            return dict(row) if row else {}

        def _query_catcher(team_name):
            q = f"""SELECT * FROM catcher_stats
                    WHERE ({_fuzz(team_name,'team_name')})
                   AND fetched_date=?
                    ORDER BY fetched_date DESC LIMIT 1"""
            row = con.execute(q, (gd,)).fetchone()
            if not row:
                q2 = f"""SELECT * FROM catcher_stats
                         WHERE ({_fuzz(team_name,'team_name')})
                         ORDER BY fetched_date DESC LIMIT 1"""
                row = con.execute(q2).fetchone()
            return dict(row) if row else {}

        def _query_matchup(home, away):
            q = f"""SELECT * FROM pregame_matchups
                   WHERE game_date=? AND (
                        ({_fuzz(home,'home_team')}) AND ({_fuzz(away,'away_team')})
                    ) ORDER BY
                      ((CASE WHEN away_starter IS NOT NULL AND TRIM(away_starter) <> '' THEN 1 ELSE 0 END) +
                       (CASE WHEN home_starter IS NOT NULL AND TRIM(home_starter) <> '' THEN 1 ELSE 0 END) +
                       (CASE WHEN matchup_summary IS NOT NULL AND TRIM(matchup_summary) <> '' THEN 1 ELSE 0 END) +
                       (CASE WHEN lineup_confirmed IS NOT NULL THEN 1 ELSE 0 END)) DESC,
                      id DESC LIMIT 1"""
            row = con.execute(q, (gd,)).fetchone()
            return dict(row) if row else {}

        matchup = _query_matchup(home_team, away_team)
        home_sp_name = matchup.get("home_starter") if matchup else None
        away_sp_name = matchup.get("away_starter") if matchup else None
        result = {
            "home_sp":      _query_sp(home_sp_name, expected_team=home_team),
            "away_sp":      _query_sp(away_sp_name, expected_team=away_team),
            "home_team_st": _query_team(home_team),
            "away_team_st": _query_team(away_team),
            "home_catcher": _query_catcher(home_team),
            "away_catcher": _query_catcher(away_team),
            "matchup":      matchup,
        }
        con.close()
        return result
    except Exception as e:
        return None


_MLB_GAME_CONTEXT_CACHE = {}
_HIST_WEATHER_CACHE = {}


def _mlb_num(v):
    try:
        if v is None or str(v).strip() in ("", "None", "nan", "â€”"):
            return None
        return float(v)
    except Exception:
        return None


SPORT_ENV_LOAD_SCALE = {
    "MLB":   0.055,
    "NBA":   0.075,
    "NHL":   0.065,
    "NFL":   0.050,
    "NCAAB": 0.070,
    "NCAAF": 0.045,
}


def _venue_row_from_game(last_game, preferred_league=None):
    """Best-effort venue row lookup for a prior game event."""
    if not isinstance(last_game, dict) or df is None or getattr(df, "empty", True):
        return {}
    try:
        frame = df
        if preferred_league:
            try:
                scoped = frame[frame["league"].apply(lambda lg: _same_league_tag(lg, preferred_league))]
                if not scoped.empty:
                    frame = scoped
            except Exception:
                pass

        lat = _mlb_num(last_game.get("venue_lat"))
        lon = _mlb_num(last_game.get("venue_lon"))
        if lat is not None and lon is not None and {"lat", "lon"}.issubset(frame.columns):
            cand = frame.copy()
            cand = cand[(cand["lat"].notna()) & (cand["lon"].notna())]
            if not cand.empty:
                try:
                    d2 = (cand["lat"].astype(float) - lat) ** 2 + (cand["lon"].astype(float) - lon) ** 2
                    idx = d2.idxmin()
                    if float(d2.loc[idx]) <= 1.0:
                        return cand.loc[idx].to_dict()
                except Exception:
                    pass

        venue = str(last_game.get("venue_name") or "").strip().lower()
        city = str(last_game.get("city") or "").strip().lower()
        state = str(last_game.get("state") or "").strip().lower()
        cand = frame.copy()
        if venue and "venue" in cand.columns:
            exact = cand[cand["venue"].astype(str).str.strip().str.lower() == venue]
            if not exact.empty:
                if city and "city" in exact.columns:
                    city_exact = exact[exact["city"].astype(str).str.strip().str.lower() == city]
                    if not city_exact.empty:
                        exact = city_exact
                return exact.iloc[0].to_dict()
            contains = cand[cand["venue"].astype(str).str.lower().str.contains(venue, na=False)]
            if not contains.empty:
                return contains.iloc[0].to_dict()

        if city and "city" in cand.columns:
            city_match = cand[cand["city"].astype(str).str.strip().str.lower() == city]
            if state and "state" in city_match.columns and not city_match.empty:
                state_match = city_match[city_match["state"].astype(str).str.strip().str.lower() == state]
                if not state_match.empty:
                    city_match = state_match
            if not city_match.empty:
                return city_match.iloc[0].to_dict()
    except Exception:
        pass
    return {}


def _team_environment_load_model(
    team_name, sport, team_home_row, current_venue_row,
    circ_state=None, rho_pct=None, weather=None
):
    """Reusable per-team environmental load score.

    load_score: 0-10 toll/strain score from travel + venue + game-time conditions.
    execution_penalty: normalized drag on execution for downstream models.
    """
    circ_state = circ_state or {}
    team_home_row = team_home_row or {}
    current_venue_row = current_venue_row or {}
    weather = weather or {}

    home_elev = _mlb_num(team_home_row.get("elevation"))
    game_elev = _mlb_num(current_venue_row.get("elevation"))
    last_game = circ_state.get("last_game") or {}
    last_row = _venue_row_from_game(last_game, preferred_league=sport)
    last_elev = _mlb_num(last_row.get("elevation"))
    last_lat = _mlb_num(last_game.get("venue_lat"))
    if last_lat is None:
        last_lat = _mlb_num(last_row.get("lat"))
    last_lon = _mlb_num(last_game.get("venue_lon"))
    if last_lon is None:
        last_lon = _mlb_num(last_row.get("lon"))
    tz_diff = abs(int(_mlb_num(circ_state.get("tz_diff")) or 0))
    days_rest = _mlb_num(circ_state.get("days_rest"))
    road_trip_len = int(_mlb_num(circ_state.get("road_trip_len")) or 0)
    condensed = bool(circ_state.get("condensed"))
    just_home = bool(circ_state.get("just_home"))
    risk_score = _mlb_num(circ_state.get("risk_score")) or 0.0
    temp = _mlb_num(weather.get("temp"))
    humidity = _mlb_num(weather.get("humidity"))
    pressure = _mlb_num(weather.get("pressure"))
    wind_speed = _mlb_num(weather.get("wind_speed"))
    rho_shift = abs(_mlb_num(rho_pct) or 0.0)

    score = 0.0
    notes = []
    components = {}

    comp = 0.0
    if tz_diff >= 3:
        comp += 2.4
        notes.append(f"{tz_diff} time zones from last game")
    elif tz_diff == 2:
        comp += 1.6
        notes.append("2 time zones from last game")
    elif tz_diff == 1:
        comp += 0.75
    if days_rest is not None:
        if days_rest <= 0:
            comp += 2.0
            notes.append("zero days rest")
        elif days_rest <= 1:
            comp += 1.1
            notes.append("short rest")
        elif days_rest == 2:
            comp += 0.45
        elif days_rest >= 4:
            comp = max(0.0, comp - 0.20)
    if condensed:
        comp += 1.0
        notes.append("condensed schedule")
    if road_trip_len >= 5:
        comp += 1.6
        notes.append(f"deep road sequence (game {road_trip_len})")
    elif road_trip_len >= 3:
        comp += 0.9
    elif road_trip_len >= 1:
        comp += 0.35
    if just_home:
        comp += 0.55
        notes.append("just returned home from travel")
    components["travel_schedule"] = round(comp, 3)
    score += comp

    comp = min(rho_shift / 1.6, 2.4)
    if rho_shift >= 3.0:
        notes.append(f"air-density swing is major ({rho_shift:.1f}% vs baseline)")
    elif rho_shift >= 1.6:
        notes.append(f"air-density swing is meaningful ({rho_shift:.1f}% vs baseline)")
    components["density_delta"] = round(comp, 3)
    score += comp

    comp = 0.0
    if home_elev is not None and game_elev is not None:
        elev_home_delta = game_elev - home_elev
        comp += min(abs(elev_home_delta) / 1500.0, 2.1)
        if abs(elev_home_delta) >= 900:
            notes.append(f"elevation shift vs home baseline ({elev_home_delta:+.0f} ft)")
    else:
        elev_home_delta = None
    if last_elev is not None and game_elev is not None:
        elev_last_delta = game_elev - last_elev
        comp += min(abs(elev_last_delta) / 2200.0, 1.1)
        if abs(elev_last_delta) >= 900:
            notes.append(f"elevation jump vs last venue ({elev_last_delta:+.0f} ft)")
    else:
        elev_last_delta = None
    components["elevation_shift"] = round(comp, 3)
    score += comp

    comp = 0.0
    if temp is not None:
        if temp <= 40 or temp >= 92:
            comp += 0.95
            notes.append(f"temperature stress ({temp:.0f}F)")
        elif temp <= 48 or temp >= 85:
            comp += 0.45
    if humidity is not None:
        if humidity >= 82 or humidity <= 18:
            comp += 0.40
        elif humidity >= 72 or humidity <= 28:
            comp += 0.18
    if pressure is not None:
        comp += min(abs(pressure - 29.92) / 0.20, 0.75)
    components["weather_stress"] = round(comp, 3)
    score += comp

    comp = 0.0
    last_weather = None
    current_hour = _hour_from_any_dt(circ_state.get("game_time_iso"), default_hour=19)
    if last_game and last_lat is not None and last_lon is not None and last_game.get("date"):
        last_hour = _hour_from_any_dt(last_game.get("game_time_iso"), default_hour=current_hour)
        last_weather = _historical_weather_at_time(last_lat, last_lon, last_game.get("date"), target_hour=last_hour)
    if last_weather:
        last_rho = _mlb_num(last_weather.get("rho"))
        curr_rho = None
        if temp is not None and humidity is not None and pressure is not None:
            try:
                curr_rho = air_density(temp, pressure, humidity)
            except Exception:
                curr_rho = None
        if curr_rho is not None and last_rho is not None and last_rho > 0:
            rho_delta_pct = abs((curr_rho - last_rho) / last_rho * 100.0)
            comp += min(rho_delta_pct / 1.8, 2.2)
            if rho_delta_pct >= 3.0:
                notes.append(f"major density change since last game ({rho_delta_pct:.1f}%)")
            elif rho_delta_pct >= 1.5:
                notes.append(f"density changed since last game ({rho_delta_pct:.1f}%)")
        else:
            rho_delta_pct = None
        last_temp = _mlb_num(last_weather.get("temp"))
        if temp is not None and last_temp is not None:
            temp_delta = abs(temp - last_temp)
            comp += min(temp_delta / 22.0, 0.9)
            if temp_delta >= 18:
                notes.append(f"temperature swung {temp_delta:.0f}F since last game")
        else:
            temp_delta = None
        last_pressure = _mlb_num(last_weather.get("pressure"))
        if pressure is not None and last_pressure is not None:
            pressure_delta = abs(pressure - last_pressure)
            comp += min(pressure_delta / 0.22, 0.8)
            if pressure_delta >= 0.18:
                notes.append(f"pressure moved {pressure_delta:.2f} inHg since last game")
        else:
            pressure_delta = None
        last_snow = _mlb_num(last_weather.get("snowfall")) or 0.0
        last_precip = _mlb_num(last_weather.get("precip")) or 0.0
        if last_snow >= 2.0:
            comp += 1.0
            notes.append(f"last game had snowfall ({last_snow:.1f})")
        elif last_precip >= 6.0:
            comp += 0.55
            notes.append(f"last game had heavy precipitation ({last_precip:.1f})")
        last_wind = _mlb_num(last_weather.get("wind_speed"))
        if last_wind is not None and wind_speed is not None:
            wind_delta = abs(wind_speed - last_wind)
            comp += min(wind_delta / 18.0, 0.6)
        else:
            wind_delta = None
    else:
        rho_delta_pct = temp_delta = pressure_delta = wind_delta = None
    components["prior_game_weather_delta"] = round(comp, 3)
    score += comp

    score = max(0.0, min(10.0, round(score, 2)))
    exec_scale = SPORT_ENV_LOAD_SCALE.get(sport, 0.055)
    execution_penalty = round(min(score * exec_scale, 0.85), 3)
    if risk_score >= 7.0:
        execution_penalty = round(min(execution_penalty + 0.05, 0.85), 3)

    return {
        "team": team_name,
        "load_score": score,
        "execution_penalty": execution_penalty,
        "notes": notes[:5],
        "components": components,
        "rho_shift_pct": round(rho_shift, 3),
        "risk_score": risk_score,
        "tz_diff": tz_diff,
        "days_rest": days_rest,
        "road_trip_len": road_trip_len,
        "home_elev": home_elev,
        "game_elev": game_elev,
        "last_elev": last_elev,
        "elev_delta_home": elev_home_delta,
        "elev_delta_last": elev_last_delta,
        "last_weather": last_weather,
        "rho_delta_last_pct": round(rho_delta_pct, 3) if rho_delta_pct is not None else None,
        "temp_delta_last": round(temp_delta, 2) if temp_delta is not None else None,
        "pressure_delta_last": round(pressure_delta, 3) if pressure_delta is not None else None,
        "wind_delta_last": round(wind_delta, 2) if wind_delta is not None else None,
    }


def _parse_pitch_arsenal(raw):
    try:
        if isinstance(raw, str):
            return json.loads(raw or "{}")
        return raw or {}
    except Exception:
        return {}


def _hour_from_any_dt(value, default_hour=19):
    try:
        if value is None:
            return default_hour
        s = str(value).strip()
        if not s:
            return default_hour
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).hour
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%m/%d %I:%M%p", "%m/%d %H:%M"):
            try:
                return datetime.strptime(s, fmt).hour
            except Exception:
                continue
    except Exception:
        pass
    return default_hour


def _historical_weather_at_time(lat, lon, date_str, target_hour=19):
    """Fetch archived hourly weather nearest the requested hour."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    if not date_str:
        return None

    cache_key = (round(lat_f, 4), round(lon_f, 4), str(date_str), int(target_hour))
    if cache_key in _HIST_WEATHER_CACHE:
        return _HIST_WEATHER_CACHE[cache_key]

    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat_f}&longitude={lon_f}"
        f"&start_date={date_str}&end_date={date_str}"
        "&hourly=temperature_2m,relative_humidity_2m,pressure_msl,wind_speed_10m,wind_direction_10m,precipitation,snowfall"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
    )
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        d = r.json() or {}
        hourly = d.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            _HIST_WEATHER_CACHE[cache_key] = None
            return None

        target_hour = int(target_hour) % 24
        best_idx = None
        best_diff = 999
        for idx, ts in enumerate(times):
            hh = _hour_from_any_dt(ts, default_hour=target_hour)
            diff = abs(hh - target_hour)
            diff = min(diff, 24 - diff)
            if diff < best_diff:
                best_diff = diff
                best_idx = idx
        if best_idx is None:
            _HIST_WEATHER_CACHE[cache_key] = None
            return None

        pressure_hpa = None
        for key in ("pressure_msl", "surface_pressure"):
            seq = hourly.get(key) or []
            if best_idx < len(seq):
                pressure_hpa = seq[best_idx]
                if pressure_hpa is not None:
                    break

        result = {
            "time_local": times[best_idx],
            "temp": _mlb_num((hourly.get("temperature_2m") or [None])[best_idx] if best_idx < len(hourly.get("temperature_2m") or []) else None),
            "humidity": _mlb_num((hourly.get("relative_humidity_2m") or [None])[best_idx] if best_idx < len(hourly.get("relative_humidity_2m") or []) else None),
            "pressure": (_mlb_num(pressure_hpa) * 0.02953) if pressure_hpa is not None else None,
            "wind_speed": _mlb_num((hourly.get("wind_speed_10m") or [None])[best_idx] if best_idx < len(hourly.get("wind_speed_10m") or []) else None),
            "wind_dir": _mlb_num((hourly.get("wind_direction_10m") or [None])[best_idx] if best_idx < len(hourly.get("wind_direction_10m") or []) else None),
            "precip": _mlb_num((hourly.get("precipitation") or [None])[best_idx] if best_idx < len(hourly.get("precipitation") or []) else None),
            "snowfall": _mlb_num((hourly.get("snowfall") or [None])[best_idx] if best_idx < len(hourly.get("snowfall") or []) else None),
        }
        if result["temp"] is not None and result["humidity"] is not None and result["pressure"] is not None:
            result["rho"] = air_density(result["temp"], result["pressure"], result["humidity"])
        else:
            result["rho"] = None
        _HIST_WEATHER_CACHE[cache_key] = result
        return result
    except Exception as ex:
        log(f"[hist_weather] {date_str} {lat_f},{lon_f} failed: {ex}", "debug")
        _HIST_WEATHER_CACHE[cache_key] = None
        return None


def _mlb_pitch_environment_model(sp, own_env, opp_env, rho_pct, headwind, weather=None):
    """Dynamic pitcher environment effect from actual pitch mix and execution load."""
    arsenal = _parse_pitch_arsenal(sp.get("pitch_arsenal"))
    if not arsenal:
        return {"score": 0.0, "notes": [], "components": {}}

    MOVEMENT_TYPES = {"SI","CU","SL","KC","FS","FC","CS","KN","SC","ST","SVB","SV","CH"}
    FLAT_TYPES     = {"FF","FA"}
    rho_factor = 1.0 + ((_mlb_num(rho_pct) or 0.0) / 100.0)
    own_drag = _mlb_num((own_env or {}).get("execution_penalty")) or 0.0
    opp_drag = _mlb_num((opp_env or {}).get("execution_penalty")) or 0.0
    avg_pc3 = _mlb_num(sp.get("avg_pc_last3")) or 90.0
    temp = _mlb_num((weather or {}).get("temp"))

    movement_score = 0.0
    total_usage = 0.0
    break_share = 0.0
    flat_share = 0.0
    notes = []
    for pt, pdata in arsenal.items():
        usage = max(0.0, _mlb_num(pdata.get("usage_pct")) or 0.0)
        if usage <= 0:
            continue
        usage_share = usage / 100.0
        ivb = abs(_mlb_num(pdata.get("ivb")) or 0.0)
        hb = abs(_mlb_num(pdata.get("hb")) or 0.0)
        spin = _mlb_num(pdata.get("spin")) or _mlb_num(sp.get("avg_spin")) or 2200.0
        whiff = _mlb_num(pdata.get("whiff_pct"))
        base_shape = ivb + hb
        sens = 1.0 if pt.upper() in MOVEMENT_TYPES else 0.35 if pt.upper() in FLAT_TYPES else 0.60
        if pt.upper() in MOVEMENT_TYPES:
            break_share += usage_share
        if pt.upper() in FLAT_TYPES:
            flat_share += usage_share
        whiff_adj = 0.0
        if whiff is not None:
            whiff_adj = max(-0.08, min(0.08, (whiff - 24.0) / 100.0))
        spin_shape = 0.55 + min(max((spin - 1800.0) / 900.0, 0.0), 1.0) * 0.45
        density_move = (rho_factor - 1.0) * sens * (0.70 + min(base_shape / 26.0, 1.2) * 0.30) * spin_shape
        movement_score += usage_share * (density_move + whiff_adj)
        total_usage += usage_share

    workload_drag = own_drag * (0.42 + break_share * 0.30 + flat_share * 0.12)
    if avg_pc3 >= 95:
        workload_drag += 0.05
    if temp is not None and temp <= 45:
        workload_drag += 0.03

    headwind_bonus = 0.0
    fb = _mlb_num(sp.get("fb_pct")) or 0.0
    if headwind is not None:
        if headwind < -3.0:
            headwind_bonus += min(abs(headwind) / 16.0, 1.0) * (0.10 + max(fb - 30.0, 0.0) / 120.0)
        elif headwind > 3.0:
            headwind_bonus -= min(abs(headwind) / 16.0, 1.0) * (0.08 + max(fb - 30.0, 0.0) / 140.0)

    opp_contact_drag = opp_drag * (0.24 + flat_share * 0.18 + break_share * 0.16)
    score = round(movement_score * 6.0 - workload_drag + headwind_bonus + opp_contact_drag, 3)

    if abs(movement_score) >= 0.04:
        notes.append(
            f"pitch-mix movement shift {movement_score:+.2f} from tonight's density"
        )
    if workload_drag >= 0.18:
        notes.append("environmental load is taxing pitch execution")
    if opp_contact_drag >= 0.12:
        notes.append("opponent hitting side is carrying real environmental tax")
    if abs(headwind_bonus) >= 0.06:
        notes.append("wind shape suppresses or extends contact window")

    return {
        "score": score,
        "notes": notes[:4],
        "components": {
            "movement_shift": round(movement_score * 6.0, 3),
            "execution_drag": round(-workload_drag, 3),
            "opponent_contact_drag": round(opp_contact_drag, 3),
            "wind_contact": round(headwind_bonus, 3),
        },
    }


def _mlb_offense_environment_model(tm, own_env, opp_pitch_env, rho_pct, headwind, weather=None):
    """Dynamic hitter-side environmental effect from contact quality + execution tax."""
    hh = _mlb_num(tm.get("hard_hit_pct")) or 34.0
    xwoba = _mlb_num(tm.get("xwoba")) or 0.315
    barrel = _mlb_num(tm.get("barrel_pct")) or 7.5
    own_drag = _mlb_num((own_env or {}).get("execution_penalty")) or 0.0
    opp_pitch_drag = max(0.0, -(_mlb_num((opp_pitch_env or {}).get("components", {}).get("execution_drag")) or 0.0))
    temp = _mlb_num((weather or {}).get("temp"))
    rho_pct = _mlb_num(rho_pct) or 0.0

    power_bias = min(max((hh - 32.0) / 10.0, 0.0), 1.2) * 0.45 + \
                 min(max((xwoba - 0.310) / 0.030, 0.0), 1.2) * 0.35 + \
                 min(max((barrel - 7.0) / 6.0, 0.0), 1.2) * 0.20

    carry_effect = 0.0
    if rho_pct >= 0:
        carry_effect -= min(rho_pct / 3.2, 1.6) * (0.12 + power_bias * 0.16)
    else:
        carry_effect += min(abs(rho_pct) / 3.2, 1.6) * (0.12 + power_bias * 0.16)

    wind_effect = 0.0
    if headwind is not None:
        if headwind < -3.0:
            wind_effect -= min(abs(headwind) / 16.0, 1.0) * (0.10 + power_bias * 0.12)
        elif headwind > 3.0:
            wind_effect += min(abs(headwind) / 16.0, 1.0) * (0.08 + power_bias * 0.10)

    execution_drag = own_drag * (0.42 + power_bias * 0.24)
    if temp is not None and temp <= 45:
        execution_drag += 0.03

    score = round(carry_effect + wind_effect - execution_drag + opp_pitch_drag * 0.65, 3)
    notes = []
    if abs(carry_effect) >= 0.08:
        notes.append("air-density shift is materially changing carry")
    if execution_drag >= 0.16:
        notes.append("offense is carrying environmental execution tax")
    if opp_pitch_drag >= 0.14:
        notes.append("opposing starter load opens contact windows")

    return {
        "score": score,
        "notes": notes[:4],
        "components": {
            "carry_effect": round(carry_effect, 3),
            "wind_effect": round(wind_effect, 3),
            "execution_drag": round(-execution_drag, 3),
            "opp_pitcher_strain": round(opp_pitch_drag * 0.65, 3),
        },
    }


def _mlb_pitcher_context_model(
    db_data, side_key, rho_pct, headwind, surface,
    circ=None, rr=None, elev_delta=None,
    own_env=None, opp_env=None, weather=None, pitch_env=None
):
    """Score one MLB starter's cumulative context.

    Positive score = favorable for that pitcher.
    Negative score = tougher for that pitcher.
    """
    if not db_data:
        return {"score": 0.0, "notes": [], "components": {}}

    sp = (db_data.get(f"{side_key}_sp") or {})
    opp_tm = (db_data.get("away_team_st" if side_key == "home" else "home_team_st") or {})
    catcher = (db_data.get(f"{side_key}_catcher") or {})
    own_state = (circ.get(f"{side_key}_state") or {}) if isinstance(circ, dict) else {}
    opp_state = (circ.get("away_state" if side_key == "home" else "home_state") or {}) if isinstance(circ, dict) else {}
    if not any([sp, opp_tm, catcher, own_state]):
        return {"score": 0.0, "notes": [], "components": {}}

    score = 0.0
    notes = []
    components = {}
    surface_l = str(surface or "").lower()

    throws = str(sp.get("throws") or "").strip().upper()[:1]
    split_key = "ops_vs_lhp" if throws == "L" else "ops_vs_rhp" if throws == "R" else None
    offense_ref = _mlb_num(opp_tm.get(split_key)) if split_key else None
    if offense_ref is None:
        offense_ref = _mlb_num(opp_tm.get("ops"))
    opp_xwoba = _mlb_num(opp_tm.get("xwoba"))
    opp_hh = _mlb_num(opp_tm.get("hard_hit_pct"))
    comp = 0.0
    if offense_ref is not None:
        if offense_ref >= 0.760:
            comp -= 0.55
            notes.append(f"opp split attack strong ({offense_ref:.3f} OPS)")
        elif offense_ref >= 0.720:
            comp -= 0.30
            notes.append(f"opp split attack above avg ({offense_ref:.3f} OPS)")
        elif offense_ref <= 0.660:
            comp += 0.35
            notes.append(f"opp split attack soft ({offense_ref:.3f} OPS)")
        elif offense_ref <= 0.690:
            comp += 0.15
            notes.append(f"opp split attack below avg ({offense_ref:.3f} OPS)")
    if opp_xwoba is not None:
        if opp_xwoba >= 0.330:
            comp -= 0.12
        elif opp_xwoba <= 0.305:
            comp += 0.08
    if opp_hh is not None:
        if opp_hh >= 38.0:
            comp -= 0.08
        elif opp_hh <= 31.0:
            comp += 0.05
    score += comp
    components["opponent_attack"] = round(comp, 3)

    gb = _mlb_num(sp.get("gb_pct"))
    fb = _mlb_num(sp.get("fb_pct"))
    dens_sens = _mlb_num(sp.get("density_sensitivity"))
    comp = 0.0
    if gb is not None and gb >= 48.0 and (rho_pct or 0) > 0.8:
        comp += 0.20
        notes.append(f"GB profile fits dense air ({gb:.1f}% GB)")
    elif fb is not None and fb >= 36.0 and headwind is not None and headwind < -3.0:
        comp += 0.16
        notes.append(f"FB profile protected by headwind ({fb:.1f}% FB)")
    elif fb is not None and fb >= 34.0 and (((rho_pct or 0) < -0.8) or (headwind is not None and headwind > 3.0)):
        comp -= 0.24
        notes.append(f"FB exposure amplified by carry conditions ({fb:.1f}% FB)")
    elif gb is not None and "grass" in surface_l:
        comp += 0.08
        notes.append("grass surface supports ground-ball contact management")
    if dens_sens is not None and rho_pct is not None:
        if dens_sens >= 0.68 and rho_pct > 0.8:
            comp += 0.12
        elif dens_sens >= 0.68 and rho_pct < -0.8:
            comp -= 0.12
    score += comp
    components["pitch_shape_fit"] = round(comp, 3)

    impact = _mlb_num(catcher.get("catcher_impact_score"))
    comp = 0.0
    if impact is not None:
        if impact >= 0.65:
            comp += 0.18
            notes.append(f"catcher support strong ({impact:.2f})")
        elif impact <= 0.35:
            comp -= 0.18
            notes.append(f"catcher support poor ({impact:.2f})")
    score += comp
    components["catcher_support"] = round(comp, 3)

    era = _mlb_num(sp.get("era"))
    era3 = _mlb_num(sp.get("era_last3"))
    avg_pc3 = _mlb_num(sp.get("avg_pc_last3"))
    avg_ip3 = _mlb_num(sp.get("avg_ip_last3"))
    comp = 0.0
    if era3 is not None:
        if era3 <= 3.20:
            comp += 0.16
            notes.append(f"recent form sharp ({era3:.2f} ERA last 3)")
        elif era3 >= 4.80:
            comp -= 0.16
            notes.append(f"recent form shaky ({era3:.2f} ERA last 3)")
    elif era is not None:
        if era <= 3.30:
            comp += 0.08
        elif era >= 4.70:
            comp -= 0.08
    if avg_pc3 is not None and avg_pc3 < 75:
        comp -= 0.06
        notes.append(f"workload ceiling light ({avg_pc3:.0f} avg pitches)")
    if avg_ip3 is not None and avg_ip3 >= 6.0:
        comp += 0.04
    score += comp
    components["form_workload"] = round(comp, 3)

    own_risk = _mlb_num(own_state.get("risk_score")) or 0.0
    opp_risk = _mlb_num(opp_state.get("risk_score")) or 0.0
    own_exec = _mlb_num((own_env or {}).get("execution_penalty")) or 0.0
    opp_exec = _mlb_num((opp_env or {}).get("execution_penalty")) or 0.0
    comp = 0.0
    if own_env:
        comp -= own_exec * 0.85
        if (own_env.get("load_score") or 0.0) >= 6.5:
            notes.append(
                f"pitcher environment load is heavy ({own_env.get('load_score'):.1f}/10)"
            )
    if opp_env:
        comp += opp_exec * 0.35
        if (opp_env.get("load_score") or 0.0) >= 6.5:
            notes.append(
                f"opposing offense environment load is heavy ({opp_env.get('load_score'):.1f}/10)"
            )
    if abs(opp_risk - own_risk) >= 1.0:
        comp += 0.10 if opp_risk > own_risk else -0.10
    score += comp
    components["travel_circadian"] = round(comp, 3)

    comp = 0.0
    if pitch_env:
        comp += _mlb_num(pitch_env.get("score")) or 0.0
        notes.extend(pitch_env.get("notes", [])[:2])
    else:
        if rho_pct is not None:
            if abs(rho_pct) >= 3.0:
                comp += 0.10 if rho_pct > 0 else -0.10
                notes.append(
                    f"baseline environment swing is material ({rho_pct:+.1f}% vs normal)"
                )
            elif abs(rho_pct) >= 1.5:
                comp += 0.05 if rho_pct > 0 else -0.05
        if elev_delta is not None and side_key == "away":
            if elev_delta >= 1000:
                comp -= 0.10
                notes.append(f"away starter stepping up sharply in elevation ({elev_delta:+.0f} ft)")
            elif elev_delta <= -1000:
                comp += 0.06
    score += comp
    components["environment_load"] = round(comp, 3)

    comp = 0.0
    if rr and rr.get("ump_name"):
        sc = rr.get("scorecard") if isinstance(rr, dict) else None
        if sc is None and _REF_ENGINE_OK and _rse_mod and hasattr(_rse_mod, "_get_ump_scorecard"):
            try:
                sc = _rse_mod._get_ump_scorecard(rr["ump_name"])
            except Exception:
                sc = None
        if sc:
            aae = _mlb_num(sc.get("aae"))
            kpg = _mlb_num(sc.get("k_per_game"))
            if aae is not None and aae >= 1.5:
                comp += 0.12
                notes.append(f"umpire zone supports pitchers ({rr.get('ump_name')})")
            elif aae is not None and aae <= -1.5:
                comp -= 0.12
                notes.append(f"umpire zone leans hitter friendly ({rr.get('ump_name')})")
            elif kpg is not None and kpg >= 18.0:
                comp += 0.08
            elif kpg is not None and kpg <= 13.0:
                comp -= 0.08
    score += comp
    components["umpire"] = round(comp, 3)

    return {
        "score": round(score, 3),
        "notes": notes,
        "components": components,
        "throws": throws,
        "pitcher_name": sp.get("player_name") or sp.get("pitcher_name") or sp.get("name"),
    }


def _mlb_offense_context_model(
    db_data, side_key, rho_pct, circ=None, elev_delta=None,
    own_env=None, opp_env=None, headwind=None, weather=None, offense_env=None
):
    """Score one MLB offense's cumulative context.

    Positive score = favorable for scoring.
    Negative score = suppressed run-scoring context.
    """
    if not db_data:
        return {"score": 0.0, "notes": [], "components": {}}

    tm = (db_data.get(f"{side_key}_team_st") or {})
    opp_sp = (db_data.get("away_sp" if side_key == "home" else "home_sp") or {})
    opp_team = (db_data.get("away_team_st" if side_key == "home" else "home_team_st") or {})
    own_state = (circ.get(f"{side_key}_state") or {}) if isinstance(circ, dict) else {}
    if not any([tm, opp_sp, own_state, opp_team]):
        return {"score": 0.0, "notes": [], "components": {}}

    score = 0.0
    notes = []
    components = {}

    opp_throws = str(opp_sp.get("throws") or "").strip().upper()[:1]
    split_key = "ops_vs_lhp" if opp_throws == "L" else "ops_vs_rhp" if opp_throws == "R" else None
    split_ops = _mlb_num(tm.get(split_key)) if split_key else None
    home_away_split = _mlb_num(tm.get("ops_home" if side_key == "home" else "ops_away"))
    season_ops = _mlb_num(tm.get("ops"))
    recent_ops = _mlb_num(tm.get("ops_last14"))
    recent_runs = _mlb_num(tm.get("runs_last14"))
    hh = _mlb_num(tm.get("hard_hit_pct"))
    xwoba = _mlb_num(tm.get("xwoba"))

    comp = 0.0
    attack_ref = split_ops if split_ops is not None else season_ops
    if attack_ref is not None:
        if attack_ref >= 0.760:
            comp += 0.34
            notes.append(f"split offense strong ({attack_ref:.3f} OPS)")
        elif attack_ref >= 0.720:
            comp += 0.18
        elif attack_ref <= 0.660:
            comp -= 0.26
            notes.append(f"split offense soft ({attack_ref:.3f} OPS)")
        elif attack_ref <= 0.690:
            comp -= 0.12
    if home_away_split is not None:
        if home_away_split >= 0.760:
            comp += 0.10
        elif home_away_split <= 0.660:
            comp -= 0.08
    if recent_ops is not None:
        if recent_ops >= 0.760:
            comp += 0.12
            notes.append(f"recent offense hot ({recent_ops:.3f} last 14d OPS)")
        elif recent_ops <= 0.660:
            comp -= 0.12
    if recent_runs is not None:
        if recent_runs >= 5.2:
            comp += 0.08
        elif recent_runs <= 3.6:
            comp -= 0.08
    if xwoba is not None:
        if xwoba >= 0.330:
            comp += 0.08
        elif xwoba <= 0.305:
            comp -= 0.08
    if hh is not None:
        if hh >= 38.0:
            comp += 0.06
        elif hh <= 31.0:
            comp -= 0.05
    score += comp
    components["offense_quality"] = round(comp, 3)

    comp = 0.0
    own_risk = _mlb_num(own_state.get("risk_score")) or 0.0
    own_exec = _mlb_num((own_env or {}).get("execution_penalty")) or 0.0
    opp_exec = _mlb_num((opp_env or {}).get("execution_penalty")) or 0.0
    if own_env:
        comp -= own_exec * 0.95
        if (own_env.get("load_score") or 0.0) >= 6.5:
            notes.append(f"offense environment load is heavy ({own_env.get('load_score'):.1f}/10)")
    else:
        if own_risk >= 6.0:
            comp -= 0.18
            notes.append(f"offense travel/body-clock tax elevated ({own_risk:.1f})")
        elif own_risk >= 4.0:
            comp -= 0.08
        elif own_risk <= 2.0:
            comp += 0.04
    if opp_env:
        comp += opp_exec * 0.18
    score += comp
    components["travel_circadian"] = round(comp, 3)

    comp = 0.0
    if offense_env:
        comp += _mlb_num(offense_env.get("score")) or 0.0
        notes.extend(offense_env.get("notes", [])[:2])
    else:
        fly_pull = 0.0
        if hh is not None:
            fly_pull += max(0.0, (hh - 34.0) / 12.0)
        if xwoba is not None:
            fly_pull += max(0.0, (xwoba - 0.315) / 0.05)
        if rho_pct is not None:
            if rho_pct >= 2.5:
                comp -= (0.10 + 0.06 * min(fly_pull, 1.5))
                notes.append(f"dense air suppresses this lineup's quality contact ({rho_pct:+.1f}%)")
            elif rho_pct <= -2.5:
                comp += (0.10 + 0.06 * min(fly_pull, 1.5))
                notes.append(f"thin air boosts this lineup's carry window ({rho_pct:+.1f}%)")
            elif rho_pct >= 1.2:
                comp -= 0.05
            elif rho_pct <= -1.2:
                comp += 0.05
        if elev_delta is not None:
            if side_key == "away" and elev_delta >= 1000:
                comp -= 0.08
                notes.append(f"away lineup stepping into altitude change ({elev_delta:+.0f} ft)")
            elif side_key == "away" and elev_delta <= -1000:
                comp += 0.05
    score += comp
    components["environment_shift"] = round(comp, 3)

    comp = 0.0
    opp_era7 = _mlb_num(opp_team.get("bullpen_era_7d"))
    opp_ip3 = _mlb_num(opp_team.get("bullpen_ip_3d"))
    if opp_ip3 is not None and opp_ip3 >= 11.0:
        comp += 0.14
        notes.append(f"opposing bullpen usage heavy ({opp_ip3:.1f} IP/3d)")
    elif opp_ip3 is not None and opp_ip3 <= 6.0:
        comp -= 0.04
    if opp_era7 is not None and opp_era7 >= 4.60:
        comp += 0.10
    elif opp_era7 is not None and opp_era7 <= 3.20:
        comp -= 0.08
    score += comp
    components["bullpen_layer"] = round(comp, 3)

    return {
        "score": round(score, 3),
        "notes": notes,
        "components": components,
        "split_key": split_key,
    }


def _mlb_game_context_model(
    home_team, away_team, game_date, rho_pct_home, rho_pct_away,
    headwind, surface, circ=None, rr=None, elev_delta=None,
    weather=None, home_venue_row=None, away_venue_row=None
):
    """Build reusable MLB game-context scoring for reports and picks."""
    gd = str(game_date or datetime.now().date())
    cache_key = (
        gd, str(away_team).lower(), str(home_team).lower(),
        round(float(rho_pct_home or 0.0), 3),
        round(float(rho_pct_away or 0.0), 3),
        round(float(headwind or 0.0), 3),
        str(surface or "").lower(),
        round(float(_mlb_num((weather or {}).get("temp")) or 0.0), 2),
        round(float(_mlb_num((weather or {}).get("pressure")) or 0.0), 2),
    )
    if cache_key in _MLB_GAME_CONTEXT_CACHE:
        return _MLB_GAME_CONTEXT_CACHE[cache_key]

    db_data = _mlb_db_lookup(home_team, away_team, gd)
    if not db_data:
        result = {
            "available": False,
            "db": None,
            "home_env": {"load_score": 0.0, "execution_penalty": 0.0, "notes": [], "components": {}},
            "away_env": {"load_score": 0.0, "execution_penalty": 0.0, "notes": [], "components": {}},
            "home_pitcher": {"score": 0.0, "notes": [], "components": {}},
            "away_pitcher": {"score": 0.0, "notes": [], "components": {}},
            "home_offense": {"score": 0.0, "notes": [], "components": {}},
            "away_offense": {"score": 0.0, "notes": [], "components": {}},
            "total_over_impact": 0.0,
            "summary": "",
            "pick_factors": [],
        }
        _MLB_GAME_CONTEXT_CACHE[cache_key] = result
        return result

    home_state = (circ.get("home_state") or {}) if isinstance(circ, dict) else {}
    away_state = (circ.get("away_state") or {}) if isinstance(circ, dict) else {}
    current_row = home_venue_row or {}
    home_env = _team_environment_load_model(
        home_team, "MLB", home_venue_row or {}, current_row,
        circ_state=home_state, rho_pct=rho_pct_home, weather=weather
    )
    away_env = _team_environment_load_model(
        away_team, "MLB", away_venue_row or {}, current_row,
        circ_state=away_state, rho_pct=rho_pct_away, weather=weather
    )
    home_pitch_env = _mlb_pitch_environment_model(
        db_data.get("home_sp") or {}, home_env, away_env, rho_pct_home, headwind, weather=weather
    )
    away_pitch_env = _mlb_pitch_environment_model(
        db_data.get("away_sp") or {}, away_env, home_env, rho_pct_away, headwind, weather=weather
    )
    home_off_env = _mlb_offense_environment_model(
        db_data.get("home_team_st") or {}, home_env, away_pitch_env, rho_pct_home, headwind, weather=weather
    )
    away_off_env = _mlb_offense_environment_model(
        db_data.get("away_team_st") or {}, away_env, home_pitch_env, rho_pct_away, headwind, weather=weather
    )

    home_pitcher = _mlb_pitcher_context_model(
        db_data, "home", rho_pct_home, headwind, surface,
        circ=circ, rr=rr, elev_delta=elev_delta,
        own_env=home_env, opp_env=away_env, weather=weather, pitch_env=home_pitch_env
    )
    away_pitcher = _mlb_pitcher_context_model(
        db_data, "away", rho_pct_away, headwind, surface,
        circ=circ, rr=rr, elev_delta=elev_delta,
        own_env=away_env, opp_env=home_env, weather=weather, pitch_env=away_pitch_env
    )
    home_offense = _mlb_offense_context_model(
        db_data, "home", rho_pct_home, circ=circ, elev_delta=elev_delta,
        own_env=home_env, opp_env=away_env, headwind=headwind, weather=weather,
        offense_env=home_off_env
    )
    away_offense = _mlb_offense_context_model(
        db_data, "away", rho_pct_away, circ=circ, elev_delta=elev_delta,
        own_env=away_env, opp_env=home_env, headwind=headwind, weather=weather,
        offense_env=away_off_env
    )

    total_over_impact = round(
        home_offense["score"] + away_offense["score"]
        - home_pitcher["score"] - away_pitcher["score"],
        3,
    )
    factor_pool = []
    factor_pool.extend(home_env.get("notes", [])[:2])
    factor_pool.extend(away_env.get("notes", [])[:2])
    factor_pool.extend(home_pitcher.get("notes", [])[:2])
    factor_pool.extend(away_pitcher.get("notes", [])[:2])
    factor_pool.extend(home_offense.get("notes", [])[:2])
    factor_pool.extend(away_offense.get("notes", [])[:2])
    pick_factors = []
    for item in factor_pool:
        if item and item not in pick_factors:
            pick_factors.append(item)
    if total_over_impact >= 0.65:
        summary = "cumulative MLB context leans OVER"
    elif total_over_impact <= -0.65:
        summary = "cumulative MLB context leans UNDER"
    else:
        summary = "cumulative MLB context is mixed"

    result = {
        "available": True,
        "db": db_data,
        "home_env": home_env,
        "away_env": away_env,
        "home_pitch_env": home_pitch_env,
        "away_pitch_env": away_pitch_env,
        "home_off_env": home_off_env,
        "away_off_env": away_off_env,
        "home_pitcher": home_pitcher,
        "away_pitcher": away_pitcher,
        "home_offense": home_offense,
        "away_offense": away_offense,
        "total_over_impact": total_over_impact,
        "summary": summary,
        "pick_factors": pick_factors[:6],
    }
    _MLB_GAME_CONTEXT_CACHE[cache_key] = result
    return result


def _render_mlb_db_section(txt, db_data, away_clean, home_clean, W=58, rw_rec=None):
    """
    Renders the MLB pre-game DB stats block inside the detail popup.
    Called from _render_detail when sport==MLB and db_data is available.
    """
    if not db_data:
        _w(txt, "  â³ No MLB pre-game stats in DB yet â€” run mlb_stats_daily.py first.\n", "na")
        return

    def _val(d, k, fmt=None, default="â€”"):
        v = d.get(k)
        if v is None or str(v).strip() in ("","None","nan","â€”"): return default
        try:
            f = float(v)
            if fmt: return fmt.format(f)
            return str(round(f,3))
        except: return str(v)

    # â”€â”€ PITCHER SEASON STATS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for side, sp_key, label in [
            ("away", "away_sp", away_clean),
            ("home", "home_sp", home_clean)]:
        sp = db_data.get(sp_key, {})
        if not sp: continue
        _w(txt, f"\n  {label.upper()} STARTER  â€”  SEASON STATS\n", "section")
        _sep(txt, "â”€", W)
        # Row 1: ERA / FIP / xFIP / WHIP
        r1 = [
            ("ERA",    _val(sp,"era",   "{:.2f}")),
            ("FIP",    _val(sp,"fip",   "{:.2f}")),
            ("xFIP",   _val(sp,"xfip",  "{:.2f}")),
            ("WHIP",   _val(sp,"whip",  "{:.2f}")),
            ("IP",     _val(sp,"innings","{:.1f}")),
        ]
        txt.insert(tk.END, "  ", "label")
        for lbl, val in r1:
            txt.insert(tk.END, f"{lbl}:", "label")
            _w(txt, f"{val}  ", "value")
        _w(txt, "\n", "value")
        # Row 2: K% / BB% / K-BB / GB% / HR/FB
        r2 = [
            ("K%",     _val(sp,"k_pct",    "{:.1f}%")),
            ("BB%",    _val(sp,"bb_pct",   "{:.1f}%")),
            ("K-BB",   _val(sp,"k_minus_bb","{:.1f}%")),
            ("GB%",    _val(sp,"gb_pct",   "{:.1f}%")),
            ("HR/FB",  _val(sp,"hr_per_fb","{:.3f}")),
            ("BABIP",  _val(sp,"babip",    "{:.3f}")),
        ]
        txt.insert(tk.END, "  ", "label")
        for lbl, val in r2:
            txt.insert(tk.END, f"{lbl}:", "label")
            _w(txt, f"{val}  ", "value")
        _w(txt, "\n", "value")
        # Row 3: Statcast
        r3 = [
            ("Velo",   _val(sp,"avg_velo",   "{:.1f}")),
            ("Spin",   _val(sp,"avg_spin",   "{:.0f}RPM")),
            ("Whiff%", _val(sp,"whiff_pct",  "{:.1f}%")),
            ("HH%",    _val(sp,"hard_hit_pct","{:.1f}%")),
            ("xwOBA-vs",_val(sp,"xwoba_against","{:.3f}")),
        ]
        txt.insert(tk.END, "  ", "label")
        for lbl, val in r3:
            txt.insert(tk.END, f"{lbl}:", "label")
            _w(txt, f"{val}  ", "value")
        _w(txt, "\n", "value")
        # Density model factors
        ds  = _val(sp,"density_sensitivity","{:.3f}")
        fbe = _val(sp,"fly_ball_exposure",  "{:.3f}")
        if ds != "â€”":
            txt.insert(tk.END, "  ", "label")
            txt.insert(tk.END, f"Density Sens:", "label")
            ds_f = float(sp.get("density_sensitivity",0) or 0)
            ds_tag = "warn" if ds_f > 0.65 else "good" if ds_f < 0.40 else "value"
            _w(txt, f"{ds}  ", ds_tag)
            txt.insert(tk.END, f"FB Exposure:", "label")
            _w(txt, f"{fbe}\n", "value")
        # Recent form
        e3  = _val(sp,"era_last3",   "{:.2f}")
        k3  = _val(sp,"k_pct_last3", "{:.1f}%")
        pc3 = _val(sp,"avg_pc_last3","{:.0f}p")
        ip3 = _val(sp,"avg_ip_last3","{:.1f}ip")
        if e3 != "â€”":
            txt.insert(tk.END, "  ", "label")
            txt.insert(tk.END, "Last 3 starts: ", "label")
            _w(txt, f"ERA {e3}  K% {k3}  Avg PC {pc3}  Avg IP {ip3}\n", "value")

    # â”€â”€ TEAM OFFENSE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for side, tk_key, label in [
            ("away","away_team_st",away_clean),
            ("home","home_team_st",home_clean)]:
        tm = db_data.get(tk_key, {})
        if not tm: continue
        _w(txt, f"\n  {label.upper()} OFFENSE\n", "section")
        _sep(txt, "â”€", W)
        off = [
            ("R/G",    _val(tm,"runs_per_game","{:.2f}")),
            ("OPS",    _val(tm,"ops",          "{:.3f}")),
            ("OBP",    _val(tm,"obp",          "{:.3f}")),
            ("SLG",    _val(tm,"slg",          "{:.3f}")),
            ("ISO",    _val(tm,"iso",          "{:.3f}")),
            ("AVG",    _val(tm,"avg",          "{:.3f}")),
        ]
        txt.insert(tk.END, "  ", "label")
        for lbl, val in off:
            txt.insert(tk.END, f"{lbl}:", "label")
            _w(txt, f"{val}  ", "value")
        _w(txt, "\n", "value")
        sc = [
            ("HH%",    _val(tm,"hard_hit_pct","{:.1f}%")),
            ("Brl%",   _val(tm,"barrel_pct",  "{:.1f}%")),
            ("EV",     _val(tm,"avg_exit_velo","{:.1f}")),
            ("xwOBA",  _val(tm,"xwoba",       "{:.3f}")),
            ("HR/G",   _val(tm,"hr_per_game", "{:.2f}")),
            ("BB/G",   _val(tm,"bb_per_game", "{:.2f}")),
        ]
        txt.insert(tk.END, "  ", "label")
        for lbl, val in sc:
            txt.insert(tk.END, f"{lbl}:", "label")
            _w(txt, f"{val}  ", "value")
        _w(txt, "\n", "value")
        # Splits if available
        ops_home = _val(tm,"ops_home","  home {:.3f}")
        ops_away = _val(tm,"ops_away","  away {:.3f}")
        ops_rhp  = _val(tm,"ops_vs_rhp","  vs RHP {:.3f}")
        ops_lhp  = _val(tm,"ops_vs_lhp","  vs LHP {:.3f}")
        splits = [x for x in [ops_home,ops_away,ops_rhp,ops_lhp] if x != "â€”"]
        if splits:
            txt.insert(tk.END, "  Splits:", "label")
            _w(txt, "  ".join(splits) + "\n", "value")

    # â”€â”€ CATCHER LAYER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    has_catcher = any([
        db_data.get("home_catcher",{}).get("catcher_name"),
        db_data.get("away_catcher",{}).get("catcher_name"),
    ])
    if has_catcher:
        _w(txt, "\n  CATCHER LAYER\n", "section")
        _sep(txt, "â”€", W)
        _w(txt, f"  {'':4} {'CATCHER':<18} {'FRAMING':>10} {'BLOCK':>8} {'ARM':>8} {'IMPACT':>8}\n","label")
        for side, ck_key, label in [
                ("Away", "away_catcher", away_clean),
                ("Home", "home_catcher", home_clean)]:
            ck = db_data.get(ck_key, {})
            cname  = ck.get("catcher_name","TBD") or "TBD"
            ftier  = ck.get("framing_tier","â€”")   or "â€”"
            btier  = ck.get("block_tier","â€”")     or "â€”"
            atier  = ck.get("arm_tier","â€”")       or "â€”"
            impact = ck.get("catcher_impact_score")
            xstr   = ck.get("extra_strikes_per100")
            imp_s  = f"{float(impact):.2f}" if impact is not None else "â€”"
            xstr_s = f"{float(xstr):+.1f}/100" if xstr is not None else ""
            # Tag by impact score
            try:
                imp_f = float(impact) if impact is not None else 0.5
                imp_tag = "good" if imp_f >= 0.65 else "warn" if imp_f <= 0.35 else "value"
            except: imp_tag = "value"
            txt.insert(tk.END, f"  {side:<4} {cname:<18} {ftier:>10} {btier:>8} {atier:>8} ", "label")
            _w(txt, f"{imp_s:>8}", imp_tag)
            if xstr_s:
                _w(txt, f"  ({xstr_s} framing)", "na")
            _w(txt, "\n", "value")
        # Impact score note
        _w(txt, "  Impact score 0â†’1: 0.5=neutral | >0.65 elite framer | <0.35 hurts pitcher.\n","na")
    # â”€â”€ BATTING LINEUPS (from RotoWire if available) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if rw_rec and True:  # sport always MLB here
        try:
            import json as _lj
            _a_lu = _lj.loads(rw_rec.get("away_lineup_json","[]") or "[]")
            _h_lu = _lj.loads(rw_rec.get("home_lineup_json","[]") or "[]")
            if _a_lu or _h_lu:
                _w(txt, "\n  BATTING LINEUPS  (RotoWire)\n", "section")
                _sep(txt, "â”€", W)
                # Side-by-side: Away | Home
                _a_st = (rw_rec.get("away_lineup_status") or "->").upper()
                _h_st = (rw_rec.get("home_lineup_status") or "->").upper()
                _a_sp = rw_rec.get("away_sp","->") or "->"
                _h_sp = rw_rec.get("home_sp","->") or "->"
                _lu_hdr_tag = lambda s: "good" if s=="CONFIRMED" else "warn" if s=="EXPECTED" else "na"
                _w(txt, f"  {'#':<3}{'POS':<5}{'AWAY â€” '+away_clean:<26} | {'HOME â€” '+home_clean}\n", "label")
                _w(txt, f"  {'':3}{'':5}{_a_sp+' ('+rw_rec.get('away_sp_hand','->')+') SP':<26} | {_h_sp+' ('+rw_rec.get('home_sp_hand','->')+') SP'}\n", "na")
                _w(txt, f"  {'':3}{'':5}{'['+_a_st+']':<26} | {'['+_h_st+']'}\n", _lu_hdr_tag(_a_st))
                _sep(txt, "â”€", W)
                max_rows = max(len(_a_lu), len(_h_lu))
                for i in range(max_rows):
                    if i < len(_a_lu):
                        ap = _a_lu[i]
                        _a_str = f"{ap['batting_order']:<3}{ap['pos']:<5}{ap['name']}"
                        if ap.get("hand"): _a_str += f" ({ap['hand']})"
                    else:
                        _a_str = ""
                    if i < len(_h_lu):
                        hp = _h_lu[i]
                        _h_str = f"{hp['batting_order']:<3}{hp['pos']:<5}{hp['name']}"
                        if hp.get("hand"): _h_str += f" ({hp['hand']})"
                    else:
                        _h_str = ""
                    _w(txt, f"  {_a_str:<33} | {_h_str}\n", "na")
        except Exception as _le:
            log(f"[lineup display] {_le}", "debug")

        # Lineup confirmation: read from _rw_a_st/_rw_h_st (live RotoWire data)
        # _rw_a_st/_rw_h_st are already set above from _rw_rec at lines ~1875-1876
        _lu_a = (_rw_a_st or "->").upper().strip()
        _lu_h = (_rw_h_st or "->").upper().strip()
        _both_conf = bool(_rw_both)
        # Also check if catchers are identified (proxy for lineup availability)
        _ack = db_data.get("away_catcher",{}).get("catcher_name","") or ""
        _hck = db_data.get("home_catcher",{}).get("catcher_name","") or ""
        _catchers_known = (bool(_ack) and _ack not in ("TBD","->") and
                           bool(_hck) and _hck not in ("TBD","->"))
        if _both_conf:
            _w(txt, "  âœ… Lineups CONFIRMED (RotoWire) â€” catcher impact fully applied.\n", "good")
        elif _lu_a in ("CONFIRMED","EXPECTED") and _lu_h in ("CONFIRMED","EXPECTED"):
            _conf_str = f"Away:{_lu_a}  Home:{_lu_h}"
            _tag = "good" if "CONFIRMED" in _lu_a+_lu_h else "warn"
            _w(txt, f"  \u26a0 Lineup status: {_conf_str} â€” impact applied at partial weight.\n", _tag)
        elif _catchers_known:
            _w(txt, "  \u26a0 Lineup status from RotoWire pending â€” catchers identified via MLB API. Impact applied.\n", "warn")
        else:
            _lu_msg = f"  \u26a0 LINEUP PENDING (Away:{_lu_a}  Home:{_lu_h})"
            _lu_msg += " â€” using expected roster. Impact applied with lower weight.\n"
            _w(txt, _lu_msg, "warn")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ================================================================
# GUI BUILD
# ================================================================
root = tk.Tk()
root.title("Overline Edge | Sports Intelligence Workstation")

def _load_startup_photo(candidates, max_w=None, max_h=None):
    for _cand in candidates:
        try:
            _p = Path(_cand)
            if not _p.exists() or not _p.is_file():
                continue
            _img = tk.PhotoImage(file=str(_p))
            if max_w or max_h:
                _wlim = int(max_w or _img.width())
                _hlim = int(max_h or _img.height())
                _sx = max(1, int(math.ceil(float(_img.width()) / float(_wlim))))
                _sy = max(1, int(math.ceil(float(_img.height()) / float(_hlim))))
                if _sx > 1 or _sy > 1:
                    _img = _img.subsample(_sx, _sy)
            return _img, str(_p)
        except Exception:
            continue
    return None, ""

def _show_startup_splash():
    _splash = tk.Toplevel(root)
    _splash.overrideredirect(True)
    _splash.configure(bg="#04070d")

    _img, _path = _load_startup_photo(_SPLASH_LOGO_CANDIDATES, max_w=360, max_h=360)
    if _img is not None:
        tk.Label(_splash, image=_img, bg="#04070d").pack(padx=28, pady=(28, 18))
        _splash._logo_ref = _img
        log(f"Splash logo loaded: {_path}", "info")
    else:
        tk.Label(
            _splash,
            text="OVERLINE EDGE",
            fg="#1dd2c2",
            bg="#04070d",
            font=("Segoe UI Semibold", 28),
        ).pack(padx=28, pady=(28, 18))

    tk.Label(
        _splash,
        text="Initializing live sports intelligence...",
        fg="#8fa9c8",
        bg="#04070d",
        font=("Segoe UI", 11),
    ).pack(padx=20, pady=(0, 24))

    _splash.update_idletasks()
    _sw = _splash.winfo_screenwidth()
    _sh = _splash.winfo_screenheight()
    _ww = _splash.winfo_reqwidth()
    _hh = _splash.winfo_reqheight()
    _x = max(0, int((_sw - _ww) / 2))
    _y = max(0, int((_sh - _hh) / 2))
    _splash.geometry(f"{_ww}x{_hh}+{_x}+{_y}")
    _splash.lift()
    _splash.attributes("-topmost", True)
    return _splash

_APP_ICON_IMAGE, _APP_ICON_PATH = _load_startup_photo(_APP_ICON_CANDIDATES, max_w=96, max_h=96)
if _APP_ICON_IMAGE is not None:
    try:
        root.iconphoto(True, _APP_ICON_IMAGE)
        log(f"App icon loaded: {_APP_ICON_PATH}", "info")
    except Exception:
        pass

root.withdraw()
_STARTUP_SPLASH = _show_startup_splash()
try:
    root.update_idletasks()
    root.update()
except Exception:
    pass

# â”€â”€ Route ALL Tkinter callback exceptions into the diagnostic error tab â”€â”€
def _tk_exc_handler(exc_type, exc_val, exc_tb):
    import traceback as _tb
    msg = "".join(_tb.format_exception(exc_type, exc_val, exc_tb))
    log(f"TKINTER EXCEPTION:\n{msg}", "error")
root.report_callback_exception = _tk_exc_handler
root.resizable(True, True)
root.minsize(1200, 820)
root.geometry("1500x920")
try:
    root.state("zoomed")
except Exception:
    pass
_UI = {
    "bg_app": "#f3f5f8",
    "bg_surface": "#ffffff",
    "bg_surface_alt": "#edf1f5",
    "bg_tab_idle": "#e5eaf1",
    "text_primary": "#132235",
    "text_secondary": "#31455a",
    "text_muted": "#6a7b8f",
    "accent": "#274f7f",
    "accent_hover": "#21456f",
    "accent_pressed": "#1b3a5d",
    "btn_idle": "#edf1f6",
    "btn_hover": "#e1e7ef",
    "btn_pressed": "#d5deea",
    "border": "#cfd7e2",
    "heading_bg": "#e8edf3",
    "heading_bg_active": "#dce5ef",
    "progress_trough": "#e6ebf2",
    "state_ready": "#edf7f1",
    "state_partial": "#f8f3e8",
    "state_blocked": "#f8eeee",
    "state_nogames": "#eef2f6",
    "success": "#1f6a45",
    "warning": "#7a5a1f",
    "danger": "#8f2d2d",
    "stripe_odd": "#fafbfd",
    "stripe_even": "#ffffff",
    "no_odds_bg": "#fbf5e7",
    "no_odds_fg": "#7b6438",
    "shell_bg": "#14263b",
    "shell_text": "#f6fbff",
    "shell_subtle": "#c7d7e7",
    "log_run_bg": "#f8fbff",
    "log_err_bg": "#fdf1f2",
    "log_warn_bg": "#fbf6ea",
    "log_text": "#17314b",
}

_VISUAL_PROFILES = {
    "Executive": {
        "bg_app": "#f3f5f8",
        "bg_surface": "#ffffff",
        "bg_surface_alt": "#edf1f5",
        "bg_tab_idle": "#e5eaf1",
        "text_primary": "#132235",
        "text_secondary": "#31455a",
        "text_muted": "#6a7b8f",
        "accent": "#274f7f",
        "accent_hover": "#21456f",
        "accent_pressed": "#1b3a5d",
        "btn_idle": "#edf1f6",
        "btn_hover": "#e1e7ef",
        "btn_pressed": "#d5deea",
        "border": "#cfd7e2",
        "heading_bg": "#e8edf3",
        "heading_bg_active": "#dce5ef",
        "progress_trough": "#e6ebf2",
        "state_ready": "#edf7f1",
        "state_partial": "#f8f3e8",
        "state_blocked": "#f8eeee",
        "state_nogames": "#eef2f6",
        "success": "#1f6a45",
        "warning": "#7a5a1f",
        "danger": "#8f2d2d",
        "stripe_odd": "#fafbfd",
        "stripe_even": "#ffffff",
        "no_odds_bg": "#fbf5e7",
        "no_odds_fg": "#7b6438",
        "shell_bg": "#14263b",
        "shell_text": "#f6fbff",
        "shell_subtle": "#c7d7e7",
        "log_run_bg": "#f8fbff",
        "log_err_bg": "#fdf1f2",
        "log_warn_bg": "#fbf6ea",
        "log_text": "#17314b",
        "hero_bg": "#1f3a57",
        "hero_title": "#f7fbff",
        "hero_subtitle": "#d7e2ef",
        "chip_bg": "#f0f4f9",
        "chip_text": "#26415f",
        "chip_ok_bg": "#edf7f1",
        "chip_ok_text": "#1f6a45",
        "chip_warn_bg": "#f8f1e4",
        "chip_warn_text": "#7a5a1f",
        "chip_danger_bg": "#f9ecec",
        "chip_danger_text": "#8f2d2d",
        "diag_tab_sel_bg": "#ffffff",
        "diag_tab_idle_bg": "#edf1f5",
        "diag_tab_sel_fg": "#132235",
        "diag_tab_idle_fg": "#31455a",
        "dashboard_canvas_bg": "#f3f5f8",
        "output_bg": "#f7faff",
        "output_fg": "#1d3550",
    },
    "Studio": {
        "bg_app": "#eef3f8",
        "bg_surface": "#fbfdff",
        "bg_surface_alt": "#e7edf4",
        "bg_tab_idle": "#dde6f0",
        "text_primary": "#14293f",
        "text_secondary": "#2c4359",
        "text_muted": "#61788f",
        "accent": "#2d557f",
        "accent_hover": "#254b73",
        "accent_pressed": "#1e3f63",
        "btn_idle": "#e8eef6",
        "btn_hover": "#dde6f1",
        "btn_pressed": "#d1dcea",
        "border": "#c7d4e2",
        "heading_bg": "#e2eaf2",
        "heading_bg_active": "#d4e0ec",
        "progress_trough": "#dde6f0",
        "state_ready": "#e9f5ef",
        "state_partial": "#f7efd9",
        "state_blocked": "#f7e8ea",
        "state_nogames": "#e7edf4",
        "success": "#1c6542",
        "warning": "#6d521d",
        "danger": "#842929",
        "stripe_odd": "#f8fbff",
        "stripe_even": "#fdfefe",
        "no_odds_bg": "#f4ebd7",
        "no_odds_fg": "#705823",
        "shell_bg": "#0f1f2f",
        "shell_text": "#f8fcff",
        "shell_subtle": "#abc2d9",
        "log_run_bg": "#f4f8fd",
        "log_err_bg": "#f8ecee",
        "log_warn_bg": "#f7f1df",
        "log_text": "#17314b",
        "hero_bg": "#17314a",
        "hero_title": "#f4f9ff",
        "hero_subtitle": "#ccdbeb",
        "chip_bg": "#eaf1f8",
        "chip_text": "#1f3b57",
        "chip_ok_bg": "#e9f5ef",
        "chip_ok_text": "#1c6542",
        "chip_warn_bg": "#f7efd9",
        "chip_warn_text": "#6d521d",
        "chip_danger_bg": "#f7e8ea",
        "chip_danger_text": "#842929",
        "diag_tab_sel_bg": "#fbfdff",
        "diag_tab_idle_bg": "#e7edf4",
        "diag_tab_sel_fg": "#112338",
        "diag_tab_idle_fg": "#2c4359",
        "dashboard_canvas_bg": "#eff3f8",
        "output_bg": "#f4f8fd",
        "output_fg": "#17314b",
    },
    "Edge Noir": {
        "bg_app": "#0f131b",
        "bg_surface": "#141a25",
        "bg_surface_alt": "#1a2230",
        "bg_tab_idle": "#151d2b",
        "text_primary": "#e6edf7",
        "text_secondary": "#c6d2e1",
        "text_muted": "#93a6bb",
        "accent": "#caa64a",
        "accent_hover": "#bc993d",
        "accent_pressed": "#a88431",
        "btn_idle": "#1a2332",
        "btn_hover": "#223046",
        "btn_pressed": "#293a54",
        "border": "#2a3749",
        "heading_bg": "#1a2230",
        "heading_bg_active": "#233146",
        "progress_trough": "#223143",
        "state_ready": "#173026",
        "state_partial": "#362f1d",
        "state_blocked": "#3a1f25",
        "state_nogames": "#1c2635",
        "success": "#72d6a1",
        "warning": "#caa64a",
        "danger": "#ff7f93",
        "stripe_odd": "#141c29",
        "stripe_even": "#111824",
        "no_odds_bg": "#352f1e",
        "no_odds_fg": "#d6b35b",
        "shell_bg": "#101724",
        "shell_text": "#e1bc58",
        "shell_subtle": "#a4b8cc",
        "log_run_bg": "#141c29",
        "log_err_bg": "#2d1b22",
        "log_warn_bg": "#302a1c",
        "log_text": "#dbe6f4",
        "hero_bg": "#131b28",
        "hero_title": "#e1bc58",
        "hero_subtitle": "#c9d7e8",
        "chip_bg": "#1a2433",
        "chip_text": "#d6e1ef",
        "chip_ok_bg": "#1c352b",
        "chip_ok_text": "#72d6a1",
        "chip_warn_bg": "#3a321e",
        "chip_warn_text": "#e1bc58",
        "chip_danger_bg": "#3e2027",
        "chip_danger_text": "#ff8fa1",
        "diag_tab_sel_bg": "#151e2d",
        "diag_tab_idle_bg": "#1c2738",
        "diag_tab_sel_fg": "#e6edf7",
        "diag_tab_idle_fg": "#b7c6d8",
        "dashboard_canvas_bg": "#0f131b",
        "output_bg": "#161f2d",
        "output_fg": "#e6edf7",
    },
}

_UI_PREFS_FILE = Path(__file__).resolve().with_name("ui_prefs.json")

def _load_visual_pref(default_name="Executive"):
    try:
        if _UI_PREFS_FILE.exists():
            _raw = json.loads(_UI_PREFS_FILE.read_text(encoding="utf-8"))
            _name = str((_raw or {}).get("visual_profile", "")).strip()
            # Migrate away from the previous aggressive default.
            if _name == "Edge Noir":
                return "Executive"
            if _name in _VISUAL_PROFILES:
                return _name
    except Exception:
        pass
    return default_name if default_name in _VISUAL_PROFILES else "Executive"

def _save_visual_pref(name):
    try:
        _UI_PREFS_FILE.write_text(
            json.dumps({"visual_profile": str(name)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as _pref_e:
        log(f"[ui] could not persist visual profile: {_pref_e}", "warning")

root.configure(bg=_UI["bg_app"])

_style = ttk.Style(root)
try:
    _style.theme_use("clam")
except Exception:
    pass
_ui_font = "Segoe UI"
_ui_font_semibold = "Segoe UI Semibold"
_style.configure(".", font=(_ui_font, 10), background=_UI["bg_app"], foreground=_UI["text_secondary"])
_style.configure("TFrame", background=_UI["bg_app"])
_style.configure("TLabelframe", background=_UI["bg_app"], borderwidth=1, relief="flat")
_style.configure("TLabelframe.Label", font=(_ui_font_semibold, 11), foreground=_UI["text_primary"])
_style.configure("Card.TLabelframe", background=_UI["bg_surface"], borderwidth=1, relief="flat")
_style.configure("Card.TLabelframe.Label", font=(_ui_font_semibold, 11), foreground=_UI["text_primary"])
_style.configure("Card.TFrame", background=_UI["bg_surface"])
_style.configure("TLabel", background=_UI["bg_app"], foreground=_UI["text_secondary"])
_style.configure("Subtle.TLabel", background=_UI["bg_app"], foreground=_UI["text_muted"])
_style.configure("Status.TLabel", background=_UI["bg_app"], foreground=_UI["text_secondary"])
_style.configure("Alert.TLabel", background=_UI["bg_app"], foreground=_UI["danger"])
_style.configure("SubtleCard.TLabel", background=_UI["bg_surface"], foreground=_UI["text_muted"])
_style.configure("StatusCard.TLabel", background=_UI["bg_surface"], foreground=_UI["text_secondary"])
_style.configure("AlertCard.TLabel", background=_UI["bg_surface"], foreground=_UI["danger"])
_style.configure("DetailTitle.TLabel", background=_UI["bg_surface"], foreground=_UI["text_primary"], font=(_ui_font_semibold, 13))
_style.configure(
    "TCombobox",
    padding=5,
    fieldbackground=_UI["bg_surface"],
    background=_UI["bg_surface"],
    foreground=_UI["text_primary"],
)
_style.map(
    "TCombobox",
    fieldbackground=[("readonly", _UI["bg_surface"])],
    selectbackground=[("readonly", _UI["bg_surface_alt"])],
    foreground=[("readonly", _UI["text_primary"])],
)
_style.configure(
    "TEntry",
    fieldbackground=_UI["bg_surface"],
    background=_UI["bg_surface"],
    foreground=_UI["text_primary"],
)
_style.configure("TButton", padding=(13, 8), borderwidth=1, relief="flat",
                 background=_UI["btn_idle"], foreground=_UI["text_primary"])
_style.map("TButton",
           background=[("active", _UI["btn_hover"]), ("pressed", _UI["btn_pressed"])],
           foreground=[("disabled", "#8ea1b7")])
_style.configure("Accent.TButton", padding=(13, 8), borderwidth=1, relief="flat",
                 background=_UI["accent"], foreground="#ffffff")
_style.map("Accent.TButton",
           background=[("active", _UI["accent_hover"]), ("pressed", _UI["accent_pressed"])],
           foreground=[("disabled", "#c9daf2")])
_style.configure("TNotebook", background=_UI["bg_app"], tabmargins=(6, 8, 6, 0))
_style.configure("TNotebook.Tab", padding=(18, 10), font=(_ui_font_semibold, 11), borderwidth=0)
_style.map("TNotebook.Tab",
           background=[("selected", _UI["bg_surface"]), ("!selected", _UI["bg_tab_idle"])],
           foreground=[("selected", _UI["text_primary"]), ("!selected", _UI["text_secondary"])])
_style.configure("Treeview", rowheight=28, font=(_ui_font, 10),
                 fieldbackground=_UI["bg_surface"], background=_UI["bg_surface"])
_style.map("Treeview",
           background=[("selected", _UI["accent"])],
           foreground=[("selected", "#ffffff")])
_style.configure("Treeview.Heading", font=(_ui_font_semibold, 10), padding=(12, 6),
                 background=_UI["heading_bg"], foreground=_UI["text_primary"])
_style.map("Treeview.Heading", background=[("active", _UI["heading_bg_active"])])
_style.configure("Games.Treeview", rowheight=26, font=(_ui_font, 10))
_style.configure("Games.Treeview.Heading", font=(_ui_font_semibold, 10), padding=(8, 5))
_style.configure("Pulse.Treeview", rowheight=24, font=(_ui_font, 10))
_style.configure(
    "Pipeline.Horizontal.TProgressbar",
    troughcolor=_UI["progress_trough"],
    background=_UI["accent"],
    bordercolor=_UI["border"],
    lightcolor=_UI["accent"],
    darkcolor=_UI["accent"],
    thickness=9,
)
_style.configure(
    "League.Horizontal.TProgressbar",
    troughcolor=_UI["progress_trough"],
    background=_UI["success"],
    bordercolor=_UI["border"],
    lightcolor=_UI["success"],
    darkcolor=_UI["success"],
    thickness=8,
)
_style.configure("Hero.TFrame", background=_UI["shell_bg"])
_style.configure(
    "HeroTitle.TLabel",
    background=_UI["shell_bg"],
    foreground=_UI["shell_text"],
    font=(_ui_font_semibold, 15),
)
_style.configure(
    "HeroSubtitle.TLabel",
    background=_UI["shell_bg"],
    foreground=_UI["shell_subtle"],
    font=(_ui_font, 10),
)
_style.configure("BrandHero.TLabel", background=_UI["shell_bg"])
_style.configure("BrandSurface.TLabel", background=_UI["bg_surface"])
_style.configure(
    "HeroChip.TLabel",
    background=_UI["bg_surface_alt"],
    foreground=_UI["text_secondary"],
    font=(_ui_font_semibold, 9),
    borderwidth=1,
    relief="solid",
    padding=(10, 5),
)
_style.configure(
    "HeroChipOk.TLabel",
    background=_UI["state_ready"],
    foreground=_UI["success"],
    font=(_ui_font_semibold, 9),
    borderwidth=1,
    relief="solid",
    padding=(10, 5),
)
_style.configure(
    "HeroChipWarn.TLabel",
    background=_UI["state_partial"],
    foreground=_UI["warning"],
    font=(_ui_font_semibold, 9),
    borderwidth=1,
    relief="solid",
    padding=(10, 5),
)
_style.configure(
    "HeroChipDanger.TLabel",
    background=_UI["state_blocked"],
    foreground=_UI["danger"],
    font=(_ui_font_semibold, 9),
    borderwidth=1,
    relief="solid",
    padding=(10, 5),
)
_style.configure("Shell.TFrame", background=_UI["shell_bg"], borderwidth=0, relief="flat")
_style.configure(
    "ShellTitle.TLabel",
    background=_UI["shell_bg"],
    foreground=_UI["shell_text"],
    font=(_ui_font_semibold, 16),
)
_style.configure(
    "ShellSubtitle.TLabel",
    background=_UI["shell_bg"],
    foreground=_UI["shell_subtle"],
    font=(_ui_font, 10),
)
_style.configure(
    "ShellMeta.TLabel",
    background=_UI["shell_bg"],
    foreground=_UI["shell_subtle"],
    font=(_ui_font_semibold, 9),
)
_style.configure("Diag.TNotebook", background=_UI["bg_surface"], tabmargins=(4, 4, 4, 0))
_style.configure("Diag.TNotebook.Tab", padding=(12, 6), font=(_ui_font_semibold, 9), borderwidth=0)
_style.map(
    "Diag.TNotebook.Tab",
    background=[("selected", _UI["bg_surface"]), ("!selected", _UI["bg_surface_alt"])],
    foreground=[("selected", _UI["text_primary"]), ("!selected", _UI["text_secondary"])],
)

pad = {"padx": 8, "pady": 5}

def _load_brand_photo(candidates, max_w=64, max_h=64):
    for _cand in candidates:
        try:
            _p = Path(_cand)
            if not _p.exists() or not _p.is_file():
                continue
            _img = tk.PhotoImage(file=str(_p))
            _sx = max(1, int(math.ceil(float(_img.width()) / float(max_w))))
            _sy = max(1, int(math.ceil(float(_img.height()) / float(max_h))))
            if _sx > 1 or _sy > 1:
                _img = _img.subsample(_sx, _sy)
            return _img, str(_p)
        except Exception:
            continue
    return None, ""

def _load_brand_assets():
    _icon, _icon_path = _load_brand_photo(_BRAND_ICON_CANDIDATES, max_w=52, max_h=52)
    _lock, _lock_path = _load_brand_photo(_BRAND_LOCKUP_CANDIDATES, max_w=340, max_h=110)
    if _icon_path:
        log(f"Brand icon loaded: {_icon_path}", "info")
    if _lock_path:
        log(f"Brand lockup loaded: {_lock_path}", "info")
    return {
        "icon": _icon,
        "lockup": _lock,
        "icon_path": _icon_path,
        "lockup_path": _lock_path,
    }

def _start_daemon_after(delay_ms, target, *args, **kwargs):
    def _launch():
        threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()
    root.after(delay_ms, _launch)

# Root workspace host for primary tabs.
tabs_host = ttk.Frame(root)
tabs_host.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
_brand_assets = _load_brand_assets()
tabs_shell = ttk.Frame(tabs_host, style="Shell.TFrame", padding=(10, 7, 10, 6))
tabs_shell.pack(fill=tk.X, padx=6, pady=(6, 0))
tabs_shell.grid_columnconfigure(0, weight=1)
tabs_shell.grid_columnconfigure(1, weight=1)

shell_left = ttk.Frame(tabs_shell, style="Shell.TFrame")
shell_left.grid(row=0, column=0, sticky="w")
shell_brand_row = ttk.Frame(shell_left, style="Shell.TFrame")
shell_brand_row.pack(anchor="w")
if _brand_assets.get("icon") is not None:
    ttk.Label(shell_brand_row, image=_brand_assets["icon"], style="BrandHero.TLabel").pack(side=tk.LEFT, padx=(0, 8))
shell_text_col = ttk.Frame(shell_brand_row, style="Shell.TFrame")
shell_text_col.pack(side=tk.LEFT)
ttk.Label(shell_text_col, text="Overline Edge", style="ShellTitle.TLabel").pack(anchor="w")
ttk.Label(
    shell_text_col,
    text="Sports Intelligence Workstation",
    style="ShellSubtitle.TLabel",
).pack(anchor="w", pady=(2, 0))

shell_right = ttk.Frame(tabs_shell, style="Shell.TFrame")
shell_right.grid(row=0, column=1, sticky="e")
_shell_mode_var = tk.StringVar(value="State: Active")
_shell_workspace_var = tk.StringVar(value="Workspace: Dashboard")
_shell_clock_var = tk.StringVar(value="")
_shell_visual_var = tk.StringVar(value=_load_visual_pref("Executive"))

shell_right_top = ttk.Frame(shell_right, style="Shell.TFrame")
shell_right_top.pack(anchor="e")
ttk.Label(shell_right_top, text="Look:", style="ShellMeta.TLabel").pack(side=tk.LEFT, padx=(0, 4))
_shell_visual_cb = ttk.Combobox(
    shell_right_top,
    textvariable=_shell_visual_var,
    state="readonly",
    width=12,
    values=tuple(_VISUAL_PROFILES.keys()),
)
_shell_visual_cb.pack(side=tk.LEFT)
ttk.Label(shell_right_top, textvariable=_shell_mode_var, style="ShellMeta.TLabel").pack(side=tk.LEFT, padx=(8, 0))
ttk.Label(shell_right, textvariable=_shell_workspace_var, style="ShellMeta.TLabel").pack(anchor="e", pady=(2, 0))
ttk.Label(shell_right, textvariable=_shell_clock_var, style="ShellMeta.TLabel").pack(anchor="e", pady=(2, 0))

def _refresh_shell_clock():
    try:
        _shell_clock_var.set(datetime.now(ET).strftime("ET %a %b %d | %I:%M %p"))
    except Exception:
        pass
    root.after(30000, _refresh_shell_clock)

_refresh_shell_clock()

main_tabs = ttk.Notebook(tabs_host)
main_tabs.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

physics_frame  = ttk.Frame(main_tabs)
matchups_frame = ttk.Frame(main_tabs)
console_frame  = ttk.Frame(main_tabs)
games_frame    = ttk.Frame(main_tabs)
main_tabs.add(matchups_frame, text="Dashboard")
main_tabs.add(console_frame,  text="System Console")
main_tabs.add(games_frame,    text="Today's Slate")
main_tabs.add(physics_frame,  text="Model")
main_tabs.select(matchups_frame)

def _sync_shell_workspace(event=None):
    try:
        tab_text = str(main_tabs.tab(main_tabs.select(), "text") or "").strip()
        _shell_workspace_var.set(f"Workspace: {tab_text or 'Dashboard'}")
    except Exception:
        pass

def _apply_visual_profile(profile_name=None):
    _name = str(profile_name or _shell_visual_var.get() or "Executive").strip()
    _v = _VISUAL_PROFILES.get(_name, _VISUAL_PROFILES["Executive"])
    try:
        for _k in list(_UI.keys()):
            if _k in _v:
                _UI[_k] = _v[_k]

        root.configure(bg=_UI["bg_app"])
        _style.configure(".", font=(_ui_font, 10), background=_UI["bg_app"], foreground=_UI["text_secondary"])
        _style.configure("TFrame", background=_UI["bg_app"])
        _style.configure("TLabelframe", background=_UI["bg_app"], borderwidth=1, relief="flat")
        _style.configure("TLabelframe.Label", font=(_ui_font_semibold, 11), foreground=_UI["text_primary"])
        _style.configure("Card.TLabelframe", background=_UI["bg_surface"], borderwidth=1, relief="flat")
        _style.configure("Card.TLabelframe.Label", font=(_ui_font_semibold, 11), foreground=_UI["text_primary"])
        _style.configure("Card.TFrame", background=_UI["bg_surface"])
        _style.configure("TLabel", background=_UI["bg_app"], foreground=_UI["text_secondary"])
        _style.configure("Subtle.TLabel", background=_UI["bg_app"], foreground=_UI["text_muted"])
        _style.configure("Status.TLabel", background=_UI["bg_app"], foreground=_UI["text_secondary"])
        _style.configure("Alert.TLabel", background=_UI["bg_app"], foreground=_UI["danger"])
        _style.configure("SubtleCard.TLabel", background=_UI["bg_surface"], foreground=_UI["text_muted"])
        _style.configure("StatusCard.TLabel", background=_UI["bg_surface"], foreground=_UI["text_secondary"])
        _style.configure("AlertCard.TLabel", background=_UI["bg_surface"], foreground=_UI["danger"])
        _style.configure(
            "DetailTitle.TLabel",
            background=_UI["bg_surface"],
            foreground=_UI["text_primary"],
            font=(_ui_font_semibold, 13),
        )
        _style.configure(
            "TCombobox",
            padding=5,
            fieldbackground=_UI["bg_surface"],
            background=_UI["bg_surface"],
            foreground=_UI["text_primary"],
        )
        _style.map(
            "TCombobox",
            fieldbackground=[("readonly", _UI["bg_surface"])],
            selectbackground=[("readonly", _UI["bg_surface_alt"])],
            foreground=[("readonly", _UI["text_primary"])],
        )
        _style.configure(
            "TEntry",
            fieldbackground=_UI["bg_surface"],
            background=_UI["bg_surface"],
            foreground=_UI["text_primary"],
        )
        _style.configure(
            "TButton",
            padding=(13, 8),
            borderwidth=1,
            relief="flat",
            background=_UI["btn_idle"],
            foreground=_UI["text_primary"],
        )
        _style.map(
            "TButton",
            background=[("active", _UI["btn_hover"]), ("pressed", _UI["btn_pressed"])],
            foreground=[("disabled", "#8ea1b7")],
        )
        _style.configure(
            "Accent.TButton",
            padding=(13, 8),
            borderwidth=1,
            relief="flat",
            background=_UI["accent"],
            foreground="#ffffff",
        )
        _style.map(
            "Accent.TButton",
            background=[("active", _UI["accent_hover"]), ("pressed", _UI["accent_pressed"])],
            foreground=[("disabled", "#c9daf2")],
        )
        _style.configure("TNotebook", background=_UI["bg_app"], tabmargins=(6, 8, 6, 0))
        _style.configure("TNotebook.Tab", padding=(18, 10), font=(_ui_font_semibold, 11), borderwidth=0)
        _style.map(
            "TNotebook.Tab",
            background=[("selected", _UI["bg_surface"]), ("!selected", _UI["bg_tab_idle"])],
            foreground=[("selected", _UI["text_primary"]), ("!selected", _UI["text_secondary"])],
        )
        _style.configure(
            "Treeview",
            rowheight=28,
            font=(_ui_font, 10),
            fieldbackground=_UI["bg_surface"],
            background=_UI["bg_surface"],
            foreground=_UI["text_primary"],
        )
        _style.map(
            "Treeview",
            background=[("selected", _UI["accent"])],
            foreground=[("selected", "#ffffff")],
        )
        _style.configure(
            "Treeview.Heading",
            font=(_ui_font_semibold, 10),
            padding=(12, 6),
            background=_UI["heading_bg"],
            foreground=_UI["text_primary"],
        )
        _style.map("Treeview.Heading", background=[("active", _UI["heading_bg_active"])])
        _style.configure("Games.Treeview", rowheight=26, font=(_ui_font, 10))
        _style.configure("Games.Treeview.Heading", font=(_ui_font_semibold, 10), padding=(8, 5))
        _style.configure("Pulse.Treeview", rowheight=24, font=(_ui_font, 10))
        _style.configure(
            "Pipeline.Horizontal.TProgressbar",
            troughcolor=_UI["progress_trough"],
            background=_UI["accent"],
            bordercolor=_UI["border"],
            lightcolor=_UI["accent"],
            darkcolor=_UI["accent"],
            thickness=9,
        )
        _style.configure(
            "League.Horizontal.TProgressbar",
            troughcolor=_UI["progress_trough"],
            background=_UI["success"],
            bordercolor=_UI["border"],
            lightcolor=_UI["success"],
            darkcolor=_UI["success"],
            thickness=8,
        )

        _style.configure("Shell.TFrame", background=_v["shell_bg"], borderwidth=0, relief="flat")
        _style.configure("ShellTitle.TLabel", background=_v["shell_bg"], foreground=_v["shell_text"])
        _style.configure("ShellSubtitle.TLabel", background=_v["shell_bg"], foreground=_v["shell_subtle"])
        _style.configure("ShellMeta.TLabel", background=_v["shell_bg"], foreground=_v["shell_subtle"])

        _style.configure("Hero.TFrame", background=_v["hero_bg"])
        _style.configure("HeroTitle.TLabel", background=_v["hero_bg"], foreground=_v["hero_title"])
        _style.configure("HeroSubtitle.TLabel", background=_v["hero_bg"], foreground=_v["hero_subtitle"])
        _style.configure("BrandHero.TLabel", background=_v["hero_bg"])
        _style.configure("BrandSurface.TLabel", background=_UI["bg_surface"])
        _style.configure("HeroChip.TLabel", background=_v["chip_bg"], foreground=_v["chip_text"])
        _style.configure("HeroChipOk.TLabel", background=_v["chip_ok_bg"], foreground=_v["chip_ok_text"])
        _style.configure("HeroChipWarn.TLabel", background=_v["chip_warn_bg"], foreground=_v["chip_warn_text"])
        _style.configure("HeroChipDanger.TLabel", background=_v["chip_danger_bg"], foreground=_v["chip_danger_text"])

        _style.configure("Diag.TNotebook", background=_UI["bg_surface"], tabmargins=(4, 4, 4, 0))
        _style.configure("Diag.TNotebook.Tab", padding=(12, 6), font=(_ui_font_semibold, 9), borderwidth=0)
        _style.map(
            "Diag.TNotebook.Tab",
            background=[("selected", _v["diag_tab_sel_bg"]), ("!selected", _v["diag_tab_idle_bg"])],
            foreground=[("selected", _v["diag_tab_sel_fg"]), ("!selected", _v["diag_tab_idle_fg"])],
        )

        _dash_canvas = globals().get("dashboard_canvas")
        if _dash_canvas is not None:
            _dash_canvas.configure(bg=_v["dashboard_canvas_bg"])

        for _name_txt, _bg, _fg in [
            ("output", _v["output_bg"], _v["output_fg"]),
            ("rpt_text", _v["output_bg"], _v["output_fg"]),
            ("audit_text", _v["output_bg"], _v["output_fg"]),
            ("run_box", _UI["log_run_bg"], _UI["log_text"]),
            ("err_box", _UI["log_err_bg"], _UI["log_text"]),
            ("data_box", _UI["log_warn_bg"], _UI["log_text"]),
        ]:
            _w = globals().get(_name_txt)
            if _w is not None:
                try:
                    _w.configure(bg=_bg, fg=_fg, insertbackground=_fg)
                except Exception:
                    pass

        _rpt = globals().get("rpt_text")
        if _rpt is not None:
            for _tag, _fg in [
                ("header", _UI["text_primary"]),
                ("section", _UI["accent"]),
                ("label", _UI["text_muted"]),
                ("value", _UI["text_primary"]),
                ("good", _UI["success"]),
                ("warn", _UI["danger"]),
                ("na", _UI["text_muted"]),
                ("sep", _UI["border"]),
            ]:
                _rpt.tag_configure(_tag, foreground=_fg)

        _audit = globals().get("audit_text")
        if _audit is not None:
            for _tag, _fg in [
                ("ts", _UI["text_muted"]),
                ("sport", _UI["accent"]),
                ("change", _UI["success"]),
                ("neutral", _UI["text_primary"]),
                ("warn", _UI["danger"]),
                ("header", _UI["text_primary"]),
            ]:
                _audit.tag_configure(_tag, foreground=_fg)

        _win_bg = _UI["state_ready"]
        _loss_bg = _UI["state_blocked"]
        _push_bg = _UI["state_partial"]
        _pend_bg = _UI["state_nogames"]

        _pipe = globals().get("pipeline_tree")
        if _pipe is not None:
            _pipe.tag_configure("READY", background=_UI["state_ready"])
            _pipe.tag_configure("PARTIAL_READY", background=_UI["state_partial"])
            _pipe.tag_configure("BLOCKED", background=_UI["state_blocked"])
            _pipe.tag_configure("NO_GAMES", background=_UI["state_nogames"])

        _match_tree = globals().get("matchup_tree")
        if _match_tree is not None:
            _match_tree.tag_configure("odd", background=_UI["stripe_odd"])
            _match_tree.tag_configure("even", background=_UI["stripe_even"])
            _match_tree.tag_configure("no_odds", background=_UI["no_odds_bg"], foreground=_UI["no_odds_fg"])
            _match_tree.tag_configure("bypass", foreground=_UI["accent"])

        _ars_tree = globals().get("ars_tree")
        if _ars_tree is not None:
            _ars_tree.tag_configure("odd", background=_UI["stripe_odd"])
            _ars_tree.tag_configure("even", background=_UI["stripe_even"])

        for _tree_name in ["pk_tree", "_yh_tree", "_mh_tree"]:
            _tr = globals().get(_tree_name)
            if _tr is not None:
                _tr.tag_configure("win", background=_win_bg, foreground=_UI["success"])
                _tr.tag_configure("loss", background=_loss_bg, foreground=_UI["danger"])
                _tr.tag_configure("push", background=_push_bg, foreground=_UI["warning"])
                _tr.tag_configure("pend", background=_pend_bg, foreground=_UI["text_muted"])

        _board_tree = globals().get("_tpk_tree")
        if _board_tree is not None:
            _board_tree.tag_configure("OVER", background=_win_bg, foreground=_UI["success"])
            _board_tree.tag_configure("UNDER", background=_push_bg, foreground=_UI["accent"])
            _board_tree.tag_configure("NEUTRAL", background=_pend_bg, foreground=_UI["text_muted"])
            _board_tree.tag_configure("odd", background=_UI["stripe_odd"])

        for _lbl_name, _fg in [("_yh_acc_lbl", _UI["success"]), ("_mh_acc_lbl", _UI["accent"])]:
            _lbl = globals().get(_lbl_name)
            if _lbl is not None:
                try:
                    _lbl.configure(foreground=_fg, background=_UI["bg_app"])
                except Exception:
                    pass

        for _dw in list(_DETAIL_TEXT_WIDGETS):
            try:
                if _dw.winfo_exists():
                    _style_detail_text_widget(_dw)
                else:
                    _DETAIL_TEXT_WIDGETS.remove(_dw)
            except Exception:
                pass
    except Exception as _viz_e:
        log(f"[ui] visual profile apply failed: {_viz_e}", "warning")

def _on_shell_visual_change(event=None):
    _picked = _shell_visual_var.get()
    _apply_visual_profile(_picked)
    _save_visual_pref(_picked)

main_tabs.bind("<<NotebookTabChanged>>", _sync_shell_workspace, add="+")
root.after(0, _sync_shell_workspace)
_shell_visual_cb.bind("<<ComboboxSelected>>", _on_shell_visual_change, add="+")

# Dashboard content host (scrollable) so status panels stay usable on shorter windows.
dashboard_canvas = tk.Canvas(
    matchups_frame,
    highlightthickness=0,
    borderwidth=0,
    bg=_UI["bg_app"],
)
dashboard_scroll_y = ttk.Scrollbar(matchups_frame, orient=tk.VERTICAL, command=dashboard_canvas.yview)
dashboard_canvas.configure(yscrollcommand=dashboard_scroll_y.set)
dashboard_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
dashboard_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
dashboard_body = ttk.Frame(dashboard_canvas)
_dashboard_window_id = dashboard_canvas.create_window((0, 0), window=dashboard_body, anchor="nw")

def _dashboard_on_body_config(event=None):
    try:
        dashboard_canvas.configure(scrollregion=dashboard_canvas.bbox("all"))
    except Exception:
        pass

def _dashboard_on_canvas_config(event):
    try:
        dashboard_canvas.itemconfigure(_dashboard_window_id, width=event.width)
    except Exception:
        pass

dashboard_body.bind("<Configure>", _dashboard_on_body_config, add="+")
dashboard_canvas.bind("<Configure>", _dashboard_on_canvas_config, add="+")

def _dashboard_mousewheel(event):
    try:
        dashboard_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    except Exception:
        pass

dashboard_canvas.bind_all("<MouseWheel>", _dashboard_mousewheel, add="+")

_dashboard_hero_state = {
    "ready": 0,
    "partial": 0,
    "blocked": 0,
    "full_ready": 0,
    "issue_count": 0,
    "slate_games": None,
    "startup_pct": 0.0,
    "matchup_pct": 0.0,
}
_dashboard_status_chip_var = tk.StringVar(value="Status: Initializing")
_dashboard_operational_chip_var = tk.StringVar(value="Operational: --/6")
_dashboard_issues_chip_var = tk.StringVar(value="Issues: --")
_dashboard_slate_chip_var = tk.StringVar(value="Slate: -- games")
_dashboard_startup_chip_var = tk.StringVar(value="Startup: 0%")
_dashboard_load_chip_var = tk.StringVar(value="Load: 0%")

# Dashboard hero band: sets visual tone and key operational signals.
dashboard_hero = ttk.Frame(dashboard_body, style="Hero.TFrame", padding=12)
dashboard_hero.pack(fill=tk.X, padx=6, pady=(6, 6))
dashboard_hero.grid_columnconfigure(0, weight=1)
dashboard_hero.grid_columnconfigure(1, weight=1)
dashboard_hero_left = ttk.Frame(dashboard_hero, style="Hero.TFrame")
dashboard_hero_left.grid(row=0, column=0, sticky="w")
ttk.Label(
    dashboard_hero_left,
    text="Command Dashboard",
    style="HeroTitle.TLabel",
).pack(anchor="w")
ttk.Label(
    dashboard_hero_left,
    text="Decision-first visibility with disciplined execution.",
    style="HeroSubtitle.TLabel",
).pack(anchor="w", pady=(2, 0))

dashboard_hero_chips = ttk.Frame(dashboard_hero, style="Hero.TFrame")
dashboard_hero_chips.grid(row=0, column=1, sticky="e")
_dashboard_status_chip = ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_status_chip_var, style="HeroChipWarn.TLabel"
)
_dashboard_status_chip.grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="e")
_dashboard_operational_chip = ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_operational_chip_var, style="HeroChip.TLabel"
)
_dashboard_operational_chip.grid(row=0, column=1, padx=(0, 6), pady=(0, 6), sticky="e")
_dashboard_issues_chip = ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_issues_chip_var, style="HeroChip.TLabel"
)
_dashboard_issues_chip.grid(row=0, column=2, pady=(0, 6), sticky="e")
ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_slate_chip_var, style="HeroChip.TLabel"
).grid(row=1, column=0, padx=(0, 6), sticky="e")
ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_startup_chip_var, style="HeroChip.TLabel"
).grid(row=1, column=1, padx=(0, 6), sticky="e")
ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_load_chip_var, style="HeroChip.TLabel"
).grid(row=1, column=2, sticky="e")
if _brand_assets.get("icon") is not None:
    ttk.Label(
        dashboard_hero_chips,
        image=_brand_assets["icon"],
        style="BrandHero.TLabel",
    ).grid(row=0, column=3, rowspan=2, padx=(12, 0), sticky="e")

dashboard_action_row = ttk.Frame(dashboard_body, style="Card.TFrame")
dashboard_action_row.pack(fill=tk.X, padx=6, pady=(0, 4))
ttk.Button(
    dashboard_action_row,
    text="Open Slate",
    style="Accent.TButton",
    command=lambda: main_tabs.select(games_frame),
).pack(side=tk.LEFT, padx=(0, 6))
ttk.Button(
    dashboard_action_row,
    text="Refresh Pulse",
    command=lambda: _refresh_pipeline_pulse(log_summary=True),
).pack(side=tk.LEFT, padx=(0, 6))
ttk.Button(
    dashboard_action_row,
    text="Open Reports",
    command=lambda: main_tabs.select(reports_frame) if "reports_frame" in globals() else None,
).pack(side=tk.LEFT)

_dashboard_top_var = tk.StringVar(value="Top opportunities: waiting for slate load.")
ttk.Label(
    dashboard_action_row,
    textvariable=_dashboard_top_var,
    style="SubtleCard.TLabel",
).pack(side=tk.LEFT, padx=(14, 0))

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 1 â€” PHYSICS MODEL
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
ctrl = ttk.LabelFrame(physics_frame, text="Game Setup", padding=10, style="Card.TLabelframe")
ctrl.pack(fill=tk.X, **pad)

league_var        = tk.StringVar()
team_var          = tk.StringVar()
roof_override_var = tk.StringVar(value="Auto")

ttk.Label(ctrl, text="League:").grid(row=0, column=0, sticky="w", **pad)
league_cb = ttk.Combobox(ctrl, textvariable=league_var, width=30, state="readonly")
league_cb["values"] = sorted(df["league"].dropna().unique().tolist())
league_cb.grid(row=0, column=1, sticky="w", **pad)

ttk.Label(ctrl, text="Team:").grid(row=0, column=2, sticky="w", **pad)
team_cb = ttk.Combobox(ctrl, textvariable=team_var, width=30, state="readonly")
team_cb.grid(row=0, column=3, sticky="w", **pad)

ttk.Label(ctrl, text="Roof Status:").grid(row=1, column=0, sticky="w", **pad)
roof_cb = ttk.Combobox(ctrl, textvariable=roof_override_var, width=30, state="readonly")
roof_cb["values"] = ["Auto", "Open", "Closed"]
roof_cb.grid(row=1, column=1, sticky="w", **pad)

ttk.Button(ctrl, text="Run Model", style="Accent.TButton", command=lambda: run_model()).grid(
    row=1, column=3, sticky="e", **pad)

out_frame  = ttk.LabelFrame(physics_frame, text="Model Output", padding=10, style="Card.TLabelframe")
out_frame.pack(fill=tk.BOTH, expand=True, **pad)
out_scroll = ttk.Scrollbar(out_frame, orient=tk.VERTICAL)
output = tk.Text(out_frame, height=18, width=100,
                 yscrollcommand=out_scroll.set, font=("Consolas", 10),
                 bg=_UI["bg_surface"], fg=_UI["text_primary"], insertbackground=_UI["text_primary"])
_install_text_sanitizer(output)
out_scroll.config(command=output.yview)
output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
out_scroll.pack(side=tk.RIGHT, fill=tk.Y)
_apply_visual_profile(_shell_visual_var.get())

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 2 â€” TODAY'S MATCHUPS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
m_ctrl = ttk.LabelFrame(games_frame, text="Slate Controls", padding=10, style="Card.TLabelframe")
m_ctrl.pack(fill=tk.X, **pad)

m_league_var = tk.StringVar()
ttk.Label(m_ctrl, text="League:").grid(row=0, column=0, sticky="w", **pad)
m_league_cb = ttk.Combobox(m_ctrl, textvariable=m_league_var, width=20, state="readonly")
m_league_cb["values"] = list(LEAGUE_MAP.keys())
m_league_cb.grid(row=0, column=1, sticky="w", **pad)

fetch_btn = ttk.Button(m_ctrl, text="Refresh Slate",
                       style="Accent.TButton",
                       command=lambda: fetch_matchups())
fetch_btn.grid(row=0, column=2, sticky="w", **pad)

load_physics_btn = ttk.Button(m_ctrl, text="Analyze Selection",
                               style="Accent.TButton",
                               command=lambda: load_matchup_into_physics(),
                               state=tk.DISABLED)
load_physics_btn.grid(row=0, column=3, sticky="w", **pad)

_auto_refresh_var = tk.StringVar(value="Off")
ttk.Label(m_ctrl, text="Auto-Refresh:").grid(row=0, column=4, sticky="e", **pad)
_auto_refresh_cb = ttk.Combobox(
    m_ctrl,
    textvariable=_auto_refresh_var,
    width=10,
    state="readonly",
    values=("Off", "2 min", "5 min", "10 min", "15 min", "30 min"),
)
_auto_refresh_cb.grid(row=0, column=5, sticky="w", **pad)

_focus_games_btn = ttk.Button(
    m_ctrl,
    text="Open Dashboard",
    style="Accent.TButton",
)
_focus_games_btn.grid(row=0, column=6, sticky="e", **pad)
ttk.Button(
    m_ctrl,
    text="Export Game",
    command=lambda: _export_slate_snapshot("selected"),
).grid(row=0, column=7, sticky="w", **pad)
ttk.Button(
    m_ctrl,
    text="Export League",
    command=lambda: _export_slate_snapshot("league"),
).grid(row=0, column=8, sticky="w", **pad)
ttk.Button(
    m_ctrl,
    text="Export Day",
    command=lambda: _export_slate_snapshot("day"),
).grid(row=0, column=9, sticky="w", **pad)

# hint label
m_hint_lbl = ttk.Label(
    m_ctrl,
    text="Select a row for live intelligence  |  Double-click for full matchup dossier",
    style="SubtleCard.TLabel",
)
m_hint_lbl.grid(row=1, column=0, columnspan=10, sticky="w", **pad)

m_status_var = tk.StringVar(value="Choose a league, then refresh the slate.")
m_status_lbl = ttk.Label(m_ctrl, textvariable=m_status_var, style="StatusCard.TLabel")
m_status_lbl.grid(row=2, column=0, columnspan=10, sticky="w", **pad)

_startup_progress_pct_var = tk.DoubleVar(value=0.0)
_startup_progress_text_var = tk.StringVar(value="Startup pipeline status: standing by")
startup_progress = ttk.Progressbar(
    m_ctrl,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_startup_progress_pct_var,
    length=520,
    style="Pipeline.Horizontal.TProgressbar",
)
startup_progress.grid(row=3, column=0, columnspan=4, sticky="ew", **pad)
_startup_progress_lbl = ttk.Label(m_ctrl, textvariable=_startup_progress_text_var, style="SubtleCard.TLabel")
_startup_progress_lbl.grid(row=4, column=0, columnspan=10, sticky="w", **pad)

_matchup_progress_pct_var = tk.DoubleVar(value=0.0)
_matchup_progress_text_var = tk.StringVar(value="Slate load status: standing by")
matchup_progress = ttk.Progressbar(
    m_ctrl,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_matchup_progress_pct_var,
    length=520,
    style="Pipeline.Horizontal.TProgressbar",
)
matchup_progress.grid(row=5, column=0, columnspan=4, sticky="ew", **pad)
_matchup_progress_lbl = ttk.Label(m_ctrl, textvariable=_matchup_progress_text_var, style="SubtleCard.TLabel")
_matchup_progress_lbl.grid(row=6, column=0, columnspan=10, sticky="w", **pad)
m_ctrl.grid_columnconfigure(3, weight=1)
m_ctrl.grid_columnconfigure(9, weight=1)

def _open_dashboard_tab():
    try:
        main_tabs.select(matchups_frame)
    except Exception:
        pass
    m_status_var.set("Dashboard in focus.")

def _export_slate_snapshot(mode: str = "league"):
    _mode = str(mode or "league").strip().lower()
    _stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _today = datetime.now().strftime("%Y%m%d")
    _out = os.path.join(ODDS_DIR, f"Slate_{_mode}_{_stamp}.xlsx")

    try:
        if _mode == "selected":
            _sel = matchup_tree.selection()
            if not _sel:
                m_status_var.set("Select a game row first to export a single matchup.")
                return
            _vals = matchup_tree.item(_sel[0], "values") or []
            _away = str(_vals[1] if len(_vals) > 1 else "").replace("  [NO ODDS]", "").strip()
            _home = str(_vals[2] if len(_vals) > 2 else "").strip()
            _row_df = None
            try:
                if data_df is not None and not data_df.empty:
                    _m = data_df[
                        (data_df.get("Away_Team", "").astype(str).str.strip() == _away)
                        & (data_df.get("Home_Team", "").astype(str).str.strip() == _home)
                    ]
                    if _m is not None and not _m.empty:
                        _row_df = _m.head(1).copy()
            except Exception:
                _row_df = None

            if _row_df is None or _row_df.empty:
                _row_df = pd.DataFrame([{
                    "League": str(m_league_var.get() or "").upper().strip(),
                    "Time": _vals[0] if len(_vals) > 0 else "",
                    "Away_Team": _away,
                    "Home_Team": _home,
                    "Away_Spread": _vals[3] if len(_vals) > 3 else "",
                    "Home_Spread": _vals[4] if len(_vals) > 4 else "",
                    "Total": _vals[5] if len(_vals) > 5 else "",
                    "Away_ML": _vals[6] if len(_vals) > 6 else "",
                    "Home_ML": _vals[7] if len(_vals) > 7 else "",
                }])
            _row_df.to_excel(_out, index=False, sheet_name="Selected_Game")
            m_status_var.set(f"Exported selected matchup -> {_out}")
            log(f"Slate export (selected): {_out}", "info")
            return

        if _mode == "league":
            if data_df is None or data_df.empty:
                m_status_var.set("No loaded league slate available to export.")
                return
            _league_df = data_df.copy()
            if "League" not in _league_df.columns:
                _league_df["League"] = str(m_league_var.get() or "").upper().strip()
            _league_df.to_excel(_out, index=False, sheet_name=f"{str(m_league_var.get() or 'LEAGUE').upper()}_Slate"[:31])
            m_status_var.set(f"Exported league slate -> {_out}")
            log(f"Slate export (league): {_out}", "info")
            return

        # full day export across all leagues with today's files
        _frames = []
        for _lg in LEAGUE_MAP.keys():
            _f = os.path.join(ODDS_DIR, f"Odds_{_lg}_{_today}.xlsx")
            if not os.path.exists(_f):
                continue
            try:
                _df = pd.read_excel(_f)
                if _df is not None and not _df.empty:
                    _df = _df.copy()
                    _df["League"] = _lg
                    _frames.append(_df)
            except Exception:
                continue
        if not _frames:
            m_status_var.set("No today odds files found for full-day export.")
            return
        pd.concat(_frames, ignore_index=True).to_excel(_out, index=False, sheet_name="Today_All_Leagues")
        m_status_var.set(f"Exported full-day slate -> {_out}")
        log(f"Slate export (day): {_out}", "info")
    except Exception as _ex:
        m_status_var.set(f"Slate export failed: {_ex}")
        log(f"Slate export failed ({_mode}): {_ex}", "error")

_focus_games_btn.configure(command=_open_dashboard_tab)

# Dashboard landing section: startup/load progress at a glance.
dashboard_progress_frame = ttk.LabelFrame(dashboard_body, text="Pipeline Status", padding=10, style="Card.TLabelframe")
dashboard_progress_frame.pack(fill=tk.X, padx=6, pady=(6, 4))
ttk.Label(dashboard_progress_frame, text="Startup Pipeline", width=18).grid(row=0, column=0, sticky="w", **pad)
ttk.Progressbar(
    dashboard_progress_frame,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_startup_progress_pct_var,
    length=360,
    style="Pipeline.Horizontal.TProgressbar",
).grid(row=0, column=1, sticky="ew", **pad)
ttk.Label(
    dashboard_progress_frame,
    textvariable=_startup_progress_text_var,
    style="SubtleCard.TLabel",
).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

ttk.Label(dashboard_progress_frame, text="Matchup Load", width=18).grid(row=2, column=0, sticky="w", **pad)
ttk.Progressbar(
    dashboard_progress_frame,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_matchup_progress_pct_var,
    length=360,
    style="Pipeline.Horizontal.TProgressbar",
).grid(row=2, column=1, sticky="ew", **pad)
ttk.Label(
    dashboard_progress_frame,
    textvariable=_matchup_progress_text_var,
    style="SubtleCard.TLabel",
).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
dashboard_progress_frame.grid_columnconfigure(1, weight=1)

# Stats/SOS data-plane control panel (live readiness pulse).
_pipeline_status_var = tk.StringVar(value="Readiness matrix awaiting startup pipeline run.")
_pipeline_last_var = tk.StringVar(value="Last update: --")
pipeline_frame = ttk.LabelFrame(dashboard_body, text="Readiness Pulse", padding=8, style="Card.TLabelframe")
pipeline_frame.pack(fill=tk.X, padx=6, pady=(0, 4))

pipeline_cols = ("league", "stats", "sos", "readiness", "note")
pipeline_tree = ttk.Treeview(
    pipeline_frame,
    columns=pipeline_cols,
    show="headings",
    height=max(6, len(_STATS_SOS_LEAGUES)),
    style="Pulse.Treeview",
)
pipeline_tree.heading("league", text="League")
pipeline_tree.heading("stats", text="Stats")
pipeline_tree.heading("sos", text="SOS")
pipeline_tree.heading("readiness", text="Readiness")
pipeline_tree.heading("note", text="Detail")
pipeline_tree.column("league", width=70, anchor="center")
pipeline_tree.column("stats", width=120, anchor="center")
pipeline_tree.column("sos", width=120, anchor="center")
pipeline_tree.column("readiness", width=130, anchor="center")
pipeline_tree.column("note", width=520, anchor="w")
pipeline_tree.tag_configure("READY", background=_UI["state_ready"])
pipeline_tree.tag_configure("PARTIAL_READY", background=_UI["state_partial"])
pipeline_tree.tag_configure("BLOCKED", background=_UI["state_blocked"])
pipeline_tree.tag_configure("NO_GAMES", background=_UI["state_nogames"])
pipeline_tree.configure(height=max(6, len(_STATS_SOS_LEAGUES)))
pipeline_tree.pack(fill=tk.X, expand=False)

pipeline_btn_row = ttk.Frame(pipeline_frame, style="Card.TFrame")
pipeline_btn_row.pack(fill=tk.X, pady=(4, 0))
ttk.Label(pipeline_btn_row, textvariable=_pipeline_status_var, style="SubtleCard.TLabel").pack(side=tk.LEFT)
ttk.Label(pipeline_btn_row, textvariable=_pipeline_last_var, style="SubtleCard.TLabel").pack(side=tk.RIGHT)
ttk.Button(
    pipeline_btn_row,
    text="Refresh Pulse",
    style="Accent.TButton",
    command=lambda: _refresh_pipeline_pulse(log_summary=True),
).pack(side=tk.RIGHT, padx=(0, 8))

# Per-league ingest board: progress + current issues for each sport.
_dashboard_league_status_var = tk.StringVar(value="League health awaiting first readiness pulse.")
league_ingest_frame = ttk.LabelFrame(dashboard_body, text="League Health", padding=8, style="Card.TLabelframe")
league_ingest_frame.pack(fill=tk.X, padx=6, pady=(0, 4))
ttk.Label(
    league_ingest_frame,
    textvariable=_dashboard_league_status_var,
    style="SubtleCard.TLabel",
).grid(row=0, column=0, columnspan=4, sticky="w", **pad)

_league_ingest_widgets = {}
for _idx, _lg in enumerate(_STATS_SOS_LEAGUES, start=1):
    _pct_var = tk.DoubleVar(value=0.0)
    _summary_var = tk.StringVar(value="queued")
    _issue_var = tk.StringVar(value="")
    ttk.Label(league_ingest_frame, text=f"{_lg}", width=7).grid(row=_idx, column=0, sticky="w", **pad)
    ttk.Progressbar(
        league_ingest_frame,
        orient=tk.HORIZONTAL,
        mode="determinate",
        maximum=100.0,
        variable=_pct_var,
        length=260,
        style="League.Horizontal.TProgressbar",
    ).grid(row=_idx, column=1, sticky="w", **pad)
    ttk.Label(
        league_ingest_frame,
        textvariable=_summary_var,
        style="StatusCard.TLabel",
        width=54,
        wraplength=520,
        justify="left",
    ).grid(row=_idx, column=2, sticky="w", **pad)
    ttk.Label(
        league_ingest_frame,
        textvariable=_issue_var,
        style="AlertCard.TLabel",
        wraplength=980,
        justify="left",
    ).grid(row=_idx, column=3, sticky="w", **pad)
    _league_ingest_widgets[_lg] = {
        "pct": _pct_var,
        "summary": _summary_var,
        "issue": _issue_var,
    }

league_ingest_frame.grid_columnconfigure(3, weight=1)

# Slate workspace split: table on the left, live intelligence rail on the right.
slate_workspace = ttk.PanedWindow(games_frame, orient=tk.HORIZONTAL)
slate_workspace.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

# â”€â”€ Treeview â”€â”€
tree_frame = ttk.LabelFrame(slate_workspace, text="Today's Slate", padding=8, style="Card.TLabelframe")

TREE_COLS  = ("time","away","home","away_spread","home_spread","total","away_ml","home_ml")
COL_LABELS = {
    "time":"Game Time","away":"Away Team","home":"Home Team",
    "away_spread":"Away Spread","home_spread":"Home Spread",
    "total":"Total (O/U)","away_ml":"Away ML","home_ml":"Home ML",
}
COL_WIDTHS = {
    "time":90,"away":175,"home":175,
    "away_spread":90,"home_spread":90,"total":80,"away_ml":80,"home_ml":80,
}
COL_ANCHORS = {
    "time": "center",
    "away": "w",
    "home": "w",
    "away_spread": "center",
    "home_spread": "center",
    "total": "center",
    "away_ml": "center",
    "home_ml": "center",
}

tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
matchup_tree  = ttk.Treeview(tree_frame, columns=TREE_COLS, show="headings",
                              yscrollcommand=tree_scroll_y.set,
                              xscrollcommand=tree_scroll_x.set,
                              selectmode="browse",
                              style="Games.Treeview")
matchup_tree.configure(height=18)
tree_scroll_y.config(command=matchup_tree.yview)
tree_scroll_x.config(command=matchup_tree.xview)

for col in TREE_COLS:
    matchup_tree.heading(
        col,
        text=COL_LABELS[col],
        command=lambda c=col: sort_tree(c),
        anchor="w" if col in ("away", "home") else "center",
    )
    matchup_tree.column(col, width=COL_WIDTHS[col], anchor=COL_ANCHORS.get(col, "center"), minwidth=60)

matchup_tree.grid(row=0, column=0, sticky="nsew")
tree_scroll_y.grid(row=0, column=1, sticky="ns")
tree_scroll_x.grid(row=1, column=0, sticky="ew")
tree_frame.grid_rowconfigure(0, weight=1)
tree_frame.grid_columnconfigure(0, weight=1)
matchup_tree.configure(height=24)
slate_workspace.add(tree_frame, weight=7)

slate_detail_frame = ttk.LabelFrame(
    slate_workspace,
    text="Live Matchup Intelligence",
    padding=10,
    style="Card.TLabelframe",
)
slate_detail_frame.grid_columnconfigure(0, weight=1)
slate_workspace.add(slate_detail_frame, weight=3)

_slate_matchup_var = tk.StringVar(value="No matchup selected")
_slate_time_var = tk.StringVar(value="Tipoff/First pitch: --")
_slate_market_var = tk.StringVar(value="Market: --")
_slate_edge_var = tk.StringVar(value="Edge posture: neutral")
_slate_risk_var = tk.StringVar(value="Risk posture: waiting for selection")
_slate_status_var = tk.StringVar(value="Data status: standing by")

ttk.Label(slate_detail_frame, textvariable=_slate_matchup_var, style="DetailTitle.TLabel").grid(
    row=0, column=0, sticky="w", padx=2, pady=(2, 4)
)
ttk.Label(slate_detail_frame, textvariable=_slate_time_var, style="SubtleCard.TLabel").grid(
    row=1, column=0, sticky="w", padx=2
)
ttk.Label(slate_detail_frame, textvariable=_slate_market_var, style="StatusCard.TLabel").grid(
    row=2, column=0, sticky="w", padx=2, pady=(4, 0)
)
ttk.Separator(slate_detail_frame, orient=tk.HORIZONTAL).grid(row=3, column=0, sticky="ew", pady=(8, 8))

ttk.Label(slate_detail_frame, text="Signal Brief", style="StatusCard.TLabel").grid(
    row=4, column=0, sticky="w", padx=2
)
ttk.Label(slate_detail_frame, textvariable=_slate_edge_var, style="StatusCard.TLabel", wraplength=320, justify="left").grid(
    row=5, column=0, sticky="w", padx=2, pady=(3, 0)
)
ttk.Label(slate_detail_frame, textvariable=_slate_risk_var, style="SubtleCard.TLabel", wraplength=320, justify="left").grid(
    row=6, column=0, sticky="w", padx=2, pady=(4, 0)
)
ttk.Label(slate_detail_frame, textvariable=_slate_status_var, style="SubtleCard.TLabel", wraplength=320, justify="left").grid(
    row=7, column=0, sticky="w", padx=2, pady=(4, 0)
)

_slate_action_row = ttk.Frame(slate_detail_frame, style="Card.TFrame")
_slate_action_row.grid(row=8, column=0, sticky="ew", pady=(10, 0))

def _slate_set_detail_empty(msg: str = "No matchup selected") -> None:
    _slate_matchup_var.set(msg)
    _slate_time_var.set("Tipoff/First pitch: --")
    _slate_market_var.set("Market: --")
    _slate_edge_var.set("Edge posture: neutral")
    _slate_risk_var.set("Risk posture: waiting for selection")
    _slate_status_var.set("Data status: standing by")

def _slate_selected_vals():
    _sel = matchup_tree.selection()
    if not _sel:
        return None
    return matchup_tree.item(_sel[0], "values")

def _slate_open_detail():
    _vals = _slate_selected_vals()
    if not _vals:
        return
    _open_matchup_detail(_vals, sport=m_league_var.get().upper(), status_callback=m_status_var.set)

def _slate_analyze_home():
    _vals = _slate_selected_vals()
    if not _vals:
        return
    _send_team_to_physics(_vals[2], _vals[1], preferred_league=m_league_var.get().upper())

def _slate_analyze_away():
    _vals = _slate_selected_vals()
    if not _vals:
        return
    _send_team_to_physics(_vals[1], _vals[2], preferred_league=m_league_var.get().upper())

def _slate_open_reports():
    try:
        _lg = str(m_league_var.get() or "").upper().strip()
        if _lg and "rpt_league_var" in globals():
            rpt_league_var.set(_lg)
        if "reports_frame" in globals():
            main_tabs.select(reports_frame)
    except Exception:
        pass

ttk.Button(_slate_action_row, text="Open Detail", style="Accent.TButton", command=_slate_open_detail).pack(
    side=tk.LEFT, padx=(0, 6)
)
ttk.Button(_slate_action_row, text="Analyze Home", command=_slate_analyze_home).pack(side=tk.LEFT, padx=(0, 6))
ttk.Button(_slate_action_row, text="Analyze Away", command=_slate_analyze_away).pack(side=tk.LEFT, padx=(0, 6))
ttk.Button(_slate_action_row, text="Open Reports", command=_slate_open_reports).pack(side=tk.LEFT)

_slate_set_detail_empty()

_matchup_auto_refresh_job = None

def _auto_refresh_interval_ms():
    raw = str(_auto_refresh_var.get() or "").strip().lower()
    if raw == "off":
        return 0
    try:
        mins = int(raw.split()[0])
    except Exception:
        return 0
    return max(0, mins) * 60 * 1000

def _cancel_matchup_auto_refresh():
    global _matchup_auto_refresh_job
    if _matchup_auto_refresh_job is not None:
        try:
            root.after_cancel(_matchup_auto_refresh_job)
        except Exception:
            pass
        _matchup_auto_refresh_job = None

def _schedule_matchup_auto_refresh():
    global _matchup_auto_refresh_job
    _cancel_matchup_auto_refresh()
    _ms = _auto_refresh_interval_ms()
    if _ms <= 0:
        return

    def _tick():
        global _matchup_auto_refresh_job
        _matchup_auto_refresh_job = None
        try:
            if str(fetch_btn.cget("state")).lower() != "disabled" and str(m_league_var.get() or "").strip():
                fetch_matchups()
        except Exception:
            pass
        _schedule_matchup_auto_refresh()

    _matchup_auto_refresh_job = root.after(_ms, _tick)

def _on_auto_refresh_change(event=None):
    _schedule_matchup_auto_refresh()
    if _auto_refresh_interval_ms() <= 0:
        m_status_var.set("Auto-refresh is off.")
    else:
        m_status_var.set(f"Auto-refresh active ({_auto_refresh_var.get()}).")

_auto_refresh_cb.bind("<<ComboboxSelected>>", _on_auto_refresh_change)

matchup_tree.tag_configure("odd",  background=_UI["stripe_odd"])
matchup_tree.tag_configure("even", background=_UI["stripe_even"])
matchup_tree.tag_configure(
    "no_odds",
    foreground=_UI["no_odds_fg"],
    background=_UI["no_odds_bg"],
    font=("Segoe UI", 9, "italic"),
)
matchup_tree.tag_configure("bypass", foreground=_UI["accent"])

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SYSTEM CONSOLE TAB (dedicated; no bottom shared pane)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
diag_outer = ttk.Frame(console_frame, style="Card.TFrame")
diag_outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
diag_header = ttk.Frame(diag_outer, style="Card.TFrame")
diag_header.pack(fill=tk.X, pady=(2, 6))
ttk.Label(diag_header, text="System Console", font=("Segoe UI Semibold", 11)).pack(side=tk.LEFT, padx=2)
ttk.Label(
    diag_header,
    text="Live activity, errors, and data health for the full platform.",
    style="SubtleCard.TLabel",
).pack(side=tk.LEFT, padx=10)

diag_tabs = ttk.Notebook(diag_outer, style="Diag.TNotebook")
diag_tabs.pack(fill=tk.BOTH, expand=True)

def _make_tab(nb, title, bg=None):
    _bg = bg or _UI["log_run_bg"]
    fr = ttk.Frame(nb)
    sc = ttk.Scrollbar(fr, orient=tk.VERTICAL)
    bx = tk.Text(fr, height=7, state=tk.DISABLED,
                 font=("Consolas", 9), bg=_bg, fg=_UI["log_text"], insertbackground=_UI["log_text"],
                 yscrollcommand=sc.set, wrap=tk.WORD)
    sc.config(command=bx.yview)
    bx.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sc.pack(side=tk.RIGHT, fill=tk.Y)
    nb.add(fr, text=title)
    return bx

run_box  = _make_tab(diag_tabs, "  Activity  ",        bg=_UI["log_run_bg"])
err_box  = _make_tab(diag_tabs, "  Errors (0)  ",      bg=_UI["log_err_bg"])
data_box = _make_tab(diag_tabs, "  Data Health (0)  ", bg=_UI["log_warn_bg"])

_gui_ready = True
_start_log_pump()

log(f"Venue data loaded â€” {len(df)} venues across {df['league'].nunique()} leagues.", "info")
for w in startup_warnings:
    log(w, "warning")
if not SCRAPER_AVAILABLE:
    log(f"odds_scraper unavailable: {_scraper_import_error}", "warning")
    log("Matchups tab will load from cached Excel files only.", "warning")

# â”€â”€ NEA Player Stats Scraper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    import importlib.util as _ilu_s
    _nea_path = os.path.join(ODDS_DIR, "nea_player_stats_scraper.py")
    _nea_spec = _ilu_s.spec_from_file_location("nea_player_stats_scraper", _nea_path)
    _nea_mod  = _ilu_s.module_from_spec(_nea_spec)
    _nea_spec.loader.exec_module(_nea_mod)
    _NEA_STATS_OK = True
    log("NEA player stats scraper loaded.", "info")
except Exception as _nea_e:
    _nea_mod    = None
    _NEA_STATS_OK = False
    log(f"NEA stats scraper unavailable: {_nea_e}", "warning")

# â”€â”€ NEA Lineup Assessor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    import importlib.util as _ilu_la
    _la_path = os.path.join(ODDS_DIR, "nea_lineup_assessor.py")
    _la_spec = _ilu_la.spec_from_file_location("nea_lineup_assessor", _la_path)
    _la_mod  = _ilu_la.module_from_spec(_la_spec)
    _la_spec.loader.exec_module(_la_mod)
    _NEA_LINEUP_OK = True
    log("NEA lineup assessor loaded.", "info")
except Exception as _la_e:
    _la_mod = None
    _NEA_LINEUP_OK = False
    log(f"NEA lineup assessor unavailable: {_la_e}", "warning")

# â”€â”€ BoydsBets injury scraper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    import importlib.util as _ilu_bb
    _bb_path = os.path.join(ODDS_DIR, "boydsbets_injury_scraper.py")
    _bb_spec = _ilu_bb.spec_from_file_location("boydsbets_injury_scraper", _bb_path)
    _bb_mod  = _ilu_bb.module_from_spec(_bb_spec)
    _bb_spec.loader.exec_module(_bb_mod)
    _BOYDS_OK = True
    log("BoydsBets injury scraper loaded.", "info")
except Exception as _bb_e:
    _bb_mod = None
    _BOYDS_OK = False
    log(f"BoydsBets scraper unavailable: {_bb_e}", "warning")

# â”€â”€ Referee / Umpire signal engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    import importlib.util as _ilu_rse
    _rse_path = os.path.join(ODDS_DIR, "referee_signal_engine.py")
    _rse_spec = _ilu_rse.spec_from_file_location("referee_signal_engine", _rse_path)
    _rse_mod  = _ilu_rse.module_from_spec(_rse_spec)
    _rse_spec.loader.exec_module(_rse_mod)
    _REF_ENGINE_OK = True
    log("Referee signal engine loaded.", "info")
except Exception as _rse_e:
    _rse_mod = None
    _REF_ENGINE_OK = False
    log(f"Referee signal engine unavailable: {_rse_e}", "warning")



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _get(url, timeout=12, **kw):
    """Lightweight JSON GET for circadian schedule + team ID lookups.
    Returns parsed dict/list on success, {} on any failure.
    """
    try:
        import urllib.request as _ur2
        import json           as _j2
        _hdr2 = {"User-Agent": "SportsPE/11 (schedule-fetch)",
                 "Accept": "application/json"}
        _req2 = _ur2.Request(url, headers=_hdr2)
        with _ur2.urlopen(_req2, timeout=timeout) as _r2:
            return _j2.loads(_r2.read())
    except Exception as _ge:
        log(f"[_get] {url[:80]}  err={_ge}", "debug")
        return {}

# CIRCADIAN RHYTHM & TRAVEL FATIGUE ENGINE  â€”  DYNAMIC  v2
#
# Analyzes BOTH teams â€” home team can be just as fatigued.
# MLB: Stats API schedule.  NBA/NHL/NFL/NCAAB: ESPN schedule.
# For each team computes:
#   â€¢ Actual travel origin (last game city, not home city)
#   â€¢ Real time zones crossed
#   â€¢ Days of rest
#   â€¢ Road trip position (or "just returned home" flag)
#   â€¢ Back-to-back flag
#   â€¢ Condensed schedule flag (3 games in 4 nights, etc.)
# Then compares both teams and renders a NET EDGE call.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _lon_to_tz(lon):
    try:
        lon = float(lon)
        # Approximate US timezone bands tuned for common sports metros.
        # ET/CT boundary intentionally shifted west to keep Indianapolis in ET.
        if lon >= -86.5:
            return ("ET", -5)
        if lon >= -101.0:
            return ("CT", -6)
        if lon >= -115.0:
            return ("MT", -7)
        return ("PT", -8)
    except:
        return ("ET", -5)

def _parse_gametime_hour(game_time_str):
    import re
    m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', str(game_time_str), re.IGNORECASE)
    if not m:
        m = re.search(r'(\d{1,2})\s*(AM|PM)', str(game_time_str), re.IGNORECASE)
        if m: h, mn, ampm = int(m.group(1)), 0, m.group(2).upper()
        else: return None, None
    else:
        h, mn, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == "PM" and h != 12: h += 12
    if ampm == "AM" and h == 12: h  = 0
    return h, mn

def _fmt_time(h, m):
    ampm = "AM" if h < 12 else "PM"
    return f"{h%12 or 12}:{m:02d} {ampm}"

def _fetch_team_id_mlb(team_name):
    try:
        data  = _get("https://statsapi.mlb.com/api/v1/teams?sportIds=1")
        nl    = team_name.lower()
        for t in data.get("teams", []):
            for f in ("name","teamName","locationName","franchiseName"):
                v = t.get(f,"").lower()
                if v in nl or nl in v or any(w in v for w in nl.split() if len(w)>3):
                    return t["id"], t.get("name", team_name)
    except: pass
    return None, team_name

def _fetch_schedule_mlb(team_id, today_str, lookback=14):
    """Fetch recent completed games for circadian/travel analysis.
    Uses MLB Stats API v1/schedule with full venue hydration (no fields filter).
    Accepts any game where abstractGameState==Final to avoid statusCode variance.
    """
    from datetime import datetime, timedelta
    try:
        gd = datetime.strptime(today_str, "%Y-%m-%d")
        sd = (gd - timedelta(days=lookback)).strftime("%Y-%m-%d")
        ed = (gd - timedelta(days=1)).strftime("%Y-%m-%d")
        # No "fields" restriction â€” let API return full objects so we get
        # status.abstractGameState AND venue.location.defaultCoordinates
        url = (f"https://statsapi.mlb.com/api/v1/schedule"
               f"?sportId=1&teamId={team_id}&startDate={sd}&endDate={ed}"
               f"&hydrate=venue(location),team&gameType=R,D,L,W,F")
        data = _get(url)
        if not data or "dates" not in data:
            return []
        games = []
        for db in sorted(data.get("dates",[]), key=lambda d: d.get("date",""), reverse=True):
            for g in db.get("games",[]):
                status = g.get("status",{})
                # Accept any abstractGameState of Final (covers F, FR, FT, FO etc.)
                ags = status.get("abstractGameState","") or ""
                sc  = status.get("statusCode","") or ""
                if ags.lower() not in ("final",) and sc not in ("F","FR","FT","FO","O"):
                    continue
                teams = g.get("teams",{})
                h = teams.get("home",{}); a = teams.get("away",{})
                h_id = (h.get("team") or {}).get("id")
                is_home = (h_id == team_id)
                venue  = g.get("venue") or {}
                loc    = venue.get("location") or {}
                coords = loc.get("defaultCoordinates") or {}
                lat    = coords.get("latitude")
                lon    = coords.get("longitude")
                city   = loc.get("city","") or loc.get("stateAbbrev","")
                state  = loc.get("state","") or loc.get("stateAbbrev","")
                games.append({
                    "date":       db.get("date",""),
                    "game_time_iso": g.get("gameDate") or g.get("officialDate") or db.get("date",""),
                    "venue_name": venue.get("name","N/A"),
                    "venue_lat":  lat,
                    "venue_lon":  lon,
                    "city":       city,
                    "state":      state,
                    "is_home":    is_home,
                    "opponent":   (a if is_home else h).get("team",{}).get("name","N/A"),
                    "status":     ags or sc,
                })
        return games  # most recent first
    except Exception as _e:
        log(f"[circadian] MLB schedule fetch failed: {_e}", "warning")
        return []


# â”€â”€ Per-sport circadian weighting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Scale: 1.0 = neutral baseline. Higher = fatigue matters MORE for O/U model.
# Research basis:
#   NBA: 82 games, frequent B2B, 3-4 TZ travel common â†’ strongest fatigue signal
#   NHL: 82 games, road trips every 7-10 days, physical recovery adds fatigue layer
#   MLB: 162 games but physical recovery faster, pitching matchup dominates
#   NFL: 17 games, 1 week rest, but Westâ†’East 1pm games are significant
#   NCAAB: tournament travel matters; regular season moderate
#   NCAAF: weekly, minimal travel fatigue in regular season
SPORT_CIRC_WEIGHT = {
    "NBA":   1.80,   # Most impactful â€” B2B / travel dominate performance variance
    "NHL":   1.50,   # High â€” physical sport, B2B fatigue + goalie workload
    "MLB":   1.00,   # Baseline â€” daily schedule, pitching matchup still primary
    "NFL":   0.70,   # Lower â€” weekly game, travel matters but rest advantage exists
    "NCAAB": 0.85,   # Moderate â€” tournament travel, bench depth constraints
    "NCAAF": 0.55,   # Lowest â€” weekly, mostly regional travel
}
# Condensed schedule: games-in-N-days thresholds
SPORT_CONDENSED = {
    "NBA":   (3, 4),   # 3 games in 4 days = condensed
    "NHL":   (3, 4),
    "MLB":   (3, 4),
    "NFL":   (2, 4),   # 2 games in 4 days (Thu after Sun) = condensed
    "NCAAB": (3, 5),
    "NCAAF": (2, 7),   # very unusual
}
# Back-to-back: same day or 1 calendar day apart
SPORT_BTB_DAYS = {
    "NBA": 1, "NHL": 1, "MLB": 1, "NFL": 3, "NCAAB": 1, "NCAAF": 6,
}

_CITY_LON = {
    "new york":-74.0,"boston":-71.1,"philadelphia":-75.2,"washington":-77.0,
    "baltimore":-76.6,"toronto":-79.4,"atlanta":-84.4,"miami":-80.2,
    "tampa":-82.5,"chicago":-87.6,"detroit":-83.0,"cleveland":-81.7,
    "cincinnati":-84.5,"pittsburgh":-80.0,"milwaukee":-87.9,"minneapolis":-93.3,
    "kansas city":-94.6,"st. louis":-90.2,"houston":-95.4,"dallas":-96.8,
    "denver":-104.9,"phoenix":-112.1,"salt lake":-111.9,"las vegas":-115.1,
    "los angeles":-118.2,"san francisco":-122.4,"san diego":-117.2,
    "seattle":-122.3,"portland":-122.7,"oakland":-122.3,"anaheim":-117.9,
    "charlotte":-80.8,"indianapolis":-86.2,"memphis":-90.0,"new orleans":-90.1,
    "oklahoma city":-97.5,"san antonio":-98.5,"sacramento":-121.5,
    "nashville":-86.8,"jacksonville":-81.7,"buffalo":-78.9,"green bay":-88.0,
}
def _city_to_lon(city):
    c = (city or "").lower()
    for k,v in _CITY_LON.items():
        if k in c: return v
    return None

def _fetch_schedule_espn(sport, team_name, today_str, lookback=12):
    from datetime import datetime, timedelta
    SPORT_MAP = {
        "NBA":  ("basketball","nba"),
        "NHL":  ("hockey",    "nhl"),
        "NFL":  ("football",  "nfl"),
        "NCAAB":("basketball","mens-college-basketball"),
        "NCAAF":("football",  "college-football"),
    }
    sp, lg = SPORT_MAP.get(sport, ("baseball","mlb"))
    try:
        gd  = datetime.strptime(today_str, "%Y-%m-%d")
        sd  = (gd - timedelta(days=lookback)).strftime("%Y%m%d")
        _COLL_ABV = {
            "unc":"north carolina","uconn":"connecticut","vcu":"virginia commonwealth",
            "lsu":"louisiana state","smu":"southern methodist","fsu":"florida state",
            "psu":"penn state","osu":"ohio state","msu":"michigan state",
            "asu":"arizona state","csu":"colorado state","ksu":"kansas state",
            "wsu":"washington state","isu":"iowa state","ucf":"central florida",
            "usc":"southern california","ucsd":"san diego","iowa st":"iowa state",
            "ohio st":"ohio state","mich st":"michigan state","nc state":"north carolina state",
            "app st":"appalachian state","ga tech":"georgia tech",
        }
        nl_raw = team_name.lower().strip()
        nl  = _COLL_ABV.get(nl_raw, nl_raw)
        srch = _get(f"https://site.api.espn.com/apis/site/v2/sports/{sp}/{lg}/teams", timeout=8)
        t_id = None
        for t in (srch.get("sports",[{}])[0]
                     .get("leagues",[{}])[0]
                     .get("teams",[])):
            tn = t.get("team",{})
            # Try both raw and expanded name
            for probe in [nl_raw, nl]:
                if any(probe in (tn.get(f,"") or "").lower()
                       for f in ("displayName","shortDisplayName","name","location")):
                    t_id = tn.get("id"); break
            if t_id: break
        if not t_id: return []
        sched = _get(f"https://site.api.espn.com/apis/site/v2/sports/{sp}/{lg}"
                     f"/teams/{t_id}/schedule?dates={sd}", timeout=8)
        games = []
        for ev in sched.get("events",[]):
            date_str = ev.get("date","")[:10]
            if date_str >= today_str: continue
            comp  = ev.get("competitions",[{}])[0]
            venue = comp.get("venue",{}); addr = venue.get("address",{})
            city  = addr.get("city",""); state = addr.get("state","")
            lon   = _city_to_lon(city)
            is_home = any(
                c.get("homeAway")=="home" and
                any(nl in (c.get("team",{}).get(f,"") or "").lower()
                    for f in ("displayName","name","location"))
                for c in comp.get("competitors",[])
            )
            games.append({
                "date": date_str, "game_time_iso": ev.get("date",""),
                "venue_name": venue.get("fullName","->"),
                "venue_lon": lon, "city": city, "state": state,
                "is_home": is_home, "opponent": "->"
            })
        return sorted(games, key=lambda g: g["date"], reverse=True)
    except: return []

def _team_circ_state(team_name, venue_row, sport, today_str, game_lon):
    """
    Compute full circadian state for one team (works for home OR away).
    Returns dict with all factors needed for rendering and scoring.
    """
    from datetime import datetime, timedelta

    # Fetch schedule
    recent = []
    if sport == "MLB":
        tid, _ = _fetch_team_id_mlb(team_name)
        if tid: recent = _fetch_schedule_mlb(tid, today_str)
    else:
        recent = _fetch_schedule_espn(sport, team_name, today_str)

    # Team home venue longitude
    try:    home_lon = float(venue_row["lon"]) if venue_row is not None else None
    except: home_lon = None

    last_game      = recent[0] if recent else None
    days_rest      = None
    origin_lon     = None
    origin_label   = "Unknown"
    road_trip_len  = 0
    just_home      = False   # returned home from road trip recently
    days_since_road = None

    if last_game:
        try:
            lg_d      = datetime.strptime(last_game["date"], "%Y-%m-%d").date()
            td_d      = datetime.strptime(today_str, "%Y-%m-%d").date()
            days_rest = (td_d - lg_d).days
        except: pass

        origin_lon = last_game.get("venue_lon") or _city_to_lon(last_game.get("city",""))
        city_str   = last_game.get("city","") or last_game.get("venue_name","->")
        state_str  = last_game.get("state","")
        origin_label = f"{city_str}{', '+state_str if state_str else ''} on {last_game['date']}"

        # Road trip / home stand analysis
        consecutive_away = 0
        consecutive_home = 0
        for g in recent:
            if not g["is_home"]: consecutive_away += 1
            else: break
        for g in recent:
            if g["is_home"]: consecutive_home += 1
            else: break

        road_trip_len = consecutive_away   # 0 = currently on home stand

        # "Just returned home": last game was away, but this game is home
        # The team flew back â€” they may still be jet-lagged even at home
        if last_game and not last_game["is_home"]:
            just_home = True   # last game was away; this is a home game
            # How far did they travel back-> Compare last game lon to home lon
            if origin_lon and home_lon:
                days_since_road = days_rest

    # Fallback: use home venue as origin if no schedule data
    if origin_lon is None:
        origin_lon   = home_lon
        _sched_miss = "(MLB schedule API returned no completed games in lookback window)"
        origin_label = f"Home venue â€” schedule data unavailable {_sched_miss}"

    # Time zone calculations
    tz_origin_lbl, tz_origin_off = _lon_to_tz(origin_lon)
    tz_game_lbl,   tz_game_off   = _lon_to_tz(game_lon)

    tz_diff = tz_origin_off - tz_game_off  # body clock shift

    # 3-game-in-4-nights detection
    _c_n, _c_d = SPORT_CONDENSED.get(sport, (3, 4))
    condensed  = False
    if len(recent) >= _c_n:
        try:
            from datetime import datetime as _dt
            d0 = _dt.strptime(today_str, "%Y-%m-%d")
            # Check: _c_n games within _c_d days
            d_ref = _dt.strptime(recent[_c_n - 1]["date"], "%Y-%m-%d")
            span = (d0 - d_ref).days
            if span <= _c_d: condensed = True
        except: pass

    # â”€â”€ Risk scoring (per team) â€” sport-weighted â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    score  = 0
    flags  = []
    _w_mult   = SPORT_CIRC_WEIGHT.get(sport, 1.0)
    _btb_days = SPORT_BTB_DAYS.get(sport, 1)
    _cond_n, _cond_d = SPORT_CONDENSED.get(sport, (3, 4))

    # Timezone shift from origin â†’ game venue
    if abs(tz_diff) >= 3:
        score += 4; flags.append(f"{abs(tz_diff)} TZ shift from last game")
    elif abs(tz_diff) == 2:
        score += 2.5; flags.append(f"2 TZ shift from last game")
    elif abs(tz_diff) == 1:
        score += 1

    # Rest days â€” uses sport-specific B2B threshold
    if days_rest is not None:
        if days_rest == 0:
            score += 3; flags.append("Back-to-back â€” zero rest")
        elif days_rest <= _btb_days:
            score += 2; flags.append(f"{days_rest}d rest (B2B threshold for {sport})")
        elif days_rest == 2 and sport in ("NBA","NHL","MLB"):
            score += 1; flags.append("Short rest (2 days)")
        elif days_rest >= 4:
            score -= 1  # rested â€” slight advantage
            flags.append(f"{days_rest}d rest â€” well rested")

    # Condensed schedule detection (sport-specific window)
    if condensed:
        score += 2.5; flags.append(f"{_cond_n} games in {_cond_d} days â€” condensed schedule")

    # Road trip depth
    _rt_thresh = {"NFL":2, "NCAAF":3}.get(sport, 2)  # road trips are shorter in NFL
    if road_trip_len == 0 and just_home and days_since_road is not None and days_since_road <= 1:
        score += 2
        flags.append("Just returned home from road trip â€” travel fatigue not yet cleared")
    elif road_trip_len >= 6 and sport not in ("NFL","NCAAF"):
        score += 3; flags.append(f"Game {road_trip_len} of road trip â€” deep road fatigue")
    elif road_trip_len >= 4 and sport not in ("NFL","NCAAF"):
        score += 2; flags.append(f"Game {road_trip_len} of road trip â€” cumulative fatigue")
    elif road_trip_len >= _rt_thresh:
        score += 1; flags.append(f"Game {road_trip_len} of road trip")
    elif road_trip_len == 1 and sport in ("NFL","NCAAF"):
        flags.append("Away game")

    # Sport weight multiplier applied to raw score
    raw_score = round(score * _w_mult, 1)
    score = max(0.0, min(10.0, raw_score))

    return {
        "team":          team_name,
        "origin_label":  origin_label,
        "tz_origin":     tz_origin_lbl,
        "tz_game":       tz_game_lbl,
        "tz_diff":       tz_diff,
        "days_rest":     days_rest,
        "road_trip_len": road_trip_len,
        "just_home":     just_home,
        "condensed":     condensed,
        "risk_score":    score,
        "risk_flags":    flags,
        "last_game":     last_game,
    }


# Sport-specific impact text â€” selected dynamically based on actual conditions
_CIRC_NOTES = {
    "MLB": {
        "b2b":       "Back-to-back: bullpen usage from previous game compounds fatigue. Starter pitch count tolerance may drop.",
        "midnight":  "Body clock past midnight â€” pitch recognition and BB/K discipline suppressed in late innings.",
        "road_deep": "Deep road trip: sleep debt accumulates. Exit velocity and sprint speed measurably decline by game 6+.",
        "just_home": "Just returned home: jet lag persists 1-2 days. Home field comfort partially offset by travel fatigue.",
        "condensed": "Condensed schedule: starter availability and bullpen depth both compromised.",
        "normal":    "No significant circadian disruption detected.",
    },
    "NBA": {
        "b2b":       "NBA back-to-back: load management risk on key players. Fatigue shows in 3rd/4th quarter execution.",
        "midnight":  "Late body clock â€” free throw % and late-game defensive rotations most affected.",
        "road_deep": "Long road trip: 3-point attempt rate drops, turnover rate rises by game 5+. Bench depth matters more.",
        "just_home": "Returned home after road stretch: still adjusting. First home game back historically underperforms.",
        "condensed": "3 games in 4 nights: minutes restriction likely. Star players' burst activity reduced.",
        "normal":    "No significant circadian disruption detected.",
    },
    "NHL": {
        "b2b":       "Back-to-back: goaltender decision is critical. Defensive zone coverage breaks down in 3rd period.",
        "midnight":  "Late body clock â€” edge speed, puck battles, and power play execution suppressed.",
        "road_deep": "Long road trip: penalty kill focus deteriorates. Neutral zone structure loses cohesion.",
        "just_home": "Just returned from road trip: conditioning partially restored but sleep cycle still off.",
        "condensed": "3 games in 4 nights â€” fatigue-related penalties and defensive zone breakdowns spike.",
        "normal":    "No significant circadian disruption detected.",
    },
    "NFL": {
        "b2b":       "Short week (Thursday game): injury recovery incomplete, game plan installation rushed for both units.",
        "midnight":  "West Coast team at East Coast early window â€” body clock reads early morning. Historically underperforms first half.",
        "road_deep": "NFL road game is always isolated disruption â€” hotel sleep, crowd noise, routine changes.",
        "just_home": "Returned home after road game â€” standard NFL preparation window applies.",
        "condensed": "Compressed NFL schedule: recovery from Sunday game not complete by Thursday.",
        "normal":    "No significant circadian disruption detected.",
    },
    "NCAAB": {
        "b2b":       "Tournament back-to-back: roster depth critical. Stars show shot-selection fatigue in second half.",
        "midnight":  "Late tip-off on body clock â€” student-athletes more vulnerable than pros. Second-half wall risk.",
        "road_deep": "Conference road swing: cumulative sleep debt on student-athletes is compounding.",
        "just_home": "Returned from road trip â€” first home game back often sees early offensive sloppiness.",
        "condensed": "3 games in 4 nights in tournament: bench depth and FT% most affected.",
        "normal":    "No significant circadian disruption detected.",
    },
}

def _pick_note(sport, days_rest, road_trip_len, just_home, condensed, risk_score, away_clock_h=None):
    notes = _CIRC_NOTES.get(sport, _CIRC_NOTES["MLB"])
    if days_rest == 0:                                     return notes["b2b"]
    if condensed:                                          return notes["condensed"]
    if away_clock_h is not None and (away_clock_h >= 22 or away_clock_h < 6):
                                                           return notes["midnight"]
    if road_trip_len >= 5 and sport != "NFL":               return notes["road_deep"]
    if just_home:                                          return notes["just_home"]
    if risk_score >= 4:                                    return notes.get("road_deep", notes["normal"])
    return                                                        notes["normal"]


def _circ_analysis(game_time, home_row, away_row, sport="MLB",
                   away_team=None, home_team=None, game_date=None):
    """
    Full bilateral circadian analysis â€” computes state for BOTH teams
    then derives a net edge comparison.
    """
    from datetime import date as _date
    today_str = game_date or str(_date.today())

    h_game, mn_game = _parse_gametime_hour(game_time)
    if h_game is None:
        return {"available": False, "reason": "Game time not parseable"}

    # Game venue longitude (home team's park)
    try:    game_lon = float(home_row["lon"]) if home_row is not None else None
    except: game_lon = None
    tz_game_lbl, _ = _lon_to_tz(game_lon) if game_lon else ("ET", -5)

    # â”€â”€ Compute state for both teams â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    away_state = _team_circ_state(away_team or "Away", away_row, sport, today_str,
                                  game_lon) if away_team else {}
    home_state = _team_circ_state(home_team or "Home", home_row, sport, today_str,
                                  game_lon) if home_team else {}

    # Away team body clock at game time
    away_tz_diff   = away_state.get("tz_diff", 0)
    away_clock_h   = (h_game + away_tz_diff) % 24
    away_body_str  = _fmt_time(away_clock_h, mn_game)

    home_tz_diff   = home_state.get("tz_diff", 0)
    home_clock_h   = (h_game + home_tz_diff) % 24
    home_body_str  = _fmt_time(home_clock_h, mn_game)

    away_score = away_state.get("risk_score", 0)
    home_score = home_state.get("risk_score", 0)
    net_diff   = away_score - home_score   # positive = away team more fatigued

    # Impact notes
    away_note = _pick_note(sport,
                           away_state.get("days_rest"),
                           away_state.get("road_trip_len",0),
                           away_state.get("just_home",False),
                           away_state.get("condensed",False),
                           away_score, away_clock_h)
    home_note = _pick_note(sport,
                           home_state.get("days_rest"),
                           home_state.get("road_trip_len",0),
                           home_state.get("just_home",False),
                           home_state.get("condensed",False),
                           home_score, home_clock_h)

    # Net edge call
    # Sport-weighted edge thresholds â€” NBA/NHL reach "significant" at lower raw gap
    _sw = SPORT_CIRC_WEIGHT.get(sport, 1.0)
    _sig_thresh = max(2.0, round(4.0 / _sw, 1))   # NBA: 2.2, MLB: 4.0, NFL: 5.7
    _mod_thresh = max(1.0, round(2.0 / _sw, 1))
    if net_diff >= _sig_thresh:
        edge = f"{away_team} carries significantly higher fatigue load â€” {home_team} has clear circadian edge."
        edge_tag = "good"
    elif net_diff >= _mod_thresh:
        edge = f"{away_team} has moderately higher fatigue â€” mild advantage to {home_team}."
        edge_tag = "good"
    elif net_diff <= -_sig_thresh:
        edge = f"{home_team} carries significantly higher fatigue load â€” circadian edge to {away_team}."
        edge_tag = "warn"
    elif net_diff <= -_mod_thresh:
        edge = f"{home_team} more fatigued than typical home team â€” {away_team} may benefit."
        edge_tag = "warn"
    else:
        edge = "Both teams in comparable circadian states â€” no meaningful fatigue edge."
        edge_tag = "na"

    def _risk_label(s):
        # Thresholds already sport-scaled (weight applied to raw score)
        if s >= 7.0: return "HIGH âš ",    "warn"
        if s >= 4.5: return "MODERATE",   "value"
        if s >= 2.0: return "LOW",         "good"
        if s >= 0.5: return "MINIMAL",     "na"
        return "NEGLIGIBLE", "na"

    away_lbl, away_tag = _risk_label(away_score)
    home_lbl, home_tag = _risk_label(home_score)

    return {
        "available":    True,
        "tz_game":      tz_game_lbl,
        "game_local":   _fmt_time(h_game, mn_game),
        "away_state":   away_state,
        "home_state":   home_state,
        "away_clock":   away_body_str,
        "home_clock":   home_body_str,
        "away_score":   away_score,
        "home_score":   home_score,
        "away_lbl":     away_lbl,
        "home_lbl":     home_lbl,
        "away_tag":     away_tag,
        "home_tag":     home_tag,
        "away_note":    away_note,
        "home_note":    home_note,
        "net_diff":     net_diff,
        "edge":         edge,
        "edge_tag":     edge_tag,
        "data_src":     "MLB Stats API" if sport == "MLB" else "ESPN API",
        "circ_weight":  SPORT_CIRC_WEIGHT.get(sport, 1.0),
    }


def _render_circadian_section(txt, circ, away_clean, home_clean, sport, W=58):
    _w(txt, "\n  CIRCADIAN & TRAVEL FATIGUE\n", "section")
    _sep(txt, "â”€", W)

    if not circ.get("available"):
        _w(txt, f"  âš  {circ.get('reason','unavailable')}\n", "na")
        return

    _w(txt, f"  Game time (venue):  {circ['game_local']}  {circ['tz_game']}"
            f"  |  Source: {circ['data_src']}\n", "na")
    _w(txt, "\n", "na")

    # â”€â”€ Per-team table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _w(txt, f"  {'':4}{'TEAM':<20}{'BODY CLOCK':>12}{'REST':>7}{'ROAD GAME#':>11}{'RISK':>10}\n","label")
    _w(txt, "  " + "â”€"*62 + "\n", "sep")

    for role, team_name, state, clock_str, lbl, tag in [
        ("Away", away_clean, circ["away_state"], circ["away_clock"],
         circ["away_lbl"], circ["away_tag"]),
        ("Home", home_clean, circ["home_state"], circ["home_clock"],
         circ["home_lbl"], circ["home_tag"]),
    ]:
        dr  = state.get("days_rest")
        rt  = state.get("road_trip_len", 0)
        dr_str = ("B2B" if dr == 0 else f"{dr}d" if dr is not None else "->")
        rt_str = ("away" if (sport == "NFL" and rt >= 1) else f"#{rt}" if rt >= 1 else ("just home" if state.get("just_home") else "home stand"))
        dr_tag = "warn" if dr == 0 else "value" if dr == 1 else "good" if (dr or 9) >= 2 else "na"
        txt.insert(tk.END, f"  {role:<4}", "label")
        txt.insert(tk.END, f"{team_name[:19]:<20}", "label")
        _w(txt, f"{clock_str:>12}", tag)
        txt.insert(tk.END, f"{dr_str:>7}", dr_tag)
        txt.insert(tk.END, f"{rt_str:>11}", "value" if rt < 4 else "warn")
        _w(txt, f"{lbl:>10}\n", tag)

        # Origin line
        origin = state.get("origin_label", "->")
        tz_o   = state.get("tz_origin", "->")
        txt.insert(tk.END, f"       Last game: ", "na")
        _w(txt, f"{origin}  ({tz_o})\n", "na")

        # Flags
        for flag in (state.get("risk_flags") or []):
            _w(txt, f"       â–¸ {flag}\n", tag)

    _w(txt, "\n", "na")

    # â”€â”€ Per-team impact notes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for role, team_name, note, tag in [
        ("Away", away_clean, circ["away_note"], circ["away_tag"]),
        ("Home", home_clean, circ["home_note"], circ["home_tag"]),
    ]:
        if "No significant" not in note:
            txt.insert(tk.END, f"  [{role}] {team_name}: ", "label")
            _w(txt, f"{note}\n", "na")

    _w(txt, "\n", "na")
    _sep(txt, "â”€", W)

    # â”€â”€ Net edge â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    txt.insert(tk.END, "  NET CIRCADIAN EDGE:  ", "label")
    _w(txt, f"{circ['edge']}\n", circ["edge_tag"])

    nd = circ["net_diff"]
    _w(txt, f"  Fatigue differential: away {circ['away_score']}/10 vs home {circ['home_score']}/10"
            f"  (ÃŽâ€ {int(nd):+d})\n", "na")




# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# INJURY / NEWS / INTEL READER
# Reads from injury_news_output/INJURY_NEWS_{SPORT}_{DATE}.xlsx
# Written by injury_news_gameday_builder.py (auto-boot fires at startup)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _inj_news_is_fresh(sport):
    """True if today's injury/news Excel exists for this sport."""
    ts  = datetime.now().strftime("%Y%m%d")
    p   = _injury_news_file_path(sport, ts)
    return p.exists()

def _cache_inj_delta(inj_rows: list, sport: str) -> dict:
    """
    Compute SPLIT injury delta from cache only. Never uses placeholders.
    Returns {"off": float, "def": float, "total": float, "has_data": bool}
      off  = offensive production lost (â†’ UNDER signal for THIS team)
      def  = defensive production lost (â†’ OVER signal, opponent scores more)
      total = off + def  (total scoring-unit impact)
    0.0 for any player not in cache â€” no estimates, no positions averages.
    """
    _empty = {"off": 0.0, "def": 0.0, "total": 0.0, "has_data": False}
    if not _NEA_STATS_OK or not _nea_mod:
        return dict(_empty)
    try:
        import sqlite3 as _sl, json as _jc
        from datetime import date as _dc
        _db_path = os.path.join(ODDS_DIR, "nea_stats_cache.db")
        if not os.path.exists(_db_path):
            return dict(_empty)
        _today = str(_dc.today())
        _con = _sl.connect(_db_path, check_same_thread=False)
        _rows = _con.execute(
            "SELECT cache_key, data_json FROM stats_cache WHERE cache_date=?",
            (_today,)).fetchall()
        _con.close()
        # Build lookup: player_name_lower â†’ stats dict
        _cache = {}
        for _ck, _dj in _rows:
            if _dj:
                # key format: "{sport}_{player_name_lower}_{team_lower}"
                _parts = _ck.split("_", 1)
                if len(_parts) >= 2:
                    _cache[_ck] = json.loads(_dj)
        if not _cache:
            return dict(_empty)
        _STATUS_M = {"out":1.0,"60-day-il":0.90,"60-day il":0.90,
                     "15-day-il":0.78,"15-day il":0.78,
                     "10-day-il":0.65,"10-day il":0.65,
                     "day-to-day":0.28,"questionable":0.22,
                     "doubtful":0.55,"injured reserve":0.92}
        off_total = 0.0
        def_total = 0.0
        found_any = False
        for r in inj_rows:
            _name = str(r.get("player","") or "").strip().lower()
            _team = str(r.get("team_name","") or "").strip().lower()
            _st   = str(r.get("status","") or "").lower().replace(" ","-")
            _pos  = str(r.get("pos","") or "").strip().upper()
            _raw_dt = str(r.get("injury_date_raw","") or r.get("date","") or "")
            # Try to find in cache by sport+name+team (exact match preferred)
            _key = f"{sport}_{_name}_{_team}"
            _sd  = _cache.get(_key)
            if _sd is None:
                # Fuzzy: try sport+name only (team may differ slightly)
                _sd = next((v for k,v in _cache.items()
                           if k.startswith(f"{sport}_") and _name in k), None)
            if _sd is None:
                continue  # NOT in cache â†’ 0.0 contribution, no placeholder
            _sc   = float(_sd.get("scoring_contribution",0) or 0)
            _rg   = _nea_mod.compute_rep_gap(
                        _nea_mod.PlayerStats.from_dict(_sd), sport, _pos)
            _smult = _STATUS_M.get(_st, 0.45)
            # Freshness: best-of injury_date_raw + boyds_date + date_reported
            # BREAKING injury (0-1d) = full signal weight â€” market not adjusted yet
            # PRICED IN (8-14d) = 0.38x â€” line already moved, edge gone
            # CHRONIC (31d+) = 0.08x â€” team stats fully absorbed the loss
            _rmult = 0.55
            _date_srcs = [
                str(r.get("injury_date_raw","") or r.get("date","") or ""),
                str(r.get("boyds_date","") or ""),
                str(r.get("date_reported","") or ""),
            ]
            _best_rmult = 9999.0
            _best_age_r = 9999
            for _ds3 in _date_srcs:
                if not _ds3 or _ds3.strip() in ("","nan","none","->"): continue
                try:
                    _rm3, _a3, _ = _nea_mod.injury_recency_mult(_ds3)
                    if _a3 >= 0 and _a3 < _best_age_r:
                        _best_age_r = _a3; _best_rmult = _rm3
                except Exception: pass
            _rmult = _best_rmult if _best_rmult < 9999.0 else 0.55
            r["freshness_mult"]  = _rmult  # store back for display
            r["age_days"]        = _best_age_r if _best_age_r < 9999 else -1
            # Classify role from cached data
            _ps_obj = None
            try: _ps_obj = _nea_mod.PlayerStats.from_dict(_sd)
            except Exception: pass
            _role = _nea_mod._classify_role(sport, _pos, _ps_obj) if _ps_obj else "OFFENSE"
            _contribution = _sc * _rg * _smult * _rmult
            if _role == "OFFENSE":
                off_total += _contribution
            elif _role == "DEFENSE":
                def_total += _contribution
            else:  # MIXED (e.g. MLB SP/RP)
                off_total += _contribution * 0.25  # small offense component
                def_total += _contribution * 0.75  # primary = runs allowed effect
            found_any = True
        return {"off": round(off_total,4), "def": round(def_total,4),
                "total": round(off_total+def_total,4), "has_data": found_any}
    except Exception:
        return dict(_empty)


def _inj_news_lookup(sport, away_clean, home_clean):
    """
    Read today's injury/news Excel for sport and fuzzy-match the game.
    Returns dict: {away_injuries, home_injuries, away_news, home_news,
                   status, source_file}
    """
    ts   = datetime.now().strftime("%Y%m%d")
    path = _injury_news_file_path(sport, ts)
    if not path.exists():
        return {"status": "no_file", "source_file": str(path)}

    # College abbreviation â†’ ESPN displayName keyword map
    _COLLEGE_ABBREV = {
        "unc":"north carolina","uconn":"connecticut","vcu":"virginia commonwealth",
        "lsu":"louisiana state","smu":"southern methodist","tcu":"tcu",
        "ucf":"central florida","usc":"southern california","ucla":"ucla",
        "byu":"brigham young","ole miss":"mississippi","unlv":"nevada las vegas",
        "utep":"texas el paso","utsa":"texas san antonio","uab":"alabama birmingham",
        "umass":"massachusetts","uri":"rhode island","uic":"illinois chicago",
        "fiu":"florida international","fau":"florida atlantic",
        "niu":"northern illinois","wku":"western kentucky",
        "wmu":"western michigan","emu":"eastern michigan",
        "cmu":"central michigan","bgsu":"bowling green","odu":"old dominion",
        "appalachian st":"appalachian state","app st":"appalachian state",
        "ga tech":"georgia tech","nc state":"north carolina state",
        "nc st":"north carolina state","fla st":"florida state",
        "fsu":"florida state","psu":"penn state","osu":"ohio state",
        "msu":"michigan state","asu":"arizona state","csu":"colorado state",
        "ksu":"kansas state","wsu":"washington state","isu":"iowa state",
        "k-state":"kansas state","iowa st":"iowa state",
        "miami fl":"miami","miami oh":"miami ohio","miami ohio":"miami ohio",
        "ohio u":"ohio","ohio univ":"ohio","bowling green":"bowling green",
        "ball st":"ball state","kent st":"kent state","akron":"akron",
        "buffalo":"buffalo","bennet":"bennett","fcs":""
    }

    def _norm(s):
        import re as _re
        s = (_re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()
        return _re.sub(r"\s+", " ", s)

    def _expand_abbrev(name):
        """Expand known college abbreviations to full name keywords."""
        nl = _norm(name)
        # Direct lookup
        if nl in _COLLEGE_ABBREV: return _COLLEGE_ABBREV[nl]
        # Partial key match (handles "UNC Charlotte" â†’ "north carolina")
        for k,v in _COLLEGE_ABBREV.items():
            if nl == k or nl.startswith(k+" "): return v
        return nl

    def _fuzzy_match(name, candidates):
        """Return True if name fuzzy-matches any candidate. College-aware."""
        n      = _norm(name)
        n_exp  = _expand_abbrev(name)   # expanded form for abbrev matching
        for c in (candidates or []):
            cv = _norm(str(c))
            if not cv: continue
            # Direct containment
            if cv in n or n in cv: return True
            if n_exp and (n_exp in cv or cv in n_exp): return True
            # Word overlap on both original and expanded
            for probe in [n, n_exp]:
                pw = set(probe.split()); cw = set(cv.split())
                if pw and cw and len(pw & cw) >= max(1, min(len(pw), len(cw)) - 1):
                    return True
        return False

    try:
        _xl = pd.ExcelFile(path)
        _sheet_set = {str(s).strip().upper() for s in (_xl.sheet_names or [])}
        inj_df = pd.read_excel(_xl, sheet_name="INJURIES", dtype=str) if "INJURIES" in _sheet_set else pd.DataFrame()
        news_df = pd.read_excel(_xl, sheet_name="TEAM_NEWS", dtype=str) if "TEAM_NEWS" in _sheet_set else pd.DataFrame()
        if inj_df.empty and news_df.empty and not {"INJURIES", "TEAM_NEWS"} & _sheet_set:
            return {"status": "no_structured_sheets", "source_file": str(path)}
    except Exception as e:
        return {"status": f"read_error: {e}", "source_file": str(path)}

    # Match rows where team_name fuzzy-matches away or home
    def _side_rows(df, team_name, side_col="team_side", side_val=None):
        mask = df["team_name"].apply(lambda x: _fuzzy_match(team_name, [x]))
        rows = df[mask]
        if side_val and "team_side" in rows.columns:
            rows = rows[rows["team_side"] == side_val]
        return rows.to_dict("records")

    away_inj  = _side_rows(inj_df,  away_clean, side_val="away") if "team_name" in inj_df.columns  else []
    home_inj  = _side_rows(inj_df,  home_clean, side_val="home") if "team_name" in inj_df.columns  else []
    away_news = _side_rows(news_df, away_clean, side_val="away") if "team_name" in news_df.columns else []
    home_news = _side_rows(news_df, home_clean, side_val="home") if "team_name" in news_df.columns else []

    # Fallback: if side filtering returns nothing, drop the side filter
    if not away_inj  and "team_name" in inj_df.columns:  away_inj  = _side_rows(inj_df,  away_clean)
    if not home_inj  and "team_name" in inj_df.columns:  home_inj  = _side_rows(inj_df,  home_clean)
    if not away_news and "team_name" in news_df.columns:  away_news = _side_rows(news_df, away_clean)
    if not home_news and "team_name" in news_df.columns:  home_news = _side_rows(news_df, home_clean)

    # Sort injuries by source_priority (lower = more authoritative)
    def _sort_inj(rows):
        pri = {"espn_core":1,"espn_html":1,"sleeper":1,"covers":2,"boydsbets":2,"cfbdepth":2,"rotowire":3}
        return sorted(rows, key=lambda r: int(pri.get(str(r.get("source","")),50)))

    # Re-classify & deduplicate at load time so old XLSX files get fixed automatically
    import re as _re2
    def _reclassify(hl, sm, url=""):
        """Apply fixed word-boundary classification to a news row."""
        blob = f"{(hl or '').lower()} {(sm or '').lower()} {(url or '').lower()}"
        _inj_exact = ["injury","injured reserve","questionable","doubtful","day-to-day","placed on","injured"]
        if any(k in blob for k in _inj_exact): return "injury"
        if _re2.search(r"\bout\b", blob) and not any(k in blob for k in ["shoutout","without","standout","throughout","throughout","bout","layout","runout","timeout","burnout","shutout","workout","cutout","blowout","carryout","stayout","payout","trout","clout","sprout","throughout","throughout"]): return "injury"
        if any(k in blob for k in ["trade","traded","waived","signed","release","released","contract"]): return "transaction"
        if any(k in blob for k in ["preview","brings","visit","hosts","take on","matchup","host","faces","opens series"]): return "preview"
        if any(k in blob for k in ["recap","beats","defeat","win over","wins","rout","homer","homers","scores","grand slam","walk-off","walkoff"]): return "recap"
        if "video" in blob: return "video"
        if any(k in blob for k in ["power rankings","straw poll","big board","bracketology","top 25"]): return "power_ranking"
        return "analysis"
    def _dedup_news(rows):
        seen, out = set(), []
        for r in rows:
            hl = str(r.get("headline","") or "").strip()
            key = hl[:60].lower()
            if key and key in seen: continue
            seen.add(key)
            # Re-classify
            r["category"] = _reclassify(hl, str(r.get("summary","") or ""), str(r.get("url","") or ""))
            out.append(r)
        return out
    # â”€â”€ Merge BoydsBets data BEFORE sorting/returning â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # BoydsBets is more current than XLSX. merge_with_xlsx() adds missing
    # players and overrides stale statuses. season_ending flag is set here.
    if _BOYDS_OK and _bb_mod:
        try:
            away_inj = _bb_mod.merge_with_xlsx(list(away_inj), sport, away_clean)
            home_inj = _bb_mod.merge_with_xlsx(list(home_inj), sport, home_clean)
        except Exception: pass
    return {
        "status":         "ok",
        "source_file":    str(path),
        "away_injuries":  _sort_inj(away_inj),
        "home_injuries":  _sort_inj(home_inj),
        "away_news":      _dedup_news(sorted(away_news, key=lambda r: int(r.get("relevance_score",0) or 0), reverse=True)),
        "home_news":      _dedup_news(sorted(home_news, key=lambda r: int(r.get("relevance_score",0) or 0), reverse=True)),
        # Injury deltas: READ FROM CACHE ONLY â€” 0.0 if not yet fetched
        # Real stats arrive after first render click (batch ESPN fetch).
        # No placeholder values. No signal > fake signal.
        "away_inj_delta": _cache_inj_delta(away_inj, sport),
        "home_inj_delta": _cache_inj_delta(home_inj, sport),
    }


# Status display tag mapping
_STATUS_TAGS = {
    "out":           "warn",
    "ir":            "warn",
    "injured reserve":"warn",
    "doubtful":      "warn",
    "questionable":  "value",
    "day-to-day":    "value",
    "probable":      "good",
    "active":        "good",
}
def _status_tag(status):
    return _STATUS_TAGS.get((status or "").lower().strip(), "na")



def _render_lineup_section(txt, away_clean, home_clean, sport, W=62):
    """
    Render per-player lineup assessment in the matchup popup.
    Shows: status (CONFIRMED/EXPECTED), top contributors, power rating,
    air density sensitivity, and any Covers.com discrepancy flags.
    Data comes from nea_lineup_assessor + rotowire_multi_sport_scraper.
    """
    if not _NEA_LINEUP_OK or not _la_mod or not _NEA_STATS_OK or not _nea_mod:
        return
    try:
        _las = _la_mod.get_lineup_assessments(
            sport, away_clean, home_clean, _nea_mod,
            max_workers=4, timeout_per_side=6.0)
    except Exception:
        return

    _w(txt, "\n  LINEUP ASSESSMENT\n", "section")
    _sep(txt, "â”€", W)

    _ST_COLOR = {"CONFIRMED":"good","EXPECTED":"warn","PROJECTED":"warn",
                 "UNKNOWN":"na","NOT_POSTED":"na"}

    for side_key, label in [("away", away_clean), ("home", home_clean)]:
        la = _las.get(side_key)
        if la is None:
            continue
        _w(txt, f"  {'AWAY' if side_key=='away' else 'HOME'} â€” {label}\n", "label")

        # Lineup status badge
        st_tag = _ST_COLOR.get(la.lineup_status, "na")
        _w(txt, f"  Status        ", "na")
        _w(txt, f"{la.lineup_status}", st_tag)
        conf_str = f"  ({la.found_count}/{la.expected_count} players with real stats)"
        _w(txt, conf_str + "\n", "na")

        if la.found_count == 0:
            _w(txt, "  Lineup not yet posted or stats not cached.\n", "na")
        else:
            # Total scoring contribution
            _w(txt, f"  Total SC      {la.total_sc:.3f}  ", "value")
            _w(txt, f"(lineup scoring-contribution sum)\n", "na")

            # Sport-specific metrics
            if sport == "MLB":
                _w(txt, f"  Avg HR/G      {la.power_rating:.4f}  ", "value")
                _w(txt, f"Avg OPS {la.avg_ops:.3f}\n", "na")
                if la.rho_delta_per_pct != 0.0:
                    _rho_dir = "benefits" if la.rho_delta_per_pct > 0 else "hurt by"
                    _w(txt, f"  Rho Sens      {la.rho_delta_per_pct:+.4f}  ", "value")
                    _w(txt, f"(lineup {_rho_dir} dense air)\n", "na")
            elif sport in ("NBA","NCAAB"):
                _w(txt, f"  Avg MPG       {la.avg_mpg:.1f} min\n", "value")
            elif sport == "NHL":
                _w(txt, f"  Avg TOI/G     {la.avg_mpg:.1f} min\n", "value")

            # Top contributors
            if la.top_contributors:
                _w(txt, "  Top players   ", "na")
                _w(txt, " | ".join(la.top_contributors[:3]) + "\n", "value")

            # BoydsBets flags (live cross-reference, highest priority)
            if _BOYDS_OK and _bb_mod:
                try:
                    _inj_d_bb = _inj_news_lookup(sport, away_clean, home_clean)
                    _bb_side  = "away_injuries" if side_key=="away" else "home_injuries"
                    _bb_rows  = _inj_d_bb.get(_bb_side, []) if _inj_d_bb else []
                    _bb_disc  = _bb_mod.cross_reference(_bb_rows, sport, label)
                    if _bb_disc:
                        _w(txt, f"\n  âš¡ BOYDSBETS FLAGS ({len(_bb_disc)})\n", "warn")
                        for _bd in _bb_disc[:6]:
                            _se = " Ã°Å¸Å¡Â¨ SEASON-ENDING" if _bd.get("season_ending") else ""
                            _ftag = "warn" if "SEASON" in _bd["discrepancy"] else "na"
                            _w(txt, f"  â€¢ {_bd['player']} ({_bd.get('pos','->')}){_se}\n", _ftag)
                            _w(txt, f"    BoydsBets: {_bd['boyds_status']}  |  XLSX: {_bd['xlsx_status']}\n", "na")
                            if _bd.get("boyds_notes"):
                                _w(txt, f"    {str(_bd['boyds_notes'])[:110]}\n", "na")
                except Exception: pass
            # Covers.com discrepancy flags
            disc = getattr(la, "covers_discrepancies", [])
            if disc:
                _w(txt, f"\n  âš  COVERS.COM FLAGS ({len(disc)} discrepancies)\n", "warn")
                for d in disc[:5]:
                    tag = "warn" if d["discrepancy"]=="COVERS_ONLY" else "na"
                    _w(txt, f"  â€¢ {d['player']} ({d.get('pos','->')}) â€” "
                             f"Covers: {d['covers_status']} | "
                             f"XLSX: {d['xlsx_status']}\n", tag)
                    if d.get("covers_details"):
                        _w(txt, f"    {d['covers_details']}\n", "na")

        _w(txt, "\n", "na")

    _sep(txt, "â”€", W)



def _render_injury_news_section(txt, inj_data, away_clean, home_clean, sport, W=58):
    """Render INJURIES & NEWS INTEL section in the detail popup."""
    inj_data = dict(inj_data or {"status": "no_file"})
    _w(txt, "\n  INJURIES & NEWS INTEL\n", "section")
    _sep(txt, "â”€", W)

    status = inj_data.get("status", "no_file")

    if status == "no_file":
        _w(txt, "  âš™  Auto-boot running â€” injury data populating in background.\n"
                "     Close and re-open this popup once Run Log shows âœ….\n", "warn")
        return
    if status == "no_structured_sheets":
        _w(txt, "  âš™  Injury workbook found but missing structured sheets (INJURIES/TEAM_NEWS).\n"
                "     Auto-boot rebuild will refresh this file format.\n", "warn")
        return

    if status != "ok":
        _w(txt, f"  âš   {status}\n", "warn")
        return

    # â”€â”€ INJURIES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _inj_team_totals = {}  # role â†’ (total_impact, team_name)
    for role, team_name, inj_rows in [
        ("AWAY", away_clean, inj_data.get("away_injuries", [])),
        ("HOME", home_clean, inj_data.get("home_injuries", [])),
    ]:
        _w(txt, f"\n  {role} â€” {team_name}\n", "label")
        real_rows = [r for r in inj_rows if str(r.get("source","")).upper() != "NO_DATA"
                                         and str(r.get("player","")).strip()]
        if not real_rows:
            _w(txt, "  No injuries reported.\n", "na")
        else:
            seen_players = set()
            # â”€â”€ Parallel stats fetch (non-blocking: max 8s, cache hit = instant) â”€â”€
            _impacts = {}
            if _NEA_STATS_OK and _nea_mod and real_rows:
                try:
                    # First: populate from cache (instant, no network)
                    import sqlite3 as _sl3, json as _jc3
                    from datetime import date as _dc3
                    _db3 = os.path.join(ODDS_DIR,"nea_stats_cache.db")
                    _today3 = str(_dc3.today())
                    _cached_keys: set = set()
                    if os.path.exists(_db3):
                        try:
                            _con3 = _sl3.connect(_db3,check_same_thread=False)
                            _cached_keys = {r[0] for r in _con3.execute(
                                "SELECT cache_key FROM stats_cache WHERE cache_date=?",
                                (_today3,)).fetchall()}
                            _con3.close()
                        except Exception: pass
                    # Only fetch players NOT already cached
                    _sp2 = sport.upper()
                    _uncached = [r for r in real_rows
                                 if f"{_sp2}_{str(r.get('player','') or '').strip().lower()}_{str(r.get('team_name','') or team_name).strip().lower()}"
                                    not in _cached_keys]
                    if _uncached:
                        _new = _nea_mod.compute_inj_impacts_batch(
                            _uncached, team_name, sport, max_workers=4, timeout=8.0)
                    else:
                        _new = {}
                    # Now load all (cached + newly fetched) via cache-only path
                    _cached_d = _cache_inj_delta(real_rows, sport)
                    # Build display dict from batch results + cache delta
                    _impacts = _new if _new else {}
                    # Supplement with any cache hits for players not in _new
                    for _rr in real_rows:
                        _pn = str(_rr.get("player","") or "").strip()
                        if _pn and _pn not in _impacts:
                            _st3 = str(_rr.get("status","")).strip()
                            _ps3 = str(_rr.get("pos","")).strip()
                            _dt3 = str(_rr.get("injury_date_raw","") or _rr.get("date","") or "").strip()
                            _ip3 = _ps3.upper() in ("SP","RP","P","CL")
                            _ir3 = _ps3.upper() in ("RP","CL")
                            try:
                                _chit = _nea_mod.compute_inj_impact(
                                    _pn, team_name, sport, _st3, _ps3, _ip3, _ir3, _dt3)
                                if _chit and _chit.get("found"): _impacts[_pn] = _chit
                            except Exception: pass
                except Exception: _impacts = {}
            _team_inj_total = 0.0
            if _impacts:
                txt.insert(tk.END, f"  {'Player':<22}{'Pos':<5}{'Status':<13}{'Details':<16}{'Date/Age':<10}Impact\n", "label")
            else:
                txt.insert(tk.END, f"  {'Player':<22}{'Pos':<5}{'Status':<13}{'Details':<16}Date/Age\n", "label")
            _w(txt, "  " + "â”€" * (W - 2) + "\n", "sep")
            for r in real_rows:
                player  = str(r.get("player","")).strip()
                if not player or player.lower() in seen_players: continue
                seen_players.add(player.lower())
                pos     = str(r.get("pos","")).strip()[:5]
                status  = str(r.get("status","")).strip()[:14]
                def _sstr(v):
                    import math
                    try:
                        if v is None: return ""
                        if isinstance(v, float) and math.isnan(v): return ""
                        s = str(v).strip()
                        return "" if s.lower() in ("nan","none","null","") else s
                    except: return ""
                details = (_sstr(r.get("injury")) or _sstr(r.get("details","")) or _sstr(r.get("note","")) or "")[:16]
                stag    = _status_tag(status)
                # Date display + age
                # â”€â”€ Freshness: use upgraded injury_recency_mult (handles BoydsBets format)
                # Best-of: XLSX date, BoydsBets boyds_date, date_reported â€” picks most recent
                _freshness_mult  = r.get("freshness_mult")   # pre-enriched if available
                _freshness_label = r.get("freshness_label","")
                _age_days_r      = r.get("age_days", -1)
                if _freshness_mult is None and _NEA_STATS_OK and _nea_mod:
                    # Not yet enriched â€” compute now
                    _date_candidates = [
                        _sstr(r.get("injury_date_raw") or r.get("date","")),
                        _sstr(r.get("boyds_date","")),
                        _sstr(r.get("date_reported","")),
                    ]
                    _best_age2 = 9999; _best_m2 = 0.55; _best_l2 = "unknown"
                    for _dc2 in _date_candidates:
                        if not _dc2: continue
                        try:
                            _m2,_a2,_l2 = _nea_mod.injury_recency_mult(_dc2)
                            if _a2 >= 0 and _a2 < _best_age2:
                                _best_age2,_best_m2,_best_l2 = _a2,_m2,_l2
                        except Exception: pass
                    _freshness_mult  = _best_m2
                    _freshness_label = _best_l2 if _best_l2 != "unknown" else ""
                    _age_days_r      = _best_age2 if _best_age2 < 9999 else -1
                # Format age label for column
                _age_lbl = _freshness_label or ""
                if not _age_lbl and _age_days_r >= 0:
                    _age_lbl = "today" if _age_days_r == 0 else f"{_age_days_r}d"
                # Freshness tag for color coding
                _fresh_tag = "na"
                if _freshness_label:
                    if "BREAKING" in _freshness_label:  _fresh_tag = "warn"   # bright orange
                    elif "RECENT"  in _freshness_label:  _fresh_tag = "value"  # yellow
                    elif "PRICED"  in _freshness_label or "STALE" in _freshness_label or "CHRONIC" in _freshness_label:
                        _fresh_tag = "good"  # green = low signal value
                imp_d   = _impacts.get(player,{})
                tier    = imp_d.get("impact_tier","") if imp_d else ""
                impact_v = imp_d.get("impact",0.0) if imp_d else 0.0
                _team_inj_total += abs(impact_v) if tier not in ("","MINIMAL","UNKNOWN") else 0.0
                # Impact badge
                TIER_TAG = {"HIGH":"warn","MOD":"value","LOW":"good","MINIMAL":"na","UNKNOWN":"na"}
                if tier and tier != "UNKNOWN":
                    sc_s = imp_d.get("scoring_contribution",0)
                    _role_s = imp_d.get("role","OFFENSE")
                    _role_badge = "" if _role_s=="OFFENSE" else "â¬†OPP" if _role_s=="DEFENSE" else "~"
                    if imp_d.get("is_pitcher") and imp_d.get("era",0)>0:
                        imp_str = f"ERA {imp_d['era']:.2f} [{tier}]{_role_badge}"
                    elif sport=="MLB":
                        imp_str = f"{sc_s:.3f}SC [{tier}]{_role_badge}"
                    elif sport in ("NBA","NCAAB"):
                        imp_str = f"{sc_s:.1f}ppg [{tier}]{_role_badge}"
                    else:
                        imp_str = f"{sc_s:.1f}SC [{tier}]{_role_badge}"
                    _rec_lbl = imp_d.get("age_label","") if imp_d else ""
                    txt.insert(tk.END, f"  {player[:21]:<22}{pos:<5}", "na")
                    _w(txt, f"{status:<13}", stag)
                    _w(txt, f"{details:<16}", "na")
                    _w(txt, f"{_age_lbl or _rec_lbl:<14}", _fresh_tag)
                    _w(txt, f"{imp_str}\n", TIER_TAG.get(tier,"na"))
                else:
                    txt.insert(tk.END, f"  {player[:21]:<22}{pos:<5}", "na")
                    _w(txt, f"{status:<13}", stag)
                    _w(txt, f"{details:<16}", "na")
                    _w(txt, f"{_age_lbl:<14}\n", _fresh_tag)
            # Store aggregate for NET INJURY IMPACT section
            _inj_team_totals[role] = (_team_inj_total, team_name)

    # â”€â”€ NET INJURY IMPACT SUMMARY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if _NEA_STATS_OK and _inj_team_totals:
        _a_total, _a_team = _inj_team_totals.get("AWAY", (0.0, away_clean))
        _h_total, _h_team = _inj_team_totals.get("HOME", (0.0, home_clean))
        _either_sig = _a_total > 0.05 or _h_total > 0.05
        if _either_sig:
            _w(txt, "\n  NET INJURY IMPACT\n", "section")
            _sep(txt, "â”€", W)
            def _itag(v): return "warn" if v>=0.55 else "value" if v>=0.22 else "good"
            def _ilbl(v):
                if sport=="MLB":  return "HIGH" if v>=0.55 else "MOD" if v>=0.22 else "LOW"
                if sport in ("NBA","NCAAB"): return "HIGH" if v>=8 else "MOD" if v>=4 else "LOW"
                return "HIGH" if v>=0.4 else "MOD" if v>=0.2 else "LOW"
            _unit = {"MLB":"runs/g","NBA":"pts/g","NCAAB":"pts/g","NHL":"goals/g","NFL":"pts/g"}.get(sport,"units/g")
                # Split from _inj_team_totals which stores (total, team_name)
            # For display we separate offense vs defense in the summary
            for _rt, (_rtotal, _rteam) in [("Away",(_a_total,_a_team)),("Home",(_h_total,_h_team))]:
                _w(txt, f"  {_rt} {_rteam:<22} ", "na")
                _w(txt, f"âˆ’{_rtotal:.3f} {_unit}  [{_ilbl(_rtotal)}]\n", _itag(_rtotal))
            _net_edge = _a_total - _h_total
            if abs(_net_edge) > 0.05:
                _edge_team = _a_team if _net_edge>0 else _h_team
                _edge_side = "Home" if _net_edge>0 else "Away"
                _w(txt, f"  \u2192 Side edge: +{abs(_net_edge):.3f} {_unit} toward {_edge_side} ({_edge_team})\n", "warn")
            else:
                _w(txt, "  \u2192 Injury impact roughly symmetric â€” no material side edge.\n", "na")
            # Total lean signal note
            if _NEA_STATS_OK:
                _a_rd = _cache_inj_delta(inj_data.get("away_injuries",[]), sport)
                _h_rd = _cache_inj_delta(inj_data.get("home_injuries",[]), sport)
                if _a_rd["def"] > 0.05 or _h_rd["def"] > 0.05:
                    _w(txt, f"  \u26a0 Defensive holes: away={_a_rd['def']:.3f} home={_h_rd['def']:.3f} {_unit}\n", "warn")
                    _w(txt, "    Missing defenders/pitchers create OVER pressure for opponent.\n", "na")
                if _a_rd["off"] > 0.05 or _h_rd["off"] > 0.05:
                    _w(txt, f"  \u25bc Offensive holes: away={_a_rd['off']:.3f} home={_h_rd['off']:.3f} {_unit}\n", "value")
                    _w(txt, "    Missing scorers create UNDER pressure on total.\n", "na")

    # â”€â”€ NEWS / INTEL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    CAT_ICON = {
        "injury":      "Ã°Å¸Â©Â¹",
        "transaction": "Ã°Å¸â€â€ž",
        "preview":     "ðŸ”",
        "recap":       "Ã°Å¸â€œâ€¹",
        "analysis":    "Ã°Å¸â€œÅ ",
        "video":       "â–¶",
        "power_ranking":"Ã°Å¸â€œË†",
    }
    for role, team_name, news_rows in [
        ("AWAY", away_clean, inj_data.get("away_news", [])),
        ("HOME", home_clean, inj_data.get("home_news", [])),
    ]:
        shown = [r for r in news_rows
                 if str(r.get("category","")) not in ("power_ranking","video","recap")
                 and str(r.get("headline","")).strip()][:8]
        if not shown: continue
        _w(txt, f"\n  INTEL â€” {team_name}\n", "label")
        _sep(txt, "â”€", W)
        for r in shown:
            cat  = str(r.get("category","analysis"))
            icon = CAT_ICON.get(cat, "â–¸")
            hl   = str(r.get("headline","")).strip()[:70]
            pub  = str(r.get("published_at","")).strip()[:16].replace("T"," ")
            stag = "warn" if cat == "injury" else "value" if cat == "transaction" else "na"
            _w(txt, f"  {icon} [{cat[:8]:<8}] {hl}\n", stag)
            if pub:
                _w(txt, f"           {pub}\n", "na")

    _w(txt, f"\n  Source: {Path(inj_data.get('source_file','')).name}\n", "na")



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MATCHUPS LOGIC
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
_current_matchups_df = None
data_df              = None   # alias â€” always kept in sync with _current_matchups_df
_matchup_fetch_seq   = 0

def _today_xlsx_path(league_upper):
    ts   = datetime.now().strftime("%Y%m%d")
    path = Path(ODDS_DIR) / f"Odds_{league_upper}_{ts}.xlsx"
    return str(path) if path.exists() else None

def _load_xlsx(path):
    try:
        d = pd.read_excel(path)
        for col in ["Away_Team","Home_Team","Time",
                    "Away_Spread","Home_Spread","Total","Away_ML","Home_ML"]:
            if col not in d.columns:
                d[col] = ""
        for col in ["Away_Team","Home_Team"]:
            d[col] = d[col].astype(str).apply(_strip_pitcher)
        return d
    except Exception as e:
        log(f"Failed to read odds file {path}: {e}", "error")
        return None


def _populate_tree(_input_df):
    global _current_matchups_df, data_df
    _current_matchups_df = _input_df
    data_df              = _input_df   # keep alias in sync
    matchup_tree.delete(*matchup_tree.get_children())
    if data_df is None or data_df.empty:
        m_status_var.set("No games found for today.")
        _set_matchup_load_progress(100.0, "no games found for today's slate")
        try:
            _dashboard_top_var.set("Top opportunities: no games on slate.")
        except Exception:
            pass
        try:
            _slate_set_detail_empty("No games on current slate")
        except Exception:
            pass
        try:
            _update_dashboard_hero(slate_games=0)
        except Exception:
            pass
        load_physics_btn.config(state=tk.DISABLED)
        return

    # Always present games in chronological order by local game start time.
    try:
        _sorted_df = data_df.copy()
        _sorted_df["_time_sort_dt"] = _sorted_df.get("Time", "").apply(
            lambda _v: _parse_game_time(str(_v)) if str(_v).strip() else None
        )
        _sorted_df["_time_sort_missing"] = _sorted_df["_time_sort_dt"].isna()
        _sorted_df = _sorted_df.sort_values(
            by=["_time_sort_missing", "_time_sort_dt", "Away_Team", "Home_Team"],
            kind="mergesort",
        ).drop(columns=["_time_sort_dt", "_time_sort_missing"], errors="ignore")
        data_df = _sorted_df.reset_index(drop=True)
        _current_matchups_df = data_df
    except Exception as _sort_e:
        log(f"[matchups] time sort skipped: {_sort_e}", "warning")

    bypassed_col = "match_method" in data_df.columns
    n_bypassed   = int((data_df["match_method"] == "resolver_bypassed").sum()) if bypassed_col else 0
    all_bypassed = (n_bypassed == len(data_df))
    mixed        = (0 < n_bypassed < len(data_df))

    for i, row in data_df.iterrows():
        asp = str(row.get("Away_Spread","") or "")
        hsp = str(row.get("Home_Spread","") or "")
        tot = str(row.get("Total","")       or "")
        aml = str(row.get("Away_ML","")     or "")
        hml = str(row.get("Home_ML","")     or "")
        no_odds   = all(v.strip() in ["","nan","NaN","None"] for v in [asp,hsp,tot,aml,hml])
        is_bypass = bypassed_col and row.get("match_method") == "resolver_bypassed"
        if is_bypass and mixed:
            tag = "bypass"
        elif no_odds:
            tag = "no_odds"
        elif i % 2 == 0:
            tag = "odd"
        else:
            tag = "even"
        def _clean(v):
            return "--" if str(v).strip().lower() in ["","nan","none"] else str(v)
        time_disp = str(row.get("Time","") or "")
        away_disp = str(row.get("Away_Team","") or "")
        home_disp = str(row.get("Home_Team","") or "")
        if no_odds:
            # Label it so the user knows exactly why it's grayed
            away_disp = f"{away_disp}  [NO ODDS]"
        matchup_tree.insert("","end",iid=str(i),tags=(tag,),values=(
            time_disp, away_disp, home_disp,
            _clean(asp), _clean(hsp), _clean(tot),
            _clean(aml), _clean(hml)
        ))

    bypass_note = (
        "  [game_id resolver N/A - odds data is live & accurate]" if all_bypassed
        else f"  [WARN] {n_bypassed} row(s) resolver-bypassed" if mixed
        else ""
    )
    m_status_var.set(
        f"{len(data_df)} game(s) loaded{bypass_note}  |  "
        f"Select row for live intelligence  |  Double-click -> Matchup Detail."
    )
    _set_matchup_load_progress(100.0, f"fully loaded - {len(data_df)} game(s) ready")
    try:
        _top_rows = data_df.head(3)
        _parts = []
        for _, _r in _top_rows.iterrows():
            _a = str(_r.get("Away_Team", "") or "").strip()
            _h = str(_r.get("Home_Team", "") or "").strip()
            _t = str(_r.get("Time", "") or "").strip()
            if _a and _h:
                _parts.append(f"{_a} @ {_h} {_t}".strip())
        _dashboard_top_var.set(
            "Top opportunities: " + (" | ".join(_parts) if _parts else "awaiting slate signal.")
        )
    except Exception:
        pass
    try:
        _update_dashboard_hero(slate_games=len(data_df))
    except Exception:
        pass
    load_physics_btn.config(state=tk.NORMAL)
    _kids = matchup_tree.get_children("")
    if _kids:
        matchup_tree.selection_set(_kids[0])
        matchup_tree.focus(_kids[0])
        try:
            _refresh_slate_detail_from_selection()
        except Exception:
            pass
    else:
        try:
            _slate_set_detail_empty("No games on current slate")
        except Exception:
            pass
    log(f"Matchups table populated - {len(data_df)} games.", "info")


def _injury_news_file_state(league: str):
    token = datetime.now().strftime("%Y%m%d")
    p = _injury_news_file_path(str(league).upper(), token)
    try:
        if not p.exists() or p.stat().st_size <= 0:
            return ("MISSING", "injury workbook missing")
        if not _injury_news_has_required_sheets(p):
            return ("MALFORMED", "injury workbook missing INJURIES/TEAM_NEWS")
        return ("READY", "")
    except Exception:
        return ("MISSING", "injury workbook missing")

def _injury_news_file_ready(league: str) -> bool:
    try:
        return _injury_news_file_state(league)[0] == "READY"
    except Exception:
        return False


def _startup_task_snapshot() -> dict:
    try:
        with _STARTUP_TASK_STATE_LOCK:
            st = _startup_task_state_read_nolock()
            return dict(st.get("tasks", {}) or {})
    except Exception:
        return {}


def _startup_task_get(tasks: dict, name: str) -> dict:
    try:
        return dict((tasks or {}).get(name, {}) or {})
    except Exception:
        return {}


def _refresh_league_ingest_board(readiness_map: dict):
    tasks = _startup_task_snapshot()
    stats_task = _startup_task_get(tasks, "stats_sos_daily")
    inj_task = _startup_task_get(tasks, "injury_news_daily")
    mlb_task = _startup_task_get(tasks, "mlb_stats_daily")
    injury_required_leagues = set(_injury_news_required_leagues_today())

    stats_task_status = str(stats_task.get("status", "")).lower().strip()
    inj_task_status = str(inj_task.get("status", "")).lower().strip()
    mlb_task_status = str(mlb_task.get("status", "")).lower().strip()
    try:
        mlb_task_pct = max(0.0, min(float(mlb_task.get("progress_pct", 0.0) or 0.0), 100.0))
    except Exception:
        mlb_task_pct = 0.0
    mlb_task_detail = str(mlb_task.get("detail", "") or "").strip()
    mlb_task_error = str(mlb_task.get("error", "") or "").strip()

    full_ready = 0
    issue_count = 0
    for lg in _STATS_SOS_LEAGUES:
        state = dict(readiness_map.get(lg, {}) or {})
        stats_state = str(state.get("stats_state", "STATS_BLOCKED")).upper().strip()
        sos_state = str(state.get("sos_state", "SOS_BLOCKED")).upper().strip()
        readiness = str(state.get("readiness_state", "BLOCKED")).upper().strip()
        stats_marker = dict(state.get("stats_marker") or {})
        sos_marker = dict(state.get("sos_marker") or {})

        _inj_state_code, _inj_state_detail = _injury_news_file_state(lg)
        injury_ready = (_inj_state_code == "READY")
        injury_required = (lg in injury_required_leagues)
        injury_effective_ready = injury_ready or (not injury_required)
        if injury_effective_ready:
            injury_state = "READY" if injury_required else "N/A"
        else:
            injury_state = "RUNNING" if inj_task_status == "running" else "PENDING"

        if stats_state == "NO_GAMES" and sos_state == "NO_GAMES":
            pct = 100.0
            summary = "100% | no games on slate"
            issue_txt = ""
            full_ready += 1
        else:
            if lg == "MLB":
                pct = 0.0
                pct += 30.0 if stats_state == "STATS_READY" else (15.0 if stats_task_status == "running" else 0.0)
                pct += 25.0 if sos_state == "SOS_READY" else (10.0 if stats_task_status == "running" else 0.0)
                pct += 20.0 if injury_effective_ready else (10.0 if inj_task_status == "running" else 0.0)
                if mlb_task_status == "success":
                    pct += 25.0
                elif mlb_task_status == "running":
                    pct += (mlb_task_pct * 0.25)
            else:
                pct = 0.0
                pct += 45.0 if stats_state == "STATS_READY" else (20.0 if stats_task_status == "running" else 0.0)
                pct += 35.0 if sos_state == "SOS_READY" else (15.0 if stats_task_status == "running" else 0.0)
                pct += 20.0 if injury_effective_ready else (10.0 if inj_task_status == "running" else 0.0)
            pct = max(0.0, min(100.0, pct))
            _summary_bits = [
                f"{int(round(pct))}%",
                f"stats:{stats_state.replace('STATS_','')}",
                f"sos:{sos_state.replace('SOS_','')}",
                f"inj:{injury_state}",
            ]
            if lg == "MLB":
                if mlb_task_status == "running":
                    _summary_bits.append(f"mlb:{int(round(mlb_task_pct))}%")
                elif mlb_task_status == "success":
                    _summary_bits.append("mlb:READY")
                elif mlb_task_status == "failed":
                    _summary_bits.append("mlb:FAILED")
            summary = " | ".join(_summary_bits)

            issues = []
            if readiness == "BLOCKED":
                issues.append("pipeline blocked")
            if stats_state == "STATS_BLOCKED":
                issues.append("stats missing/failed")
            if sos_state == "SOS_BLOCKED":
                issues.append("sos missing/failed")
            if stats_marker.get("error") and stats_state != "STATS_READY":
                issues.append(f"stats err: {str(stats_marker.get('error'))[:56]}")
            if sos_marker.get("error") and sos_state != "SOS_READY":
                issues.append(f"sos err: {str(sos_marker.get('error'))[:56]}")
            if injury_required and (not injury_ready) and inj_task_status != "running":
                issues.append(_inj_state_detail or "injury file pending")
            if lg == "MLB":
                if mlb_task_status == "failed":
                    issues.append(f"mlb stats failed: {mlb_task_error[:64] or 'unknown error'}")
            issue_txt = " | ".join(issues)
            if not issue_txt:
                full_ready += 1
            else:
                issue_count += 1

        widget = _league_ingest_widgets.get(lg)
        if widget:
            try:
                widget["pct"].set(float(pct))
                widget["summary"].set(summary)
                widget["issue"].set(issue_txt)
            except Exception:
                pass

    _dashboard_league_status_var.set(
        f"League readiness: {full_ready}/{len(_STATS_SOS_LEAGUES)} fully operational | open issues: {issue_count}"
    )
    try:
        _update_dashboard_hero(full_ready=full_ready, issue_count=issue_count)
    except Exception:
        pass


def _refresh_pipeline_pulse(log_summary: bool = False):
    if not STATS_SOS_AVAILABLE:
        _pipeline_status_var.set("Data readiness: stats_sos_integration unavailable.")
        _pipeline_last_var.set(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
        try:
            _update_dashboard_hero(blocked=len(_STATS_SOS_LEAGUES))
        except Exception:
            pass
        return

    try:
        readiness_map = _get_stats_sos_all_readiness(_STATS_SOS_LEAGUES)
    except Exception:
        readiness_map = {
            lg: _get_stats_sos_league_readiness(lg) for lg in _STATS_SOS_LEAGUES
        }

    pipeline_tree.delete(*pipeline_tree.get_children())
    ready_count = 0
    partial_count = 0
    blocked_count = 0

    for lg in _STATS_SOS_LEAGUES:
        state = dict(readiness_map.get(lg, {}) or {})
        stats_state = str(state.get("stats_state", "STATS_BLOCKED"))
        sos_state = str(state.get("sos_state", "SOS_BLOCKED"))
        readiness = str(state.get("readiness_state", "BLOCKED")).upper().strip()
        if readiness not in _STATUS_READYNESS_ALLOWED:
            readiness = "BLOCKED"

        stats_marker = dict(state.get("stats_marker") or {})
        sos_marker = dict(state.get("sos_marker") or {})
        detail = str(state.get("detail", "") or "").strip()
        if not detail:
            bits = []
            if str(stats_marker.get("status", "")).upper() == "NO_GAMES":
                bits.append("stats: no slate")
            if str(sos_marker.get("status", "")).upper() == "NO_GAMES":
                bits.append("sos: no slate")
            if stats_marker.get("error") and stats_state not in {"STATS_READY", "NO_GAMES"}:
                bits.append(f"stats err: {stats_marker.get('error')}")
            if sos_marker.get("error") and sos_state not in {"SOS_READY", "NO_GAMES"}:
                bits.append(f"sos err: {sos_marker.get('error')}")
            detail = " | ".join(bits)

        if readiness == "READY":
            ready_count += 1
        elif readiness in ("PARTIAL_READY", "STATS_READY", "SOS_READY"):
            partial_count += 1
        elif readiness == "NO_GAMES":
            pass
        else:
            blocked_count += 1

        pipeline_tree.insert(
            "",
            "end",
            values=(lg, stats_state, sos_state, readiness, detail[:160]),
            tags=(readiness if readiness in {"READY", "PARTIAL_READY", "BLOCKED", "NO_GAMES"} else ""),
        )

    _refresh_league_ingest_board(readiness_map)
    _pipeline_status_var.set(
        f"Readiness pulse: READY {ready_count} | PARTIAL {partial_count} | BLOCKED {blocked_count}"
    )
    _pipeline_last_var.set(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
    try:
        _update_dashboard_hero(ready=ready_count, partial=partial_count, blocked=blocked_count)
    except Exception:
        pass
    if log_summary:
        log(
            f"[pipeline] readiness READY={ready_count} PARTIAL={partial_count} BLOCKED={blocked_count}",
            "info",
        )


def _schedule_pipeline_pulse(ms: int = 15000):
    def _tick():
        try:
            _refresh_pipeline_pulse(log_summary=False)
        except Exception as e:
            log(f"[pipeline] pulse refresh failed: {e}", "warning")
        finally:
            root.after(ms, _tick)
    root.after(ms, _tick)


root.after(1200, lambda: _refresh_pipeline_pulse(log_summary=True))
_schedule_pipeline_pulse(15000)


def _update_dashboard_hero(
    *,
    ready=None,
    partial=None,
    blocked=None,
    full_ready=None,
    issue_count=None,
    slate_games=None,
    startup_pct=None,
    matchup_pct=None,
):
    if ready is not None:
        _dashboard_hero_state["ready"] = max(0, int(ready))
    if partial is not None:
        _dashboard_hero_state["partial"] = max(0, int(partial))
    if blocked is not None:
        _dashboard_hero_state["blocked"] = max(0, int(blocked))
    if full_ready is not None:
        _dashboard_hero_state["full_ready"] = max(0, int(full_ready))
    if issue_count is not None:
        _dashboard_hero_state["issue_count"] = max(0, int(issue_count))
    if slate_games is not None:
        _dashboard_hero_state["slate_games"] = max(0, int(slate_games))
    if startup_pct is not None:
        try:
            _dashboard_hero_state["startup_pct"] = max(0.0, min(float(startup_pct), 100.0))
        except Exception:
            pass
    if matchup_pct is not None:
        try:
            _dashboard_hero_state["matchup_pct"] = max(0.0, min(float(matchup_pct), 100.0))
        except Exception:
            pass

    st = _dashboard_hero_state
    status = "Status: Initializing"
    status_style = "HeroChipWarn.TLabel"
    if st["blocked"] > 0 or st["issue_count"] > 0:
        status = "Status: Attention Required"
        status_style = "HeroChipDanger.TLabel"
    elif st["ready"] > 0 and st["partial"] == 0:
        status = "Status: Fully Operational"
        status_style = "HeroChipOk.TLabel"
    elif st["ready"] > 0 or st["partial"] > 0:
        status = "Status: Stabilizing"
        status_style = "HeroChipWarn.TLabel"

    _dashboard_status_chip_var.set(status)
    _dashboard_operational_chip_var.set(
        f"Operational: {st['full_ready']}/{len(_STATS_SOS_LEAGUES)}"
    )
    _dashboard_issues_chip_var.set(f"Issues: {st['issue_count']}")
    _games = st["slate_games"]
    _dashboard_slate_chip_var.set(f"Slate: {('--' if _games is None else _games)} games")
    _dashboard_startup_chip_var.set(f"Startup: {st['startup_pct']:.0f}%")
    _dashboard_load_chip_var.set(f"Load: {st['matchup_pct']:.0f}%")
    try:
        _dashboard_status_chip.configure(style=status_style)
        if st["issue_count"] > 0:
            _dashboard_issues_chip.configure(style="HeroChipDanger.TLabel")
        else:
            _dashboard_issues_chip.configure(style="HeroChip.TLabel")
        if status_style == "HeroChipDanger.TLabel":
            _shell_mode_var.set("State: Intervention")
        elif status_style == "HeroChipOk.TLabel":
            _shell_mode_var.set("State: Prime")
        else:
            _shell_mode_var.set("State: Precision")
    except Exception:
        pass


def _set_startup_progress(step_done: int, step_total: int, status_text: str):
    try:
        _total = max(int(step_total or 1), 1)
        _done = max(0, min(int(step_done or 0), _total))
        _pct = round((_done / _total) * 100.0, 1)
    except Exception:
        _pct = 0.0
        _done = 0
        _total = 1
    _msg = f"Startup pipeline: {_pct:.1f}% ({_done}/{_total}) - {status_text}"

    def _apply():
        try:
            _startup_progress_pct_var.set(_pct)
            _startup_progress_text_var.set(_msg)
            _update_dashboard_hero(startup_pct=_pct)
        except Exception:
            pass

    try:
        root.after(0, _apply)
    except Exception:
        pass


def _set_startup_progress_pct(percent: float, status_text: str):
    try:
        _pct = max(0.0, min(float(percent), 100.0))
    except Exception:
        _pct = 0.0
    _msg = f"Startup pipeline: {_pct:.1f}% - {status_text}"

    def _apply():
        try:
            _startup_progress_pct_var.set(_pct)
            _startup_progress_text_var.set(_msg)
            _update_dashboard_hero(startup_pct=_pct)
        except Exception:
            pass

    try:
        root.after(0, _apply)
    except Exception:
        pass


def _set_matchup_load_progress(percent: float, status_text: str):
    try:
        _pct = max(0.0, min(float(percent), 100.0))
    except Exception:
        _pct = 0.0
    _msg = f"Matchup load: {_pct:.1f}% - {status_text}"

    def _apply():
        try:
            _matchup_progress_pct_var.set(_pct)
            _matchup_progress_text_var.set(_msg)
            _update_dashboard_hero(matchup_pct=_pct)
        except Exception:
            pass

    try:
        root.after(0, _apply)
    except Exception:
        pass


def fetch_matchups():
    global _matchup_fetch_seq
    league_upper = m_league_var.get().strip().upper()
    if not league_upper:
        m_status_var.set("Please select a league first.")
        _set_matchup_load_progress(0.0, "select a league first")
        return

    _matchup_fetch_seq += 1
    _req_id = _matchup_fetch_seq

    def _is_current():
        return (
            _req_id == _matchup_fetch_seq
            and str(m_league_var.get() or "").strip().upper() == league_upper
        )

    def _progress_safe(percent, status_text):
        if _is_current():
            _set_matchup_load_progress(percent, status_text)

    def _status_safe(msg):
        if _is_current():
            m_status_var.set(msg)

    def _after_safe(fn):
        def _wrapped():
            if _is_current():
                fn()
        root.after(0, _wrapped)

    _progress_safe(3.0, f"initializing {league_upper} matchup load")

    cached = _today_xlsx_path(league_upper)
    if cached:
        log(f"Cache hit: {cached}", "info")
        _progress_safe(45.0, "found today's cached file - loading")
        d = _load_xlsx(cached)
        if d is not None and _is_current():
            _progress_safe(80.0, "cached file parsed - populating table")
            _populate_tree(d)
            _refresh_pipeline_pulse(log_summary=False)
        return

    if not SCRAPER_AVAILABLE:
        _status_safe("Scraper unavailable and no cached file.")
        _progress_safe(100.0, "blocked - scraper unavailable and no cache")
        log("Live scrape needed but odds_scraper not available.", "error")
        return

    sport_key = LEAGUE_MAP.get(league_upper)
    if not sport_key:
        return

    fetch_btn.config(state=tk.DISABLED)
    _status_safe(f"Scraping live data for {league_upper} - please wait...")
    _progress_safe(12.0, f"running live scrape for {league_upper}")
    # Preserve diagnostic history across fetches/screens.
    # Logs should only clear via explicit user action.
    log(f"Starting live scrape for {league_upper} ({sport_key})...", "info")

    def _scrape_thread():
        try:
            if not _is_current():
                return
            os.makedirs(ODDS_DIR, exist_ok=True)
            data, count = scrape_sport(sport_key)
            if not _is_current():
                return
            _progress_safe(55.0, f"scrape returned {count} game(s)")
            log(f"Scrape complete â€” {count} game(s) found for {league_upper}.", "info")
            if count == 0:
                _progress_safe(100.0, f"{league_upper}: no games found today")
                _after_safe(lambda: m_status_var.set(f"No games found for {league_upper} today."))
                return

            saved = None
            try:
                saved = save_excel(data, sport_key, ODDS_DIR)
                _progress_safe(72.0, "saved fresh odds file")
                log(f"Odds saved via full pipeline: {saved}", "info")
            except RuntimeError as resolver_err:
                log(
                    f"[resolver] Blocking {league_upper} ingest due to unresolved threshold: {resolver_err}",
                    "error",
                )
                _progress_safe(100.0, "blocked - resolver integrity threshold failed")
                _after_safe(
                    lambda: m_status_var.set(
                        f"{league_upper} blocked: resolver integrity failed. Check diagnostics before use."
                    )
                )
                return

            if saved and _is_current():
                d = _load_xlsx(saved)
                _progress_safe(88.0, "fresh file parsed - populating table")
                _after_safe(lambda _d=d: _populate_tree(_d))
            elif _is_current():
                _progress_safe(100.0, "failed - save did not return output file")
                _after_safe(lambda: m_status_var.set("Save returned None."))

        except Exception as e:
            log(f"Scrape failed for {league_upper}: {str(e)}", "error")
            log(traceback.format_exc(), "error")
            _progress_safe(100.0, f"failed - {str(e)[:64]}")
            _after_safe(lambda _e=str(e): m_status_var.set(f"Scrape failed: {_e[:80]}."))
        finally:
            root.after(0, lambda: fetch_btn.config(state=tk.NORMAL))
            _after_safe(lambda: _refresh_pipeline_pulse(log_summary=False))

    threading.Thread(target=_scrape_thread, daemon=True).start()


def sort_tree(col):
    items = [(matchup_tree.set(k, col), k) for k in matchup_tree.get_children("")]
    if col == "time":
        items.sort(key=lambda t: _parse_game_time(t[0]) or datetime.max)
    else:
        try:
            items.sort(key=lambda t: float(t[0]) if t[0].strip() not in ["","nan"] else 0)
        except (ValueError, TypeError):
            items.sort(key=lambda t: t[0].lower())
    for idx,(_, k) in enumerate(items):
        matchup_tree.move(k,"",idx)
        _existing = list(matchup_tree.item(k, "tags") or [])
        _base_tags = [t for t in _existing if t not in ("odd", "even")]
        _parity = "odd" if idx % 2 == 0 else "even"
        matchup_tree.item(k, tags=tuple(_base_tags + [_parity] if _base_tags else [_parity]))


def load_matchup_into_physics(event=None):
    sel = matchup_tree.selection()
    if not sel:
        m_status_var.set("[WARN] Select a row first.")
        return
    vals = matchup_tree.item(sel[0], "values")
    _send_team_to_physics(vals[2], vals[1], preferred_league=m_league_var.get().upper())  # home first, away as fallback


def _send_team_to_physics(primary, alt=None, preferred_league=None):
    t, lg = _find_team_fuzzy(primary, preferred_league=preferred_league)
    if t is None and alt:
        t, lg = _find_team_fuzzy(alt, preferred_league=preferred_league)
        if t:
            log(f"Primary '{primary}' unmatched â€” loaded alt '{t}'.", "warning")
    if t is None:
        cleaned = _strip_pitcher(primary)
        m_status_var.set(f"[WARN] '{cleaned}' not matched in venue database.")
        log(f"Team '{cleaned}' not found after 4-tier fuzzy search.", "warning")
        return
    league_var.set(lg)
    update_teams()
    team_var.set(t)
    main_tabs.select(physics_frame)
    log(f"Loaded '{t}' ({lg}) into Model.", "info")
    m_status_var.set(f"[OK] '{t}' sent to Model - click Run Model.")

def _refresh_slate_detail_from_selection(event=None):
    _sel = matchup_tree.selection()
    if not _sel:
        _slate_set_detail_empty()
        return

    _vals = matchup_tree.item(_sel[0], "values")
    if not _vals:
        _slate_set_detail_empty()
        return

    _time = str(_vals[0] or "").strip()
    _away = str(_vals[1] or "").replace("  [NO ODDS]", "").strip()
    _home = str(_vals[2] or "").strip()
    _away_spread = str(_vals[3] or "").strip()
    _home_spread = str(_vals[4] or "").strip()
    _total = str(_vals[5] or "").strip()
    _away_ml = str(_vals[6] or "").strip()
    _home_ml = str(_vals[7] or "").strip()
    _league = str(m_league_var.get() or "").upper().strip()

    _tags = set(matchup_tree.item(_sel[0], "tags") or [])
    _no_odds = "no_odds" in _tags
    _bypass = "bypass" in _tags

    _slate_matchup_var.set(f"{_away} @ {_home}")
    _slate_time_var.set(f"Tipoff/First pitch: {_time or '--'}")
    _slate_market_var.set(
        f"Total {_total or '--'}  |  Spread {_away_spread or '--'} / {_home_spread or '--'}  |  ML {_away_ml or '--'} / {_home_ml or '--'}"
    )

    _thresholds = {
        "MLB": 8.5,
        "NHL": 6.5,
        "NBA": 228.5,
        "NCAAB": 145.5,
        "NFL": 45.5,
        "NCAAF": 52.5,
    }
    _edge_msg = "Edge posture: neutral market framing"
    _mt = re.search(r"-?\d+(?:\.\d+)?", _total or "")
    if _mt:
        try:
            _total_num = float(_mt.group(0))
            _thr = float(_thresholds.get(_league, _total_num))
            if _total_num >= _thr + 0.5:
                _edge_msg = "Edge posture: offense-lean market expectation; confirm with weather/injury context"
            elif _total_num <= _thr - 0.5:
                _edge_msg = "Edge posture: defense-lean market expectation; verify pace and lineup certainty"
            else:
                _edge_msg = "Edge posture: balanced market baseline"
        except Exception:
            pass
    _slate_edge_var.set(_edge_msg)

    _inj_state, _inj_detail = _injury_news_file_state(_league) if _league else ("MISSING", "injury workbook missing")
    if _no_odds:
        _slate_risk_var.set("Risk posture: odds fields are missing; keep this matchup in watch mode until market lines populate")
    elif _bypass:
        _slate_risk_var.set("Risk posture: resolver bypassed this row; run matchup detail before making a final call")
    elif _inj_state != "READY":
        _slate_risk_var.set(
            f"Risk posture: injury/news intel not ready ({_inj_detail or _inj_state.lower()}); confidence should be moderated"
        )
    else:
        _slate_risk_var.set("Risk posture: core data layers are available; ready for deeper model analysis")

    _slate_status_var.set(f"Data status: {_league or 'UNSET'} | injury intel {_inj_state}")


def _on_double_click(event):
    global _LAST_MATCHUP_OPEN_TS, _DETAIL_WINDOW_OPENING
    sel = matchup_tree.selection()
    if not sel:
        return
    _now = time.time()
    if _DETAIL_WINDOW_OPENING:
        return
    if (_now - _LAST_MATCHUP_OPEN_TS) < _DETAIL_POPUP_DEBOUNCE_SEC:
        return
    _LAST_MATCHUP_OPEN_TS = _now
    _DETAIL_WINDOW_OPENING = True
    def _release_open_gate():
        global _DETAIL_WINDOW_OPENING
        _DETAIL_WINDOW_OPENING = False
    root.after(int(_DETAIL_POPUP_DEBOUNCE_SEC * 1000), _release_open_gate)
    vals = matchup_tree.item(sel[0], "values")
    _open_matchup_detail(vals, sport=m_league_var.get().upper(), status_callback=m_status_var.set)


def _tree_context_menu(event):
    item = matchup_tree.identify_row(event.y)
    if item:
        matchup_tree.selection_set(item)
    sel = matchup_tree.selection()
    if not sel:
        return
    vals      = matchup_tree.item(sel[0], "values")
    away_team = vals[1]
    home_team = vals[2]
    ctx = tk.Menu(root, tearoff=0)
    ctx.add_command(label=f"Open Matchup Detail",
                    command=lambda: _open_matchup_detail(vals, sport=m_league_var.get().upper(),
                                                          status_callback=m_status_var.set))
    ctx.add_separator()
    ctx.add_command(label=f"Analyze HOME ({home_team})",
                    command=lambda: _send_team_to_physics(home_team, away_team, preferred_league=m_league_var.get().upper()))
    ctx.add_command(label=f"Analyze AWAY ({away_team})",
                    command=lambda: _send_team_to_physics(away_team, home_team, preferred_league=m_league_var.get().upper()))
    ctx.tk_popup(event.x_root, event.y_root)

matchup_tree.bind("<Double-1>", _on_double_click)
matchup_tree.bind("<Button-3>", _tree_context_menu)
matchup_tree.bind("<<TreeviewSelect>>", _refresh_slate_detail_from_selection, add="+")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PHYSICS MODEL EVENTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def update_teams(event=None):
    teams = get_teams(league_var.get())
    team_cb["values"] = teams
    team_var.set("")

def run_model():
    output.delete(1.0, tk.END)
    run_warnings = []
    t_start = datetime.now()

    team = team_var.get().strip()
    if not team:
        output.insert(tk.END, "âš   Please select a League and then a Team.\n")
        return

    row = get_row(team)
    if row is None:
        output.insert(tk.END, f"âš   Team '{team}' not found in venue database.\n")
        return

    log(f"Run started â€” {team}", "info")

    lat             = safe(row, "lat")
    lon             = safe(row, "lon")
    elevation       = safe(row, "elevation")
    orientation_deg = safe(row, "orientation_deg")
    orientation_lbl = safe(row, "orientation_label")
    surface_type    = safe(row, "surface_type")
    surface_detail  = safe(row, "surface_detail")
    roof_type       = safe(row, "roof_type")

    has_coords = (lat != "" and lon != "")
    if not has_coords:
        run_warnings.append("lat/lon missing -> weather unavailable for this run.")
    elev_ft = safe_float(elevation, None, "elevation_ft")
    if elev_ft is None:
        run_warnings.append("elevation missing -> density-altitude suppressed.")

    surface = f"{surface_type} ({surface_detail})" if surface_detail else surface_type
    weather = get_weather(lat, lon) if has_coords else None
    if weather is None:
        run_warnings.append("Weather unavailable â€” physics analysis suppressed for this run.")
    elif _weather_used_fallback:
        run_warnings.append("Weather API failed â€” FALLBACK DEFAULTS shown, not live.")

    if weather is None:
        elapsed = int((datetime.now() - t_start).total_seconds() * 1000)
        o = output.insert
        if run_warnings:
            o(tk.END,"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n")
            o(tk.END,"â•‘              âš   DATA / MODEL WARNINGS               â•‘\n")
            o(tk.END,"â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£\n")
            for w in run_warnings:
                log(w, "warning")
                o(tk.END, f"â•‘  â€¢ {w}\n")
            o(tk.END,"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n")
        W = 56
        o(tk.END, f"{'â•'*W}\n")
        o(tk.END, f"  {team}\n")
        o(tk.END, f"{'â•'*W}\n\n")
        o(tk.END, f"  {'Venue':<18}: {safe(row,'venue')}\n")
        o(tk.END, f"  {'Elevation':<18}: {elevation if elevation!='' else 'N/A'} ft\n")
        o(tk.END, f"  {'Surface':<18}: {surface if surface.strip() else 'N/A'}\n")
        o(tk.END, f"  {'Roof':<18}: {roof_type if roof_type!='' else 'N/A'}\n")
        o(tk.END, f"  {'Orientation':<18}: {orientation_deg if orientation_deg!='' else 'N/A'}Â°"
                  f"  {orientation_lbl}\n\n")
        o(tk.END, "  Weather/physics data unavailable for this team right now.\n")
        o(tk.END, f"{'â•'*W}\n")
        log(f"Run halted ({elapsed}ms) â€” weather unavailable for {team}", "warning")
        return

    try:
        rho = air_density(weather["temp"], weather["pressure"], weather["humidity"])
    except Exception as ex:
        rho = 0.0
        run_warnings.append(f"Air density calc failed: {ex}")

    try:
        da = density_altitude(weather["temp"], elev_ft, weather["pressure"], weather["humidity"]) if elev_ft is not None else None
    except Exception as ex:
        da = None
        run_warnings.append(f"Density altitude calc failed: {ex}")

    wind_speed = weather["wind_speed"]
    wind_dir   = weather["wind_dir"]
    override   = roof_override_var.get()
    roof_note  = ""

    if override == "Closed":
        wind_speed = 0.0
        roof_note  = "  [Override: Closed â€” wind zeroed]"
    elif override == "Auto" and str(roof_type).lower() in ["closed", "dome"]:
        wind_speed = 0.0
        roof_note  = f"  [Auto: {roof_type} â€” wind zeroed]"

    try:
        head, cross = wind_components(wind_speed, wind_dir,
                                      orientation_deg if orientation_deg != "" else 0.0)
    except Exception as ex:
        head = cross = 0.0
        run_warnings.append(f"Wind component calc failed: {ex}")

    elapsed = int((datetime.now() - t_start).total_seconds() * 1000)
    o = output.insert

    if run_warnings:
        o(tk.END,"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n")
        o(tk.END,"â•‘              âš   DATA / MODEL WARNINGS               â•‘\n")
        o(tk.END,"â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£\n")
        for w in run_warnings:
            log(w, "warning")
            o(tk.END, f"â•‘  â€¢ {w}\n")
        o(tk.END,"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n")

    W = 56
    o(tk.END, f"{'â•'*W}\n")
    o(tk.END, f"  {team}\n")
    o(tk.END, f"{'â•'*W}\n\n")
    o(tk.END, f"  {'Venue':<18}: {safe(row,'venue')}\n")
    o(tk.END, f"  {'Elevation':<18}: {elevation if elevation!='' else 'N/A'} ft\n")
    o(tk.END, f"  {'Surface':<18}: {surface if surface.strip() else 'N/A'}\n")
    o(tk.END, f"  {'Roof':<18}: {roof_type if roof_type!='' else 'N/A'}{roof_note}\n")
    o(tk.END, f"  {'Orientation':<18}: {orientation_deg if orientation_deg!='' else 'N/A'}Â°"
              f"  {orientation_lbl}\n\n")
    wx_flag = "  âš  FALLBACK" if _weather_used_fallback else "  âœ” Live"
    o(tk.END, f"  â”€â”€â”€ Weather{wx_flag} â”€â”€â”€\n")
    o(tk.END, f"  {'Temp':<18}: {weather['temp']} Â°F\n")
    o(tk.END, f"  {'Humidity':<18}: {weather['humidity']}%\n")
    o(tk.END, f"  {'Pressure':<18}: {round(weather['pressure'],2)} inHg\n")
    o(tk.END, f"  {'Wind':<18}: {weather['wind_speed']} mph @ {weather['wind_dir']}Â°\n\n")
    o(tk.END, f"  â”€â”€â”€ Physics â”€â”€â”€\n")
    o(tk.END, f"  {'Air Density':<18}: {round(rho,5)} lb/ftÂ³\n")
    o(tk.END, f"  {'Density Altitude':<18}: {f'{round(da):,} ft' if da is not None else 'N/A (missing elevation)'}\n\n")
    o(tk.END, f"  â”€â”€â”€ Wind Components â”€â”€â”€\n")
    o(tk.END, f"  {'Headwind':<18}: {head} mph\n")
    o(tk.END, f"  {'Crosswind':<18}: {cross} mph\n")
    o(tk.END, f"{'â•'*W}\n")

    log(f"Run complete ({elapsed}ms) â€” rho={round(rho,5)} DA={(f'{round(da):,}' if da is not None else 'N/A')} "
        f"head={head} cross={cross} warnings={len(run_warnings)}", "info")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 3 â€” âš¾ PITCHER ARSENAL
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
arsenal_frame = ttk.Frame(main_tabs)
main_tabs.add(arsenal_frame, text="Arsenal")

ars_ctrl = ttk.LabelFrame(arsenal_frame, text="Arsenal Operations", padding=10, style="Card.TLabelframe")
ars_ctrl.pack(fill=tk.X, **pad)

ars_status_var = tk.StringVar(value="Arsenal dataset not loaded.")

def _ars_set_status(msg):
    root.after(0, lambda m=str(msg)[:120]: ars_status_var.set(m))

def _populate_arsenal_tree(starters, arsenal):
    global _starters_df, _arsenal_df
    _starters_df = starters
    _arsenal_df  = arsenal
    ars_tree.delete(*ars_tree.get_children())
    if arsenal is None or (hasattr(arsenal, "empty") and arsenal.empty):
        _ars_set_status("[WARN] Arsenal dataset is empty.")
        return
    if "Usage %" not in arsenal.columns and "Total Pitches" in arsenal.columns:
        tots = arsenal.groupby("name")["Total Pitches"].transform("sum")
        arsenal = arsenal.copy()
        arsenal["Usage %"] = (arsenal["Total Pitches"] / tots * 100).round(1)
    try:
        ars_sorted = arsenal.sort_values(
            ["name", "Usage %"], ascending=[True, False])
    except Exception:
        ars_sorted = arsenal
    prev_name = None
    for i, (_, row) in enumerate(ars_sorted.iterrows()):
        name = str(row.get("name", ""))
        team = str(row.get("team", ""))
        pt   = str(row.get("Pitch Type", ""))
        def _f(v, d=1):
            try: return f"{round(float(v), d)}"
            except: return str(v)
        try:    spin_s = f"{int(round(float(row.get('Spin Rate (RPM)', 0)))):,}"
        except: spin_s = "N/A"
        disp_name = name if name != prev_name else ""
        disp_team = team if name != prev_name else ""
        prev_name = name
        tag = "odd" if i % 2 == 0 else "even"
        ars_tree.insert("", "end", tags=(tag,), values=(
            disp_name, disp_team, pt,
            _f(row.get("Velocity (MPH)", "")),
            spin_s,
            _f(row.get("Horiz Mov (in)", "")),
            _f(row.get("Vert Mov (in)", "")),
            _f(row.get("Usage %", "")) + "%",
        ))
    n_p = len(starters) if starters is not None and not (hasattr(starters,"empty") and starters.empty) else "->"
    n_s = int(arsenal["name"].nunique()) if not (hasattr(arsenal,"empty") and arsenal.empty) else 0
    _ars_set_status(f"[OK] {n_p} starters | {len(arsenal)} pitch-type rows | {n_s} pitchers with Statcast coverage")

def _fetch_arsenal_thread():
    global _starters_df, _arsenal_df, _arsenal_fetching, _arsenal_progress
    if not ARSENAL_AVAILABLE:
        _ars_set_status("âš  arsenal_engine.py not found in script directory.")
        return
    _arsenal_fetching = True
    root.after(0, lambda: fetch_ars_btn.config(state=tk.DISABLED))

    # Dual callback: updates Arsenal tab status bar AND the run log
    def _dual_cb(msg):
        global _arsenal_progress
        _arsenal_progress = str(msg)
        _ars_set_status(msg)
        log(f"[ARSENAL] {msg}", "info")

    _dual_cb("[RUN] Fetching starters from MLB API...")
    try:
        starters, arsenal, _, saved = get_todays_arsenal(
            output_dir=ODDS_DIR, progress_cb=_dual_cb)
        root.after(0, lambda: _populate_arsenal_tree(starters, arsenal))
        if saved:
            _dual_cb(f"[OK] Completed - {len(arsenal)} pitch-type rows saved to {saved}")
    except Exception as exc:
        import traceback
        _arsenal_progress = f"[ERROR] Fetch failed: {exc}"
        _ars_set_status(_arsenal_progress)
        log(f"Arsenal fetch failed:\n{traceback.format_exc()}", "error")
    finally:
        _arsenal_fetching = False
        root.after(0, lambda: fetch_ars_btn.config(state=tk.NORMAL))

def _load_cached_arsenal_action():
    if not ARSENAL_AVAILABLE:
        _ars_set_status("âš  arsenal_engine.py not found.")
        return
    starters, arsenal = load_cached_arsenal(ODDS_DIR)
    if starters is None:
        _ars_set_status("âš  No cached arsenal file found for today.")
        return
    _populate_arsenal_tree(starters, arsenal)

fetch_ars_btn = ttk.Button(ars_ctrl, text="Refresh Arsenal Dataset",
    command=lambda: threading.Thread(target=_fetch_arsenal_thread, daemon=True).start())
fetch_ars_btn.grid(row=0, column=0, sticky="w", **pad)

ttk.Button(ars_ctrl, text="Load Cached Dataset",
    command=_load_cached_arsenal_action).grid(row=0, column=1, sticky="w", **pad)

def _check_changes_thread():
    """Fast starter-change check â€” API only, no Statcast re-pull."""
    global _starters_df, _arsenal_df
    if not ARSENAL_AVAILABLE:
        _ars_set_status("âš  arsenal_engine not available.")
        return
    if _starters_df is None:
        _ars_set_status("âš  Load or fetch arsenal first before checking changes.")
        return
    root.after(0, lambda: chk_btn.config(state=tk.DISABLED))
    _ars_set_status("ðŸ” Checking MLB API for starter changes...")
    try:
        changes = check_starter_changes(_starters_df)
        if not changes:
            _ars_set_status("âœ… No starter changes detected â€” lineup is current.")
            return
        # One or more changes found â€” patch each one
        for ch in changes:
            _ars_set_status(
                f"âš¡ Change: {ch['team']} â€” {ch['old_name']} â†’ {ch['new_name']}  "
                f"(Game {ch['game_number']}). Fetching new Statcast...")
            s, a = patch_arsenal_with_new_pitcher(
                _starters_df, _arsenal_df, ch,
                output_dir=ODDS_DIR, progress_cb=_ars_set_status)
            _starters_df = s
            _arsenal_df  = a
        root.after(0, lambda: _populate_arsenal_tree(_starters_df, _arsenal_df))
        _ars_set_status(
            f"âœ… {len(changes)} change(s) patched â€” arsenal updated.")
    except Exception as exc:
        _ars_set_status(f"âŒ Change-check failed: {exc}")
        log(str(exc), "error")
    finally:
        root.after(0, lambda: chk_btn.config(state=tk.NORMAL))

chk_btn = ttk.Button(ars_ctrl, text="Detect Starter Changes",
    command=lambda: threading.Thread(
        target=_check_changes_thread, daemon=True).start())
chk_btn.grid(row=0, column=2, sticky="w", **pad)

if not PYBASEBALL_AVAILABLE:
    ttk.Label(ars_ctrl,
        text="[WARN] pybaseball not installed - run: pip install pybaseball"
             "then restart the app.",
        foreground=_UI["danger"], font=("Consolas", 9, "bold")
    ).grid(row=1, column=0, columnspan=5, sticky="w", **pad)
else:
    ttk.Label(ars_ctrl,
        text="Statcast season averages via pybaseball - not game-by-game. "
             "Fetch once per day; auto-loads cache on startup.",
        foreground=_UI["text_muted"]).grid(row=1, column=0, columnspan=5, sticky="w", **pad)

ttk.Label(ars_ctrl, textvariable=ars_status_var,
    style="SubtleCard.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", **pad)

# â”€â”€ Arsenal Treeview â”€â”€
ars_tree_frame = ttk.LabelFrame(arsenal_frame, text="Arsenal Table", padding=8, style="Card.TLabelframe")
ars_tree_frame.pack(fill=tk.BOTH, expand=True, **pad)

ARS_COLS   = ("name","team","pitch","velo","spin","hmov","vmov","usage")
ARS_LABELS = {"name":"Pitcher","team":"Team","pitch":"Pitch",
              "velo":"Velo (MPH)","spin":"Spin (RPM)",
              "hmov":"H.Mov (in)","vmov":"V.Mov (in)","usage":"Usage %"}
ARS_WIDTHS = {"name":165,"team":160,"pitch":55,"velo":80,"spin":90,
              "hmov":90,"vmov":90,"usage":65}

ars_sy = ttk.Scrollbar(ars_tree_frame, orient=tk.VERTICAL)
ars_sx = ttk.Scrollbar(ars_tree_frame, orient=tk.HORIZONTAL)
ars_tree = ttk.Treeview(ars_tree_frame, columns=ARS_COLS, show="headings",
                        yscrollcommand=ars_sy.set, xscrollcommand=ars_sx.set,
                        selectmode="browse")
ars_sy.config(command=ars_tree.yview)
ars_sx.config(command=ars_tree.xview)
for col in ARS_COLS:
    ars_tree.heading(col, text=ARS_LABELS[col])
    ars_tree.column(col, width=ARS_WIDTHS[col], anchor="center", minwidth=45)
ars_tree.grid(row=0, column=0, sticky="nsew")
ars_sy.grid(row=0, column=1, sticky="ns")
ars_sx.grid(row=1, column=0, sticky="ew")
ars_tree_frame.grid_rowconfigure(0, weight=1)
ars_tree_frame.grid_columnconfigure(0, weight=1)
ars_tree.tag_configure("odd",  background=_UI["stripe_odd"])
ars_tree.tag_configure("even", background=_UI["stripe_even"])

# Auto-load cache on startup; auto-fetch if no usable cache found
def _try_autoload():
    if not ARSENAL_AVAILABLE:
        root.after(0, lambda: _ars_set_status(
            "âš  arsenal_engine.py not found â€” place it in the same folder as this script."))
        log("ARSENAL_AVAILABLE=False at startup â€” arsenal_engine.py missing or import error.", "error")
        return
    try:
        s, a = load_cached_arsenal(ODDS_DIR)
    except Exception as exc:
        log(f"load_cached_arsenal raised: {exc}", "error")
        s, a = None, None
    n_starters = len(s) if s is not None and not (hasattr(s,"empty") and s.empty) else 0
    n_ars      = len(a) if a is not None and not (hasattr(a,"empty") and a.empty) else 0
    log(f"Startup cache check: starters={n_starters}  arsenal_rows={n_ars}", "info")
    has_data = n_starters > 0 and n_ars > 0
    if has_data:
        root.after(0, lambda: _populate_arsenal_tree(s, a))
        log(f"Arsenal auto-loaded: {n_starters} starters, {n_ars} arsenal rows.", "info")
    else:
        if not PYBASEBALL_AVAILABLE:
            log("pybaseball not installed â€” arsenal auto-fetch skipped. "
                "Run: pip install pybaseball", "error")
            root.after(0, lambda: _ars_set_status(
                "âŒ pybaseball not installed â€” run: pip install pybaseball  then restart"))
        else:
            log(f"No usable cache (starters={n_starters}, arsenal={n_ars}) â€” auto-fetching...", "info")
            root.after(0, lambda: _ars_set_status(
                "â³ No cache found â€” auto-fetching today's arsenal..."))
            _fetch_arsenal_thread()
_start_daemon_after(100, _try_autoload)

# â”€â”€ Injury cache warm-up â€” runs at startup, all sports, background thread â”€â”€â”€â”€â”€â”€
def _warm_injury_cache_all_sports():
    """
    Cache warm-up at startup. Three strict filters keep it fast:
      1. TODAY'S GAME TEAMS ONLY â€” reads odds XLSXs to get active teams.
         No fetching all 30 MLB teams when only 15 play tonight.
      2. INJURED PLAYERS ONLY â€” status must match a real injury designation.
         Eliminates the full-roster rows that bloated the XLSX to 1870.
      3. FLAT PARALLEL BATCH â€” all players fetched in one ThreadPoolExecutor
         per sport, not a sequential team-by-team loop.
    Net result: ~30-120 players total vs 2407 previously. Runtime < 60s.
    """
    if not _NEA_STATS_OK or not _nea_mod:
        log("Injury cache warm skipped â€” NEA stats scraper not loaded.", "warning")
        return
    from pathlib import Path as _P
    import time as _time
    from concurrent.futures import (
        ThreadPoolExecutor as _TPE,
        as_completed as _ac,
        TimeoutError as _FTimeout,
    )
    _today_ts  = datetime.now().strftime("%Y%m%d")
    _inj_dir   = _injury_news_output_dir()
    if not _inj_dir.exists(): return
    # Statuses that represent actual injuries/absences worth fetching
    _INJ_ST = {"out","60-day-il","60-day il","15-day-il","15-day il",
               "10-day-il","10-day il","day-to-day","day to day",
               "questionable","doubtful","injured reserve","ir"}
    # Map sport â†’ odds XLSX name pattern to find today's active teams
    _SP_ODDS = {"MLB":"MLB","NBA":"NBA","NHL":"NHL","NFL":"NFL",
               "NCAAB":"NCAAB","NCAAF":"NCAAF"}
    _SPORTS = ["MLB","NBA","NHL","NFL","NCAAB","NCAAF"]
    _total_fetched = 0; _total_players = 0
    for _sp in _SPORTS:
        _xl = _inj_dir / f"INJURY_NEWS_{_sp}_{_today_ts}.xlsx"
        if not _xl.exists(): continue
        try:
            _sheets = {str(_s).strip().upper() for _s in (pd.ExcelFile(str(_xl)).sheet_names or [])}
        except Exception:
            _sheets = set()
        if "INJURIES" not in _sheets:
            log(f"Injury warm [{_sp}]: INJURIES sheet missing; waiting for rebuilt workbook.", "info")
            continue
        try:
            _df = pd.read_excel(str(_xl), sheet_name="INJURIES", dtype=str)
        except Exception as _e:
            log(f"Injury warm [{_sp}]: XLSX read error - {_e}", "warning"); continue
        if _df.empty: continue
        # â”€â”€ Filter 1: actual injury statuses only â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _all_rows = _df.to_dict("records")
        _inj_rows = [r for r in _all_rows
                     if str(r.get("status","") or "").strip().lower() in _INJ_ST
                     and str(r.get("player","") or "").strip()]
        if not _inj_rows: continue
        # â”€â”€ Filter 2: today's game teams only â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _odds_xl = _P(ODDS_DIR) / f"Odds_{_SP_ODDS[_sp]}_{_today_ts}.xlsx"
        _today_teams: set = set()
        if _odds_xl.exists():
            try:
                _odf = pd.read_excel(str(_odds_xl), dtype=str)
                for _col in ("Away","Home","Away_Team","Home_Team","away","home"):
                    if _col in _odf.columns:
                        _today_teams.update(_odf[_col].dropna().str.strip().tolist())
            except Exception: pass
        if _today_teams:
            _inj_rows = [r for r in _inj_rows
                         if any(str(r.get("team_name","") or "").strip().lower()
                                  in t.lower() or
                                t.lower() in str(r.get("team_name","") or "").strip().lower()
                                for t in _today_teams)]
        if not _inj_rows: continue
        _max_per_sport = 60
        if len(_inj_rows) > _max_per_sport:
            _inj_rows = _inj_rows[:_max_per_sport]
            log(
                f"Injury warm [{_sp}]: startup cap {_max_per_sport}; remaining players deferred to on-demand lookups.",
                "info",
            )
        _total_players += len(_inj_rows)
        log(f"Injury warm [{_sp}]: {len(_inj_rows)} injured players on today's teams", "info")
        # â”€â”€ Filter 3: flat parallel batch (all players, one executor) â”€â”€
        def _fetch_one(r, sp=_sp):
            _nm  = str(r.get("player","") or "").strip()
            _tm  = str(r.get("team_name","") or "").strip()
            _st  = str(r.get("status","") or "").strip()
            _pos = str(r.get("pos","") or "").strip().upper()
            _dt  = str(r.get("injury_date_raw","") or r.get("date","") or "").strip()
            _isp = _pos in ("SP","RP","P","CL")
            _irp = _pos in ("RP","CL")
            try:
                return _nea_mod.compute_inj_impact(
                    _nm, _tm, sp, _st, _pos, _isp, _irp, _dt)
            except Exception: return None
        _fetched = 0
        _startup_timeout_sec = 12
        _ex = _TPE(max_workers=4)
        _pending = set()
        try:
            _pending = {_ex.submit(_fetch_one, r) for r in _inj_rows}
            _deadline = _time.time() + _startup_timeout_sec
            while _pending and _time.time() < _deadline:
                _slice = max(0.2, min(1.0, _deadline - _time.time()))
                try:
                    _done_any = False
                    for _f in _ac(_pending, timeout=_slice):
                        _pending.discard(_f)
                        _done_any = True
                        try:
                            _res = _f.result(timeout=0.2)
                            if _res and _res.get("found"):
                                _fetched += 1
                        except Exception:
                            pass
                    if not _done_any:
                        continue
                except _FTimeout:
                    continue
            if _pending:
                for _f in list(_pending):
                    _f.cancel()
                log(
                    f"Injury warm [{_sp}]: startup warm timed out; deferred {len(_pending)} lookups to on-demand.",
                    "info",
                )
        finally:
            try:
                _ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        _total_fetched += _fetched
        log(f"Injury warm [{_sp}]: {_fetched}/{len(_inj_rows)} resolved", "info")
    log(f"âœ… Injury cache warm complete â€” {_total_fetched}/{_total_players} players resolved.", "info")

_start_daemon_after(250, _warm_injury_cache_all_sports)

# â”€â”€ BoydsBets warm-up â€” fires at startup, all active sports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _warm_boyds_cache():
    """
    Pre-fetch all BoydsBets injury pages at startup.
    Runs in 6 parallel threads (one per sport). Typical runtime: 8-15s.
    After this, all get_injuries() calls are instant SQLite reads.
    """
    if not _BOYDS_OK or not _bb_mod: return
    from concurrent.futures import ThreadPoolExecutor as _TPE2, as_completed as _ac2
    _ACTIVE_SPORTS = ["MLB","NBA","NHL","NFL","NCAAB","NCAAF"]
    def _fetch_one_sport(sp):
        try: return sp, _bb_mod.fetch_and_store(sp)
        except Exception: return sp, 0
    with _TPE2(max_workers=4) as ex:
        futs = {ex.submit(_fetch_one_sport, sp): sp for sp in _ACTIVE_SPORTS}
        for f in _ac2(futs, timeout=30):
            try:
                sp, n = f.result(timeout=1)
                if n > 0:
                    log(f"BoydsBets [{sp}]: {n} injuries cached.", "info")
            except Exception as _be:
                log(f"BoydsBets warm failed for one sport: {_be}", "warning")
    log("âœ… BoydsBets cache warm complete.", "info")

_start_daemon_after(500, _warm_boyds_cache)


# â”€â”€ Lineup assessment warm-up â€” fires after startup, all today's games â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _warm_lineup_cache_all_sports():
    """
    For every game on today's slate (all sports with odds XLSXs),
    call get_lineup_assessments() to fetch + cache all player stats.
    This replaces the injury-only warm-up as the PRIMARY cache source:
    â€¢ Actual playing roster, not just injured players
    â€¢ Includes batting order, starters, rotations
    â€¢ air_density_sensitivity computed from real hr_per_game data
    Total players: ~18-22/game Ã— 15 games = 270-330 for MLB. Runtime ~60-90s.
    """
    if not _NEA_LINEUP_OK or not _la_mod or not _NEA_STATS_OK or not _nea_mod:
        log("Lineup warm skipped â€” lineup assessor or stats scraper not loaded.", "warning")
        return
    from pathlib import Path as _P2
    _today_ts2 = datetime.now().strftime("%Y%m%d")
    _SP_ODDS2 = {"MLB":"MLB","NBA":"NBA","NHL":"NHL","NFL":"NFL",
                 "NCAAB":"NCAAB","NCAAF":"NCAAF"}
    _total_games = 0; _total_players = 0; _total_found = 0
    for _sp2, _odds_tag in _SP_ODDS2.items():
        _odds_xl2 = _P2(ODDS_DIR) / f"Odds_{_odds_tag}_{_today_ts2}.xlsx"
        if not _odds_xl2.exists(): continue
        try:
            _odf2 = pd.read_excel(str(_odds_xl2), dtype=str)
        except Exception: continue
        # Identify away/home team columns
        _away_col = next((c for c in _odf2.columns
                          if c.lower() in ("away","away_team","away team")), None)
        _home_col = next((c for c in _odf2.columns
                          if c.lower() in ("home","home_team","home team")), None)
        if not _away_col or not _home_col: continue
        for _, _gr in _odf2.iterrows():
            _aw = str(_gr.get(_away_col,"") or "").strip()
            _hw = str(_gr.get(_home_col,"") or "").strip()
            if not _aw or not _hw: continue
            try:
                _las = _la_mod.get_lineup_assessments(
                    _sp2, _aw, _hw, _nea_mod,
                    max_workers=4, timeout_per_side=18.0)
                _total_games += 1
                for _side, _la in _las.items():
                    _total_players += _la.expected_count
                    _total_found   += _la.found_count
            except Exception as _lg_e:
                log(f"Lineup warm [{_sp2}/{_aw}@{_hw}]: {_lg_e}", "warning")
    log(f"âœ… Lineup cache warm complete â€” {_total_found}/{_total_players} players "
        f"across {_total_games} games.", "info")

# Stagger: lineup warm starts 5s after injury warm to avoid hammering ESPN
import threading as _th_lineup
def _delayed_lineup_warm():
    # Stability mode: do not run full lineup warm at startup.
    # It is still available on-demand when matchup detail is opened.
    log("Lineup startup warm disabled for responsiveness (on-demand only).", "info")
_start_daemon_after(750, _delayed_lineup_warm)




# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 4 â€” REPORTS
# Export Summary Excel  |  Full Per-Game Logic Breakdown
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
reports_frame = ttk.Frame(main_tabs)
main_tabs.add(reports_frame, text="Reports")

if _brand_assets.get("lockup") is not None:
    _rpt_brand = ttk.Frame(reports_frame, style="Card.TFrame")
    _rpt_brand.pack(fill=tk.X, padx=8, pady=(6, 0))
    ttk.Label(_rpt_brand, image=_brand_assets["lockup"], style="BrandSurface.TLabel").pack(anchor="w")

rpt_ctrl = ttk.LabelFrame(reports_frame, text="Report Studio", padding=10, style="Card.TLabelframe")
rpt_ctrl.pack(fill=tk.X, **pad)

rpt_league_var = tk.StringVar(value="MLB")
ttk.Label(rpt_ctrl, text="League:").grid(row=0, column=0, sticky="w", **pad)
ttk.Combobox(rpt_ctrl, textvariable=rpt_league_var,
             values=list(LEAGUE_MAP.keys()), width=10,
             state="readonly").grid(row=0, column=1, sticky="w", **pad)

rpt_export_btn = ttk.Button(rpt_ctrl, text="Export Summary Workbook",
                             command=lambda: threading.Thread(target=_rpt_export_excel, daemon=True).start())
rpt_export_btn.grid(row=0, column=2, **pad)

rpt_breakdown_btn = ttk.Button(rpt_ctrl, text="Generate Full Analysis",
                                command=lambda: threading.Thread(target=_rpt_generate_breakdown, daemon=True).start())
rpt_breakdown_btn.grid(row=0, column=3, **pad)

rpt_save_btn = ttk.Button(rpt_ctrl, text="Save Analysis (.txt)",
                           command=lambda: _rpt_save_txt(), state=tk.DISABLED)
rpt_save_btn.grid(row=0, column=4, **pad)

rpt_logic_mode_var = tk.StringVar(value="Current Model Snapshot")
ttk.Label(rpt_ctrl, text="Model/Logic:").grid(row=1, column=0, sticky="w", **pad)
ttk.Combobox(
    rpt_ctrl,
    textvariable=rpt_logic_mode_var,
    values=("Current Model Snapshot", "Calibration Weights", "Audit Timeline"),
    width=28,
    state="readonly",
).grid(row=1, column=1, sticky="w", **pad)

rpt_history_var = tk.StringVar(value="Select model/logic history entry...")
ttk.Label(rpt_ctrl, text="Model/Logic History:").grid(row=1, column=2, sticky="e", **pad)
rpt_history_cb = ttk.Combobox(
    rpt_ctrl,
    textvariable=rpt_history_var,
    values=(),
    width=62,
    state="readonly",
)
rpt_history_cb.grid(row=1, column=3, columnspan=2, sticky="w", **pad)

rpt_status_var = tk.StringVar(value="Reporting console ready. Run an analysis to populate results.")
ttk.Label(rpt_ctrl, textvariable=rpt_status_var,
          style="SubtleCard.TLabel").grid(row=2, column=0, columnspan=8, sticky="w", **pad)

# â”€â”€ Preview pane â€” sub-notebook with Breakdown + Model Audit Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
rpt_nb = ttk.Notebook(reports_frame)
rpt_nb.pack(fill=tk.BOTH, expand=True, **pad)

# â”€â”€ Tab A: Breakdown Report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
rpt_pane = ttk.Frame(rpt_nb)
rpt_nb.add(rpt_pane, text="Analysis Preview")
rpt_pane.rowconfigure(0, weight=1)
rpt_pane.columnconfigure(0, weight=1)

rpt_text = tk.Text(rpt_pane, font=("Consolas", 9), wrap=tk.NONE,
                   bg=_UI["bg_surface"], fg=_UI["text_primary"],
                   insertbackground=_UI["text_primary"], state=tk.DISABLED)
_install_text_sanitizer(rpt_text)
rpt_sv = ttk.Scrollbar(rpt_pane, orient=tk.VERTICAL,   command=rpt_text.yview)
rpt_sh = ttk.Scrollbar(rpt_pane, orient=tk.HORIZONTAL, command=rpt_text.xview)
rpt_text.configure(yscrollcommand=rpt_sv.set, xscrollcommand=rpt_sh.set)
rpt_text.grid(row=0, column=0, sticky="nsew")
rpt_sv.grid(row=0, column=1, sticky="ns")
rpt_sh.grid(row=1, column=0, sticky="ew")

# â”€â”€ Tab B: Model Audit Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
rpt_audit_frame = ttk.Frame(rpt_nb)
rpt_nb.add(rpt_audit_frame, text="Model History")
rpt_audit_frame.rowconfigure(1, weight=1)
rpt_audit_frame.columnconfigure(0, weight=1)

_audit_ctrl = ttk.Frame(rpt_audit_frame)
_audit_ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
ttk.Button(_audit_ctrl, text="Refresh",
           command=lambda: _audit_refresh()).pack(side=tk.LEFT, **pad)
ttk.Button(_audit_ctrl, text="Export Log (.txt)",
           command=lambda: _audit_export_txt()).pack(side=tk.LEFT, **pad)
ttk.Button(_audit_ctrl, text="Export Log (.csv)",
           command=lambda: _audit_export_csv()).pack(side=tk.LEFT, **pad)
ttk.Label(
    _audit_ctrl,
    text="Full history of model weight changes and pick algorithm updates.",
    style="SubtleCard.TLabel",
).pack(side=tk.LEFT, padx=12)

audit_text = tk.Text(
    rpt_audit_frame,
    font=("Consolas", 9),
    wrap=tk.WORD,
    bg=_UI["bg_surface"],
    fg=_UI["text_primary"],
    insertbackground=_UI["text_primary"],
    state=tk.DISABLED,
)
_install_text_sanitizer(audit_text)
_audit_sv = ttk.Scrollbar(rpt_audit_frame, orient=tk.VERTICAL, command=audit_text.yview)
audit_text.configure(yscrollcommand=_audit_sv.set)
audit_text.grid(row=1, column=0, sticky="nsew")
_audit_sv.grid(row=1, column=1, sticky="ns")

# Colour tags for audit log
for _at, _ac in [
    ("ts", _UI["text_muted"]),
    ("sport", _UI["accent"]),
    ("change", _UI["success"]),
    ("neutral", _UI["text_primary"]),
    ("warn", _UI["danger"]),
    ("header", _UI["text_primary"]),
]:
    audit_text.tag_configure(_at, foreground=_ac)

# Tag colours mirroring the popup
for _tag, _fg in [
    ("header", _UI["text_primary"]),
    ("section", _UI["accent"]),
    ("label", _UI["text_muted"]),
    ("value", _UI["text_primary"]),
    ("good", _UI["success"]),
    ("warn", _UI["danger"]),
    ("na", _UI["text_muted"]),
    ("sep", _UI["border"]),
]:
    rpt_text.tag_configure(_tag, foreground=_fg)

_rpt_breakdown_text = [""]   # mutable container so Save btn can access it

# â”€â”€ Model Audit Log helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import csv as _csv_mod
import json as _audit_json

def _audit_refresh():
    """Load model_audit_log.json and render it in the audit_text widget."""
    audit_text.config(state=tk.NORMAL)
    audit_text.delete("1.0", tk.END)
    try:
        with open(AUDIT_LOG_FILE, encoding="utf-8") as f:
            entries = _audit_json.load(f)
    except FileNotFoundError:
        audit_text.insert(tk.END,
            "No audit log found yet.\n"
            "Auto-Grade picks from the Pick Tracker to generate weight tuning entries.\n"
            "Manual notes can be added programmatically via _audit_write_note().\n")
        audit_text.config(state=tk.DISABLED)
        return
    except Exception as e:
        audit_text.insert(tk.END, f"Error reading audit log: {e}\n")
        audit_text.config(state=tk.DISABLED)
        return

    audit_text.insert(tk.END, f"MODEL AUDIT LOG  â€”  {len(entries)} entries\n", "header")
    audit_text.insert(tk.END, "â•" * 70 + "\n\n", "neutral")

    for i, entry in enumerate(reversed(entries), 1):
        ts      = entry.get("timestamp", "->")
        trigger = entry.get("trigger", "->")
        n_picks = entry.get("picks_used", "->")
        note    = entry.get("note", "")
        non_def = entry.get("non_default", {})
        weights = entry.get("weights", {})

        audit_text.insert(tk.END, f"[{i}]  ", "neutral")
        audit_text.insert(tk.END, f"{ts}", "ts")
        audit_text.insert(tk.END, f"  trigger={trigger}  picks_used={n_picks}\n", "neutral")
        if note:
            audit_text.insert(tk.END, f"     Note: {note}\n", "neutral")

        if non_def:
            for sport_k, factors in non_def.items():
                if factors:
                    audit_text.insert(tk.END, f"     {sport_k:8}", "sport")
                    for factor, val in factors.items():
                        delta = val - 1.0
                        tag = "change" if delta > 0.02 else ("warn" if delta < -0.02 else "neutral")
                        arrow = "â–²" if delta > 0 else "â–¼"
                        audit_text.insert(tk.END,
                            f"  {factor}={val:.3f} ({arrow}{abs(delta):.3f})", tag)
                    audit_text.insert(tk.END, "\n")
        else:
            audit_text.insert(tk.END, "     All weights at default (1.000) â€” no significant signal yet.\n", "neutral")

        # Show full weights if they exist
        if weights:
            for sport_k, wdict in sorted(weights.items()):
                row_parts = [f"{k}={v:.3f}" for k,v in sorted(wdict.items())]
                audit_text.insert(tk.END,
                    f"     Full [{sport_k}]: {'  '.join(row_parts)}\n", "ts")
        audit_text.insert(tk.END, "\n")

    audit_text.config(state=tk.DISABLED)
    audit_text.see("1.0")

_rpt_history_index = {}

def _rpt_refresh_history_dropdown():
    global _rpt_history_index
    _rpt_history_index = {}
    _items = []
    try:
        with open(AUDIT_LOG_FILE, encoding="utf-8") as _af:
            _audit_entries = _audit_json.load(_af) or []
        if isinstance(_audit_entries, list):
            for _entry in reversed(_audit_entries[-500:]):
                _ts = str(_entry.get("timestamp") or "--")
                _trigger = str(_entry.get("trigger") or "manual")
                _note = str(_entry.get("note") or "").strip()
                _weights = _entry.get("weights") or {}
                _non_default = _entry.get("non_default") or {}
                _delta_count = 0
                if isinstance(_non_default, dict):
                    for _sport_vals in _non_default.values():
                        if isinstance(_sport_vals, dict):
                            _delta_count += len(_sport_vals)
                _note_short = (_note[:70] + "...") if len(_note) > 73 else (_note or "no note")
                _label = f"AUDIT | {_ts} | {_trigger} | delta:{_delta_count} | {_note_short}"
                _sort_key = re.sub(r"\D+", "", _ts) or "0"
                _items.append((_sort_key, _label, {
                    "kind": "audit",
                    "timestamp": _ts,
                    "trigger": _trigger,
                    "picks_used": _entry.get("picks_used"),
                    "note": _note,
                    "weights": _weights if isinstance(_weights, dict) else {},
                    "non_default": _non_default if isinstance(_non_default, dict) else {},
                }))
    except FileNotFoundError:
        pass
    except Exception as _ax:
        log(f"[reports] audit history load failed: {_ax}", "warning")
    try:
        _db = globals().get("PICKS_DB", "")
        if not _db:
            raise RuntimeError("missing PICKS_DB")
        con = _sqlite3.connect(_db)
        rows = con.execute(
            """
            SELECT id, game_date, game_time, league, away_team, home_team,
                   ou_line, pick, confidence, key_factors, actual_total, pick_result
            FROM model_picks
            ORDER BY id DESC
            LIMIT 500
            """
        ).fetchall()
        con.close()
        for _r in rows:
            (_id, _gd, _gt, _lg, _away, _home, _ou, _pick, _conf, _facts, _act, _res) = _r
            _label = (
                f"PICK | {_gd or '--'} {_gt or ''} | {_lg or '--'} | "
                f"{_away or '--'} @ {_home or '--'} | {_pick or '--'} | {_res or 'PENDING'}"
            )
            _sort_key = re.sub(r"\D+", "", f"{_gd or ''}{_gt or ''}") or "0"
            _items.append((_sort_key, _label, {
                "kind": "pick",
                "id": _id, "game_date": _gd, "game_time": _gt, "league": _lg,
                "away_team": _away, "home_team": _home, "ou_line": _ou,
                "pick": _pick, "confidence": _conf, "key_factors": _facts,
                "actual_total": _act, "pick_result": _res,
            }))
    except Exception as _hx:
        log(f"[reports] history dropdown refresh failed: {_hx}", "warning")
    try:
        _labels = []
        for _k, _label, _payload in sorted(_items, key=lambda x: x[0], reverse=True)[:700]:
            _labels.append(_label)
            _rpt_history_index[_label] = _payload
        rpt_history_cb.configure(values=_labels)
        if not _labels:
            rpt_history_var.set("Select model/logic history entry...")
    except Exception:
        pass

def _rpt_show_history_selection(event=None):
    _label = str(rpt_history_var.get() or "").strip()
    if not _label or _label not in _rpt_history_index:
        return
    _row = _rpt_history_index[_label]
    audit_text.config(state=tk.NORMAL)
    audit_text.delete("1.0", tk.END)
    _kind = str(_row.get("kind") or "pick").lower()
    if _kind == "audit":
        audit_text.insert(tk.END, "MODEL/LOGIC HISTORY ENTRY — AUDIT\n", "header")
        audit_text.insert(tk.END, "═" * 72 + "\n\n", "neutral")
        audit_text.insert(tk.END, f"Timestamp: {_row.get('timestamp')}\n", "ts")
        audit_text.insert(tk.END, f"Trigger: {_row.get('trigger')}  |  Picks Used: {_row.get('picks_used')}\n", "neutral")
        audit_text.insert(tk.END, f"Note: {_row.get('note') or '(none)'}\n\n", "neutral")
        _non_default = _row.get("non_default") or {}
        _weights = _row.get("weights") or {}
        audit_text.insert(tk.END, "Calibration Deltas\n", "header")
        audit_text.insert(tk.END, "─" * 72 + "\n", "neutral")
        _has_delta = False
        for _sport, _vals in sorted(_non_default.items()):
            if not isinstance(_vals, dict) or not _vals:
                continue
            _has_delta = True
            audit_text.insert(tk.END, f"{_sport}\n", "sport")
            for _factor, _val in sorted(_vals.items()):
                try:
                    _delta = float(_val) - 1.0
                    _tag = "change" if _delta > 0 else ("warn" if _delta < 0 else "neutral")
                    _arrow = "▲" if _delta > 0 else ("▼" if _delta < 0 else "=")
                    audit_text.insert(tk.END, f"  {_factor}: {_val:.3f} ({_arrow}{abs(_delta):.3f})\n", _tag)
                except Exception:
                    audit_text.insert(tk.END, f"  {_factor}: {_val}\n", "neutral")
        if not _has_delta:
            audit_text.insert(tk.END, "No non-default calibration deltas recorded.\n", "neutral")
        audit_text.insert(tk.END, "\nFull Weights Snapshot\n", "header")
        audit_text.insert(tk.END, "─" * 72 + "\n", "neutral")
        if isinstance(_weights, dict) and _weights:
            for _sport, _vals in sorted(_weights.items()):
                audit_text.insert(tk.END, f"{_sport}\n", "sport")
                if isinstance(_vals, dict):
                    for _factor, _val in sorted(_vals.items()):
                        audit_text.insert(tk.END, f"  {_factor}: {_val}\n", "neutral")
        else:
            audit_text.insert(tk.END, "No weights snapshot saved for this audit entry.\n", "neutral")
    else:
        audit_text.insert(tk.END, "MODEL/LOGIC HISTORY ENTRY — PICK\n", "header")
        audit_text.insert(tk.END, "═" * 72 + "\n\n", "neutral")
        audit_text.insert(tk.END, f"ID: {_row.get('id')}\n", "neutral")
        audit_text.insert(tk.END, f"Date: {_row.get('game_date')}  Time: {_row.get('game_time')}\n", "neutral")
        audit_text.insert(tk.END, f"League: {_row.get('league')}\n", "sport")
        audit_text.insert(tk.END, f"Matchup: {_row.get('away_team')} @ {_row.get('home_team')}\n", "neutral")
        audit_text.insert(tk.END, f"Pick: {_row.get('pick')}  |  Confidence: {_row.get('confidence')}\n", "neutral")
        audit_text.insert(tk.END, f"O/U Line: {_row.get('ou_line')}  |  Actual Total: {_row.get('actual_total')}\n", "neutral")
        audit_text.insert(tk.END, f"Result: {_row.get('pick_result')}\n\n", "change" if str(_row.get("pick_result","")).upper()=="WIN" else "warn")
        audit_text.insert(tk.END, "Reasoning / Key Factors\n", "header")
        audit_text.insert(tk.END, "─" * 72 + "\n", "neutral")
        audit_text.insert(tk.END, f"{_row.get('key_factors') or 'No key factors logged.'}\n", "neutral")
    audit_text.config(state=tk.DISABLED)
    audit_text.see("1.0")

def _on_rpt_logic_mode_change(event=None):
    _mode = str(rpt_logic_mode_var.get() or "").strip()
    if _mode == "Current Model Snapshot":
        try:
            _mw = _load_model_weights() if "_load_model_weights" in globals() else {}
        except Exception:
            _mw = {}
        audit_text.config(state=tk.NORMAL)
        audit_text.delete("1.0", tk.END)
        audit_text.insert(tk.END, "CURRENT MODEL/LOGIC SNAPSHOT\n", "header")
        audit_text.insert(tk.END, "═" * 72 + "\n\n", "neutral")
        if not _mw:
            audit_text.insert(tk.END, "No saved model_weights.json found. Defaults are active.\n", "neutral")
        else:
            for _lg, _w in sorted(_mw.items()):
                audit_text.insert(tk.END, f"{_lg}\n", "sport")
                for _k, _v in sorted((_w or {}).items()):
                    audit_text.insert(tk.END, f"  {_k}: {_v}\n", "neutral")
                audit_text.insert(tk.END, "\n", "neutral")
        audit_text.config(state=tk.DISABLED)
        audit_text.see("1.0")
    elif _mode in ("Calibration Weights", "Audit Timeline"):
        _audit_refresh()

def _audit_export_txt():
    """Export audit log as a plain-text file."""
    try:
        content = audit_text.get("1.0", tk.END)
        today = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = os.path.join(ODDS_DIR, f"ModelAuditLog_{today}.txt")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        rpt_status_var.set(f"[OK] Audit log exported -> {fpath}")
        log(f"Audit log exported: {fpath}", "info")
    except Exception as e:
        rpt_status_var.set(f"[ERROR] Export failed: {e}")

def _audit_export_csv():
    """Export audit log entries as CSV."""
    try:
        with open(AUDIT_LOG_FILE, encoding="utf-8") as f:
            entries = _audit_json.load(f)
        today = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = os.path.join(ODDS_DIR, f"ModelAuditLog_{today}.csv")
        rows = []
        for entry in entries:
            base = {
                "timestamp": entry.get("timestamp",""),
                "trigger":   entry.get("trigger",""),
                "picks_used":entry.get("picks_used",""),
                "note":      entry.get("note",""),
            }
            weights = entry.get("weights", {})
            if weights:
                for sport_k, wdict in weights.items():
                    for factor, val in wdict.items():
                        rows.append({**base,
                                     "sport": sport_k,
                                     "factor": factor,
                                     "weight": val,
                                     "delta_from_default": round(val - 1.0, 3)})
            else:
                rows.append({**base, "sport":"", "factor":"", "weight":"", "delta_from_default":""})
        if rows:
            with open(fpath, "w", newline="", encoding="utf-8") as f:
                writer = _csv_mod.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            rpt_status_var.set(f"[OK] Audit CSV exported -> {fpath}")
            log(f"Audit CSV exported: {fpath}", "info")
        else:
            rpt_status_var.set("[WARN] Audit log is empty.")
    except FileNotFoundError:
        rpt_status_var.set("[WARN] No audit log found - auto-grade picks first.")
    except Exception as e:
        rpt_status_var.set(f"[ERROR] CSV export failed: {e}")

def _audit_write_note(note: str, trigger: str = "manual"):
    """Write a manual note entry to the audit log (e.g. for manual algorithm changes)."""
    os.makedirs(ODDS_DIR, exist_ok=True)
    try:
        with open(AUDIT_LOG_FILE, encoding="utf-8") as f:
            entries = _audit_json.load(f)
    except Exception:
        entries = []
    entries.append({
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trigger":     trigger,
        "picks_used":  "N/A",
        "weights":     {},
        "non_default": {},
        "note":        note,
    })
    with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
        _audit_json.dump(entries, f, indent=2)

# Auto-load audit log when Reports tab is selected
def _on_rpt_tab_selected(event=None):
    sel = rpt_nb.select()
    if sel and rpt_nb.tab(sel, "text") == "Model History":
        _audit_refresh()
    _rpt_refresh_history_dropdown()

rpt_nb.bind("<<NotebookTabChanged>>", _on_rpt_tab_selected)
rpt_history_cb.bind("<<ComboboxSelected>>", _rpt_show_history_selection, add="+")
rpt_history_cb.bind("<Button-1>", lambda e: _rpt_refresh_history_dropdown(), add="+")
rpt_history_cb.bind("<FocusIn>", lambda e: _rpt_refresh_history_dropdown(), add="+")
rpt_history_cb.configure(postcommand=_rpt_refresh_history_dropdown)
rpt_logic_mode_var.trace_add("write", lambda *_: _on_rpt_logic_mode_change())

# â”€â”€ Report helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _rpt_set_status(msg, colour="#555555"):
    root.after(0, lambda: rpt_status_var.set(_clean_display_text(str(msg))))

def _rpt_write(txt_widget, text, tag="value"):
    """Thread-safe write to rpt_text."""
    def _do():
        txt_widget.config(state=tk.NORMAL)
        txt_widget.insert(tk.END, _clean_display_text(text), tag)
        txt_widget.config(state=tk.DISABLED)
        txt_widget.see(tk.END)
    root.after(0, _do)

def _rpt_clear():
    root.after(0, lambda: (rpt_text.config(state=tk.NORMAL),
                            rpt_text.delete("1.0", tk.END),
                            rpt_text.config(state=tk.DISABLED)))

# â”€â”€ Core per-game analysis builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _rpt_build_game_block(row, sport=None) -> dict:
    """Return a dict with every computed field for one game row.
    Uses the same physics functions as the popup â€” no duplication of logic."""
    league = str(
        sport
        or row.get("League", "")
        or row.get("Sport", "")
        or row.get("_sport_hint", "")
        or rpt_league_var.get()
    ).upper().strip()
    away_raw  = str(row.get("Away_Team","") or "")
    home_raw  = str(row.get("Home_Team","") or "")
    away_clean = _strip_pitcher(away_raw)
    home_clean = _strip_pitcher(home_raw)
    game_time  = str(row.get("Time","") or "")

    # Venue lookup
    home_db, _  = _find_team_fuzzy(home_clean, preferred_league=league)
    away_db, _  = _find_team_fuzzy(away_clean, preferred_league=league)
    _home_row = get_row(home_db, preferred_league=league) if home_db else None
    _away_row = get_row(away_db, preferred_league=league) if away_db else None
    home_venue = _home_row.to_dict() if _home_row is not None else {}
    away_venue = _away_row.to_dict() if _away_row is not None else {}

    # â”€â”€ ESPN Live Venue Override (actual venue, not team home) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        from datetime import datetime as _dt2
        _gd=game_time.split()[0]; _gm,_gday=_gd.split("/")
        _gdate_str=f"{_dt2.now().year}-{int(_gm):02d}-{int(_gday):02d}"
    except Exception:
        from datetime import datetime as _dt2; _gdate_str=_dt2.now().strftime("%Y-%m-%d")
    _espn_v=None
    if league:
        try: _espn_v=_resolve_game_venue(league,away_clean,home_clean,_gdate_str)
        except Exception: pass
    if _espn_v:
        if _espn_v.get("lat")       is not None: home_venue["lat"]        = _espn_v["lat"]
        if _espn_v.get("lon")       is not None: home_venue["lon"]        = _espn_v["lon"]
        if _espn_v.get("elevation") is not None: home_venue["elevation"]  = _espn_v["elevation"]
        if _espn_v.get("venue_name"):             home_venue["venue"]      = _espn_v["venue_name"]
        if _espn_v.get("indoor"):                 home_venue["roof_type"]  = "closed"
        elif _espn_v.get("neutral_site"):         home_venue["roof_type"]  = "open"

    h_elev_f  = safe_float(home_venue.get("elevation"), None, "elev") if home_venue.get("elevation") not in (None, "", "N/A") else None
    a_elev_f  = safe_float(away_venue.get("elevation"), None, "a_elev") if away_venue.get("elevation") not in (None, "", "N/A") else None
    h_orient  = home_venue.get("orientation_deg", "")
    h_roof    = str(home_venue.get("roof_type", "")).lower()
    h_lat     = safe_float(home_venue.get("lat"),  None, "lat") if home_venue.get("lat") not in (None, "", "N/A") else None
    h_lon     = safe_float(home_venue.get("lon"), None, "lon") if home_venue.get("lon") not in (None, "", "N/A") else None

    # Weather (sync fetch using gametime hint)
    wx = None
    if h_lat is not None and h_lon is not None:
        wx = get_weather_at_gametime(h_lat, h_lon, game_time)

    # Physics
    rho = da = hw = cw = None
    if wx and wx != "error" and h_elev_f is not None:
        try:
            h_elev_use = h_elev_f
            h_orient_f = safe_float(h_orient, 0.0, "orient") if (h_orient is not None and h_orient != "") else 0.0
            wind_eff   = wx["wind_speed"]
            if h_roof in ("closed","dome"):
                wind_eff = 0.0
            rho = air_density(wx["temp"], wx["pressure"], wx["humidity"])
            da  = density_altitude(wx["temp"], h_elev_use, wx["pressure"], wx["humidity"])
            hw, cw = wind_components(wind_eff, wx["wind_dir"], h_orient_f)
        except Exception:
            pass

    # Elevation delta
    elev_delta = None
    if h_elev_f is not None and a_elev_f is not None:
        elev_delta = h_elev_f - a_elev_f

    # Air density % vs home baseline
    def _std_rho(h):
        import math
        m = max(0.0,h)*0.3048
        T = 288.15 - 0.0065*m
        P = 101325*(T/288.15)**5.2561
        return P*0.0289644/(8.31446*T)*0.0624279606
    rho_pct_home = rho_pct_away = None
    if rho and h_elev_f is not None:
        base_h = _std_rho(h_elev_f)
        rho_pct_home = (rho - base_h)/base_h*100 if base_h else None
    if rho and a_elev_f is not None:
        base_a = _std_rho(a_elev_f)
        rho_pct_away = (rho - base_a)/base_a*100 if base_a else None

    try:
        _circ = _circ_analysis(
            game_time, home_venue, away_venue, league,
            away_team=away_clean, home_team=home_clean,
            game_date=_gdate_str
        )
    except Exception:
        _circ = {"available": False}

    # Over/under lean (air density physics)
    ou_lean = "NEUTRAL"
    if rho and hw is not None:
        pitcher_score = 0
        if rho > 0.0765:  pitcher_score += 1
        if hw and hw < -4: pitcher_score += 1
        if pitcher_score >= 2:
            ou_lean = "UNDER"
        elif pitcher_score == 0 and (rho < 0.0755 or (hw and hw > 4)):
            ou_lean = "OVER"

    # â”€â”€ CRE: merge Circadian Rhythm Effect into lean + confidence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _cre_rec    = get_cre_for_game(league, away_clean, home_clean) if _CRE_AVAILABLE else None
    _cre_result = apply_cre_to_model(
        ou_lean, "NEUTRAL", 3, _cre_rec, league,
        rho_pct=rho_pct_home if rho_pct_home is not None else 0.0)
    ou_lean = _cre_result["final_ou_lean"]   # CRE-adjusted lean
    _side_lean = _cre_result.get("cre_side_lean","NEUTRAL")
    _lineup_signal_weight = 0.0

    # â”€â”€ INJURY DELTA INTEGRATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Load fast-path injury deltas (status+pos+recency, no ESPN calls)
    # â”€â”€ Referee / Umpire signal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _ref_result = None
    if _REF_ENGINE_OK and _rse_mod:
        try:
            from datetime import date as _date_ref
            _ref_result = _rse_mod.get_ref_signal(
                league, away_clean, home_clean, _date_ref.today())
            _ref_conf = _ref_result.get("confidence", 0.0)
            if _ref_conf >= 0.30:
                _ref_ou   = _ref_result.get("ou_signal","NEUTRAL")
                _ref_side = _ref_result.get("side_signal","NEUTRAL")
                # Ref signal supplements â€” same agreement/fill logic as lineup
                if _ref_ou != "NEUTRAL" and ou_lean == "NEUTRAL":
                    ou_lean = _ref_ou
                elif _ref_ou != "NEUTRAL" and _ref_ou == ou_lean and _ref_conf >= 0.50:
                    pass  # reinforcement
                elif _ref_ou != "NEUTRAL" and _ref_ou != ou_lean and _ref_conf >= 0.70:
                    ou_lean = _ref_ou  # strong override only at high confidence
                if _ref_side != "NEUTRAL" and _side_lean == "NEUTRAL":
                    _side_lean = _ref_side
        except Exception:
            _ref_result = None
    # â”€â”€ Lineup assessment: real per-player rho adjustment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _la_result = None
    if _NEA_LINEUP_OK and _la_mod and _NEA_STATS_OK and _nea_mod and rho is not None:
        try:
            _las2 = _la_mod.get_lineup_assessments(
                league, away_clean, home_clean, _nea_mod,
                max_workers=4, timeout_per_side=5.0)  # mostly cache hits
            _rho_pct_for_lineup = rho_pct_home if rho_pct_home is not None else 0.0
            _la_result = _la_mod.compute_lineup_rho_adjustments(
                _las2["away"], _las2["home"], _rho_pct_for_lineup, league)
            # Lineup signal gated by confidence AND confirmation status
            _la_conf = _la_result.get("confidence", 0.0)
            _a_la    = _la_result.get("away_la")
            _h_la    = _la_result.get("home_la")
            # Discount projected lineups (not confirmed) by 40%
            _a_conf_mult = 1.0 if (hasattr(_a_la,"lineup_confirmed") and _a_la.lineup_confirmed) else 0.60
            _h_conf_mult = 1.0 if (hasattr(_h_la,"lineup_confirmed") and _h_la.lineup_confirmed) else 0.60
            _eff_conf = _la_conf * ((_a_conf_mult + _h_conf_mult) / 2)
            # Track lineup signal strength for pick system weighting
            _lineup_signal_weight = round(_eff_conf, 3)  # 0.0-1.0
            if _eff_conf >= 0.30:  # floor: 30% effective coverage
                _lu_ou   = _la_result.get("ou_signal","NEUTRAL")
                _lu_side = _la_result.get("side_signal","NEUTRAL")
                # Confirmed alignment: OVER if two sources agree, UNDER if two agree
                if _lu_ou != "NEUTRAL" and ou_lean == "NEUTRAL":
                    ou_lean = _lu_ou
                elif _lu_ou != "NEUTRAL" and _lu_ou == ou_lean:
                    pass  # reinforcement â€” no change, already aligned
                elif _lu_ou != "NEUTRAL" and _lu_ou != ou_lean and _eff_conf >= 0.65:
                    # Only override existing lean if very high confidence
                    ou_lean = _lu_ou
                if _lu_side != "NEUTRAL" and _side_lean == "NEUTRAL":
                    _side_lean = _lu_side
        except Exception:
            _la_result = None
    # â”€â”€ Injury delta: REAL CACHED DATA ONLY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # _cache_inj_delta() reads from nea_stats_cache.db (populated by render clicks).
    # Returns 0.0 for any player not yet fetched â€” never uses position averages.
    # This means the signal builds progressively: first open = 0 (no phantom signal),
    # subsequent opens = real data. Correct behavior: no signal > fake signal.
    _inj_data_m  = _inj_news_lookup(league, away_clean, home_clean)
    _a_inj_raw   = _inj_data_m.get("away_injuries", []) if _inj_data_m else []
    _h_inj_raw   = _inj_data_m.get("home_injuries", []) if _inj_data_m else []
    _a_inj      = _cache_inj_delta(_a_inj_raw, league)  # dict: off/def/total
    _h_inj      = _cache_inj_delta(_h_inj_raw, league)
    _inj_has_data = _a_inj["has_data"] or _h_inj["has_data"]
    # Thresholds: minimum real-data signal to act on
    _INJ_THR    = {"MLB":0.26,"NBA":5.0,"NCAAB":4.0,"NHL":0.20,"NFL":4.0,"NCAAF":3.0}
    _thr        = _INJ_THR.get(league, 0.26)
    if _inj_has_data:
        # â”€â”€ SIDE LEAN: based on net OFFENSIVE delta â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Which team loses more offensive production->
        _off_net = _a_inj["off"] - _h_inj["off"]   # >0 = away offense more hurt
        if abs(_off_net) >= _thr:
            _side_lean = "HOME" if _off_net > 0 else "AWAY"
        # â”€â”€ TOTAL LEAN: UNDER from lost offense, OVER from lost defense â”€
        # Lost offense on BOTH sides â†’ combined scoring drops â†’ UNDER
        _both_off_hurt = (_a_inj["off"] >= _thr and _h_inj["off"] >= _thr)
        _one_off_bad   = max(_a_inj["off"],_h_inj["off"]) >= _thr * 1.5
        # Lost defense on EITHER side â†’ opponent scores more â†’ OVER
        # (missing closer, DE, shutdown corner â€” opponent now has advantage)
        _either_def_hurt = max(_a_inj["def"],_h_inj["def"]) >= _thr
        if _either_def_hurt and not _both_off_hurt:
            # Defensive hole outweighs offense loss â†’ more scoring expected
            if ou_lean in ("NEUTRAL","UNDER"): ou_lean = "OVER"
        elif _both_off_hurt or _one_off_bad:
            if ou_lean == "NEUTRAL": ou_lean = "UNDER"
        # Competing: both off and def hit â†’ net effect, pick dominant
        if _both_off_hurt and _either_def_hurt:
            _off_signal = _a_inj["off"] + _h_inj["off"]
            _def_signal = _a_inj["def"] + _h_inj["def"]
            ou_lean = "UNDER" if _off_signal > _def_signal else "OVER"
    _a_inj_d = _a_inj["total"]; _h_inj_d = _h_inj["total"]  # for game dict

    _home_env_load = _team_environment_load_model(
        home_clean, league, home_venue, home_venue,
        circ_state=((_circ or {}).get("home_state") or {}),
        rho_pct=rho_pct_home, weather=wx,
    )
    _away_env_load = _team_environment_load_model(
        away_clean, league, away_venue, home_venue,
        circ_state=((_circ or {}).get("away_state") or {}),
        rho_pct=rho_pct_away, weather=wx,
    )
    _env_gap = (_away_env_load.get("load_score", 0.0) or 0.0) - (_home_env_load.get("load_score", 0.0) or 0.0)
    _env_total_exec = (_away_env_load.get("execution_penalty", 0.0) or 0.0) + (_home_env_load.get("execution_penalty", 0.0) or 0.0)
    if _side_lean == "NEUTRAL" and abs(_env_gap) >= 2.4:
        _side_lean = "HOME" if _env_gap > 0 else "AWAY"
    if ou_lean == "NEUTRAL" and _env_total_exec >= 0.78:
        ou_lean = "UNDER"

    _mlb_ctx = {
        "available": False,
        "home_pitcher": {"score": 0.0, "notes": [], "components": {}},
        "away_pitcher": {"score": 0.0, "notes": [], "components": {}},
        "home_offense": {"score": 0.0, "notes": [], "components": {}},
        "away_offense": {"score": 0.0, "notes": [], "components": {}},
        "total_over_impact": 0.0,
        "summary": "",
        "pick_factors": [],
    }
    if league == "MLB":
        _mlb_ctx = _mlb_game_context_model(
            home_clean, away_clean, _gdate_str,
            rho_pct_home, rho_pct_away, hw,
            home_venue.get("surface_type", ""),
            circ=_circ, rr=_ref_result, elev_delta=elev_delta,
            weather=wx, home_venue_row=home_venue, away_venue_row=away_venue,
        )
        _ctx_total = _mlb_ctx.get("total_over_impact", 0.0) or 0.0
        if _ctx_total >= 0.65:
            if ou_lean == "NEUTRAL" or _ctx_total >= 1.00:
                ou_lean = "OVER"
        elif _ctx_total <= -0.65:
            if ou_lean == "NEUTRAL" or _ctx_total <= -1.00:
                ou_lean = "UNDER"
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # Starters
    home_starter = away_starter = None
    if _starters_df is not None:
        try:
            home_starter = find_pitcher_for_team(home_clean, _starters_df)
            away_starter = find_pitcher_for_team(away_clean, _starters_df)
        except Exception:
            pass

    return {
        "game_time": game_time,
        "away": away_clean, "home": home_clean,
        "away_spread": row.get("Away_Spread",""), "home_spread": row.get("Home_Spread",""),
        "total": row.get("Total",""),
        "away_ml": row.get("Away_ML",""), "home_ml": row.get("Home_ML",""),
        "venue": home_venue.get("venue","N/A"),
        "h_elev_ft": h_elev_f, "a_elev_ft": a_elev_f, "elev_delta": elev_delta,
        "surface": home_venue.get("surface_type",""), "roof": home_venue.get("roof_type",""),
        "temp": wx["temp"] if wx and wx!="error" else None,
        "humidity": wx["humidity"] if wx and wx!="error" else None,
        "pressure": wx["pressure"] if wx and wx!="error" else None,
        "wind_speed": wx["wind_speed"] if wx and wx!="error" else None,
        "wind_dir": wx["wind_dir"] if wx and wx!="error" else None,
        "air_density": rho, "density_alt": da,
        "headwind": hw, "crosswind": cw,
        "rho_pct_home": rho_pct_home, "rho_pct_away": rho_pct_away,
        "ou_lean": ou_lean,
        "home_env_load": _home_env_load,
        "away_env_load": _away_env_load,
        "home_env_score": _home_env_load.get("load_score", 0.0),
        "away_env_score": _away_env_load.get("load_score", 0.0),
        "home_env_exec": _home_env_load.get("execution_penalty", 0.0),
        "away_env_exec": _away_env_load.get("execution_penalty", 0.0),
        "home_env_notes": " | ".join(_home_env_load.get("notes", [])),
        "away_env_notes": " | ".join(_away_env_load.get("notes", [])),
        "home_starter": home_starter["name"] if home_starter else "N/A",
        "away_starter": away_starter["name"] if away_starter else "N/A",
        # CRE fields
        "cre_result":         _cre_result,
        "cre_away_severity":  _cre_result.get("away_severity",  "N/A") if _cre_result else "N/A",
        "cre_home_severity":  _cre_result.get("home_severity",  "N/A") if _cre_result else "N/A",
        "cre_lean":           _cre_result.get("cre_ou_lean",    "N/A") if _cre_result else "N/A",
        "cre_side_lean":      _cre_result.get("cre_side_lean",  "N/A") if _cre_result else "N/A",
        "compound_signal":    _cre_result.get("compound_signal", False) if _cre_result else False,
        "cre_confidence":     _cre_result.get("final_confidence", 3)  if _cre_result else 3,
        "side_lean":          _side_lean,
        "circadian_result":   _circ,
        "away_inj_delta":     _a_inj_d,
        "home_inj_delta":     _h_inj_d,
        "lineup_rho_result":    _la_result,
        "ref_result":           _ref_result,
        "mlb_context":          _mlb_ctx,
        "mlb_context_total":    _mlb_ctx.get("total_over_impact", 0.0),
        "mlb_context_summary":  _mlb_ctx.get("summary", ""),
        "mlb_pick_factors":     " | ".join(_mlb_ctx.get("pick_factors", [])),
        "mlb_home_pitcher_ctx": _mlb_ctx.get("home_pitcher", {}).get("score", 0.0),
        "mlb_away_pitcher_ctx": _mlb_ctx.get("away_pitcher", {}).get("score", 0.0),
        "mlb_home_offense_ctx": _mlb_ctx.get("home_offense", {}).get("score", 0.0),
        "mlb_away_offense_ctx": _mlb_ctx.get("away_offense", {}).get("score", 0.0),
        "lineup_signal_weight": _lineup_signal_weight,
        "lineup_away_sc":       _la_result.get("away_la").total_sc if _la_result and _la_result.get("away_la") else 0.0,
        "lineup_home_sc":       _la_result.get("home_la").total_sc if _la_result and _la_result.get("home_la") else 0.0,
        "lineup_away_power":    _la_result.get("away_power_rating",0.0) if _la_result else 0.0,
        "lineup_home_power":    _la_result.get("home_power_rating",0.0) if _la_result else 0.0,
        "lineup_away_conf":     str(_la_result.get("away_la").lineup_status if _la_result and _la_result.get("away_la") else "N/A"),
        "lineup_home_conf":     str(_la_result.get("home_la").lineup_status if _la_result and _la_result.get("home_la") else "N/A"),
        "cre_notes":          _cre_result.get("notes", "")            if _cre_result else "",
    }

# â”€â”€ EXPORT SUMMARY EXCEL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _rpt_export_excel():
    global data_df
    league = rpt_league_var.get()
    _rpt_set_status(f"Building {league} summary â€” fetching weather for all games...")
    root.after(0, lambda: rpt_export_btn.config(state=tk.DISABLED))
    try:
        if data_df is None or data_df.empty:
            _rpt_set_status("âš  No matchup data loaded. Fetch matchups first.")
            return
        rows = []
        n = len(data_df)
        for i, (_, row) in enumerate(data_df.iterrows()):
            _rpt_set_status(f"Processing {i+1}/{n}: {row.get('Away_Team','')} @ {row.get('Home_Team','')}")
            g = _rpt_build_game_block(row, league)
            rows.append(g)
        summary_df = pd.DataFrame(rows)

        today = str(datetime.now().date())
        fpath = os.path.join(ODDS_DIR, f"Report_{league}_{today}.xlsx")
        os.makedirs(ODDS_DIR, exist_ok=True)

        # Arsenal sheet â€” all pitchers for today
        ars_sheet = _arsenal_df.copy() if _arsenal_df is not None and not _arsenal_df.empty else pd.DataFrame()

        with pd.ExcelWriter(fpath, engine="openpyxl") as writer:
            # Sheet 1: Summary
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
            # Sheet 2: Arsenal (per-pitch Statcast)
            if not ars_sheet.empty:
                ars_sheet.to_excel(writer, sheet_name="PitcherArsenal", index=False)
            # Sheet 3: Odds (raw)
            data_df.to_excel(writer, sheet_name="RawOdds", index=False)

        _rpt_set_status(f"âœ… Exported â†’ {fpath}")
        log(f"Report exported: {fpath}", "info")
    except Exception as exc:
        import traceback
        _rpt_set_status(f"âŒ Export failed: {exc}")
        log(f"Report export failed:\n{traceback.format_exc()}", "error")
    finally:
        root.after(0, lambda: rpt_export_btn.config(state=tk.NORMAL))

# â”€â”€ GENERATE FULL BREAKDOWN TEXT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _rpt_generate_breakdown():
    league = rpt_league_var.get()
    _rpt_set_status(f"Generating {league} full breakdown...")
    root.after(0, lambda: rpt_breakdown_btn.config(state=tk.DISABLED))
    _rpt_clear()
    try:
        if data_df is None or data_df.empty:
            _rpt_set_status("âš  No matchup data loaded.")
            return

        W = 62
        SEP = "â•" * W
        buf = []

        for _, row in data_df.iterrows():
            g = _rpt_build_game_block(row, league)
            lines = []
            lines.append(SEP)
            lines.append(f"  {g['away']}  @  {g['home']}")
            lines.append(f"  Game Time: {g['game_time']}")
            lines.append(SEP)
            lines.append("")
            # Odds
            lines.append("  ODDS")
            lines.append("  " + "â”€"*W)
            lines.append(f"  {'Spread':<12}  {str(g['away']):<22} {str(g['away_spread']):<8}  {str(g['home']):<22} {str(g['home_spread'])}")
            lines.append(f"  {'Total':<12}  {str(g['total'])}")
            lines.append(f"  {'Moneyline':<12}  {str(g['away']):<22} {str(g['away_ml']):<8}  {str(g['home']):<22} {str(g['home_ml'])}")
            lines.append("")
            # Venue
            lines.append("  VENUE")
            lines.append("  " + "â”€"*W)
            lines.append(f"  {'Venue':<16}  {g['venue']}")
            if g['h_elev_ft'] is not None:
                lines.append(f"  {'Elevation':<16}  {int(g['h_elev_ft']):,} ft")
            lines.append(f"  {'Surface':<16}  {g['surface']}")
            lines.append(f"  {'Roof':<16}  {g['roof'] or 'open'}")
            lines.append("")
            # Weather
            lines.append("  WEATHER @ GAME VENUE")
            lines.append("  " + "â”€"*W)
            if g['temp'] is not None:
                lines.append(f"  {'Temperature':<16}  {g['temp']:.1f} Â°F")
                lines.append(f"  {'Humidity':<16}  {g['humidity']:.0f}%")
                lines.append(f"  {'Pressure':<16}  {g['pressure']:.2f} inHg")
                _ws=g['wind_speed']; _wd=g['wind_dir']
                if _ws is not None and _wd is not None:
                    lines.append(f"  {'Wind':<16}  {_ws:.1f} mph  @  {_wd:.0f}Â°")
                else:
                    lines.append(f"  {'Wind':<16}  (unavailable)")
            else:
                lines.append("  (Weather unavailable)")
            lines.append("")
            # Physics
            lines.append("  PHYSICS")
            lines.append("  " + "â”€"*W)
            if g.get("cre_result") and g["cre_result"].get("cre_contributed"):
                cre_block = cre_display_block(g["cre_result"], width=W)
                if cre_block:
                    lines.append(cre_block)
            if g['air_density'] is not None:
                rho_pct = g['rho_pct_home'] if g['rho_pct_home'] is not None else 0.0
                sign = "DENSER" if rho_pct >= 0 else "THINNER"
                lines.append(f"  {'Air Density':<20}  {g['air_density']:.5f} lb/ftÂ³  ({abs(rho_pct):.1f}% {sign} than home baseline)")
                if g['density_alt'] is not None:
                    lines.append(f"  {'Density Altitude':<20}  {int(g['density_alt']):,} ft")
                else:
                    lines.append(f"  {'Density Altitude':<20}  N/A (missing elevation)")
                hw_lbl = f"{abs(g['headwind']):.1f} mph {'HEADWIND' if g['headwind']<0 else 'TAILWIND'}"
                lines.append(f"  {'Headwind':<20}  {hw_lbl}")
                lines.append(f"  {'Crosswind':<20}  {abs(g['crosswind']):.1f} mph")
            else:
                lines.append("  (Physics unavailable â€” no weather data)")
            lines.append("")
            # Elevation analysis
            lines.append("  ELEVATION ANALYSIS")
            lines.append("  " + "â”€"*W)
            if g['elev_delta'] is not None:
                if abs(g['elev_delta']) < 100:
                    lines.append(f"  Delta â‰ˆ 0 ft â€” negligible elevation change.")
                elif g['elev_delta'] > 0:
                    lines.append(f"  Away steps UP {int(abs(g['elev_delta'])):,} ft vs their home ({int(g['a_elev_ft']):,} ft).")
                    if g['rho_pct_away'] is not None:
                        verdict = "DENSER than away home" if g['rho_pct_away']>0 else "THINNER than away home"
                        lines.append(f"  Net air vs away home baseline: {abs(g['rho_pct_away']):.1f}% {verdict}.")
                else:
                    lines.append(f"  Away steps DOWN {int(abs(g['elev_delta'])):,} ft vs their home ({int(g['a_elev_ft']):,} ft).")
            lines.append("")
            # Environment load
            lines.append("  ENVIRONMENT LOAD")
            lines.append("  " + "â”€"*W)
            _a_env_sc = g.get("away_env_score", 0.0) or 0.0
            _h_env_sc = g.get("home_env_score", 0.0) or 0.0
            _a_env_ex = g.get("away_env_exec", 0.0) or 0.0
            _h_env_ex = g.get("home_env_exec", 0.0) or 0.0
            lines.append(f"  Away  {g['away']:<22}  load {_a_env_sc:.1f}/10  |  exec drag {_a_env_ex:.2f}")
            if g.get("away_env_notes"):
                lines.append(f"       {g['away_env_notes']}")
            _a_env = g.get("away_env_load") or {}
            if _a_env.get("rho_delta_last_pct") is not None or _a_env.get("temp_delta_last") is not None:
                _bits = []
                if _a_env.get("rho_delta_last_pct") is not None:
                    _bits.append(f"ÏÎ” last game {_a_env['rho_delta_last_pct']:.1f}%")
                if _a_env.get("temp_delta_last") is not None:
                    _bits.append(f"TempÃŽâ€ {_a_env['temp_delta_last']:.0f}F")
                if _a_env.get("pressure_delta_last") is not None:
                    _bits.append(f"PressÃŽâ€ {_a_env['pressure_delta_last']:.2f} inHg")
                lines.append("       " + "  |  ".join(_bits))
            lines.append(f"  Home  {g['home']:<22}  load {_h_env_sc:.1f}/10  |  exec drag {_h_env_ex:.2f}")
            if g.get("home_env_notes"):
                lines.append(f"       {g['home_env_notes']}")
            _h_env = g.get("home_env_load") or {}
            if _h_env.get("rho_delta_last_pct") is not None or _h_env.get("temp_delta_last") is not None:
                _bits = []
                if _h_env.get("rho_delta_last_pct") is not None:
                    _bits.append(f"ÏÎ” last game {_h_env['rho_delta_last_pct']:.1f}%")
                if _h_env.get("temp_delta_last") is not None:
                    _bits.append(f"TempÃŽâ€ {_h_env['temp_delta_last']:.0f}F")
                if _h_env.get("pressure_delta_last") is not None:
                    _bits.append(f"PressÃŽâ€ {_h_env['pressure_delta_last']:.2f} inHg")
                lines.append("       " + "  |  ".join(_bits))
            lines.append("")
            # Starters
            lines.append("  PITCHING MATCHUP")
            lines.append("  " + "â”€"*W)
            lines.append(f"  {'Home Starter':<16}  {g['home_starter']}")
            lines.append(f"  {'Away Starter':<16}  {g['away_starter']}")
            lines.append("")
            # â”€â”€ Lineup Assessment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            _lrr = g.get("lineup_rho_result")
            _lsw = g.get("lineup_signal_weight", 0.0)
            if _lrr and _lsw > 0.0:
                lines.append("  LINEUP ASSESSMENT")
                lines.append("  " + "â”€"*W)
                _a_sc  = g.get("lineup_away_sc",  0.0)
                _h_sc  = g.get("lineup_home_sc",  0.0)
                _a_pw  = g.get("lineup_away_power",0.0)
                _h_pw  = g.get("lineup_home_power",0.0)
                _a_st2 = g.get("lineup_away_conf", "N/A")
                _h_st2 = g.get("lineup_home_conf", "N/A")
                _a_nm  = g.get("away","Away")
                _h_nm  = g.get("home","Home")
                lines.append(f"  Away  {_a_nm:<22}  SC={_a_sc:.3f}  HR/G={_a_pw:.4f}  [{_a_st2}]")
                lines.append(f"  Home  {_h_nm:<22}  SC={_h_sc:.3f}  HR/G={_h_pw:.4f}  [{_h_st2}]")
                _lu_ou   = _lrr.get("ou_signal","N/A")
                _lu_side = _lrr.get("side_signal","N/A")
                lines.append(f"  Signal weight: {_lsw:.2f}  |  OU: {_lu_ou}  |  Side: {_lu_side}")
                if _lrr.get("detail"):
                    lines.append(f"  {_lrr['detail']}")
                lines.append("")

            # â”€â”€ Injury Signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            _a_inj_d2 = g.get("away_inj_delta",0.0)
            _h_inj_d2 = g.get("home_inj_delta",0.0)
            if _a_inj_d2 > 0 or _h_inj_d2 > 0:
                lines.append("  INJURY SIGNALS")
                lines.append("  " + "â”€"*W)
                lines.append(f"  Away inj delta {_a_inj_d2:.4f}  |  Home inj delta {_h_inj_d2:.4f}")
                lines.append("")

            # Net verdict
            lines.append("  NET VERDICT")
            lines.append("  " + "â”€"*W)
            ou    = g['ou_lean']
            _side = g.get("side_lean","NEUTRAL")
            _sw   = g.get("lineup_signal_weight", 0.0)
            verdict_note = {
                "UNDER":   "Weather, environmental load, and/or matchup context suppress scoring conditions â€” lean UNDER.",
                "OVER":    "Carry, hitter environment, and/or matchup context support scoring â€” lean OVER.",
                "NEUTRAL": "Environmental and contextual factors roughly cancel â€” no strong lean.",
            }.get(ou, "")
            lines.append(f"  OU LEAN:   {ou}  |  {verdict_note}")
            _rr2 = g.get("ref_result")
            if _rr2 and _rr2.get("ref_names"):
                _ref_names_str = ", ".join(_rr2["ref_names"])[:70]
                lines.append(f"  Officials: {_ref_names_str}")
            if _rr2 and _rr2.get("ou_signal","NEUTRAL") != "NEUTRAL":
                lines.append(f"  Ref lean:  {_rr2['ou_signal']}  "
                             f"(conf={_rr2.get('confidence',0):.0%})  "
                             f"{_rr2.get('detail','')[:60]}")
            if _side != "NEUTRAL":
                lines.append(f"  SIDE LEAN: {_side}  |  Injury/lineup data favors {_side.title()} team.")
            if _sw > 0:
                _conf_lbl = "confirmed" if _sw >= 0.85 else "projected/partial"
                lines.append(f"  Lineup confidence: {_sw:.0%}  ({_conf_lbl})")
            if league == "MLB" and g.get("mlb_context_summary"):
                lines.append(f"  MLB context: {g['mlb_context_summary']}  "
                             f"(total {float(g.get('mlb_context_total', 0.0) or 0.0):+.2f})")
                if g.get("mlb_pick_factors"):
                    lines.append(f"  MLB drivers: {g['mlb_pick_factors']}")
            lines.append(SEP)
            lines.append("")

            block = _clean_display_text(chr(10).join(lines))
            buf.append(block)
            _rpt_write(rpt_text, block, "value")

        _rpt_breakdown_text[0] = _clean_display_text(chr(10).join(buf))
        _rpt_set_status(f"[OK] Breakdown complete - {len(data_df)} games analyzed. Select Save to export.")
        root.after(0, lambda: rpt_save_btn.config(state=tk.NORMAL))
    except Exception as exc:
        import traceback
        _rpt_set_status(f"[ERROR] Breakdown failed: {exc}")
        log(f"Breakdown failed:\n{traceback.format_exc()}", "error")
    finally:
        root.after(0, lambda: rpt_breakdown_btn.config(state=tk.NORMAL))

# â”€â”€ SAVE BREAKDOWN TO .txt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _rpt_save_txt():
    from tkinter import filedialog
    today = str(datetime.now().date())
    league = rpt_league_var.get()
    default_name = f"Breakdown_{league}_{today}.txt"
    fpath = filedialog.asksaveasfilename(
        defaultextension=".txt", initialfile=default_name,
        filetypes=[("Text files","*.txt"),("All files","*.*")],
        title="Save Breakdown Report")
    if not fpath:
        return
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(_clean_display_text(_rpt_breakdown_text[0]))
        _rpt_set_status(f"[OK] Report saved -> {fpath}")
        log(f"Breakdown saved: {fpath}", "info")
    except Exception as exc:
        _rpt_set_status(f"[ERROR] Save failed: {exc}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 5 â€” PICK TRACKER
# Log picks â†’ enter results â†’ review accuracy â†’ model self-calibration
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
import sqlite3 as _sqlite3
import tempfile as _tempfile

def _picktracker_db_candidates():
    _cands = [
        Path(ODDS_DIR) / "picks_history.db",
        Path(__file__).resolve().parent / "picks_history.db",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SportsPhysicsEngine" / "picks_history.db",
        Path(_tempfile.gettempdir()) / "SportsPhysicsEngine" / "picks_history.db",
    ]
    _out, _seen = [], set()
    for _p in _cands:
        _s = str(_p)
        if _s in _seen:
            continue
        _seen.add(_s)
        _out.append(_p)
    return _out


PICKS_DB = str(_picktracker_db_candidates()[0])

def _picks_init_db():
    """Create DB and tables if they don't exist (with writable-path fallback)."""
    global PICKS_DB
    _ddl_picks = """
        CREATE TABLE IF NOT EXISTS picks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at     TEXT,
            game_date     TEXT,
            game_time     TEXT,
            league        TEXT,
            away_team     TEXT,
            home_team     TEXT,
            ou_line       REAL,
            pick          TEXT,        -- OVER / UNDER / NEUTRAL
            confidence    INTEGER,     -- 1-5
            home_starter  TEXT,
            away_starter  TEXT,
            air_dens_pct  REAL,        -- rho_pct_home
            headwind_mph  REAL,
            elev_delta_ft REAL,
            ou_lean_factors TEXT,      -- JSON string of contributing factors
            actual_total  REAL,        -- filled in after game
            pick_result   TEXT,        -- WIN / LOSS / PUSH / PENDING
            notes         TEXT
        )"""
    _ddl_model = """
        CREATE TABLE IF NOT EXISTS model_picks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at     TEXT,
            game_date     TEXT,
            game_time     TEXT,
            league        TEXT,
            away_team     TEXT,
            home_team     TEXT,
            ou_line       REAL,
            pick          TEXT,
            confidence    TEXT,
            key_factors   TEXT,
            actual_total  REAL,
            pick_result   TEXT DEFAULT 'PENDING',
            UNIQUE(game_date, away_team, home_team)
        )"""
    _errs = []
    _chosen = None

    for _db_path in _picktracker_db_candidates():
        try:
            _db_path.parent.mkdir(parents=True, exist_ok=True)
            con = _sqlite3.connect(str(_db_path), timeout=8)
            con.execute(_ddl_picks)
            con.execute(_ddl_model)
            con.commit()
            con.close()
            _chosen = str(_db_path)
            break
        except Exception as _db_e:
            _errs.append(f"{_db_path}: {_db_e}")
            try:
                con.close()
            except Exception:
                pass

    if _chosen is None:
        # Last-resort non-persistent DB so UI can still boot.
        _chosen = ":memory:"
        con = _sqlite3.connect(_chosen)
        con.execute(_ddl_picks)
        con.execute(_ddl_model)
        con.commit()
        con.close()
        log("[picktracker] All filesystem DB paths failed; using in-memory DB for this session.", "error")
        for _e in _errs:
            log(f"[picktracker] { _e }", "error")
    elif _chosen != PICKS_DB:
        log(f"[picktracker] Using writable DB path: {_chosen}", "warning")

    PICKS_DB = _chosen

_picks_init_db()

# â”€â”€ Tab frame â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
execution_frame = ttk.Frame(main_tabs)
main_tabs.add(execution_frame, text="Picks")
execution_nb = ttk.Notebook(execution_frame)
execution_nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

picks_frame = ttk.Frame(execution_nb)
execution_nb.add(picks_frame, text="My Picks")

# â”€â”€ Log Pick control bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
pk_ctrl = ttk.LabelFrame(picks_frame, text="Position Entry", padding=10, style="Card.TLabelframe")
pk_ctrl.pack(fill=tk.X, **pad)

# Row 0: game selector + quick-fill button
# Pick Tracker owns its own league selector â€” independent of Today's Matchups tab
pk_sport_var = tk.StringVar(value="MLB")
ttk.Label(pk_ctrl, text="League:").grid(row=0, column=0, sticky="e", **pad)
pk_sport_cb = ttk.Combobox(pk_ctrl, textvariable=pk_sport_var,
                           values=["MLB","NBA","NHL","NFL","NCAAB","NCAAF"],
                           state="readonly", width=7)
pk_sport_cb.grid(row=0, column=1, **pad)
pk_game_var = tk.StringVar(value="-- select game --")
pk_game_cb  = ttk.Combobox(pk_ctrl, textvariable=pk_game_var, width=36, state="readonly")
pk_game_cb.grid(row=0, column=2, sticky="w", **pad)
pk_game_cb.bind("<<ComboboxSelected>>", lambda e: _pk_autofill(e))
ttk.Button(pk_ctrl, text="Load Slate",
           command=lambda: threading.Thread(target=_pk_load_games_for_sport, daemon=True).start()
           ).grid(row=0, column=3, **pad)

# Row 1: pick + line + confidence
ttk.Label(pk_ctrl, text="Pick:").grid(row=1, column=0, sticky="e", **pad)
pk_pick_var = tk.StringVar(value="OVER")
ttk.Combobox(pk_ctrl, textvariable=pk_pick_var, values=["OVER","UNDER","NEUTRAL"],
             width=10, state="readonly").grid(row=1, column=1, sticky="w", **pad)

ttk.Label(pk_ctrl, text="  O/U Line:").grid(row=1, column=2, sticky="e", **pad)
pk_line_var = tk.StringVar()
ttk.Entry(pk_ctrl, textvariable=pk_line_var, width=8).grid(row=1, column=3, sticky="w", **pad)

ttk.Label(pk_ctrl, text="  Confidence (1-5):").grid(row=1, column=4, sticky="e", **pad)
pk_conf_var = tk.StringVar(value="3")
ttk.Combobox(pk_ctrl, textvariable=pk_conf_var, values=["1","2","3","4","5"],
             width=5, state="readonly").grid(row=1, column=5, sticky="w", **pad)

# Row 2: notes + log button
ttk.Label(pk_ctrl, text="Notes:").grid(row=2, column=0, sticky="e", **pad)
pk_notes_var = tk.StringVar()
ttk.Entry(pk_ctrl, textvariable=pk_notes_var, width=50).grid(row=2, column=1, columnspan=4, sticky="w", **pad)
ttk.Button(pk_ctrl, text="Record Position",
           command=lambda: _pk_log_pick()).grid(row=2, column=5, **pad)

pk_log_status = tk.StringVar(value="")
ttk.Label(pk_ctrl, textvariable=pk_log_status,
          style="SubtleCard.TLabel").grid(row=3, column=0, columnspan=6, sticky="w", **pad)

def _pk_set_status(msg):
    root.after(0, lambda m=str(msg): pk_log_status.set(m))

# â”€â”€ Pick History grid â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
pk_hist_frame = ttk.LabelFrame(picks_frame, text="Execution History", padding=8, style="Card.TLabelframe")
pk_hist_frame.pack(fill=tk.X, expand=False, **pad)
pk_hist_frame.rowconfigure(0, weight=1)
pk_hist_frame.columnconfigure(0, weight=1)

PK_COLS = ("Date","Game Time","Away","Home","Line","Pick","Conf","Result","Actual","Notes")
pk_tree = ttk.Treeview(pk_hist_frame, columns=PK_COLS, show="headings", height=5)
PK_WIDTHS = {"Date":85,"Game Time":75,"Away":100,"Home":100,"Line":55,
             "Pick":65,"Conf":45,"Result":65,"Actual":60,"Notes":200}
for col in PK_COLS:
    pk_tree.heading(col, text=col)
    pk_tree.column(col, width=PK_WIDTHS[col], anchor="center", minwidth=40)
pk_tree.tag_configure("win",  background=_UI["state_ready"], foreground=_UI["success"])
pk_tree.tag_configure("loss", background=_UI["state_blocked"], foreground=_UI["danger"])
pk_tree.tag_configure("push", background=_UI["state_partial"], foreground=_UI["warning"])
pk_tree.tag_configure("pend", background=_UI["state_nogames"], foreground=_UI["text_muted"])
pk_tree_scroll = ttk.Scrollbar(pk_hist_frame, orient=tk.VERTICAL, command=pk_tree.yview)
pk_tree.configure(yscrollcommand=pk_tree_scroll.set)
pk_tree.grid(row=0, column=0, sticky="nsew")
pk_tree_scroll.grid(row=0, column=1, sticky="ns")

# â”€â”€ Enter result bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
pk_res_frame = ttk.LabelFrame(picks_frame, text="Result Reconciliation", padding=8, style="Card.TLabelframe")
pk_res_frame.pack(fill=tk.X, **pad)

# Auto-grade button â€” hits ESPN API directly for final scores
ttk.Button(pk_res_frame, text="Auto-Reconcile (ESPN API)",
           command=lambda: threading.Thread(target=_pk_auto_grade, daemon=True).start()
).grid(row=0, column=5, padx=6)

ttk.Label(pk_res_frame, text="Actual Total:").grid(row=0, column=0, sticky="e", **pad)
pk_actual_var = tk.StringVar()
ttk.Entry(pk_res_frame, textvariable=pk_actual_var, width=8).grid(row=0, column=1, sticky="w", **pad)

ttk.Label(pk_res_frame, text="  Result:").grid(row=0, column=2, sticky="e", **pad)
pk_result_var = tk.StringVar(value="WIN")
ttk.Combobox(pk_res_frame, textvariable=pk_result_var,
             values=["WIN","LOSS","PUSH"], width=8,
             state="readonly").grid(row=0, column=3, sticky="w", **pad)
ttk.Button(pk_res_frame, text="Save Reconciled Result",
           command=lambda: _pk_save_result()).grid(row=0, column=4, **pad)

# â”€â”€ Dual Accuracy Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ACCURACY NOTEBOOK â€” Your Picks sub-tab | Model Picks sub-tab
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
pk_acc_nb = ttk.Notebook(picks_frame)
pk_acc_nb.pack(fill=tk.BOTH, expand=True, **pad)

# Keep StringVars for backward-compat with _pk_update_dual_accuracy
pk_acc_var  = tk.StringVar(value="No completed picks yet.")
pk_macc_var = tk.StringVar(value="No model picks graded yet.")

# â”€â”€â”€ YOUR PICKS tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_yt = ttk.Frame(pk_acc_nb)
pk_acc_nb.add(_yt, text="  Your Picks  ")
_yt_top = ttk.Frame(_yt)
_yt_top.pack(fill=tk.X, padx=6, pady=(4,2))
_yh_acc_lbl = ttk.Label(
    _yt_top,
    textvariable=pk_acc_var,
    font=("Consolas", 9),
    foreground=_UI["success"],
)
_yh_acc_lbl.pack(side=tk.LEFT)
ttk.Button(_yt_top, text="Reset Analyst Record",
           command=lambda: _reset_picks("yours")).pack(side=tk.RIGHT, padx=4)
ttk.Button(_yt_top, text="Normalize League Tags",
           command=lambda: threading.Thread(target=_repair_leagues,daemon=True).start()
           ).pack(side=tk.RIGHT, padx=4)
_yh_cols = ("Date","Time","Sport","Away","Home","O/U","Pick","Conf","Result","Actual","Margin","Notes")
_yh_frm  = ttk.Frame(_yt)
_yh_frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
_yh_tree = ttk.Treeview(_yh_frm, columns=_yh_cols, show="headings", height=9)
_yh_sby  = ttk.Scrollbar(_yh_frm, orient=tk.VERTICAL,   command=_yh_tree.yview)
_yh_sbx  = ttk.Scrollbar(_yh_frm, orient=tk.HORIZONTAL, command=_yh_tree.xview)
_yh_tree.configure(yscrollcommand=_yh_sby.set, xscrollcommand=_yh_sbx.set)
_yh_cw   = {"Date":90,"Time":100,"Sport":52,"Away":115,"Home":115,"O/U":55,
             "Pick":58,"Conf":45,"Result":62,"Actual":58,"Margin":70,"Notes":200}
for _c in _yh_cols:
    _yh_tree.heading(_c, text=_c)
    _yh_tree.column(_c, width=_yh_cw.get(_c,80), anchor="w")
_yh_tree.tag_configure("win",  background=_UI["state_ready"], foreground=_UI["success"])
_yh_tree.tag_configure("loss", background=_UI["state_blocked"], foreground=_UI["danger"])
_yh_tree.tag_configure("push", background=_UI["state_partial"], foreground=_UI["warning"])
_yh_tree.tag_configure("pend", background=_UI["state_nogames"], foreground=_UI["text_muted"])
_yh_sby.pack(side=tk.RIGHT,  fill=tk.Y)
_yh_sbx.pack(side=tk.BOTTOM, fill=tk.X)
_yh_tree.pack(fill=tk.BOTH,  expand=True)

# â”€â”€â”€ MODEL PICKS tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_mt = ttk.Frame(pk_acc_nb)
pk_acc_nb.add(_mt, text="  Model Record  ")
_mt_top = ttk.Frame(_mt)
_mt_top.pack(fill=tk.X, padx=6, pady=(4,2))
_mh_acc_lbl = ttk.Label(
    _mt_top,
    textvariable=pk_macc_var,
    font=("Consolas", 9),
    foreground=_UI["accent"],
)
_mh_acc_lbl.pack(side=tk.LEFT)
ttk.Button(_mt_top, text="Reset Model Record",
           command=lambda: _reset_picks("model")).pack(side=tk.RIGHT, padx=4)
_mh_cols = ("Date","Time","Sport","Away","Home","O/U","Lean","Conf","Result","Actual","Margin","Key Factors")
_mh_frm  = ttk.Frame(_mt)
_mh_frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
_mh_tree = ttk.Treeview(_mh_frm, columns=_mh_cols, show="headings", height=9)
_mh_sby  = ttk.Scrollbar(_mh_frm, orient=tk.VERTICAL,   command=_mh_tree.yview)
_mh_sbx  = ttk.Scrollbar(_mh_frm, orient=tk.HORIZONTAL, command=_mh_tree.xview)
_mh_tree.configure(yscrollcommand=_mh_sby.set, xscrollcommand=_mh_sbx.set)
_mh_cw   = {"Date":90,"Time":100,"Sport":52,"Away":115,"Home":115,"O/U":55,
             "Lean":58,"Conf":45,"Result":62,"Actual":58,"Margin":70,"Key Factors":340}
for _c in _mh_cols:
    _mh_tree.heading(_c, text=_c)
    _mh_tree.column(_c, width=_mh_cw.get(_c,80), anchor="w")
_mh_tree.tag_configure("win",  background=_UI["state_ready"], foreground=_UI["success"])
_mh_tree.tag_configure("loss", background=_UI["state_blocked"], foreground=_UI["danger"])
_mh_tree.tag_configure("push", background=_UI["state_partial"], foreground=_UI["warning"])
_mh_tree.tag_configure("pend", background=_UI["state_nogames"], foreground=_UI["text_muted"])
_mh_sby.pack(side=tk.RIGHT,  fill=tk.Y)
_mh_sbx.pack(side=tk.BOTTOM, fill=tk.X)
_mh_tree.pack(fill=tk.BOTH,  expand=True)


# â”€â”€ History + Reset + League-repair functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _margin_str(result, actual, line):
    try:
        m = round(float(actual) - float(line), 1)
        if result in ("WIN","LOSS","PUSH"):
            sign = "+" if m >= 0 else ""
            return f"{sign}{m}"
    except Exception: pass
    return "â€”"

def _yh_load():
    _yh_tree.delete(*_yh_tree.get_children())
    try:
        con = _sqlite3.connect(PICKS_DB)
        rows = con.execute("""SELECT game_date,game_time,league,away_team,home_team,
                               ou_line,pick,confidence,pick_result,actual_total,notes
                               FROM picks ORDER BY id DESC LIMIT 300""").fetchall()
        con.close()
    except Exception: return
    for r in rows:
        gdate,gtime,lg,away,home,line,pick,conf,result,actual,notes = r
        result = result or "PENDING"
        tag    = {"WIN":"win","LOSS":"loss","PUSH":"push"}.get(result,"pend")
        margin = _margin_str(result,actual,line) if result in ("WIN","LOSS","PUSH") else "â€”"
        _yh_tree.insert("","end",tags=(tag,),values=(
            gdate or "",gtime or "",lg or "",away or "",home or "",
            f"{line:.1f}" if line else "â€”",pick or "â€”",str(conf) if conf else "â€”",
            result,f"{actual:.1f}" if actual else "â€”",margin,notes or ""))

def _mh_load():
    _mh_tree.delete(*_mh_tree.get_children())
    try:
        con = _sqlite3.connect(PICKS_DB)
        rows = con.execute("""SELECT game_date,game_time,league,away_team,home_team,
                               ou_line,pick,confidence,pick_result,actual_total,key_factors
                               FROM model_picks ORDER BY id DESC LIMIT 300""").fetchall()
        con.close()
    except Exception: return
    for r in rows:
        gdate,gtime,lg,away,home,line,pick,conf,result,actual,factors = r
        result = result or "PENDING"
        tag    = {"WIN":"win","LOSS":"loss","PUSH":"push"}.get(result,"pend")
        margin = _margin_str(result,actual,line) if result in ("WIN","LOSS","PUSH") else "â€”"
        _mh_tree.insert("","end",tags=(tag,),values=(
            gdate or "",gtime or "",lg or "",away or "",home or "",
            f"{line:.1f}" if line else "â€”",pick or "â€”",conf or "â€”",
            result,f"{actual:.1f}" if actual else "â€”",margin,factors or ""))

def _mph_load(): _mh_load()  # backward-compat alias

def _all_history_load():
    _yh_load(); _mh_load()

root.after(700, _all_history_load)

def _reset_picks(which):
    import tkinter.messagebox as _mb
    label = "YOUR" if which == "yours" else "MODEL"
    table = "picks" if which == "yours" else "model_picks"
    if not _mb.askyesno("Reset W/L Ticker",
        f"PERMANENTLY delete ALL {label} picks->\n\n"
        f"Table: {table}\nThis cannot be undone.\n"
        f"Type of reset: {which.upper()}", icon="warning"): return
    try:
        con = _sqlite3.connect(PICKS_DB)
        con.execute(f"DELETE FROM {table}")
        con.commit(); con.close()
        log(f"[reset] {label} picks cleared.", "info")
    except Exception as _re: log(f"[reset] {_re}", "warning"); return
    root.after(0, _pk_load_history)
    root.after(0, _all_history_load)
    root.after(0, _pk_update_dual_accuracy)

_MLB_NICKNAMES = {"yankees","red sox","cubs","mets","dodgers","giants","astros","braves",
    "nationals","cardinals","padres","phillies","brewers","athletics","tigers","guardians",
    "mariners","angels","rangers","royals","twins","white sox","orioles","rays","blue jays",
    "rockies","diamondbacks","marlins","pirates","reds"}
_NBA_NICKNAMES = {"lakers","celtics","bulls","heat","knicks","warriors","nets","bucks",
    "suns","clippers","nuggets","jazz","pelicans","hawks","76ers","raptors","hornets",
    "pacers","pistons","cavaliers","magic","wizards","spurs","thunder","blazers",
    "timberwolves","grizzlies","rockets","mavericks"}
def _repair_leagues():
    try:
        con = _sqlite3.connect(PICKS_DB)
        rows = con.execute("SELECT id,away_team,home_team,league FROM picks").fetchall()
        fixed = 0
        for rid,away,home,lg in rows:
            teams_lower = " ".join([str(away or ""),str(home or "")]).lower()
            detected = None
            if any(t in teams_lower for t in _MLB_NICKNAMES): detected = "MLB"
            elif any(t in teams_lower for t in _NBA_NICKNAMES): detected = "NBA"
            if detected and detected != (lg or "").upper():
                con.execute("UPDATE picks SET league=? WHERE id=?", (detected, rid))
                fixed += 1
        con.commit(); con.close()
        log(f"[repair] Fixed league on {fixed} picks.", "info")
        root.after(0, _pk_load_history)
        root.after(0, _all_history_load)
        root.after(0, _pk_update_dual_accuracy)
        _pk_set_status(f"[repair] Done â€” fixed {fixed} league tag(s).")
    except Exception as _e: log(f"[repair] {_e}", "warning")


# â”€â”€ Picks logic functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _pk_load_games_for_sport():
    """Load games for the Pick Tracker league dropdown.
    Priority: today's odds file â†’ ESPN scoreboard API live.
    Never silently falls back to stale local files.
    """
    sport = pk_sport_var.get().upper()
    _pk_set_status(f"Loading {sport} games...")
    today_str = datetime.now().strftime("%Y%m%d")
    found_df  = None

    # 1. Today's odds file
    _today_file = os.path.join(ODDS_DIR, f"Odds_{sport}_{today_str}.xlsx")
    if os.path.exists(_today_file):
        try:
            found_df = pd.read_excel(_today_file)
            _pk_set_status(f"Loaded from {os.path.basename(_today_file)}")
        except Exception:
            found_df = None

    # 2. ESPN scoreboard API fallback (covers NCAAB tournament + any sport)
    if found_df is None or found_df.empty:
        try:
            import urllib.request as _ur, json as _j
            sp_map = {"MLB":("baseball","mlb","limit=300"),
                      "NBA":("basketball","nba","limit=200"),
                      "NHL":("hockey","nhl","limit=200"),
                      "NFL":("football","nfl","limit=200"),
                      "NCAAB":("basketball","mens-college-basketball","limit=500&groups=50"),
                      "NCAAF":("football","college-football","limit=500")}
            if sport in sp_map:
                sp,lg,params = sp_map[sport]
                url = (f"https://site.api.espn.com/apis/site/v2/sports/{sp}/{lg}/scoreboard"
                       f"?dates={today_str}&{params}")
                with _ur.urlopen(url, timeout=10) as r:
                    data = _j.loads(r.read())
                rows = []
                for ev in data.get("events",[]):
                    comp = (ev.get("competitions") or [{}])[0]
                    ea=eh=""
                    for c in comp.get("competitors",[]):
                        nm=c.get("team",{}).get("displayName","")
                        if c.get("homeAway")=="away": ea=nm
                        else: eh=nm
                    gt = ev.get("date","")
                    try:
                        from datetime import datetime as _dt3
                        gt = _dt3.strptime(gt, "%Y-%m-%dT%H:%MZ").strftime("%-m/%-d %-I:%M%p")
                    except Exception: pass
                    # Try to get O/U from odds
                    ou = ""
                    for odd in comp.get("odds",[]):
                        if odd.get("overUnder"): ou = str(odd["overUnder"]); break
                    rows.append({"Time":gt,"Away_Team":ea,"Home_Team":eh,
                                 "Total":ou,"Away_Spread":"","Home_Spread":"",
                                 "Away_ML":"","Home_ML":""})
                if rows:
                    found_df = pd.DataFrame(rows)
                    _pk_set_status(f"âœ… {len(rows)} {sport} games from ESPN API")
        except Exception as ex:
            log(f"ESPN game load failed for {sport}: {ex}", "warning")

    if found_df is None or found_df.empty:
        _pk_set_status(f"No {sport} games found. Fetch matchups first.")
        return

    games = []
    for _, row in found_df.iterrows():
        t = str(row.get("Time","") or "")
        a = _strip_pitcher(str(row.get("Away_Team","") or ""))
        h = _strip_pitcher(str(row.get("Home_Team","") or ""))
        if a and h:
            games.append(f"{t}  {a} @ {h}")

    if games:
        _pk_autofill._last_df = found_df
        root.after(0, lambda: pk_game_cb.configure(values=games))
        root.after(0, lambda: pk_game_cb.current(0))
        root.after(0, _pk_autofill)
        _pk_set_status(f"âœ… {len(games)} {sport} games loaded.")
    else:
        _pk_set_status(f"No valid games found for {sport}.")


def _pk_refresh_games():
    """Populate the game selector from today's loaded matchup data."""
    if data_df is None or data_df.empty:
        _pk_set_status("âš  No matchup data â€” fetch matchups first.")
        return
    games = []
    for _, row in data_df.iterrows():
        t = str(row.get("Time","") or "")
        a = _strip_pitcher(str(row.get("Away_Team","") or ""))
        h = _strip_pitcher(str(row.get("Home_Team","") or ""))
        games.append(f"{t}  {a} @ {h}")
    pk_game_cb["values"] = games
    if games:
        pk_game_cb.current(0)
        _pk_autofill()
    _pk_set_status(f"âœ… {len(games)} games loaded.")

def _pk_autofill(event=None):
    """Auto-fill O/U line and pick lean from selected game."""
    sel = pk_game_var.get()
    if not sel or sel == "â€” select game â€”": return
    _df = getattr(_pk_autofill, "_last_df", None)
    if _df is None or _df.empty: _df = _current_matchups_df
    if _df is None or _df.empty:
        try:
            _sp = pk_sport_var.get().upper()
            _today = datetime.now().strftime("%Y%m%d")
            _today_file = os.path.join(ODDS_DIR, f"Odds_{_sp}_{_today}.xlsx")
            if os.path.exists(_today_file):
                _df = pd.read_excel(_today_file)
                _pk_autofill._last_df = _df
        except Exception:
            pass
    if _df is None or _df.empty: return
    for _, row in _df.iterrows():
        try:
            t=str(row.get("Time","") or ""); a=_strip_pitcher(str(row.get("Away_Team","") or "")); h=_strip_pitcher(str(row.get("Home_Team","") or ""))
            if f"{t}  {a} @ {h}".strip() != sel.strip(): continue
            for col in ["Total","OU_Line","ou_line","total","O/U","ou","OU"]:
                val=str(row.get(col,"") or "").replace("o","").replace("u","").replace("O","").replace("U","").strip()
                if val and val.lower() not in ("","nan","none"):
                    pk_line_var.set(val)
                    break
            try:
                g = _rpt_build_game_block(row, pk_sport_var.get().upper())
                lean = g.get("ou_lean","NEUTRAL").upper()
                if lean in ("OVER","UNDER","NEUTRAL"):
                    pk_pick_var.set(lean)
            except Exception: pass
            break
        except Exception: continue


def _pk_log_pick():
    sel = pk_game_var.get()
    if not sel or sel == "â€” select game â€”":
        _pk_set_status("âš  Select a game first.")
        return
    # Parse game identifier from selection string
    parts = sel.strip().split("  ", 1)
    game_time_str = parts[0] if parts else ""
    matchup_str   = parts[1] if len(parts)>1 else sel
    teams = matchup_str.split(" @ ")
    away = teams[0].strip() if teams else ""
    home = teams[1].strip() if len(teams)>1 else ""

    # Fetch physics context for the row
    row_data = {}
    if data_df is not None:
        for _, row in data_df.iterrows():
            t = str(row.get("Time","") or "")
            a = _strip_pitcher(str(row.get("Away_Team","") or ""))
            h = _strip_pitcher(str(row.get("Home_Team","") or ""))
            if f"{t}  {a} @ {h}" == sel:
                row_data = _rpt_build_game_block(row, pk_sport_var.get().upper())
                break

    try:
        line_val = float(pk_line_var.get()) if pk_line_var.get() else None
    except ValueError:
        line_val = None

    con = _sqlite3.connect(PICKS_DB)
    con.execute("""INSERT INTO picks
        (logged_at,game_date,game_time,league,away_team,home_team,
         ou_line,pick,confidence,home_starter,away_starter,
         air_dens_pct,headwind_mph,elev_delta_ft,ou_lean_factors,
         actual_total,pick_result,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(),
         str(datetime.now().date()),
         game_time_str,
         pk_sport_var.get(),   # fixed: was rpt_league_var (wrong tab variable)
         away, home,
         line_val,
         pk_pick_var.get(),
         int(pk_conf_var.get()),
         row_data.get("home_starter",""),
         row_data.get("away_starter",""),
         row_data.get("rho_pct_home"),
         row_data.get("headwind"),
         row_data.get("elev_delta"),
         str({"ou_lean": row_data.get("ou_lean"), "rho":row_data.get("air_density"),
              "hw":row_data.get("headwind"), "dalt":row_data.get("density_alt")}),
         None, "PENDING",
         pk_notes_var.get()))
    con.commit()
    con.close()
    pk_notes_var.set("")
    _pk_set_status(f"âœ… Logged: {away} @ {home}  {pk_pick_var.get()}  {line_val}")
    _pk_load_history()


def _pk_auto_grade():
    """Auto-grade PENDING picks by querying ESPN API directly for final scores.
    Uses same API as daily_scores_espn_api_final.py â€” no external files needed.
    """
    import urllib.request as _ur, json as _j

    _pk_set_status("â³ Fetching final scores from ESPN API...")

    SPORT_MAP = {
        "MLB":   ("baseball",  "mlb",                        "limit=300"),
        "NBA":   ("basketball","nba",                        "limit=300"),
        "NHL":   ("hockey",    "nhl",                        "limit=300"),
        "NFL":   ("football",  "nfl",                        "limit=300"),
        "NCAAB": ("basketball","mens-college-basketball",    "limit=500&groups=50"),
        "NCAAF": ("football",  "college-football",           "limit=500"),
    }

    def _nm(n1, n2):
        n1 = n1.lower().strip(); n2 = n2.lower().strip()
        return (n1 in n2 or n2 in n1 or
                n1.split()[-1] == n2.split()[-1] or
                n1.split()[0]  == n2.split()[0])

    # Get all PENDING picks + unique dates
    con = _sqlite3.connect(PICKS_DB)
    pending = con.execute(
        "SELECT id, game_date, league, away_team, home_team, ou_line, pick "
        "FROM picks WHERE pick_result='PENDING'"
    ).fetchall()
    con.close()

    if not pending:
        _pk_set_status("âœ… No pending picks to grade.")
        return

    # Build set of (date_str, league) combos â€” always query ALL leagues
    # so wrong-league picks still match (fixes rpt_league_var bug)
    from datetime import timedelta as _td
    needed = set()
    dates_seen = set()
    for _, gdate, league, *_ in pending:
        if gdate:
            ds = gdate.replace("-","")[:8]
            dates_seen.add(ds)
            needed.add((ds, str(league).upper()))  # stored league
    # Also add all leagues for each date so wrong-stored league still resolves
    for ds in list(dates_seen):
        for lg in SPORT_MAP:
            needed.add((ds, lg))
    # If nothing has a date, try yesterday + today for all leagues
    if not dates_seen:
        for d in [datetime.now(), datetime.now() - _td(1)]:
            for lg in SPORT_MAP:
                needed.add((d.strftime("%Y%m%d"), lg))

    # Fetch final scores from ESPN
    score_lookup = {}   # key=(away_lower, home_lower) â†’ {total, away_score, home_score}
    fetched = 0
    for (ds, lg) in needed:
        if lg not in SPORT_MAP: continue
        sp, league_slug, params = SPORT_MAP[lg]
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{sp}/{league_slug}/scoreboard"
               f"?dates={ds}&{params}")
        try:
            import time as _t; _t.sleep(0.3)
            with _ur.urlopen(url, timeout=12) as r:
                data = _j.loads(r.read())
            for ev in data.get("events", []):
                status = ev.get("status", {}).get("type", {}).get("description", "")
                if "Final" not in status:
                    continue  # only grade completed games
                comp = (ev.get("competitions") or [{}])[0]
                ea = eh = ""; as_ = hs = 0
                for c in comp.get("competitors", []):
                    nm = c.get("team", {}).get("displayName", "")
                    try: sc = float(c.get("score", 0) or 0)
                    except: sc = 0
                    if c.get("homeAway") == "away": ea = nm; as_ = sc
                    else:                           eh = nm; hs  = sc
                if ea and eh:
                    score_lookup[(ea.lower(), eh.lower())] = {
                        "away_score": as_, "home_score": hs,
                        "total": as_ + hs, "away": ea, "home": eh, "league": lg
                    }
                    fetched += 1
        except Exception as ex:
            log(f"ESPN score fetch failed {lg} {ds}: {ex}", "warning")

    log(f"[grade] ESPN score_lookup: {list(score_lookup.keys())[:10]}", "info")
    if not score_lookup:
        _pk_set_status("[WARN] No final scores found yet â€” games may still be in progress.")
        return

    # Grade pending picks
    con  = _sqlite3.connect(PICKS_DB)
    graded = 0
    no_match = 0
    for (row_id, gdate, league, away, home, ou_line, pick) in pending:
        # Fuzzy match against score_lookup
        matched = None
        for (k_away, k_home), sdata in score_lookup.items():
            if _nm(str(away), k_away) and _nm(str(home), k_home):
                matched = sdata; break
        if matched is None:
            no_match += 1
            continue

        actual = matched["total"]
        away_s = matched["away_score"]
        home_s = matched["home_score"]

        if ou_line is None:
            result = "PENDING"
        elif abs(actual - float(ou_line)) < 0.05:
            result = "PUSH"
        elif pick == "OVER":
            result = "WIN" if actual > float(ou_line) else "LOSS"
        elif pick == "UNDER":
            result = "WIN" if actual < float(ou_line) else "LOSS"
        else:
            result = "PENDING"

        if result != "PENDING":
            con.execute(
                "UPDATE picks SET actual_total=?, pick_result=? WHERE id=?",
                (actual, result, row_id))
            graded += 1

    con.commit(); con.close()

    msg = (f"âœ… Auto-graded {graded}/{len(pending)} pick(s). "
           f"Scores pulled from ESPN API ({fetched} finals found).")
    if no_match:
        msg += f" {no_match} pick(s) â€” score not found (may be postponed or no line match)."
    _pk_set_status(msg)
    log(msg, "info")
    try: _tune_model_weights()
    except Exception: pass
    root.after(0, _pk_load_history)  # refresh treeview
    root.after(200, _pk_update_dual_accuracy)  # update scoreboard after treeview reloads

    # â”€â”€ Also grade model_picks with the same scores â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    m_graded = 0
    try:
        con_m = _sqlite3.connect(PICKS_DB)
        m_pending = con_m.execute(
            "SELECT id, away_team, home_team, ou_line, pick "
            "FROM model_picks WHERE pick_result='PENDING'"
        ).fetchall()
        for (rid, away, home, ou_line, pick) in m_pending:
            matched = None
            for (k_away, k_home), sdata in score_lookup.items():
                if _nm(str(away), k_away) and _nm(str(home), k_home):
                    matched = sdata; break
            if not matched or ou_line is None: continue
            actual = matched["total"]
            if abs(actual - float(ou_line)) < 0.05:   result = "PUSH"
            elif pick == "OVER":  result = "WIN" if actual > float(ou_line) else "LOSS"
            elif pick == "UNDER": result = "WIN" if actual < float(ou_line) else "LOSS"
            else: continue
            con_m.execute("UPDATE model_picks SET actual_total=?, pick_result=? WHERE id=?",
                          (actual, result, rid))
            m_graded += 1
        con_m.commit(); con_m.close()
    except Exception as _em: log(f"model_picks grading: {_em}", "warning")

    root.after(0, _pk_update_dual_accuracy)


def _pk_update_dual_accuracy():
    """Update both accuracy panels â€” YOUR picks and MODEL picks."""
    def _stats(rows):
        w=l=p=0
        for r in rows:
            if r=="WIN": w+=1
            elif r=="LOSS": l+=1
            elif r=="PUSH": p+=1
        tot = w+l+p
        pct = round(w/max(tot-p,1)*100,1) if tot>0 else 0.0
        return w, l, p, tot, pct
    try:
        con = _sqlite3.connect(PICKS_DB)
        # Your picks
        your_results = [r[0] for r in con.execute(
            "SELECT pick_result FROM picks WHERE pick_result IN ('WIN','LOSS','PUSH')").fetchall()]
        yw,yl,yp,yt,ypct = _stats(your_results)
        # Model picks
        mod_results = [r[0] for r in con.execute(
            "SELECT pick_result FROM model_picks WHERE pick_result IN ('WIN','LOSS','PUSH')").fetchall()]
        mw,ml,mp,mt,mpct = _stats(mod_results)
        con.close()
    except Exception as _e:
        pk_acc_var.set(f"DB error: {_e}"); return
    # â”€â”€ YOUR PICKS panel â”€â”€
    if yt == 0:
        pk_acc_var.set("No completed picks yet.")
    else:
        # Sport-by-sport
        try:
            con2 = _sqlite3.connect(PICKS_DB)
            by_lg = {}
            for lg, res in con2.execute(
                "SELECT league, pick_result FROM picks "
                "WHERE pick_result IN ('WIN','LOSS','PUSH')").fetchall():
                by_lg.setdefault(lg,[]).append(res)
            con2.close()
        except: by_lg = {}
        lines = [f"Overall: {yw}-{yl}-{yp}  ({ypct}% win rate)"]
        for lg in sorted(by_lg):
            lr = by_lg[lg]; lw=lr.count("WIN"); ll=lr.count("LOSS"); lp=lr.count("PUSH")
            lt = lw+ll+lp; lpct = round(lw/max(lt-lp,1)*100,1)
            be = "âœ…" if lpct > 52.4 else "âŒ"
            lines.append(f"  {lg:7s} {lw}-{ll}-{lp}  ({lpct}%) {be}")
        pk_acc_var.set("\n".join(lines))
    # â”€â”€ MODEL PICKS panel â”€â”€
    if mt == 0:
        pk_macc_var.set("No model picks graded yet.")
    else:
        try:
            con3 = _sqlite3.connect(PICKS_DB)
            by_mlg = {}
            for lg, res in con3.execute(
                "SELECT league, pick_result FROM model_picks "
                "WHERE pick_result IN ('WIN','LOSS','PUSH')").fetchall():
                by_mlg.setdefault(lg,[]).append(res)
            con3.close()
        except: by_mlg = {}
        be_overall = "âœ… ABOVE" if mpct > 52.4 else "âŒ BELOW"
        mlines = [f"Overall: {mw}-{ml}-{mp}  ({mpct}%)  {be_overall} break-even"]
        for lg in sorted(by_mlg):
            mr = by_mlg[lg]; mwl=mr.count("WIN"); mll=mr.count("LOSS"); mpl=mr.count("PUSH")
            mtl = mwl+mll+mpl; mpctlg = round(mwl/max(mtl-mpl,1)*100,1)
            be2 = "âœ…" if mpctlg > 52.4 else "âŒ"
            mlines.append(f"  {lg:7s} {mwl}-{mll}-{mpl}  ({mpctlg}%) {be2}")
        pk_macc_var.set("\n".join(mlines))


def _pk_load_history():
    """Reload pick history from DB into the treeview."""
    pk_tree.delete(*pk_tree.get_children())
    try:
        con = _sqlite3.connect(PICKS_DB)
        rows = con.execute("""SELECT id, game_date, game_time, away_team, home_team,
                               ou_line, pick, confidence, pick_result, actual_total, notes
                               FROM picks ORDER BY id DESC LIMIT 200""").fetchall()
        con.close()
    except Exception:
        return
    for r in rows:
        row_id, gdate, gtime, away, home, line, pick, conf, result, actual, notes = r
        result = result or "PENDING"
        tag = {"WIN":"win","LOSS":"loss","PUSH":"push"}.get(result,"pend")
        pk_tree.insert("","end", iid=str(row_id), tags=(tag,), values=(
            gdate, gtime, away, home,
            f"{line:.1f}" if line else "â€”",
            pick or "â€”",
            str(conf) if conf else "â€”",
            result,
            f"{actual:.1f}" if actual else "â€”",
            notes or ""))
    _pk_update_accuracy()
    try: root.after(0, _all_history_load)
    except Exception: pass

def _pk_save_result():
    sel = pk_tree.focus()
    if not sel:
        _pk_set_status("âš  Select a pick in the history grid first.")
        return
    try:
        actual_val = float(pk_actual_var.get()) if pk_actual_var.get() else None
    except ValueError:
        actual_val = None
    result_val = pk_result_var.get()
    con = _sqlite3.connect(PICKS_DB)
    con.execute("UPDATE picks SET actual_total=?, pick_result=? WHERE id=?",
                (actual_val, result_val, int(sel)))
    con.commit()
    con.close()
    _pk_set_status(f"âœ… Result saved: {result_val}  (actual {actual_val})")
    _pk_load_history()

def _pk_update_accuracy():
    """Compute rolling accuracy and factor breakdown, show in summary bar."""
    try:
        con = _sqlite3.connect(PICKS_DB)
        rows = con.execute("""SELECT pick, pick_result, air_dens_pct, headwind_mph,
                               elev_delta_ft, confidence
                               FROM picks WHERE pick_result IN ('WIN','LOSS','PUSH')""").fetchall()
        con.close()
    except Exception:
        return
    if not rows:
        pk_acc_var.set("No completed picks yet.")
        return

    total = len(rows)
    wins  = sum(1 for r in rows if r[1]=="WIN")
    losses= sum(1 for r in rows if r[1]=="LOSS")
    pushes= sum(1 for r in rows if r[1]=="PUSH")
    pct   = wins/(wins+losses)*100 if (wins+losses)>0 else 0

    # Factor breakdown: when dense air was a factor (rho_pct > 1.5), did UNDER win->
    dense_under = [r for r in rows if r[0]=="UNDER" and r[2] and r[2]>1.5]
    dense_under_w = sum(1 for r in dense_under if r[1]=="WIN")
    dense_pct = dense_under_w/len(dense_under)*100 if dense_under else None

    hw_under = [r for r in rows if r[0]=="UNDER" and r[3] and r[3]<-4]
    hw_under_w = sum(1 for r in hw_under if r[1]=="WIN")
    hw_pct = hw_under_w/len(hw_under)*100 if hw_under else None

    # Per-sport breakdown
    try:
        sport_con = _sqlite3.connect(PICKS_DB)
        sport_rows = sport_con.execute(
            "SELECT league, pick_result FROM picks WHERE pick_result IN ('WIN','LOSS','PUSH')"
        ).fetchall()
        sport_con.close()
    except Exception:
        sport_rows = []

    sport_records = {}
    for lg, res in sport_rows:
        if not lg: lg = "->"  
        r = sport_records.setdefault(lg, {"W":0,"L":0,"P":0})
        if res=="WIN": r["W"]+=1
        elif res=="LOSS": r["L"]+=1
        elif res=="PUSH": r["P"]+=1

    parts = [f"YOUR PICKS â€” Overall: {wins}W-{losses}L-{pushes}P  ({pct:.1f}%)"]
    if dense_pct is not None:
        parts.append(f"  Dense airâ†’UNDER: {dense_under_w}/{len(dense_under)} ({dense_pct:.0f}%)")
    if hw_pct is not None:
        parts.append(f"  Headwindâ†’UNDER: {hw_under_w}/{len(hw_under)} ({hw_pct:.0f}%)")
    if sport_records:
        sport_str = "  |  By Sport: " + "  ".join(
            f"{lg}: {r['W']}W-{r['L']}L" for lg,r in sorted(sport_records.items()))
        parts.append(sport_str)

    pk_acc_var.set("  ".join(parts))


# Load history on startup + auto-repair leagues + repopulate model picks
root.after(500, _pk_load_history)
root.after(1200, _repair_leagues)
root.after(2000, lambda: _launch_tpk_refresh_async())


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADAPTIVE MODEL WEIGHT TUNING
# Analyzes graded picks to find which physics factors predict outcomes
# Saves weights to odds_data/model_weights.json â€” loaded at render time
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
import json as _mw_json

_MW_FILE      = os.path.join(ODDS_DIR, "model_weights.json")
_FACTOR_KEYS  = ["air_density", "headwind", "elevation", "temperature", "pressure"]
_SPORTS_LIST  = ["MLB", "NBA", "NHL", "NFL", "NCAAB", "NCAAF"]

def _load_model_weights():
    try:
        with open(_MW_FILE, encoding="utf-8") as f: return _mw_json.load(f)
    except Exception: return {}

def _save_model_weights(w):
    os.makedirs(ODDS_DIR, exist_ok=True)
    with open(_MW_FILE, "w", encoding="utf-8") as f: _mw_json.dump(w, f, indent=2)

def _tune_model_weights():
    """
    Real calibration â€” delegates to model_calibration.run_calibration().
    Reads game_context.db, runs per-league logistic regression,
    updates model_weights.json. Respects MIN_SAMPLES_TO_RETRAIN guard.
    """
    try:
        import importlib, sys as _sys
        _mcd = os.path.join(ODDS_DIR, "model_calibration.py")
        if os.path.exists(_mcd):
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("model_calibration", _mcd)
            _mc   = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mc)
            reports = _mc.run_calibration(verbose=False)
            if reports:
                summary = ", ".join(
                    f"{lg}: {r.get('status','->')} "
                    f"({r.get('acc_before',0):.0%}â†’{r.get('acc_after',0):.0%})"
                    for lg, r in reports.items()
                    if r.get("status") == "updated"
                )
                if summary:
                    log(f"Weights recalibrated â€” {summary}", "info")
    except Exception as _e:
        log(f"_tune_model_weights: {_e}", "warning")


def _on_matchup_league_change(event=None):
    matchup_tree.delete(*matchup_tree.get_children())
    _slate_set_detail_empty("No matchup selected")
    m_status_var.set("League changed - click Refresh Slate.")
    _set_matchup_load_progress(0.0, "waiting for fetch")
m_league_cb.bind("<<ComboboxSelected>>", _on_matchup_league_change)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB 6 â€” TODAY'S PICKS
# Auto-populated after every fetch. Shows model's environmental lean (OVER/UNDER/
# NEUTRAL) for every game across all loaded leagues. Exportable.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

picks_tab_frame = ttk.Frame(execution_nb)
execution_nb.add(picks_tab_frame, text="Model Picks")

# â”€â”€ Controls row â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_tpk_ctrl = ttk.Frame(picks_tab_frame)
_tpk_ctrl.pack(fill=tk.X, padx=8, pady=(6,2))

ttk.Label(_tpk_ctrl, text="Signal Board", font=("Segoe UI",10,"bold")).pack(side=tk.LEFT, padx=4)
ttk.Button(_tpk_ctrl, text="Refresh Board",
           command=lambda: _launch_tpk_refresh_async()
           ).pack(side=tk.LEFT, padx=4)
ttk.Button(_tpk_ctrl, text="Export Board CSV",
           command=lambda: _tpk_export_csv()
           ).pack(side=tk.LEFT, padx=4)
_tpk_status = tk.StringVar(value="Load slate data in the Slate tab, then refresh board.")
ttk.Label(_tpk_ctrl, textvariable=_tpk_status, style="Subtle.TLabel").pack(side=tk.LEFT, padx=8)

def _tpk_set_status(msg):
    root.after(0, lambda m=str(msg): _tpk_status.set(m))

# â”€â”€ Treeview â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_tpk_cols = ("Sport","Time","Away","Home","O/U","Lean","Confidence","Key Factors")
_tpk_tree_frame = ttk.Frame(picks_tab_frame)
_tpk_tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

_tpk_tree = ttk.Treeview(_tpk_tree_frame, columns=_tpk_cols, show="headings", height=22)
_tpk_sb_y = ttk.Scrollbar(_tpk_tree_frame, orient=tk.VERTICAL,   command=_tpk_tree.yview)
_tpk_sb_x = ttk.Scrollbar(_tpk_tree_frame, orient=tk.HORIZONTAL, command=_tpk_tree.xview)
_tpk_tree.configure(yscrollcommand=_tpk_sb_y.set, xscrollcommand=_tpk_sb_x.set)

_col_widths = {"Sport":55,"Time":110,"Away":150,"Home":150,
               "O/U":55,"Lean":80,"Confidence":90,"Key Factors":400}
for col in _tpk_cols:
    _tpk_tree.heading(col, text=col)
    _tpk_tree.column(col, width=_col_widths.get(col,100), anchor="w")

_tpk_tree.tag_configure("OVER",    background=_UI["state_ready"], foreground=_UI["success"])
_tpk_tree.tag_configure("UNDER",   background=_UI["state_partial"], foreground=_UI["accent"])
_tpk_tree.tag_configure("NEUTRAL", background=_UI["state_nogames"], foreground=_UI["text_muted"])
_tpk_tree.tag_configure("odd",     background=_UI["stripe_odd"])

_tpk_sb_y.pack(side=tk.RIGHT, fill=tk.Y)
_tpk_sb_x.pack(side=tk.BOTTOM, fill=tk.X)
_tpk_tree.pack(fill=tk.BOTH, expand=True)

# â”€â”€ Core logic â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _tpk_compute_lean(row, sport):
    """Compute OVER/UNDER/NEUTRAL lean from physics for one game row.
    Returns dict: {lean, confidence_txt, factors}
    """
    std_rho = 0.07647
    factors = []
    score   = 0.0

    try:
        import json as _j
        _mw_path = os.path.join(ODDS_DIR, "model_weights.json")
        try:
            with open(_mw_path) as _f: _mw = _j.load(_f)
        except Exception: _mw = {}
        def _w8(k): return float(_mw.get(sport,{}).get(k,1.0))
    except Exception:
        def _w8(k): return 1.0

    # â”€â”€ Air density from cached physics or re-compute â”€â”€
    rho = None
    for col in ["rho_home","air_density","rho"]:
        v = row.get(col, None)
        if v and str(v) not in ("","nan","None"):
            try: rho = float(v); break
            except Exception: pass

    if rho is None:
        # Re-compute from weather cols if available
        for t_col,p_col,h_col in [("temp_home","pressure_home","humidity_home"),
                                    ("Temp","Pressure","Humidity"),("temp","pressure","humidity")]:
            t = row.get(t_col); p = row.get(p_col); h = row.get(h_col)
            if all(v not in (None,"",float("nan")) for v in [t,p,h]):
                try:
                    rho = air_density(float(t), float(p), float(h))
                    break
                except Exception: pass

    if rho is not None:
        pct = ((rho - std_rho) / std_rho) * 100
        w   = _w8("air_density")
        if abs(pct) >= 0.5:
            score += -pct * w
            sign = "THINNER" if pct < 0 else "DENSER"
            factors.append(f"Air {sign} ({abs(pct):.1f}%)")

    # â”€â”€ Headwind â”€â”€
    head = None
    for col in ["headwind_home","headwind","head"]:
        v = row.get(col, None)
        if v not in (None,"",float("nan")):
            try: head = float(v); break
            except Exception: pass

    INDOOR = {"NBA","NCAAB","NHL"}
    is_ind = sport in INDOOR
    if head is not None and not is_ind:
        w = _w8("headwind")
        if abs(head) >= 2:
            score += head * w
            lbl = "HEADWIND" if head < 0 else "TAILWIND"
            factors.append(f"{abs(head):.1f} mph {lbl}")

    # â”€â”€ Elevation delta â”€â”€
    h_elev = row.get("home_elevation") or row.get("h_elev") or row.get("elevation_home") or row.get("_elev_ft")
    a_elev = row.get("away_elevation") or row.get("a_elev") or row.get("elevation_away")
    if h_elev and a_elev:
        try:
            delta = float(h_elev) - float(a_elev)
            w = _w8("elevation")
            if abs(delta) > 200:
                elev_effect = -delta / 1000 * w
                score += elev_effect
                factors.append(f"Elev ÃŽâ€ {delta:+.0f} ft")
        except Exception: pass

    # â€”â€” Reusable environment-load score (when upstream row has it) â€”â€”
    try:
        away_env_exec = row.get("away_env_exec", None)
        home_env_exec = row.get("home_env_exec", None)
        away_env_score = row.get("away_env_score", None)
        home_env_score = row.get("home_env_score", None)
        if away_env_exec not in (None, "", "None", "nan") and home_env_exec not in (None, "", "None", "nan"):
            away_env_exec = float(away_env_exec)
            home_env_exec = float(home_env_exec)
            env_total = away_env_exec + home_env_exec
            if env_total > 0:
                score += -env_total * 2.1 * _w8("env_load")
                factors.append(f"Env load total {env_total:.2f}")
        for key in ("away_env_notes", "home_env_notes"):
            txt = str(row.get(key, "") or "").strip()
            if txt:
                for part in [p.strip() for p in txt.split("|") if p.strip()]:
                    if part not in factors:
                        factors.append(part)
        if away_env_score not in (None, "", "None", "nan") and home_env_score not in (None, "", "None", "nan"):
            away_env_score = float(away_env_score)
            home_env_score = float(home_env_score)
            if abs(away_env_score - home_env_score) >= 2.4:
                factors.append(f"Env gap {away_env_score-home_env_score:+.1f}")
    except Exception:
        pass

    if sport == "MLB":
        try:
            ctx_total = row.get("mlb_context_total", None)
            if ctx_total not in (None, "", "None", "nan"):
                ctx_total = float(ctx_total)
                score += ctx_total * 2.25 * _w8("mlb_context")
                if abs(ctx_total) >= 0.20:
                    factors.append(
                        ("MLB ctx OVER" if ctx_total > 0 else "MLB ctx UNDER")
                        + f" ({ctx_total:+.2f})"
                    )
                ctx_facts = str(row.get("mlb_pick_factors", "") or "").strip()
                if ctx_facts:
                    for part in [p.strip() for p in ctx_facts.split("|") if p.strip()]:
                        if part not in factors:
                            factors.append(part)
        except Exception:
            pass

    # â”€â”€ Lean + confidence â”€â”€
    # Stats/SOS quant signal from startup scrapers (strictly data-driven)
    if STATS_SOS_AVAILABLE:
        try:
            _away_nm = str(
                row.get("_away_team_clean")
                or row.get("Away_Team")
                or row.get("away_team")
                or row.get("Away")
                or ""
            ).strip()
            _home_nm = str(
                row.get("_home_team_clean")
                or row.get("Home_Team")
                or row.get("home_team")
                or row.get("Home")
                or ""
            ).strip()
            _ou_line = row.get("Total") or row.get("OU_Line") or row.get("ou_line")
            if _away_nm and _home_nm:
                _ss_sig = _get_stats_sos_model_signal(sport, _away_nm, _home_nm, _ou_line)
                _ss_score = float(_ss_sig.get("score", 0.0) or 0.0) * _w8("stats_sos")
                if abs(_ss_score) >= 0.01:
                    score += _ss_score

                _cov = _ss_sig.get("coverage", None)
                if _cov not in (None, "", "nan"):
                    factors.append(f"Stats/SOS cov {float(_cov):.0%}")

                for _f in (_ss_sig.get("factors", []) or []):
                    _f = str(_f).strip()
                    if _f and _f not in factors:
                        factors.append(_f)
        except Exception:
            pass

    if abs(score) < 2:
        lean = "NEUTRAL"
        conf = "Low"
    elif abs(score) < 5:
        lean = "OVER" if score > 0 else "UNDER"
        conf = "Moderate"
    elif abs(score) < 9:
        lean = "OVER" if score > 0 else "UNDER"
        conf = "High"
    else:
        lean = "OVER" if score > 0 else "UNDER"
        conf = "Strong"

    _uniq_factors = []
    _seen_f = set()
    for _f in factors:
        _fs = str(_f).strip()
        if not _fs:
            continue
        _k = _fs.lower()
        if _k in _seen_f:
            continue
        _seen_f.add(_k)
        _uniq_factors.append(_fs)

    return {
        "lean": lean,
        "confidence": conf,
        "factors": " | ".join(_uniq_factors) if _uniq_factors else "Conditions near neutral",
    }

def _tpk_refresh():
    """Populate Today's Picks from data_df (has weather+physics) with ESPN fallback."""
    _tpk_set_status("Computing picks...")
    root.after(0, lambda: _tpk_tree.delete(*_tpk_tree.get_children()))

    today_str = datetime.now().strftime("%Y%m%d")
    rows_added = 0
    SPORTS = ["MLB","NBA","NHL","NFL","NCAAB","NCAAF"]

    # â”€â”€ Build unified source: loaded grid first, then explicit TODAY files only â”€â”€â”€â”€â”€â”€
    frames = []
    represented_sports = set()
    selected_sport = str(m_league_var.get() or "").upper().strip()

    # 1. data_df already has weather+physics cols from last matchup fetch
    try:
        _src_df = data_df if (data_df is not None and not data_df.empty) else None
    except Exception:
        _src_df = None
    if _src_df is None:
        try:
            _src_df = _current_matchups_df if (_current_matchups_df is not None and not _current_matchups_df.empty) else None
        except Exception:
            _src_df = None
    if _src_df is not None and not _src_df.empty:
        _loaded_sport = selected_sport if selected_sport in SPORTS else "MLB"
        frames.append((_loaded_sport, _src_df.copy()))
        represented_sports.add(_loaded_sport)

    # 2. Per-sport odds files as fallback (NO wildcard stale-file bleed)
    for sport in SPORTS:
        if sport in represented_sports:
            continue
        _today_file = os.path.join(ODDS_DIR, f"Odds_{sport}_{today_str}.xlsx")
        if not os.path.exists(_today_file):
            continue
        try:
            _df2 = pd.read_excel(_today_file)
            if not _df2.empty:
                _df2 = _df2.copy()
                _df2["_sport_hint"] = sport
                frames.append((sport, _df2))
                represented_sports.add(sport)
        except Exception:
            continue

    seen = set()
    for (fsport, df) in frames:
        for i, (_, row) in enumerate(df.iterrows()):
            try:
                a = _strip_pitcher(str(row.get("Away_Team","") or ""))
                h = _strip_pitcher(str(row.get("Home_Team","") or ""))
                if not a or not h or a == h: continue
                sport = str(row.get("_sport_hint","") or row.get("League","") or row.get("Sport","") or fsport or "").upper().strip()
                if sport not in SPORTS:
                    sport = fsport if fsport in SPORTS else (selected_sport if selected_sport in SPORTS else "MLB")
                t = str(row.get("Time","") or "")
                key = (sport, t.strip().lower(), a.lower(), h.lower())
                if key in seen: continue
                seen.add(key)
                # Skip games not from today (off-season file bleed)
                try:
                    _tnow = datetime.now()
                    _opts = {f"{_tnow.month}/{_tnow.day}",
                             f"{_tnow.month:02d}/{_tnow.day:02d}"}
                    _tp   = t.split()[0] if " " in t else ""
                    if _tp and "/" in _tp and _tp not in _opts: continue
                except Exception: pass
                ou_raw= str(row.get("Total","") or row.get("OU_Line","") or "")
                ou    = ou_raw.replace("o","").replace("u","").replace("O","").replace("U","").strip()

                row_d = dict(row)
                row_d["_away_team_clean"] = a
                row_d["_home_team_clean"] = h

                # If weather/physics missing from row, attempt live fetch for this game
                has_physics = any(str(row.get(c,"")) not in ("","nan","None")
                                  for c in ["rho_home","air_density","rho","temp","Temp","temp_home"])
                if not has_physics:
                    try:
                        home_db, _ = _find_team_fuzzy(h, preferred_league=sport)
                        home_vrow  = get_row(home_db, preferred_league=sport) if home_db else None
                        if home_vrow is not None:
                            _hlat = safe_float(safe(home_vrow,"lat"),  None, "lat")
                            _hlon = safe_float(safe(home_vrow,"lon"),  None, "lon")
                            _helv = safe_float(safe(home_vrow,"elevation"), None, "elev")
                            if _hlat is not None and _hlon is not None:
                                wx = get_weather(_hlat, _hlon)
                                if wx and wx != "error":
                                    row_d.update({"temp": wx["temp"], "pressure": wx["pressure"],
                                                  "humidity": wx["humidity"], "rho_home": air_density(wx["temp"], wx["pressure"], wx["humidity"]),
                                                  "home_elevation": _helv or 0.0,
                                                  "_elev_ft": _helv or 0.0})
                    except Exception: pass

                # Avoid report-grade heavy recompute for each row during picks refresh.
                # Picks should use already-loaded fields and lightweight fallbacks only.

                result = _tpk_compute_lean(row_d, sport)
                lean   = result["lean"]
                conf   = result["confidence"]
                facts  = result["factors"]

                tag  = lean if lean in ("OVER","UNDER","NEUTRAL") else ("odd" if i%2 else "")
                vals = (sport, t, a, h, ou, lean, conf, facts)
                root.after(0, lambda v=vals, tg=tag: _tpk_tree.insert("","end",values=v,tags=(tg,)))
                rows_added += 1
                # â”€â”€ Auto-log model lean to model_picks table â”€â”€
                if lean in ("OVER","UNDER"):
                    try:
                        _gdate = datetime.now().strftime("%Y-%m-%d")
                        _con_m = _sqlite3.connect(PICKS_DB)
                        _con_m.execute(
                            "INSERT INTO model_picks "
                            "(logged_at,game_date,game_time,league,away_team,home_team,"
                            " ou_line,pick,confidence,key_factors) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?) "
                            "ON CONFLICT(game_date, away_team, home_team) DO UPDATE SET "
                            "logged_at=excluded.logged_at, "
                            "game_time=excluded.game_time, "
                            "league=excluded.league, "
                            "ou_line=COALESCE(excluded.ou_line, model_picks.ou_line), "
                            "pick=excluded.pick, "
                            "confidence=excluded.confidence, "
                            "key_factors=excluded.key_factors",
                            (datetime.now().isoformat(), _gdate, t, sport,
                             a, h,
                             float(ou) if ou and str(ou).replace(".","").isdigit() else None,
                             lean, conf, facts))
                        _con_m.commit(); _con_m.close()
                    except Exception: pass
            except Exception: continue

    _tpk_set_status(
        f"âœ… {rows_added} picks computed." if rows_added
        else "No data loaded â€” fetch matchups first.")


_tpk_refresh_gate = threading.Lock()
_tpk_refresh_running = False

def _launch_tpk_refresh_async():
    """Run at most one picks refresh at a time to avoid UI thrash."""
    def _runner():
        global _tpk_refresh_running
        with _tpk_refresh_gate:
            if _tpk_refresh_running:
                return
            _tpk_refresh_running = True
        try:
            _tpk_refresh()
        finally:
            with _tpk_refresh_gate:
                _tpk_refresh_running = False
    threading.Thread(target=_runner, daemon=True).start()


def _tpk_export_csv():
    """Export Today\'s Picks treeview to CSV."""
    try:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV","*.csv")],
            initialfile="TodaysPicks_" + datetime.now().strftime("%Y%m%d") + ".csv"
        )
        if not path: return
        import csv
        with open(path,"w",newline="",encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(_tpk_cols)
            for iid in _tpk_tree.get_children():
                w.writerow(_tpk_tree.item(iid,"values"))
        _tpk_status.set(f"[OK] Exported: {os.path.basename(path)}")
    except Exception as ex:
        _tpk_status.set(f"Export failed: {ex}")

# â”€â”€ AUTO-BOOT: Injury/News Builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Startup hard-refresh for daily matchup/stat/SOS ingestion.
# Policy:
# - First app-open each day: run full stats + SOS pipeline.
# - Later opens same day: skip if already successful.
# - If a prior run failed, retry on next open.
def _autoboot_stats_sos_daily():
    import queue
    import sys
    import subprocess
    import time
    import json

    _base_dir = Path(__file__).resolve().parent
    _stats_script = _base_dir / "scrapes.py"
    _sos_script = _base_dir / "sos_scraper.py"
    _target_date = datetime.now().strftime("%Y-%m-%d")
    _target_token = datetime.now().strftime("%Y%m%d")
    _step_total = len(_STATS_SOS_LEAGUES) + 3  # init + stats + each SOS + finalize
    _step_done = 0
    _task_name = "stats_sos_daily"

    def _advance(_msg: str):
        nonlocal _step_done
        _step_done = min(_step_done + 1, _step_total)
        _set_startup_progress(_step_done, _step_total, _msg)
        try:
            _startup_task_mark(
                _task_name,
                "running",
                progress_pct=round((_step_done / max(_step_total, 1)) * 100.0, 1),
                detail=str(_msg or "").strip(),
            )
        except Exception:
            pass

    _should_run, _last = _startup_task_should_run(_task_name)
    if not _should_run:
        _when = str(_last.get("updated_at", "") or "earlier today")
        log(f"[startup_data] Skipping stats/SOS pipeline (already completed today at {_when}).", "info")
        _set_startup_progress(_step_total, _step_total, "daily startup data already complete")
        root.after(0, lambda: m_status_var.set(
            "Startup data already completed earlier today; using today's cached files."
        ))
        root.after(0, lambda: _refresh_pipeline_pulse(log_summary=True))
        try:
            _launch_tpk_refresh_async()
        except Exception:
            pass
        return

    _startup_task_mark(
        _task_name,
        "running",
        started_at=datetime.now().astimezone().isoformat(),
        progress_pct=0.0,
        detail="queued",
    )
    _set_startup_progress(0, _step_total, "queued")

    root.after(0, lambda: m_status_var.set(
        "Running startup data build (watchdog active): stats -> sos per league..."
    ))
    log("[startup_data] Launching fresh daily stats/SOS pipeline with watchdogs.", "info")

    _all_ok = True
    _stats_marker_state = {}
    _env = _runtime_env_copy()
    _env["PYTHONIOENCODING"] = "utf-8"
    _env["PYTHONUTF8"] = "1"
    _env["HEADLESS"] = str(_env.get("HEADLESS", "1") or "1")

    def _read_status_marker(_folder: Path, _prefix: str, _league: str):
        _p = _folder / f"{_prefix}_{_league}_{_target_token}.json"
        if not _p.exists():
            return {}
        try:
            return json.loads(_p.read_text(encoding="utf-8"))
        except Exception as _e:
            log(f"[startup_data] Failed reading marker {_p.name}: {_e}", "warning")
            return {}

    def _write_status_marker(_folder: Path, _prefix: str, _league: str, payload: dict):
        _p = _folder / f"{_prefix}_{_league}_{_target_token}.json"
        _tmp = _p.with_suffix(_p.suffix + ".tmp")
        try:
            _folder.mkdir(parents=True, exist_ok=True)
            _tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(str(_tmp), str(_p))
        except Exception as _wm_err:
            log(f"[startup_data] Failed writing marker {_p.name}: {_wm_err}", "warning")
            try:
                if _tmp.exists():
                    _tmp.unlink()
            except Exception:
                pass

    def _run_with_watchdog(_cmd, _tag: str, _timeout_sec: int, _on_progress=None):
        _q = queue.Queue()
        _timed_out = False
        _start = time.time()
        _last_progress_emit = 0.0
        _last_progress_line = ""
        _proc = subprocess.Popen(
            _cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_base_dir),
            env=_env,
            bufsize=1,
        )

        def _reader():
            try:
                for _line in _proc.stdout:
                    _q.put(_line.rstrip())
            finally:
                _q.put(None)

        threading.Thread(target=_reader, daemon=True).start()

        while True:
            if (time.time() - _start) > _timeout_sec:
                _timed_out = True
                try:
                    _proc.kill()
                except Exception:
                    pass
                break
            try:
                _item = _q.get(timeout=0.4)
            except queue.Empty:
                if _proc.poll() is not None:
                    break
                continue

            if _item is None:
                if _proc.poll() is not None:
                    break
                continue
            if not _item:
                continue
            _is_progress_line = bool(
                re.search(r"\b\d+/\d+\b|\b\d{1,3}%\b|\|\s*\d+/\d+\s*\[", _item)
            )
            if _is_progress_line:
                _now = time.time()
                if _item == _last_progress_line and (_now - _last_progress_emit) < _LOG_PROGRESS_THROTTLE_SEC:
                    continue
                if (_now - _last_progress_emit) < _LOG_PROGRESS_THROTTLE_SEC:
                    continue
                _last_progress_emit = _now
                _last_progress_line = _item
            if callable(_on_progress):
                try:
                    _m_pct = re.search(r"(\d{1,3})%\|", _item) or re.search(r"\b(\d{1,3})%\b", _item)
                    if _m_pct:
                        _pct = max(0, min(int(_m_pct.group(1)), 100))
                        _on_progress(_pct, _item)
                except Exception:
                    pass
            _lvl = "warning" if any(x in _item for x in ("WARN", "ERROR", "Failed", "Traceback")) else "info"
            log(f"[{_tag}] {_item}", _lvl)

        try:
            _rc = _proc.wait(timeout=5)
        except Exception:
            _rc = _proc.returncode if _proc.returncode is not None else -9
        _dur = time.time() - _start
        return _rc, _timed_out, _dur

    if not _stats_script.exists():
        log(f"[startup_data] Missing script: {_stats_script}", "error")
        _all_ok = False
        _advance("stats script missing")
    else:
        _step_done = 1
        _set_startup_progress(_step_done, _step_total, f"running {_stats_script.name} ...")
        _startup_task_mark(
            _task_name,
            "running",
            progress_pct=round((_step_done / max(_step_total, 1)) * 100.0, 1),
            detail=f"running {_stats_script.name}",
        )
        log(f"[startup_data] Running {_stats_script.name} ...", "info")
        try:
            def _stats_progress_cb(_pct: int, _line: str):
                _step_units = max(_step_total, 1)
                _overall_pct = ((1.0 + (max(0, min(_pct, 100)) / 100.0)) / _step_units) * 100.0
                _detail = f"{_stats_script.name}: {_pct}%"
                _set_startup_progress_pct(_overall_pct, _detail)
                _startup_task_mark(
                    _task_name,
                    "running",
                    progress_pct=round(_overall_pct, 1),
                    detail=_detail,
                )

            _rc, _to, _dur = _run_with_watchdog(
                [sys.executable, "-u", str(_stats_script)],
                "stats_scraper",
                _timeout_sec=900,
                _on_progress=_stats_progress_cb,
            )
            if _to:
                _all_ok = False
                log(f"[startup_data] {_stats_script.name} timed out after {_dur:.0f}s.", "error")
                _advance(f"{_stats_script.name} timeout")
            elif _rc != 0:
                _all_ok = False
                log(f"[startup_data] {_stats_script.name} exited with code {_rc}.", "error")
                _advance(f"{_stats_script.name} failed (code {_rc})")
            else:
                log(f"[startup_data] {_stats_script.name} completed in {_dur:.1f}s.", "info")
                for _lg in _STATS_SOS_LEAGUES:
                    _sm = _read_status_marker(_base_dir / "stats_output", "StatsStatus", _lg)
                    if not _sm:
                        _all_ok = False
                        log(f"[startup_data] Stats marker missing for {_lg}.", "warning")
                        _stats_marker_state[_lg] = "MISSING"
                        continue
                    _sm_status = str(_sm.get("status", "")).upper().strip()
                    _stats_marker_state[_lg] = _sm_status or "UNKNOWN"
                    if _sm_status not in {"READY", "NO_GAMES"}:
                        _all_ok = False
                    log(
                        f"[startup_data] Stats {_lg} marker: status={_sm_status or 'UNKNOWN'} "
                        f"games={_sm.get('games_found', 0)} stats_rows={_sm.get('stats_rows', 0)}.",
                        "info",
                    )
                _advance(f"{_stats_script.name} complete")
        except Exception as _e_sd:
            _all_ok = False
            log(f"[startup_data] {_stats_script.name} failed: {_e_sd}", "error")
            _advance(f"{_stats_script.name} exception")

    for _lg in _STATS_SOS_LEAGUES:
        if not _sos_script.exists():
            _all_ok = False
            log(f"[startup_data] Missing script: {_sos_script}", "error")
            _advance("sos script missing")
            break

        _st_state = str(_stats_marker_state.get(_lg, "")).upper().strip()
        if _st_state == "NO_GAMES":
            _write_status_marker(
                _base_dir / "sos_data",
                "SOSStatus",
                _lg,
                {
                    "league": _lg,
                    "date": _target_date,
                    "status": "NO_GAMES",
                    "games_found": 0,
                    "games_matched": 0,
                    "output_file": "",
                    "error": "",
                    "note": "No slate for target date.",
                    "updated_at": datetime.now().astimezone().isoformat(),
                },
            )
            log(f"[startup_data] Skipping SOS for {_lg}: stats marker reports NO_GAMES.", "info")
            _advance(f"SOS {_lg} skipped (no games)")
            continue

        root.after(0, lambda _l=_lg: m_status_var.set(
            f"Building SOS for {_l} ({_target_date}) ..."
        ))
        _set_startup_progress(
            max(_step_done, 1),
            _step_total,
            f"running SOS {_lg} ..."
        )
        _startup_task_mark(
            _task_name,
            "running",
            progress_pct=round((max(_step_done, 1) / max(_step_total, 1)) * 100.0, 1),
            detail=f"running SOS {_lg}",
        )
        _cmd = [sys.executable, "-u", str(_sos_script), "--date", _target_date, "--sport", _lg.lower()]
        log(f"[startup_data] Running sos_scraper.py for {_lg} ...", "info")
        try:
            _base_step = max(_step_done, 1)

            def _sos_progress_cb(_pct: int, _line: str, _league: str = _lg, _base: int = _base_step):
                _step_units = max(_step_total, 1)
                _overall_pct = ((_base + (max(0, min(_pct, 100)) / 100.0)) / _step_units) * 100.0
                _detail = f"SOS {_league}: {_pct}%"
                _set_startup_progress_pct(_overall_pct, _detail)
                _startup_task_mark(
                    _task_name,
                    "running",
                    progress_pct=round(_overall_pct, 1),
                    detail=_detail,
                )

            _rc, _to, _dur = _run_with_watchdog(
                _cmd,
                f"sos_{_lg.lower()}",
                _timeout_sec=420,
                _on_progress=_sos_progress_cb,
            )
            _marker = _read_status_marker(_base_dir / "sos_data", "SOSStatus", _lg)
            _m_status = str(_marker.get("status", "")).upper().strip()

            if _to:
                _all_ok = False
                log(f"[startup_data] sos_scraper.py {_lg} timed out after {_dur:.0f}s.", "error")
                _advance(f"SOS {_lg} timeout")
            elif _rc != 0:
                _all_ok = False
                log(f"[startup_data] sos_scraper.py {_lg} exited with code {_rc}.", "error")
                _advance(f"SOS {_lg} failed (code {_rc})")
            elif _m_status not in {"READY", "NO_GAMES"}:
                _all_ok = False
                log(
                    f"[startup_data] SOS marker for {_lg} not ready "
                    f"(status={_m_status or 'missing'})",
                    "error",
                )
                _advance(f"SOS {_lg} marker {(_m_status or 'missing').upper()}")
            else:
                log(
                    f"[startup_data] SOS {_lg} completed: status={_m_status} "
                    f"games={_marker.get('games_found', 0)} matched={_marker.get('games_matched', 0)}.",
                    "info",
                )
                _advance(f"SOS {_lg} complete")
        except Exception as _e_sos:
            _all_ok = False
            log(f"[startup_data] sos_scraper.py {_lg} failed: {_e_sos}", "error")
            _advance(f"SOS {_lg} exception")

    # Bust integration caches so model reads only fresh startup files.
    if STATS_SOS_AVAILABLE:
        for _lg in _STATS_SOS_LEAGUES:
            try:
                _invalidate_stats_cache(_lg)
                _invalidate_sos_cache(_lg)
            except Exception:
                pass

    root.after(0, lambda: _refresh_pipeline_pulse(log_summary=True))
    if _all_ok:
        _startup_task_mark(
            _task_name,
            "success",
            date=_target_date,
            progress_pct=100.0,
            detail="startup data complete",
        )
        root.after(0, lambda: m_status_var.set(
            "Fresh startup stats/SOS build complete. Model is using today's files."
        ))
        _set_startup_progress(_step_total, _step_total, "startup data complete")
    else:
        _startup_task_mark(
            _task_name,
            "failed",
            date=_target_date,
            progress_pct=100.0,
            detail="startup data completed with errors",
        )
        root.after(0, lambda: m_status_var.set(
            "Startup stats/SOS build had errors. Check Run Log before trusting picks."
        ))
        _set_startup_progress(_step_total, _step_total, "startup data completed with errors")

    try:
        _launch_tpk_refresh_async()
    except Exception:
        pass

_start_daemon_after(600, _autoboot_stats_sos_daily)
def _injury_news_is_fresh_any():
    """True if there is at least one today's injury workbook with required sheets."""
    ts = datetime.now().strftime("%Y%m%d")
    out_dir = _injury_news_output_dir()
    if not out_dir.exists():
        return False
    for _p in out_dir.glob(f"INJURY_NEWS_*_{ts}.xlsx"):
        try:
            if _p.exists() and _p.stat().st_size > 0 and _injury_news_has_required_sheets(_p):
                return True
        except Exception:
            continue
    return False

def _injury_news_required_leagues_today():
    """Leagues that appear to have a live slate today.

    Priority:
    1) Today's StatsStatus/SOSStatus marker files
    2) Today's odds workbooks (fallback)
    """
    ts = datetime.now().strftime("%Y%m%d")
    base_dir = Path(__file__).resolve().parent
    required = set()
    ready_states = {"READY", "PARTIAL_READY", "STATS_READY", "SOS_READY"}

    def _read_marker(folder_name: str, prefix: str, league: str) -> dict:
        p = base_dir / folder_name / f"{prefix}_{league}_{ts}.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _marker_has_games(marker: dict) -> bool:
        if not marker:
            return False
        status = str(marker.get("status", "")).upper().strip()
        if status == "NO_GAMES":
            return False

        games_keys = ("games_found", "games", "game_count")
        has_games_field = any(k in marker for k in games_keys)
        games_found = 0
        for k in games_keys:
            try:
                if marker.get(k) is not None:
                    games_found = max(games_found, int(str(marker.get(k)).strip()))
            except Exception:
                continue

        if status in ready_states:
            return (games_found > 0) or (not has_games_field)
        return games_found > 0

    for _lg in _STATS_SOS_LEAGUES:
        _stats_marker = _read_marker("stats_output", "StatsStatus", _lg)
        _sos_marker = _read_marker("sos_data", "SOSStatus", _lg)
        if _marker_has_games(_stats_marker) or _marker_has_games(_sos_marker):
            required.add(_lg)

    for _lg in _STATS_SOS_LEAGUES:
        _p = Path(ODDS_DIR) / f"Odds_{_lg}_{ts}.xlsx"
        if not _p.exists():
            continue
        try:
            _probe = pd.read_excel(_p, nrows=1, dtype=str)
            if _probe is not None and not _probe.empty:
                required.add(_lg)
        except Exception:
            required.add(_lg)

    if not required:
        required = {"MLB", "NBA", "NHL"}
    return tuple(sorted(required))

def _injury_news_missing_leagues_today():
    missing = []
    for _lg in _injury_news_required_leagues_today():
        if not _injury_news_file_ready(_lg):
            missing.append(_lg)
    return missing

def _autoboot_injury_news():
    _task_name = "injury_news_daily"
    _should_run, _last = _startup_task_should_run(_task_name)
    _fresh_any = _injury_news_is_fresh_any()
    _missing_leagues = _injury_news_missing_leagues_today()
    if (not _should_run) and _fresh_any and (not _missing_leagues):
        _when = str(_last.get("updated_at", "") or "earlier today")
        log(f"[injury_news] Skipping auto-run (already completed today at {_when}).", "info")
        return
    if (not _should_run) and ((not _fresh_any) or _missing_leagues):
        _miss = f" missing leagues={','.join(_missing_leagues)}" if _missing_leagues else ""
        log(f"[injury_news] Today's file set incomplete despite prior success marker - retrying build.{_miss}", "warning")
    _startup_task_mark(
        _task_name,
        "running",
        started_at=datetime.now().astimezone().isoformat(),
        progress_pct=0.0,
        detail="queued",
    )
    log("[RUN] Running daily injury/news build (once-per-day startup policy).", "info")
    root.after(0, lambda: m_status_var.set(
        "[RUN] Fetching injury/news data for all leagues (auto-boot) - ~3-5 min ..."))
    _base_dir = Path(__file__).resolve().parent
    _script_candidates = [
        _base_dir / "injury_news_gameday_builder_FINAL_v3.py",
        _base_dir / "injury_news_gameday_builder.py",
        _base_dir / "injury_news_gameday_builder_FINAL.py",
        _base_dir / "injury_news_gameday_builder_FINAL_v4.py",
        _base_dir / "injury_news_gameday_builder_PRO_INTEL_REF_v3.py",
    ]
    script = ""
    for _cand in _script_candidates:
        if _cand.exists():
            script = str(_cand)
            break
    if script:
        log(f"[injury_news] Using builder: {os.path.basename(script)}", "info")
    _builder_name = os.path.basename(script) if script else "injury_news_gameday_builder_FINAL_v3.py"
    if not script or (not os.path.exists(script)):
        # Last-chance fallback: glob for any matching file (handles OneDrive rename quirks)
        import glob as _glob
        _matches = _glob.glob(str(_base_dir / "injury_news_gameday_builder*.py"))
        if not _matches:
            _matches = _glob.glob(os.path.join(ODDS_DIR, "injury_news_gameday_builder*.py"))
        if _matches:
            script = sorted(_matches)[-1]
            log(f"[injury_news] Using fallback builder: {os.path.basename(script)}", "info")
    _builder_name = os.path.basename(script) if script else _builder_name
    if not os.path.exists(script):
        log(f"[WARN] {_builder_name} not found at {_base_dir}", "warning")
        log(f"      If file is on OneDrive: right-click it -> Always keep on this device", "warning")
        root.after(0, lambda: m_status_var.set(f"[WARN] {_builder_name} not found - see Run Log."))
        _startup_task_mark(_task_name, "failed", error="script missing", progress_pct=100.0, detail="script missing")
        return
    import subprocess, sys
    try:
        _env = _runtime_env_copy()
        _env["PYTHONIOENCODING"] = "utf-8"
        _env["PYTHONUTF8"] = "1"
        _required_leagues = set(_injury_news_required_leagues_today())
        _seen_leagues = set()
        _last_pct = 0.0
        proc = subprocess.Popen(
            [sys.executable, script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            cwd=str(_base_dir), env=_env,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _optional_auth = (
                    ("Auth/forbidden" in line)
                    or ("Skip blocked host" in line)
                    or ("balldontlie.io" in line and "401" in line)
                    or ("rapidapi" in line and "403" in line)
                )
                _lg_match = re.search(r"BoydsBets\s+\[([A-Z0-9]+)\]", line)
                if _lg_match:
                    _seen_leagues.add(_lg_match.group(1).upper())
                _pct_match = re.search(r"\b(\d{1,3})%\b", line)
                _calc_pct = 0.0
                if _required_leagues:
                    _calc_pct = (len(_seen_leagues.intersection(_required_leagues)) / float(len(_required_leagues))) * 92.0
                if _pct_match:
                    try:
                        _calc_pct = max(_calc_pct, float(int(_pct_match.group(1))))
                    except Exception:
                        pass
                _calc_pct = max(_last_pct, min(_calc_pct, 99.0))
                if _calc_pct > _last_pct:
                    _last_pct = _calc_pct
                    _startup_task_mark(
                        _task_name,
                        "running",
                        progress_pct=round(_calc_pct, 1),
                        detail=line[:96],
                    )
                lvl = "warning" if (not _optional_auth and any(x in line for x in ("[WARN]", "WARN", "ERROR", "error", "Failed", "Traceback"))) else "info"
                log(f"[injury_news] {line}", lvl)
        proc.wait()
        if proc.returncode == 0:
            log(f"[OK] {_builder_name} auto-boot complete.", "info")
            _startup_task_mark(_task_name, "success", progress_pct=100.0, detail="injury/news build complete")
            root.after(0, lambda: m_status_var.set(
                "[OK] Injury/news data loaded - double-click any game for full breakdown."))
        else:
            log(f"[WARN] {_builder_name} exited with code {proc.returncode}.", "warning")
            _startup_task_mark(
                _task_name,
                "failed",
                error=f"exit code {proc.returncode}",
                progress_pct=100.0,
                detail=f"exit code {proc.returncode}",
            )
    except Exception as e:
        log(f"[WARN] Injury/news auto-boot failed: {e}", "warning")
        _startup_task_mark(_task_name, "failed", error=str(e), progress_pct=100.0, detail="exception")

_start_daemon_after(1000, _autoboot_injury_news)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AUTO-BOOT: MLB PRE-GAME STATS CHECK
# If mlb_pregame.db is missing or has no data for today, auto-run
# mlb_stats_daily.py in background before the UI is fully active.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _mlb_db_health_report():
    """Return a completeness report for today's MLB pregame DB."""
    import sqlite3 as _sq

    today = datetime.now().strftime("%Y-%m-%d")
    db = os.path.join(ODDS_DIR, "mlb_pregame.db")
    report = {
        "ok": False,
        "today": today,
        "db_path": db,
        "reason": "DB missing.",
        "games": 0,
        "expected_team_rows": 0,
        "expected_starter_rows": 0,
        "starter_rows": 0,
        "starter_blank_throws": 0,
        "team_rows": 0,
        "team_missing_xwoba": 0,
        "team_missing_vs_rhp": 0,
        "team_missing_vs_lhp": 0,
        "matchups_missing_summary": 0,
    }
    if not os.path.exists(db):
        return report

    con = None
    try:
        con = _sq.connect(db)

        def _scalar(sql, params=(today,)):
            try:
                return int(con.execute(sql, params).fetchone()[0] or 0)
            except Exception:
                return 0

        report["games"] = _scalar(
            "SELECT COUNT(*) FROM pregame_matchups WHERE game_date=?"
        )
        report["expected_team_rows"] = report["games"] * 2
        report["expected_starter_rows"] = report["games"] * 2
        report["starter_rows"] = _scalar(
            "SELECT COUNT(*) FROM starter_stats WHERE fetched_date=?"
        )
        report["starter_blank_throws"] = _scalar(
            "SELECT COUNT(*) FROM starter_stats "
            "WHERE fetched_date=? AND (throws IS NULL OR TRIM(throws)='')"
        )
        report["team_rows"] = _scalar(
            "SELECT COUNT(*) FROM team_stats WHERE fetched_date=?"
        )
        report["team_missing_xwoba"] = _scalar(
            "SELECT COUNT(*) FROM team_stats WHERE fetched_date=? AND xwoba IS NULL"
        )
        report["team_missing_vs_rhp"] = _scalar(
            "SELECT COUNT(*) FROM team_stats WHERE fetched_date=? AND ops_vs_rhp IS NULL"
        )
        report["team_missing_vs_lhp"] = _scalar(
            "SELECT COUNT(*) FROM team_stats WHERE fetched_date=? AND ops_vs_lhp IS NULL"
        )
        report["matchups_missing_summary"] = _scalar(
            "SELECT COUNT(*) FROM pregame_matchups "
            "WHERE game_date=? AND (matchup_summary IS NULL OR TRIM(matchup_summary)='')"
        )

        reasons = []
        games = report["games"]
        expected_team_rows = report["expected_team_rows"]
        expected_starter_rows = report["expected_starter_rows"]
        team_missing_limit = max(1, expected_team_rows // 4) if expected_team_rows else 0
        starter_missing_limit = max(1, expected_starter_rows // 6) if expected_starter_rows else 0
        summary_missing_limit = max(1, games // 3) if games else 0

        if games <= 0:
            reasons.append("no pregame_matchups rows for today")
        if report["starter_rows"] < expected_starter_rows:
            reasons.append(
                f"starter rows {report['starter_rows']}/{expected_starter_rows}"
            )
        if report["team_rows"] < expected_team_rows:
            reasons.append(
                f"team rows {report['team_rows']}/{expected_team_rows}"
            )
        if report["starter_blank_throws"] > starter_missing_limit:
            reasons.append(
                f"blank starter throws {report['starter_blank_throws']}/{report['starter_rows'] or expected_starter_rows}"
            )
        if report["team_missing_xwoba"] > team_missing_limit:
            reasons.append(
                f"missing team xwoba {report['team_missing_xwoba']}/{report['team_rows'] or expected_team_rows}"
            )
        if report["team_missing_vs_rhp"] > team_missing_limit:
            reasons.append(
                f"missing ops_vs_rhp {report['team_missing_vs_rhp']}/{report['team_rows'] or expected_team_rows}"
            )
        if report["team_missing_vs_lhp"] > team_missing_limit:
            reasons.append(
                f"missing ops_vs_lhp {report['team_missing_vs_lhp']}/{report['team_rows'] or expected_team_rows}"
            )
        if report["matchups_missing_summary"] > summary_missing_limit:
            reasons.append(
                f"missing matchup summaries {report['matchups_missing_summary']}/{games}"
            )

        report["ok"] = not reasons
        report["reason"] = (
            "Today's MLB DB passed completeness checks."
            if report["ok"]
            else "; ".join(reasons)
        )
        return report
    except Exception as e:
        report["reason"] = f"DB health check failed: {e}"
        return report
    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass


def _mlb_db_is_fresh():
    """Backward-compatible bool check used by startup logic."""
    return _mlb_db_health_report().get("ok", False)


def _autoboot_mlb_stats():
    """
    Called once at startup in a daemon thread.
    If DB is missing or stale, runs mlb_stats_daily.py as a subprocess
    and streams its output to the Run Log. UI stays responsive throughout.
    """
    _task_name = "mlb_stats_daily"
    _should_run, _last = _startup_task_should_run(_task_name)
    _db_health = _mlb_db_health_report()
    if (not _should_run) and _db_health.get("ok"):
        _when = str(_last.get("updated_at", "") or "earlier today")
        log(
            f"[mlb_stats] Skipping mlb_stats_daily.py (already completed today at {_when}).",
            "info",
        )
        return
    if (not _should_run) and (not _db_health.get("ok")):
        log("[mlb_stats] DB is stale/incomplete despite prior success marker â€” retrying build.", "warning")
    elif _should_run and _db_health.get("ok"):
        log(
            "âš™  First-open daily policy: refreshing MLB pre-game stats even though DB is already healthy.",
            "info",
        )
    _startup_task_mark(
        _task_name,
        "running",
        started_at=datetime.now().astimezone().isoformat(),
        progress_pct=0.0,
        detail="starting",
    )

    log(
        "âš™  Running mlb_stats_daily.py for daily startup policy â€” "
        f"auto-running mlb_stats_daily.py for {_db_health.get('today')} "
        f"because {_db_health.get('reason')}.",
        "info",
    )

    # Show a banner in the status bar of the Matchups tab
    root.after(0, lambda: m_status_var.set(
        "âš™  Refreshing today's MLB pre-game stats for today's scheduled games only ..."))

    script = os.path.join(ODDS_DIR, "mlb_stats_daily.py")
    if not os.path.exists(script):
        log(f"âš   mlb_stats_daily.py not found at {script} â€” skipping auto-boot.", "warning")
        root.after(0, lambda: m_status_var.set(
            "âš   mlb_stats_daily.py not found â€” pre-game stats unavailable."))
        _startup_task_mark(_task_name, "failed", error="script missing", progress_pct=100.0, detail="script missing")
        return

    import subprocess, sys
    try:
        proc = subprocess.Popen(
            [sys.executable, script, _db_health.get("today") or datetime.now().strftime("%Y-%m-%d")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ODDS_DIR,
            env={**_runtime_env_copy(), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        _mlb_progress_last = -1
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _prog_m = re.search(r"(\d{1,3})%\|", line)
                if _prog_m:
                    try:
                        _pct = int(_prog_m.group(1))
                    except Exception:
                        _pct = -1
                    if _pct >= 0:
                        if (_pct != 100) and (_pct % 5 != 0):
                            continue
                        if _pct == _mlb_progress_last:
                            continue
                        _mlb_progress_last = _pct
                        _startup_task_mark(
                            _task_name,
                            "running",
                            progress_pct=float(_pct),
                            detail=f"statcast pull {_pct}%",
                        )
                        line = f"progress {_pct}%"
                lvl = "warning" if any(x in line for x in ("âš ","WARN","ERROR","error")) else "info"
                log(f"[mlb_stats] {line}", lvl)
        proc.wait()
        if proc.returncode == 0:
            log("âœ… mlb_stats_daily.py auto-boot complete â€” DB populated.", "info")
            _startup_task_mark(_task_name, "success", progress_pct=100.0, detail="mlb pre-game stats loaded")
            root.after(0, lambda: m_status_var.set(
                "âœ… MLB pre-game stats loaded â€” double-click any game for full breakdown."))
        else:
            log(f"âš   mlb_stats_daily.py exited with code {proc.returncode}.", "warning")
            _startup_task_mark(
                _task_name,
                "failed",
                error=f"exit code {proc.returncode}",
                progress_pct=100.0,
                detail=f"exit code {proc.returncode}",
            )
            root.after(0, lambda: m_status_var.set(
                f"âš   MLB stats auto-boot finished with errors (code {proc.returncode})."))
    except Exception as e:
        log(f"âš   mlb_stats auto-boot failed: {e}", "warning")
        _startup_task_mark(_task_name, "failed", error=str(e), progress_pct=100.0, detail="exception")
        _msg = str(e)
        root.after(0, lambda _m=_msg: m_status_var.set(f"[WARN] MLB stats auto-boot failed: {_m}"))


# Fire auto-boot in background â€” non-blocking, UI launches immediately
_start_daemon_after(1250, _autoboot_mlb_stats)

def _enforce_main_tab_order():
    try:
        _desired = [
            (matchups_frame, "Dashboard"),
            (console_frame, "System Console"),
            (games_frame, "Today's Slate"),
            (physics_frame, "Model"),
            (arsenal_frame, "Arsenal"),
            (execution_frame, "Picks"),
            (reports_frame, "Reports"),
        ]
        for _idx, (_frame, _label) in enumerate(_desired):
            if str(_frame) in main_tabs.tabs():
                main_tabs.insert(_idx, _frame)
                main_tabs.tab(_frame, text=_label)
        main_tabs.select(matchups_frame)
    except Exception as _ord_e:
        log(f"[ui] tab order enforcement failed: {_ord_e}", "warning")

def _finalize_startup_ui():
    try:
        _enforce_main_tab_order()
        _rpt_refresh_history_dropdown()
    except Exception:
        pass
    try:
        _apply_visual_profile(_shell_visual_var.get())
    except Exception:
        pass
    try:
        if "_STARTUP_SPLASH" in globals() and _STARTUP_SPLASH is not None:
            _STARTUP_SPLASH.destroy()
    except Exception:
        pass
    try:
        root.deiconify()
        root.state("zoomed")
        root.lift()
        root.focus_force()
    except Exception:
        pass

root.after(200, _finalize_startup_ui)

root.mainloop()

