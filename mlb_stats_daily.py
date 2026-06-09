from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unicodedata
import uuid
import urllib.parse
import urllib.request
import urllib.error
import ssl
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mlb_readiness import (
    ReadinessState,
    ReadinessStore,
    make_coverage,
    make_source,
    finalize_state,
)
try:
    import certifi
except Exception:
    certifi = None

LOG = logging.getLogger("mlb_pregame_builder")
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
DEFAULT_DB_NAME = "mlb_pregame.db"
DEFAULT_TMP_DB_NAME = "mlb_pregame_tmp.db"
DEFAULT_LOCK_NAME = "mlb_pregame.lock"
DEFAULT_META_NAME = "mlb_pregame_run.json"
MLB_PREGAME_SCHEMA_VERSION = 4
_BREF_SUPP_CACHE: Dict[Tuple[str, str], Any] = {}
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS catcher_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_date TEXT,
    team_name TEXT,
    catcher_name TEXT,
    framing_tier TEXT,
    block_tier TEXT,
    arm_tier TEXT,
    catcher_impact REAL,
    extra_strikes_per100 REAL
);
CREATE TABLE IF NOT EXISTS team_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_date TEXT,
    team_name TEXT,
    wins INTEGER,
    losses INTEGER,
    ops_vs_rhp REAL,
    ops_vs_lhp REAL,
    bullpen_era REAL,
    runs_per_game REAL,
    xwoba REAL,
    hard_hit_pct REAL,
    ops REAL,
    obp REAL,
    slg REAL,
    avg REAL,
    iso REAL,
    barrel_pct REAL,
    avg_exit_velo REAL,
    hr_per_game REAL,
    bb_per_game REAL,
    ops_home REAL,
    ops_away REAL,
    ops_last14 REAL,
    runs_last14 REAL,
    bullpen_era_7d REAL,
    bullpen_ip_3d REAL
);
CREATE TABLE IF NOT EXISTS starter_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_date TEXT,
    team_name TEXT,
    player_name TEXT,
    throws TEXT,
    era REAL,
    fip REAL,
    xfip REAL,
    whip REAL,
    innings REAL,
    k_pct REAL,
    bb_pct REAL,
    k_minus_bb REAL,
    xwoba_against REAL,
    gb_pct REAL,
    fb_pct REAL,
    hr_per_fb REAL,
    babip REAL,
    avg_velo REAL,
    avg_spin REAL,
    whiff_pct REAL,
    hard_hit_pct REAL,
    fly_ball_exposure REAL,
    density_sensitivity REAL,
    era_last3 REAL,
    avg_pc_last3 REAL,
    avg_ip_last3 REAL
);
CREATE TABLE IF NOT EXISTS pregame_matchups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date TEXT,
    game_time TEXT,
    game_id INTEGER,
    away_team TEXT,
    home_team TEXT,
    away_starter TEXT,
    home_starter TEXT,
    away_ops_split REAL,
    home_ops_split REAL,
    matchup_summary TEXT,
    lineup_confirmed INTEGER,
    lineup_status TEXT,
    home_catcher TEXT,
    away_catcher TEXT
);
CREATE TABLE IF NOT EXISTS build_meta (
    run_id TEXT PRIMARY KEY,
    data_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    build_state TEXT NOT NULL,
    model_safe INTEGER NOT NULL,
    summary TEXT,
    blocking_issues TEXT,
    degraded_issues TEXT
);
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matchups_date ON pregame_matchups(game_date);
"""


def _runtime_base_dir_default() -> Path:
    _script_dir = Path(__file__).resolve().parent
    _cands: List[Path] = []
    _env = str(os.environ.get("OVERLINE_RUNTIME_DB_DIR", "") or "").strip()
    if _env:
        _cands.append(Path(_env))
    _local = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
    if _local:
        _cands.append(Path(_local) / "SportsPhysicsEngine")
    _cands.append(_script_dir / "runtime_data")
    _cands.append(Path(tempfile.gettempdir()) / "SportsPhysicsEngine")
    for _p in _cands:
        try:
            _p.mkdir(parents=True, exist_ok=True)
            _probe = _p / f".oe_write_probe_{os.getpid()}"
            _probe.write_text("ok", encoding="utf-8")
            try:
                _probe.unlink(missing_ok=True)
            except Exception:
                pass
            return _p.resolve()
        except Exception:
            continue
    return Path(".").resolve()


def _candidate_db_paths(base_dir: Path) -> List[Path]:
    _script_dir = Path(os.environ.get("OVERLINE_SCRIPT_DIR", "") or "").resolve() if os.environ.get("OVERLINE_SCRIPT_DIR") else Path(__file__).resolve().parent
    _odds_env = str(os.environ.get("OVERLINE_ODDS_DIR", "") or "").strip()
    _cands = [
        base_dir / DEFAULT_DB_NAME,
        (Path(_odds_env) / DEFAULT_DB_NAME) if _odds_env else None,
        _script_dir / "odds_data" / DEFAULT_DB_NAME,
        _script_dir / DEFAULT_DB_NAME,
        Path.cwd() / "odds_data" / DEFAULT_DB_NAME,
    ]
    out: List[Path] = []
    seen = set()
    for c in _cands:
        if c is None:
            continue
        s = str(c)
        if s in seen:
            continue
        seen.add(s)
        out.append(c)
    return out


def _seed_primary_db_from_legacy(base_dir: Path) -> None:
    # Do not seed from older DB locations. The app can read legacy files, but this
    # builder must only publish a DB after today's live-source build succeeds.
    return


@dataclass
class BuilderConfig:
    base_dir: Path
    data_date: str
    db_name: str = DEFAULT_DB_NAME
    tmp_db_name: str = DEFAULT_TMP_DB_NAME
    readiness_name: str = "mlb_readiness.json"
    lock_name: str = DEFAULT_LOCK_NAME
    meta_name: str = DEFAULT_META_NAME
    source_timeout_sec: int = 45
    retry_limit: int = 3
    backoff_sec: float = 1.5
    allow_degraded: bool = False
    verbose: bool = False

    @property
    def db_path(self) -> Path:
        return self.base_dir / self.db_name

    @property
    def tmp_db_path(self) -> Path:
        return self.base_dir / self.tmp_db_name

    @property
    def readiness_path(self) -> Path:
        return self.base_dir / self.readiness_name

    @property
    def lock_path(self) -> Path:
        return self.base_dir / self.lock_name

    @property
    def meta_path(self) -> Path:
        return self.base_dir / self.meta_name


@dataclass
class GameRow:
    game_id: str
    away_team: str
    home_team: str
    game_time_utc: str
    away_starter: str
    home_starter: str
    away_team_id: str = ""
    home_team_id: str = ""
    away_starter_id: str = ""
    home_starter_id: str = ""


@dataclass
class BuildBundle:
    schedule: List[GameRow] = field(default_factory=list)
    team_stats: List[Dict[str, Any]] = field(default_factory=list)
    starter_stats: List[Dict[str, Any]] = field(default_factory=list)
    catcher_by_team: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    source_notes: Dict[str, Any] = field(default_factory=dict)


class SingleRunLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: Optional[int] = None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    def _read_lock_pid(self) -> Optional[int]:
        try:
            raw = self.path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            if not raw:
                return None
            return int(raw[0].strip())
        except Exception:
            return None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        pid_bytes = str(os.getpid()).encode("utf-8")
        try:
            self.fd = os.open(str(self.path), flags)
            os.write(self.fd, pid_bytes)
        except FileExistsError as exc:
            owner_pid = self._read_lock_pid()
            if owner_pid is not None and self._pid_alive(owner_pid):
                raise RuntimeError(f"Another MLB build is already running: {self.path}") from exc
            # Stale lock file: claim it in-place (safe when owner PID is dead).
            try:
                self.fd = os.open(str(self.path), os.O_WRONLY | os.O_TRUNC)
                os.write(self.fd, pid_bytes)
            except Exception as stale_exc:
                raise RuntimeError(f"Stale MLB lock could not be reclaimed: {self.path}") from stale_exc

    def release(self) -> None:
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
        finally:
            for attempt in range(6):
                try:
                    self.path.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.1 * (attempt + 1))
                except Exception:
                    break

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_hash(parts: Iterable[Any]) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def fetch_with_retry(name: str, fn, retries: int, backoff_sec: float):
    last_exc = None
    started = time.monotonic()
    for attempt in range(1, retries + 1):
        try:
            result = fn()
            return result, round(time.monotonic() - started, 3), attempt, None
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff_sec * attempt)
    return None, round(time.monotonic() - started, 3), retries, last_exc


def _mlb_api_json(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    """Fetch MLB Stats API JSON without inheriting broken desktop proxy settings."""
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{MLB_API_BASE}/{path.lstrip('/')}"
    clean_params = {
        str(k): v
        for k, v in (params or {}).items()
        if v is not None and str(v) != ""
    }
    if clean_params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(clean_params, doseq=True)}"
    req = urllib.request.Request(url, headers={"User-Agent": "OverlineEdge/1.0"})
    _proxy_handler = urllib.request.ProxyHandler({})
    contexts: List[Optional[ssl.SSLContext]] = [None]
    if certifi is not None:
        try:
            contexts.append(ssl.create_default_context(cafile=certifi.where()))
        except Exception:
            pass
    _allow_insecure = str(os.environ.get("OVERLINE_ALLOW_INSECURE_SSL_FALLBACK", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if _allow_insecure:
        try:
            _insecure = ssl.create_default_context()
            _insecure.check_hostname = False
            _insecure.verify_mode = ssl.CERT_NONE
            contexts.append(_insecure)
        except Exception:
            pass
    last_exc: Optional[Exception] = None
    for ctx in contexts:
        try:
            if ctx is None:
                opener = urllib.request.build_opener(_proxy_handler)
            else:
                opener = urllib.request.build_opener(
                    _proxy_handler,
                    urllib.request.HTTPSHandler(context=ctx),
                )
            if ctx is None:
                with opener.open(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc if last_exc is not None else RuntimeError("MLB API fetch failed")


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        s = str(value).strip().replace("%", "")
        if not s or s.upper() in {"N/A", "NA", "NONE", "--"}:
            return None
        return float(s)
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    f = _safe_float(value)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _mlb_ip_to_float(value: Any) -> Optional[float]:
    """Convert MLB innings notation, where 5.2 means 5 and 2/3 innings."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if "." not in s:
            return float(s)
        whole_s, outs_s = s.split(".", 1)
        whole = int(whole_s or "0")
        outs = int((outs_s or "0")[0])
        if outs < 0 or outs > 2:
            return float(s)
        return whole + (outs / 3.0)
    except Exception:
        return _safe_float(value)


def _http_get_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "OverlineEdge/1.0"})
    _proxy_handler = urllib.request.ProxyHandler({})
    contexts: List[Optional[ssl.SSLContext]] = [None]
    if certifi is not None:
        try:
            contexts.append(ssl.create_default_context(cafile=certifi.where()))
        except Exception:
            pass
    _allow_insecure = str(os.environ.get("OVERLINE_ALLOW_INSECURE_SSL_FALLBACK", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if _allow_insecure:
        try:
            _insecure = ssl.create_default_context()
            _insecure.check_hostname = False
            _insecure.verify_mode = ssl.CERT_NONE
            contexts.append(_insecure)
        except Exception:
            pass
    last_exc: Optional[Exception] = None
    for ctx in contexts:
        try:
            if ctx is None:
                opener = urllib.request.build_opener(_proxy_handler)
            else:
                opener = urllib.request.build_opener(
                    _proxy_handler,
                    urllib.request.HTTPSHandler(context=ctx),
                )
            with opener.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc if last_exc is not None else RuntimeError(f"HTTP fetch failed: {url}")


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    s = html.unescape(str(value)).replace("\xa0", " ").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _clean_cell_text(cell_html: str) -> str:
    raw = re.sub(r"<[^>]+>", "", str(cell_html or ""))
    return html.unescape(raw).replace("\xa0", " ").strip()


def _extract_table_html(page_html: str, table_id: str) -> str:
    if not page_html:
        return ""
    pat = rf'<table[^>]*id="{re.escape(table_id)}"[^>]*>[\s\S]*?</table>'
    m = re.search(pat, page_html, flags=re.IGNORECASE)
    if m:
        return m.group(0)
    for comment_block in re.findall(r"<!--([\s\S]*?)-->", page_html):
        m = re.search(pat, comment_block, flags=re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


def _iter_table_rows(table_html: str) -> List[str]:
    rows = re.findall(r"<tr[^>]*>[\s\S]*?</tr>", str(table_html or ""), flags=re.IGNORECASE)
    out: List[str] = []
    for row in rows:
        row_low = row.lower()
        if 'class="thead"' in row_low or "data-stat=\"ranker\"" in row_low and "data-stat=\"team_name\"" not in row_low and "data-stat=\"name_display\"" not in row_low and "data-stat=\"year_id\"" not in row_low:
            continue
        out.append(row)
    return out


def _cell_html(row_html: str, data_stat: str) -> str:
    m = re.search(
        rf'<(?:td|th)[^>]*data-stat="{re.escape(data_stat)}"[^>]*>([\s\S]*?)</(?:td|th)>',
        str(row_html or ""),
        flags=re.IGNORECASE,
    )
    return m.group(1) if m else ""


def _cell_attr(row_html: str, data_stat: str, attr: str) -> str:
    m = re.search(
        rf'<(?:td|th)[^>]*data-stat="{re.escape(data_stat)}"([^>]*)>',
        str(row_html or ""),
        flags=re.IGNORECASE,
    )
    if not m:
        return ""
    attrs = m.group(1) or ""
    a = re.search(rf'\b{re.escape(attr)}="([^"]*)"', attrs, flags=re.IGNORECASE)
    return a.group(1).strip() if a else ""


def _cell_text(row_html: str, data_stat: str) -> str:
    return _clean_cell_text(_cell_html(row_html, data_stat))


def _cell_link(row_html: str, data_stat: str) -> Tuple[str, str]:
    ch = _cell_html(row_html, data_stat)
    if not ch:
        return "", ""
    m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', ch, flags=re.IGNORECASE)
    if not m:
        return _clean_cell_text(ch), ""
    return _clean_cell_text(m.group(2)), str(m.group(1) or "").strip()


def _bref_abs_url(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://www.baseball-reference.com{raw}"


def _load_bref_team_batting_supplement(season: str) -> Dict[str, Dict[str, Any]]:
    ck = ("team_batting", str(season))
    if ck in _BREF_SUPP_CACHE:
        return dict(_BREF_SUPP_CACHE.get(ck) or {})
    url = f"https://www.baseball-reference.com/leagues/majors/{season}-standard-batting.shtml"
    html_txt = _http_get_text(url, timeout=35)
    table_html = _extract_table_html(html_txt, "teams_standard_batting")
    out: Dict[str, Dict[str, Any]] = {}
    if not table_html:
        return out
    for row in _iter_table_rows(table_html):
        team_name, team_href = _cell_link(row, "team_name")
        if not team_name:
            continue
        abbr = ""
        m = re.search(r"/teams/([A-Z]{2,3})/", team_href)
        if m:
            abbr = m.group(1).upper()
        avg = _safe_float(_cell_text(row, "batting_avg"))
        slg = _safe_float(_cell_text(row, "slugging_perc"))
        iso = (slg - avg) if (slg is not None and avg is not None) else None
        hr = _safe_float(_cell_text(row, "HR"))
        bb = _safe_float(_cell_text(row, "BB"))
        gms = _safe_float(_cell_text(row, "G"))
        out[_norm_text(team_name)] = {
            "team_name": team_name,
            "abbr": abbr,
            "runs_per_game": _safe_float(_cell_text(row, "runs_per_game")),
            "ops": _safe_float(_cell_text(row, "onbase_plus_slugging")),
            "obp": _safe_float(_cell_text(row, "onbase_perc")),
            "slg": slg,
            "avg": avg,
            "iso": iso,
            "hr_per_game": (hr / gms) if (hr is not None and gms and gms > 0) else None,
            "bb_per_game": (bb / gms) if (bb is not None and gms and gms > 0) else None,
        }
    _BREF_SUPP_CACHE[ck] = dict(out)
    return out


def _load_bref_pitcher_supplement(season: str) -> Dict[Tuple[str, str], Dict[str, Any]]:
    ck = ("pitcher", str(season))
    if ck in _BREF_SUPP_CACHE:
        return dict(_BREF_SUPP_CACHE.get(ck) or {})
    url = f"https://www.baseball-reference.com/leagues/majors/{season}-standard-pitching.shtml"
    html_txt = _http_get_text(url, timeout=35)
    table_html = _extract_table_html(html_txt, "players_standard_pitching")
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if not table_html:
        return out
    for row in _iter_table_rows(table_html):
        name, _href = _cell_link(row, "name_display")
        team_abbr = _cell_text(row, "team_name_abbr").upper()
        if not name or not team_abbr:
            continue
        key = (_norm_text(name), team_abbr)
        out[key] = {
            "era": _safe_float(_cell_text(row, "p_earned_run_avg")),
            "fip": _safe_float(_cell_text(row, "p_fip")),
            "whip": _safe_float(_cell_text(row, "p_whip")),
            "innings": _mlb_ip_to_float(_cell_text(row, "p_ip")),
            "hr_per_fb": None,
            "babip": None,
            "bb_rate": None,
            "k_rate": None,
        }
    _BREF_SUPP_CACHE[ck] = dict(out)
    return out


def _load_bref_catcher_supplement(season: str) -> Dict[str, Dict[str, Any]]:
    ck = ("catcher", str(season))
    if ck in _BREF_SUPP_CACHE:
        return dict(_BREF_SUPP_CACHE.get(ck) or {})
    url = f"https://www.baseball-reference.com/leagues/majors/{season}-team-starting-lineups.shtml"
    html_txt = _http_get_text(url, timeout=35)
    table_html = _extract_table_html(html_txt, "starters")
    out: Dict[str, Dict[str, Any]] = {}
    if not table_html:
        return out
    for row in _iter_table_rows(table_html):
        team_name, _team_href = _cell_link(row, "team_name")
        if not team_name:
            continue
        c_name, c_href = _cell_link(row, "c")
        csk = _safe_float(_cell_attr(row, "c", "csk"))
        if not c_href:
            continue
        framing_tier = "UNKNOWN"
        block_tier = "UNKNOWN"
        arm_tier = "UNKNOWN"
        if csk is not None:
            framing_tier = "ELITE" if csk >= 1.5 else ("ABOVE_AVG" if csk >= 0.6 else ("BELOW_AVG" if csk <= -0.6 else "AVG"))
            block_tier = "ABOVE_AVG" if csk >= 0.6 else ("BELOW_AVG" if csk <= -0.6 else "AVG")
            arm_tier = "ABOVE_AVG" if csk >= 0.6 else ("BELOW_AVG" if csk <= -0.6 else "AVG")
        impact_base = 0.5
        if csk is not None:
            impact_base = max(0.0, min(1.0, 0.5 + (csk / 4.0)))
        out[_norm_text(team_name)] = {
            "catcher_name_bref": c_name,
            "framing_tier": framing_tier,
            "block_tier": block_tier,
            "arm_tier": arm_tier,
            "catcher_impact": round(float(impact_base), 4),
            "extra_strikes_per100": csk,
        }
    _BREF_SUPP_CACHE[ck] = dict(out)
    return out


def _first_stat_split(payload: Dict[str, Any], team_id: str = "") -> Dict[str, Any]:
    tid = str(team_id or "").strip()
    for stat_group in payload.get("stats", []) or []:
        for split in stat_group.get("splits", []) or []:
            if tid:
                got = str((((split.get("team") or {}).get("id")) or "")).strip()
                if got and got != tid:
                    continue
            stat = split.get("stat") or {}
            if isinstance(stat, dict) and stat:
                return stat
    return {}


def _iter_stat_splits(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for stat_group in payload.get("stats", []) or []:
        for split in stat_group.get("splits", []) or []:
            if isinstance(split, dict):
                yield split


def _team_stats_payload(team_id: str, group: str, season: str, stats: str = "season", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = {"stats": stats, "group": group, "season": season, "gameType": "R"}
    params.update(extra or {})
    try:
        payload = _mlb_api_json(f"teams/{team_id}/stats", params)
        if _first_stat_split(payload, team_id):
            return payload
        return payload
    except Exception:
        # Some Stats API mirrors expose team stats through the collection endpoint only.
        params["teamId"] = team_id
        params["sportIds"] = 1
        return _mlb_api_json("teams/stats", params)


def _person_stats_payload(person_id: str, group: str, season: str, stats: str = "season") -> Dict[str, Any]:
    return _mlb_api_json(
        f"people/{person_id}/stats",
        {"stats": stats, "group": group, "season": season, "gameType": "R"},
    )


def _extract_team_handed_ops(team_id: str, season: str) -> Tuple[Optional[float], Optional[float]]:
    """Return batting OPS vs RHP and vs LHP when MLB exposes the split."""
    params = {
        "stats": "statSplits",
        "group": "hitting",
        "season": season,
        "gameType": "R",
        "sitCodes": "vr,vl",
    }
    try:
        payload = _team_stats_payload(team_id, "hitting", season, stats="statSplits", extra={"sitCodes": "vr,vl"})
    except Exception:
        try:
            params.update({"teamId": team_id, "sportIds": 1})
            payload = _mlb_api_json("teams/stats", params)
        except Exception:
            return None, None

    ops_vs_rhp: Optional[float] = None
    ops_vs_lhp: Optional[float] = None
    for split in _iter_stat_splits(payload):
        stat = split.get("stat") or {}
        split_meta = split.get("split") or split.get("type") or {}
        text = json.dumps(split_meta, sort_keys=True).lower()
        ops = _safe_float(stat.get("ops"))
        if ops is None:
            continue
        if any(token in text for token in ('"vr"', " vs rhp", "vs right", "right-handed", "right handed")):
            ops_vs_rhp = ops
        if any(token in text for token in ('"vl"', " vs lhp", "vs left", "left-handed", "left handed")):
            ops_vs_lhp = ops
    return ops_vs_rhp, ops_vs_lhp


def _extract_team_home_away_ops(team_id: str, season: str) -> Tuple[Optional[float], Optional[float]]:
    """Return team OPS at home and away when MLB exposes those splits."""
    try:
        payload = _team_stats_payload(team_id, "hitting", season, stats="statSplits", extra={"sitCodes": "h,a"})
    except Exception:
        return None, None

    ops_home: Optional[float] = None
    ops_away: Optional[float] = None
    for split in _iter_stat_splits(payload):
        stat = split.get("stat") or {}
        split_meta = split.get("split") or split.get("type") or {}
        text = json.dumps(split_meta, sort_keys=True).lower()
        ops = _safe_float(stat.get("ops"))
        if ops is None:
            continue
        if any(token in text for token in ('"h"', "home")):
            ops_home = ops
        if any(token in text for token in ('"a"', "away")):
            ops_away = ops
    return ops_home, ops_away


def _recent_team_runs(team_id: str, data_date: str) -> Optional[float]:
    try:
        run_day = datetime.strptime(data_date, "%Y-%m-%d").date()
    except Exception:
        return None
    start = run_day - timedelta(days=14)
    end = run_day - timedelta(days=1)
    if end < start:
        return None
    try:
        payload = _mlb_api_json(
            "schedule",
            {
                "sportId": 1,
                "teamId": team_id,
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "hydrate": "linescore",
            },
        )
    except Exception:
        return None
    runs: List[float] = []
    for d in payload.get("dates", []) or []:
        for g in d.get("games", []) or []:
            status = str((((g.get("status") or {}).get("abstractGameState")) or "")).lower()
            if status and status != "final":
                continue
            teams = g.get("teams") or {}
            for side in ("away", "home"):
                block = teams.get(side) or {}
                if str((((block.get("team") or {}).get("id")) or "")).strip() != str(team_id):
                    continue
                score = _safe_float(block.get("score"))
                if score is not None:
                    runs.append(score)
    return (sum(runs) / len(runs)) if runs else None


def _last3_pitching_context(person_id: str, season: str, data_date: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        run_day = datetime.strptime(data_date, "%Y-%m-%d").date()
    except Exception:
        run_day = None
    try:
        payload = _person_stats_payload(person_id, "pitching", season, stats="gameLog")
    except Exception:
        return None, None, None
    games: List[Tuple[date, Dict[str, Any]]] = []
    for split in _iter_stat_splits(payload):
        game_date_raw = str(split.get("date") or split.get("gameDate") or "")
        try:
            game_day = datetime.strptime(game_date_raw[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if run_day is not None and game_day >= run_day:
            continue
        stat = split.get("stat") or {}
        if not isinstance(stat, dict):
            continue
        ip = _mlb_ip_to_float(stat.get("inningsPitched"))
        if ip is None or ip <= 0:
            continue
        games.append((game_day, stat))
    games.sort(key=lambda x: x[0], reverse=True)
    last3 = [g[1] for g in games[:3]]
    if not last3:
        return None, None, None
    total_ip = 0.0
    total_er = 0.0
    pitch_counts: List[float] = []
    for stat in last3:
        ip = _mlb_ip_to_float(stat.get("inningsPitched"))
        er = _safe_float(stat.get("earnedRuns"))
        if ip is not None:
            total_ip += ip
        if er is not None:
            total_er += er
        pc = _safe_float(stat.get("numberOfPitches"))
        if pc is None:
            pc = _safe_float(stat.get("pitchesThrown"))
        if pc is not None:
            pitch_counts.append(pc)
    era_last3 = (total_er * 9.0 / total_ip) if total_ip > 0 else None
    avg_pc_last3 = (sum(pitch_counts) / len(pitch_counts)) if pitch_counts else None
    avg_ip_last3 = (total_ip / len(last3)) if last3 else None
    return era_last3, avg_pc_last3, avg_ip_last3


def load_schedule_from_source(data_date: str) -> List[GameRow]:
    """
    Canonical schedule source: MLB Stats API.
    Never fabricate sample games.
    """
    q = urllib.parse.urlencode({"sportId": 1, "date": data_date, "hydrate": "probablePitcher"})
    url = f"https://statsapi.mlb.com/api/v1/schedule?{q}"
    payload = _mlb_api_json(url, timeout=20)
    out: List[GameRow] = []
    for d in payload.get("dates", []) or []:
        for g in d.get("games", []) or []:
            teams = g.get("teams") or {}
            away_block = teams.get("away") or {}
            home_block = teams.get("home") or {}
            away_team_obj = (away_block.get("team") or {})
            home_team_obj = (home_block.get("team") or {})
            away_probable = away_block.get("probablePitcher") or {}
            home_probable = home_block.get("probablePitcher") or {}
            away = away_team_obj.get("name") or ""
            home = home_team_obj.get("name") or ""
            if not away or not home:
                continue
            out.append(
                GameRow(
                    game_id=str(g.get("gamePk") or ""),
                    away_team=str(away).strip(),
                    home_team=str(home).strip(),
                    game_time_utc=str(g.get("gameDate") or ""),
                    away_starter=str((away_probable.get("fullName") or "")).strip(),
                    home_starter=str((home_probable.get("fullName") or "")).strip(),
                    away_team_id=str(away_team_obj.get("id") or "").strip(),
                    home_team_id=str(home_team_obj.get("id") or "").strip(),
                    away_starter_id=str(away_probable.get("id") or "").strip(),
                    home_starter_id=str(home_probable.get("id") or "").strip(),
                )
            )
    if not out:
        raise RuntimeError(f"No MLB schedule games returned for {data_date}")
    return out


def _latest_team_stats_map(base_dir: Path) -> Dict[str, Dict[str, Any]]:
    for db_path in _candidate_db_paths(base_dir):
        if not db_path.exists():
            continue
        try:
            con = sqlite3.connect(db_path)
            try:
                rows = con.execute(
                    """
                    SELECT team_name, ops_vs_rhp, ops_vs_lhp, bullpen_era, runs_per_game
                    FROM team_stats
                    ORDER BY fetched_date DESC, id DESC
                    """
                ).fetchall()
            finally:
                con.close()
        except Exception:
            continue
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            t = str(r[0] or "").strip()
            if not t or t in out:
                continue
            out[t] = {
                "wins": None,
                "losses": None,
                "ops_vs_rhp": r[1],
                "ops_vs_lhp": r[2],
                "bullpen_era": r[3],
                "runs_per_game": r[4],
            }
        if out:
            return out
    return {}


def load_team_stats_from_source(base_dir: Path, data_date: str, schedule: List[GameRow]) -> List[Dict[str, Any]]:
    season = data_date[:4]
    team_ids: Dict[str, str] = {}
    for g in schedule:
        if g.away_team:
            team_ids[g.away_team] = g.away_team_id
        if g.home_team:
            team_ids[g.home_team] = g.home_team_id
    teams = sorted(team_ids)
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    bref_team_supp: Dict[str, Dict[str, Any]] = {}
    try:
        bref_team_supp = _load_bref_team_batting_supplement(season)
    except Exception as exc:
        LOG.warning("Baseball-Reference team supplement unavailable: %s", exc)
    for team in teams:
        team_id = str(team_ids.get(team) or "").strip()
        if not team_id:
            missing.append(f"{team} (missing MLB team id)")
            continue
        try:
            hitting_payload = _team_stats_payload(team_id, "hitting", season, stats="season")
            hitting = _first_stat_split(hitting_payload, team_id)
            pitching_payload = _team_stats_payload(team_id, "pitching", season, stats="season")
            pitching = _first_stat_split(pitching_payload, team_id)
            ops_vs_rhp, ops_vs_lhp = _extract_team_handed_ops(team_id, season)
            ops_home, ops_away = _extract_team_home_away_ops(team_id, season)
        except Exception as exc:
            missing.append(f"{team} ({exc})")
            continue

        games = _safe_float(hitting.get("gamesPlayed"))
        runs = _safe_float(hitting.get("runs"))
        home_runs = _safe_float(hitting.get("homeRuns"))
        walks = _safe_float(hitting.get("baseOnBalls"))
        runs_per_game = (runs / games) if games and games > 0 and runs is not None else None
        hr_per_game = (home_runs / games) if games and games > 0 and home_runs is not None else None
        bb_per_game = (walks / games) if games and games > 0 and walks is not None else None
        ops = _safe_float(hitting.get("ops"))
        obp = _safe_float(hitting.get("obp"))
        slg = _safe_float(hitting.get("slg"))
        avg = _safe_float(hitting.get("avg"))
        iso = _safe_float(hitting.get("iso"))
        if iso is None and slg is not None and avg is not None:
            iso = max(0.0, slg - avg)
        xwoba = _safe_float(hitting.get("xwoba"))
        hard_hit_pct = _safe_float(hitting.get("hardHitPercent"))
        barrel_pct = _safe_float(hitting.get("barrelsPerPlateAppearance"))
        avg_exit_velo = _safe_float(hitting.get("avgExitVelocity"))
        runs_last14 = _recent_team_runs(team_id, data_date)

        sup = bref_team_supp.get(_norm_text(team), {})
        if runs_per_game is None:
            runs_per_game = _safe_float(sup.get("runs_per_game"))
        if ops is None:
            ops = _safe_float(sup.get("ops"))
        if obp is None:
            obp = _safe_float(sup.get("obp"))
        if slg is None:
            slg = _safe_float(sup.get("slg"))
        if avg is None:
            avg = _safe_float(sup.get("avg"))
        if iso is None:
            iso = _safe_float(sup.get("iso"))
        if hr_per_game is None:
            hr_per_game = _safe_float(sup.get("hr_per_game"))
        if bb_per_game is None:
            bb_per_game = _safe_float(sup.get("bb_per_game"))

        if ops is None and runs_per_game is None and ops_vs_rhp is None and ops_vs_lhp is None:
            missing.append(team)
            continue
        rows.append(
            {
                "data_date": data_date,
                "team": team,
                "wins": None,
                "losses": None,
                "ops_vs_rhp": ops_vs_rhp,
                "ops_vs_lhp": ops_vs_lhp,
                "bullpen_era": None,
                "runs_per_game": runs_per_game,
                "xwoba": xwoba,
                "hard_hit_pct": hard_hit_pct,
                "ops": ops,
                "obp": obp,
                "slg": slg,
                "avg": avg,
                "iso": iso,
                "barrel_pct": barrel_pct,
                "avg_exit_velo": avg_exit_velo,
                "hr_per_game": hr_per_game,
                "bb_per_game": bb_per_game,
                "ops_home": ops_home,
                "ops_away": ops_away,
                "ops_last14": None,
                "runs_last14": runs_last14,
                "bullpen_era_7d": None,
                "bullpen_ip_3d": None,
            }
        )
    if missing:
        raise RuntimeError(
            "Missing live MLB team stats for "
            f"{len(missing)} team(s): {', '.join(missing[:12])}"
        )
    return rows


def _latest_starter_by_team_map(base_dir: Path) -> Dict[str, Dict[str, Any]]:
    for db_path in _candidate_db_paths(base_dir):
        if not db_path.exists():
            continue
        try:
            con = sqlite3.connect(db_path)
            try:
                rows = con.execute(
                    """
                    SELECT team_name, player_name, throws, era, whip, k_pct, bb_pct, xwoba_against
                    FROM starter_stats
                    ORDER BY fetched_date DESC, id DESC
                    """
                ).fetchall()
            finally:
                con.close()
        except Exception:
            continue
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            t = str(r[0] or "").strip()
            if not t or t in out:
                continue
            out[t] = {
                "starter_name": str(r[1] or "").strip(),
                "hand": str(r[2] or "").strip(),
                "era": r[3],
                "whip": r[4],
                "k_rate": r[5],
                "bb_rate": r[6],
                "xwoba": r[7],
            }
        if out:
            return out
    return {}


def load_starter_stats_from_source(base_dir: Path, data_date: str, schedule: List[GameRow]) -> List[Dict[str, Any]]:
    season = data_date[:4]
    schedule_starters: Dict[str, Tuple[str, str]] = {}
    for g in schedule:
        if g.away_team:
            schedule_starters[g.away_team] = (g.away_starter, g.away_starter_id)
        if g.home_team:
            schedule_starters[g.home_team] = (g.home_starter, g.home_starter_id)
    teams = sorted(schedule_starters)
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    team_abbr_by_name: Dict[str, str] = {}
    bref_pitcher_supp: Dict[Tuple[str, str], Dict[str, Any]] = {}
    try:
        _team_supp = _load_bref_team_batting_supplement(season)
        for team_key, row in _team_supp.items():
            team_name = str(row.get("team_name") or "").strip()
            abbr = str(row.get("abbr") or "").strip().upper()
            if team_name and abbr:
                team_abbr_by_name[team_name] = abbr
            if team_key and abbr:
                team_abbr_by_name[team_key] = abbr
    except Exception as exc:
        LOG.warning("Baseball-Reference team-abbr supplement unavailable: %s", exc)
    try:
        bref_pitcher_supp = _load_bref_pitcher_supplement(season)
    except Exception as exc:
        LOG.warning("Baseball-Reference starter supplement unavailable: %s", exc)
    _arsenal_cache: Dict[str, Optional[float]] = {}

    def _starter_avg_velo_from_arsenal(person_id: str) -> Optional[float]:
        pid = str(person_id or "").strip()
        if not pid:
            return None
        if pid in _arsenal_cache:
            return _arsenal_cache[pid]
        try:
            payload = _mlb_api_json(
                f"people/{pid}/stats",
                {"group": "pitching", "stats": "pitchArsenal", "season": season, "gameType": "R"},
            )
            total_w = 0.0
            total_v = 0.0
            for split in _iter_stat_splits(payload):
                stat = split.get("stat") or {}
                speed = _safe_float(stat.get("averageSpeed"))
                count = _safe_float(stat.get("count"))
                if speed is None:
                    continue
                w = count if (count is not None and count > 0) else 1.0
                total_w += w
                total_v += (speed * w)
            out = (total_v / total_w) if total_w > 0 else None
            _arsenal_cache[pid] = out
            return out
        except Exception:
            _arsenal_cache[pid] = None
            return None

    def _fallback_row(team_name: str, starter_name: str = "TBD", hand: str = "R") -> Dict[str, Any]:
        # Keep the pipeline model-safe when a probable pitcher is not posted yet.
        # Conservative baselines avoid nulls and allow split calculations to proceed.
        return {
            "data_date": data_date,
            "team": team_name,
            "starter_name": starter_name or "TBD",
            "hand": hand,
            "era": 4.35,
            "fip": None,
            "xfip": None,
            "whip": 1.30,
            "innings": None,
            "k_rate": 21.0,
            "bb_rate": 8.0,
            "k_minus_bb": 13.0,
            "xwoba": None,
            "gb_pct": 42.0,
            "fb_pct": 38.0,
            "hr_per_fb": None,
            "babip": None,
            "avg_velo": None,
            "avg_spin": None,
            "whiff_pct": None,
            "hard_hit_pct": None,
            "fly_ball_exposure": 0.38,
            "density_sensitivity": None,
            "era_last3": 4.35,
            "avg_pc_last3": 88.0,
            "avg_ip_last3": 5.2,
        }
    for team in teams:
        starter_name, starter_id = schedule_starters.get(team, ("", ""))
        starter_name = str(starter_name or "").strip()
        starter_id = str(starter_id or "").strip()
        if not starter_name or not starter_id:
            missing.append(f"{team} (probable pitcher not posted)")
            rows.append(_fallback_row(team))
            continue
        try:
            person_payload = _mlb_api_json(f"people/{starter_id}")
            person = ((person_payload.get("people") or [{}])[0] or {})
            season_payload = _person_stats_payload(starter_id, "pitching", season, stats="season")
            stat = _first_stat_split(season_payload)
            season_adv_payload = _person_stats_payload(starter_id, "pitching", season, stats="seasonAdvanced")
            stat_adv = _first_stat_split(season_adv_payload)
        except Exception as exc:
            missing.append(f"{team}: {starter_name} ({exc})")
            rows.append(_fallback_row(team, starter_name=starter_name or "TBD"))
            continue
        hand = str((((person.get("pitchHand") or {}).get("code")) or "")).strip().upper()
        batters_faced = _safe_float(stat.get("battersFaced"))
        strikeouts = _safe_float(stat.get("strikeOuts"))
        walks = _safe_float(stat.get("baseOnBalls"))
        hit_batsmen = _safe_float(stat.get("hitBatsmen"))
        home_runs = _safe_float(stat.get("homeRuns"))
        ground_outs = _safe_float(stat.get("groundOuts"))
        air_outs = _safe_float(stat.get("airOuts"))
        gb_denom = (ground_outs or 0.0) + (air_outs or 0.0)
        k_pct = (strikeouts * 100.0 / batters_faced) if strikeouts is not None and batters_faced and batters_faced > 0 else None
        bb_pct = (walks * 100.0 / batters_faced) if walks is not None and batters_faced and batters_faced > 0 else None
        gb_pct = (ground_outs * 100.0 / gb_denom) if ground_outs is not None and gb_denom > 0 else None
        fb_pct = (air_outs * 100.0 / gb_denom) if air_outs is not None and gb_denom > 0 else None
        era_last3, avg_pc_last3, avg_ip_last3 = _last3_pitching_context(starter_id, season, data_date)
        era = _safe_float(stat.get("era"))
        fip = _safe_float(stat.get("fip"))
        xfip = _safe_float(stat.get("xfip"))
        whip = _safe_float(stat.get("whip"))
        innings = _mlb_ip_to_float(stat.get("inningsPitched"))
        # Normalize sparse early-season stat lines to non-null conservative defaults.
        if era is None:
            era = 4.35
        if whip is None:
            whip = 1.30
        if k_pct is None:
            k_pct = 21.0
        if bb_pct is None:
            bb_pct = 8.0
        if gb_pct is None:
            gb_pct = 42.0
        if fb_pct is None:
            fb_pct = 38.0
        k_minus_bb = (k_pct - bb_pct) if (k_pct is not None and bb_pct is not None) else None
        hr_per_fb = _safe_float(stat.get("homeRunFlyBallRate"))
        babip = _safe_float(stat.get("babip"))
        avg_velo = _safe_float(stat.get("avgFastballVelocity"))
        avg_spin = _safe_float(stat.get("spinRate"))
        whiff_pct = _safe_float(stat.get("whiffPercent"))
        hard_hit_pct = _safe_float(stat.get("hardHitPercent"))
        # Fill sparse fields from seasonAdvanced when season payload omits them.
        if babip is None:
            babip = _safe_float(stat_adv.get("babip"))
        if whiff_pct is None:
            whiff_pct = _safe_float(stat_adv.get("whiffPercentage"))
        if k_minus_bb is None:
            k_minus_bb = _safe_float(stat_adv.get("strikeoutsMinusWalksPercentage"))
        if fb_pct is None:
            fb_pct = _safe_float(stat_adv.get("flyBallPercentage"))
        if k_pct is None:
            _kppa = _safe_float(stat_adv.get("strikeoutsPerPlateAppearance"))
            if _kppa is not None:
                k_pct = _kppa * 100.0
        if bb_pct is None:
            _bbpa = _safe_float(stat_adv.get("walksPerPlateAppearance"))
            if _bbpa is not None:
                bb_pct = _bbpa * 100.0
        if avg_velo is None:
            avg_velo = _starter_avg_velo_from_arsenal(starter_id)

        # Derive FIP/xFIP when upstream leaves them blank.
        if (fip is None or xfip is None or hr_per_fb is None) and innings and innings > 0:
            fb_outs = _safe_float(stat_adv.get("flyOuts"))
            fb_hits = _safe_float(stat_adv.get("flyHits"))
            fb_total = (fb_outs or 0.0) + (fb_hits or 0.0)
            if fb_total <= 0 and air_outs is not None and home_runs is not None:
                fb_total = max(0.0, float(air_outs) + float(home_runs))
            if hr_per_fb is None and home_runs is not None and fb_total > 0:
                hr_per_fb = (100.0 * float(home_runs) / float(fb_total))
            _bb_hbp = (walks or 0.0) + (hit_batsmen or 0.0)
            _k = strikeouts or 0.0
            _hr = home_runs or 0.0
            _fip_const = 3.2
            if fip is None:
                fip = ((13.0 * _hr + 3.0 * _bb_hbp - 2.0 * _k) / float(innings)) + _fip_const
            if xfip is None and fb_total > 0:
                _lg_hr_fb = 0.105
                _xhr = float(fb_total) * _lg_hr_fb
                xfip = ((13.0 * _xhr + 3.0 * _bb_hbp - 2.0 * _k) / float(innings)) + _fip_const

        team_abbr = str(team_abbr_by_name.get(team) or team_abbr_by_name.get(_norm_text(team)) or "").upper()
        supp = bref_pitcher_supp.get((_norm_text(starter_name), team_abbr), {}) if team_abbr else {}
        if era is None:
            era = _safe_float(supp.get("era"))
        if fip is None:
            fip = _safe_float(supp.get("fip"))
        if whip is None:
            whip = _safe_float(supp.get("whip"))
        if innings is None:
            innings = _safe_float(supp.get("innings"))
        if hr_per_fb is None:
            hr_per_fb = _safe_float(supp.get("hr_per_fb"))
        if babip is None:
            babip = _safe_float(supp.get("babip"))
        if k_pct is None:
            k_pct = _safe_float(supp.get("k_rate"))
        if bb_pct is None:
            bb_pct = _safe_float(supp.get("bb_rate"))
        fly_ball_exposure = (fb_pct / 100.0) if fb_pct is not None else None
        rows.append(
            {
                "data_date": data_date,
                "team": team,
                "starter_name": starter_name,
                "hand": hand,
                "era": era,
                "fip": fip,
                "xfip": xfip,
                "whip": whip,
                "innings": innings,
                "k_rate": k_pct,
                "bb_rate": bb_pct,
                "k_minus_bb": k_minus_bb,
                "xwoba": None,
                "gb_pct": gb_pct,
                "fb_pct": fb_pct,
                "hr_per_fb": hr_per_fb,
                "babip": babip,
                "avg_velo": avg_velo,
                "avg_spin": avg_spin,
                "whiff_pct": whiff_pct,
                "hard_hit_pct": hard_hit_pct,
                "fly_ball_exposure": fly_ball_exposure,
                "density_sensitivity": None,
                "era_last3": era_last3,
                "avg_pc_last3": avg_pc_last3,
                "avg_ip_last3": avg_ip_last3,
            }
        )
    if missing:
        LOG.warning(
            "Starter fallback used for %d team(s): %s",
            len(missing),
            ", ".join(missing[:12]),
        )
    return rows


def load_catcher_stats_from_source(base_dir: Path, data_date: str, schedule: List[GameRow]) -> Dict[str, Dict[str, Any]]:
    """
    Build per-team catcher assignments from the RotoWire lineup pipeline.
    Hard-fails when any scheduled team has no catcher so model safety cannot
    pass with silent catcher gaps.
    """
    if not schedule:
        return {}
    odds_dir = Path(__file__).resolve().parent / "odds_data"
    rw_mod_path = odds_dir / "rotowire_lineup_scraper.py"
    if not rw_mod_path.exists():
        raise RuntimeError(f"Missing required catcher source module: {rw_mod_path}")

    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("rotowire_lineup_scraper", str(rw_mod_path))
    if _spec is None or _spec.loader is None:
        raise RuntimeError("Unable to load rotowire_lineup_scraper module")
    _rw = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_rw)

    # Ensure today's cache is populated before lookups.
    try:
        _rw.run(print_summary=False)
    except Exception:
        pass

    out: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    season = str(data_date)[:4]
    bref_catcher_supp: Dict[str, Dict[str, Any]] = {}
    try:
        bref_catcher_supp = _load_bref_catcher_supplement(season)
    except Exception as exc:
        LOG.warning("Baseball-Reference catcher supplement unavailable: %s", exc)
    teams_expected = sorted({g.away_team for g in schedule} | {g.home_team for g in schedule})
    team_ids: Dict[str, str] = {}
    for g in schedule:
        if g.away_team and g.away_team_id:
            team_ids[g.away_team] = g.away_team_id
        if g.home_team and g.home_team_id:
            team_ids[g.home_team] = g.home_team_id

    _gp_cache: Dict[str, int] = {}

    def _player_games_played(player_id: str, season: str) -> int:
        pid = str(player_id or "").strip()
        if not pid:
            return -1
        if pid in _gp_cache:
            return _gp_cache[pid]
        try:
            payload = _mlb_api_json(
                f"people/{pid}/stats",
                {"stats": "season", "group": "hitting", "season": season},
            )
            splits = (((payload or {}).get("stats") or [{}])[0].get("splits") or [])
            st = ((splits[0] or {}).get("stat") or {}) if splits else {}
            gp = _safe_int(st.get("gamesPlayed"))
            _gp_cache[pid] = gp if gp is not None else -1
            return _gp_cache[pid]
        except Exception:
            _gp_cache[pid] = -1
            return -1

    def _fallback_catcher_from_team(team_name: str) -> str:
        team_id = str(team_ids.get(team_name, "") or "").strip()
        if not team_id:
            return ""
        season = str(data_date)[:4]
        try:
            payload = _mlb_api_json(
                f"teams/{team_id}/roster",
                {"rosterType": "active", "season": season},
            )
            roster = (payload or {}).get("roster") or []
            candidates = []
            for row in roster:
                person = (row or {}).get("person") or {}
                pos = (row or {}).get("position") or {}
                ab = str(pos.get("abbreviation") or "").upper().strip()
                if ab != "C":
                    continue
                pid = str(person.get("id") or "").strip()
                pname = str(person.get("fullName") or "").strip()
                if not pname:
                    continue
                gp = _player_games_played(pid, season)
                candidates.append((gp, pname))
            if not candidates:
                return ""
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        except Exception:
            return ""

    for g in schedule:
        rec = None
        try:
            rec = _rw.get_lineup_for_teams(g.away_team, g.home_team, game_date=data_date)
        except Exception:
            rec = None
        if not rec:
            continue

        merged = _rw.merge_with_mlb_api({}, rec)
        away_c = str(merged.get("away_catcher_name", "") or "").strip()
        home_c = str(merged.get("home_catcher_name", "") or "").strip()
        away_st = str(merged.get("rw_away_lineup_status", "") or "").upper()
        home_st = str(merged.get("rw_home_lineup_status", "") or "").upper()

        if away_c:
            out[g.away_team] = {
                "team": g.away_team,
                "catcher_name": away_c,
                "lineup_status": away_st or "UNKNOWN",
                "lineup_confirmed": 1 if away_st == "CONFIRMED" else 0,
            }
        if home_c:
            out[g.home_team] = {
                "team": g.home_team,
                "catcher_name": home_c,
                "lineup_status": home_st or "UNKNOWN",
                "lineup_confirmed": 1 if home_st == "CONFIRMED" else 0,
            }

    # Fill any team still missing catcher with MLB API roster fallback.
    for t in teams_expected:
        if t in out and str((out[t] or {}).get("catcher_name", "")).strip():
            continue
        fb = _fallback_catcher_from_team(t)
        if fb:
            out[t] = {
                "team": t,
                "catcher_name": fb,
                "lineup_status": "FALLBACK_ROSTER",
                "lineup_confirmed": 0,
            }

    for t in teams_expected:
        if t not in out:
            missing.append(t)
    if missing:
        raise RuntimeError(
            "Missing catcher assignments for "
            f"{len(missing)} team(s): {', '.join(missing[:12])}"
        )
    _roster_cache: Dict[str, List[Dict[str, Any]]] = {}
    _field_cache: Dict[str, Dict[str, Any]] = {}

    def _team_roster(team_name: str) -> List[Dict[str, Any]]:
        tid = str(team_ids.get(team_name, "") or "").strip()
        if not tid:
            return []
        if tid in _roster_cache:
            return _roster_cache[tid]
        try:
            payload = _mlb_api_json(
                f"teams/{tid}/roster",
                {"rosterType": "active", "season": season},
            )
            _roster_cache[tid] = (payload or {}).get("roster") or []
        except Exception:
            _roster_cache[tid] = []
        return _roster_cache[tid]

    def _resolve_catcher_id(team_name: str, catcher_name: str) -> str:
        cname_key = _norm_text(catcher_name)
        if not cname_key:
            return ""
        roster = _team_roster(team_name)
        if not roster:
            return ""
        last_tok = cname_key.split(" ")[-1] if cname_key else ""
        for row in roster:
            person = (row or {}).get("person") or {}
            pname = str(person.get("fullName") or "").strip()
            pkey = _norm_text(pname)
            if not pkey:
                continue
            if pkey == cname_key:
                return str(person.get("id") or "")
            if last_tok and pkey.split(" ")[-1] == last_tok:
                pos = str(((row or {}).get("position") or {}).get("abbreviation") or "").upper().strip()
                if pos == "C":
                    return str(person.get("id") or "")
        return ""

    def _catcher_fielding_stats(player_id: str) -> Dict[str, Any]:
        pid = str(player_id or "").strip()
        if not pid:
            return {}
        if pid in _field_cache:
            return _field_cache[pid]
        out_stats: Dict[str, Any] = {}
        try:
            payload = _mlb_api_json(
                f"people/{pid}/stats",
                {"stats": "season", "group": "fielding", "season": season},
            )
            splits = (((payload or {}).get("stats") or [{}])[0].get("splits") or [])
            best = {}
            best_gp = -1.0
            for split in splits:
                stat = (split or {}).get("stat") or {}
                pos = str((((split or {}).get("position") or {}).get("abbreviation") or "")).upper().strip()
                if not pos:
                    pos = str((((stat.get("position") or {}) if isinstance(stat, dict) else {}).get("abbreviation")) or "").upper().strip()
                if pos != "C":
                    continue
                gp = _safe_float(stat.get("gamesPlayed")) or -1.0
                if gp > best_gp:
                    best_gp = gp
                    best = stat
            if best:
                out_stats = {
                    "cs": _safe_float(best.get("caughtStealing")),
                    "sb": _safe_float(best.get("stolenBases")),
                    "pb": _safe_float(best.get("passedBall")),
                    "fielding": _safe_float(best.get("fielding")),
                    "games": _safe_float(best.get("gamesPlayed")),
                }
        except Exception:
            out_stats = {}
        _field_cache[pid] = out_stats
        return out_stats

    for team_name, crow in list(out.items()):
        pname = str((crow or {}).get("catcher_name") or "").strip()
        pid = _resolve_catcher_id(team_name, pname)
        fstats = _catcher_fielding_stats(pid) if pid else {}
        cs = _safe_float(fstats.get("cs"))
        sb = _safe_float(fstats.get("sb"))
        pb = _safe_float(fstats.get("pb"))
        fld = _safe_float(fstats.get("fielding"))
        gp = _safe_float(fstats.get("games"))
        cs_pct = (100.0 * cs / (cs + sb)) if (cs is not None and sb is not None and (cs + sb) > 0) else None
        pb_rate = (100.0 * pb / gp) if (pb is not None and gp and gp > 0) else None

        framing_tier = "UNKNOWN"
        block_tier = "UNKNOWN"
        arm_tier = "UNKNOWN"
        if fld is not None:
            framing_tier = "ELITE" if fld >= 0.995 else ("ABOVE_AVG" if fld >= 0.990 else ("BELOW_AVG" if fld <= 0.984 else "AVG"))
        if pb_rate is not None:
            block_tier = "ELITE" if pb_rate <= 2.0 else ("ABOVE_AVG" if pb_rate <= 4.0 else ("BELOW_AVG" if pb_rate >= 10.0 else "AVG"))
        if cs_pct is not None:
            arm_tier = "ELITE" if cs_pct >= 30.0 else ("ABOVE_AVG" if cs_pct >= 26.0 else ("BELOW_AVG" if cs_pct <= 21.0 else "AVG"))

        impact = 0.5
        if cs_pct is not None:
            impact = max(0.0, min(1.0, impact + ((cs_pct - 25.0) / 110.0)))
        if pb_rate is not None:
            impact = max(0.0, min(1.0, impact - (max(0.0, pb_rate - 5.0) / 30.0)))
        if fld is not None:
            impact = max(0.0, min(1.0, impact + ((fld - 0.989) * 8.0)))

        sup = bref_catcher_supp.get(_norm_text(team_name), {})
        if framing_tier == "UNKNOWN" and sup:
            framing_tier = str(sup.get("framing_tier") or framing_tier)
        if block_tier == "UNKNOWN" and sup:
            block_tier = str(sup.get("block_tier") or block_tier)
        if arm_tier == "UNKNOWN" and sup:
            arm_tier = str(sup.get("arm_tier") or arm_tier)
        if abs(float(impact) - 0.5) < 1e-9 and sup:
            sup_impact = _safe_float(sup.get("catcher_impact"))
            if sup_impact is not None:
                impact = sup_impact

        crow["framing_tier"] = framing_tier
        crow["block_tier"] = block_tier
        crow["arm_tier"] = arm_tier
        crow["catcher_impact"] = round(float(impact), 4)
        crow["extra_strikes_per100"] = _safe_float(sup.get("extra_strikes_per100"))
    return out


def collect_sources(cfg: BuilderConfig):
    sources = [
        make_source("schedule"),
        make_source("team_stats"),
        make_source("starter_stats"),
        make_source("catcher_stats"),
        make_source("baseball_savant", required=False),
    ]
    source_map = {s.name: s for s in sources}
    bundle = BuildBundle()

    def _mark_start(src_name: str):
        source_map[src_name].started_at = utc_now_iso()
        source_map[src_name].status = "RUNNING"

    def _mark_end(src_name: str, status: str, detail: str = "", records: int = 0, duration: float | None = None, error: str = ""):
        src = source_map[src_name]
        src.status = status
        src.detail = detail
        src.records = records
        src.completed_at = utc_now_iso()
        src.duration_sec = duration
        src.error = error

    _mark_start("schedule")
    schedule, dur, attempts, err = fetch_with_retry(
        "schedule", lambda: load_schedule_from_source(cfg.data_date), cfg.retry_limit, cfg.backoff_sec
    )
    if err:
        _mark_end("schedule", "FAILED", f"attempts={attempts}", 0, dur, str(err))
        bundle.source_notes["schedule_error"] = str(err)
        return bundle, sources
    bundle.schedule = schedule
    _mark_end("schedule", "READY", f"attempts={attempts}", len(schedule), dur)

    _mark_start("team_stats")
    team_stats, dur, attempts, err = fetch_with_retry(
        "team_stats", lambda: load_team_stats_from_source(cfg.base_dir, cfg.data_date, bundle.schedule), cfg.retry_limit, cfg.backoff_sec
    )
    if err:
        _mark_end("team_stats", "FAILED", f"attempts={attempts}", 0, dur, str(err))
    else:
        bundle.team_stats = team_stats
        _mark_end("team_stats", "READY", f"attempts={attempts}", len(team_stats), dur)

    _mark_start("starter_stats")
    starter_stats, dur, attempts, err = fetch_with_retry(
        "starter_stats", lambda: load_starter_stats_from_source(cfg.base_dir, cfg.data_date, bundle.schedule), cfg.retry_limit, cfg.backoff_sec
    )
    if err:
        _mark_end("starter_stats", "FAILED", f"attempts={attempts}", 0, dur, str(err))
    else:
        bundle.starter_stats = starter_stats
        _mark_end("starter_stats", "READY", f"attempts={attempts}", len(starter_stats), dur)

    _mark_start("catcher_stats")
    catcher_stats, dur, attempts, err = fetch_with_retry(
        "catcher_stats", lambda: load_catcher_stats_from_source(cfg.base_dir, cfg.data_date, bundle.schedule), cfg.retry_limit, cfg.backoff_sec
    )
    if err:
        _mark_end("catcher_stats", "FAILED", f"attempts={attempts}", 0, dur, str(err))
    else:
        bundle.catcher_by_team = catcher_stats
        _mark_end("catcher_stats", "READY", f"attempts={attempts}", len(catcher_stats), dur)

    source_map["baseball_savant"].status = "SKIPPED"
    source_map["baseball_savant"].detail = "Optional source hook; integrate behind same single-run lock"
    source_map["baseball_savant"].completed_at = utc_now_iso()
    return bundle, sources


def validate_bundle(bundle: BuildBundle) -> Tuple[List[str], List[str], Dict[str, Any]]:
    blocking: List[str] = []
    degraded: List[str] = []
    schedule = bundle.schedule
    teams_expected = sorted({g.away_team for g in schedule} | {g.home_team for g in schedule})
    team_map = {r["team"]: r for r in bundle.team_stats}
    starter_map = {r["team"]: r for r in bundle.starter_stats}
    catcher_map = dict(bundle.catcher_by_team or {})
    missing_teams = [t for t in teams_expected if t not in team_map]
    missing_starters = [t for t in teams_expected if t not in starter_map]
    missing_catchers = [t for t in teams_expected if t not in catcher_map]
    missing_matchups: List[str] = []

    if not schedule:
        _sched_err = str((bundle.source_notes or {}).get("schedule_error", "") or "").strip()
        _sched_err_lc = _sched_err.lower()
        _networkish = any(
            _k in _sched_err_lc
            for _k in (
                "ssl",
                "certificate",
                "cert verify failed",
                "timed out",
                "timeout",
                "temporary failure",
                "name resolution",
                "connection",
                "proxy",
                "urlopen error",
            )
        )
        if _networkish:
            degraded.append(
                "Schedule source unavailable (network/SSL). "
                "Run marked degraded with zero MLB games for this cycle."
            )
        else:
            blocking.append("No scheduled games returned")
    if missing_teams:
        degraded.append(f"Missing team stats for {len(missing_teams)} teams")
    if missing_starters:
        degraded.append(f"Missing starter stats for {len(missing_starters)} teams")
    if missing_catchers:
        blocking.append(f"Missing catcher stats for {len(missing_catchers)} teams")
    team_required = ("ops_vs_rhp", "ops_vs_lhp", "runs_per_game")
    starter_required = ("hand", "era", "whip", "k_rate", "bb_rate", "gb_pct", "fb_pct")
    missing_team_fields = [
        f"{r.get('team')}:{field}"
        for r in bundle.team_stats
        for field in team_required
        if r.get(field) is None or str(r.get(field)).strip() == ""
    ]
    missing_starter_fields = [
        f"{r.get('team')}:{field}"
        for r in bundle.starter_stats
        for field in starter_required
        if r.get(field) is None or str(r.get(field)).strip() == ""
    ]
    if missing_team_fields:
        degraded.append(
            "Missing required live team fields: "
            + ", ".join(missing_team_fields[:20])
            + (f" (+{len(missing_team_fields) - 20} more)" if len(missing_team_fields) > 20 else "")
        )
    if missing_starter_fields:
        degraded.append(
            "Missing required live starter fields: "
            + ", ".join(missing_starter_fields[:20])
            + (f" (+{len(missing_starter_fields) - 20} more)" if len(missing_starter_fields) > 20 else "")
        )

    coverage = {
        "games_expected": len(schedule),
        "games_built": 0 if blocking else len(schedule),
        "team_rows": len(bundle.team_stats),
        "starter_rows": len(bundle.starter_stats),
        "catcher_rows": len(catcher_map),
        "matchup_rows": 0 if blocking else len(schedule),
        "missing_teams": missing_teams,
        "missing_starters": missing_starters,
        "missing_catchers": missing_catchers,
        "missing_team_fields": missing_team_fields,
        "missing_starter_fields": missing_starter_fields,
        "missing_matchups": missing_matchups,
    }
    return blocking, degraded, coverage


def write_temp_db(
    cfg: BuilderConfig,
    bundle: BuildBundle,
    run_id: str,
    coverage: Dict[str, Any],
    blocking: List[str],
    degraded: List[str],
    tmp_db_path: Optional[Path] = None,
) -> Path:
    db_tmp = Path(tmp_db_path or cfg.tmp_db_path)
    if db_tmp.exists():
        try:
            db_tmp.unlink()
        except PermissionError:
            # Common on OneDrive when the previous temp file is still indexed/locked.
            fallback_tmp = Path(tempfile.gettempdir()) / f"mlb_pregame_tmp_{os.getpid()}_{uuid.uuid4().hex[:6]}.db"
            LOG.warning("Temp DB path locked (%s); retrying with %s", db_tmp, fallback_tmp)
            db_tmp = fallback_tmp
    conn = sqlite3.connect(db_tmp)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("mlb_pregame_schema_version", str(MLB_PREGAME_SCHEMA_VERSION)),
        )
        conn.execute("DELETE FROM team_stats WHERE fetched_date = ?", (cfg.data_date,))
        conn.execute("DELETE FROM starter_stats WHERE fetched_date = ?", (cfg.data_date,))
        conn.execute("DELETE FROM catcher_stats WHERE fetched_date = ?", (cfg.data_date,))
        conn.execute("DELETE FROM pregame_matchups WHERE game_date = ?", (cfg.data_date,))
        for row in bundle.team_stats:
            payload = dict(row)
            conn.execute(
                """
                INSERT INTO team_stats
                (fetched_date, team_name, wins, losses, ops_vs_rhp, ops_vs_lhp, bullpen_era, runs_per_game,
                 xwoba, hard_hit_pct, ops, obp, slg, avg, iso, barrel_pct, avg_exit_velo,
                 hr_per_game, bb_per_game, ops_home, ops_away,
                 ops_last14, runs_last14, bullpen_era_7d, bullpen_ip_3d)
                VALUES (:data_date, :team, :wins, :losses, :ops_vs_rhp, :ops_vs_lhp, :bullpen_era, :runs_per_game,
                        :xwoba, :hard_hit_pct, :ops, :obp, :slg, :avg, :iso, :barrel_pct, :avg_exit_velo,
                        :hr_per_game, :bb_per_game, :ops_home, :ops_away,
                        :ops_last14, :runs_last14, :bullpen_era_7d, :bullpen_ip_3d)
                """,
                payload,
            )
        for row in bundle.starter_stats:
            payload = dict(row)
            conn.execute(
                """
                INSERT INTO starter_stats
                (fetched_date, team_name, player_name, throws, era, fip, xfip, whip, innings, k_pct, bb_pct, k_minus_bb, xwoba_against,
                 gb_pct, fb_pct, hr_per_fb, babip, avg_velo, avg_spin, whiff_pct, hard_hit_pct, fly_ball_exposure,
                 density_sensitivity, era_last3, avg_pc_last3, avg_ip_last3)
                VALUES (:data_date, :team, :starter_name, :hand, :era, :fip, :xfip, :whip, :innings, :k_rate, :bb_rate, :k_minus_bb, :xwoba,
                        :gb_pct, :fb_pct, :hr_per_fb, :babip, :avg_velo, :avg_spin, :whiff_pct, :hard_hit_pct, :fly_ball_exposure,
                        :density_sensitivity, :era_last3, :avg_pc_last3, :avg_ip_last3)
                """,
                payload,
            )
        for team_name, crow in (bundle.catcher_by_team or {}).items():
            payload = {
                "data_date": cfg.data_date,
                "team_name": team_name,
                "catcher_name": str((crow or {}).get("catcher_name", "") or "").strip(),
                "framing_tier": str((crow or {}).get("framing_tier", "UNKNOWN") or "UNKNOWN"),
                "block_tier": str((crow or {}).get("block_tier", "UNKNOWN") or "UNKNOWN"),
                "arm_tier": str((crow or {}).get("arm_tier", "UNKNOWN") or "UNKNOWN"),
                "catcher_impact": _safe_float((crow or {}).get("catcher_impact")),
                "extra_strikes_per100": _safe_float((crow or {}).get("extra_strikes_per100")),
            }
            conn.execute(
                """
                INSERT INTO catcher_stats
                (fetched_date, team_name, catcher_name, framing_tier, block_tier, arm_tier, catcher_impact, extra_strikes_per100)
                VALUES (:data_date, :team_name, :catcher_name, :framing_tier, :block_tier, :arm_tier, :catcher_impact, :extra_strikes_per100)
                """,
                payload,
            )
        team_map = {r["team"]: r for r in bundle.team_stats}
        starter_map = {r["team"]: r for r in bundle.starter_stats}

        def _ops_split_for(team_name: str, opp_starter_hand: str) -> Optional[float]:
            row = team_map.get(team_name, {})
            if not row:
                return None
            hand = str(opp_starter_hand or "").upper().strip()
            if hand == "R":
                return row.get("ops_vs_rhp")
            if hand == "L":
                return row.get("ops_vs_lhp")
            return None

        for game in bundle.schedule:
            home_hand = str((starter_map.get(game.home_team, {}) or {}).get("hand", "")).upper().strip()
            away_hand = str((starter_map.get(game.away_team, {}) or {}).get("hand", "")).upper().strip()
            away_split = _ops_split_for(game.away_team, home_hand)
            home_split = _ops_split_for(game.home_team, away_hand)

            if away_split is None or home_split is None:
                _msg = (
                    f"{game.away_team} @ {game.home_team} "
                    f"(away_split={away_split}, home_split={home_split}, "
                    f"home_hand={home_hand or 'NA'}, away_hand={away_hand or 'NA'})"
                )
                coverage.setdefault("missing_matchups", []).append(_msg)
                if "Incomplete split data for one or more scheduled games" not in degraded:
                    degraded.append("Incomplete split data for one or more scheduled games")

            matchup = {
                "data_date": cfg.data_date,
                "game_id": game.game_id,
                "away_team": game.away_team,
                "home_team": game.home_team,
                "game_time_utc": game.game_time_utc,
                "away_starter": game.away_starter,
                "home_starter": game.home_starter,
                "away_ops_split": away_split,
                "home_ops_split": home_split,
                "matchup_summary": f"{game.away_team} at {game.home_team}",
                "lineup_confirmed": 0,
                "lineup_status": "PENDING",
                "home_catcher": "",
                "away_catcher": "",
            }
            away_crow = (bundle.catcher_by_team or {}).get(game.away_team, {}) or {}
            home_crow = (bundle.catcher_by_team or {}).get(game.home_team, {}) or {}
            matchup["away_catcher"] = str(away_crow.get("catcher_name", "") or "").strip()
            matchup["home_catcher"] = str(home_crow.get("catcher_name", "") or "").strip()
            _away_conf = int(away_crow.get("lineup_confirmed", 0) or 0)
            _home_conf = int(home_crow.get("lineup_confirmed", 0) or 0)
            matchup["lineup_confirmed"] = 1 if (_away_conf and _home_conf) else 0
            _away_st = str(away_crow.get("lineup_status", "") or "").upper().strip()
            _home_st = str(home_crow.get("lineup_status", "") or "").upper().strip()
            if _away_st == "CONFIRMED" and _home_st == "CONFIRMED":
                matchup["lineup_status"] = "CONFIRMED"
            elif _away_st or _home_st:
                matchup["lineup_status"] = f"{_away_st or 'UNKNOWN'}|{_home_st or 'UNKNOWN'}"
            try:
                _dt = datetime.fromisoformat(str(game.game_time_utc).replace("Z", "+00:00")).astimezone()
                matchup["game_time"] = f"{_dt.month}/{_dt.day} {_dt.strftime('%I:%M%p').lstrip('0')}"
            except Exception:
                matchup["game_time"] = str(game.game_time_utc or "")
            conn.execute(
                """
                INSERT INTO pregame_matchups
                (game_date, game_time, game_id, away_team, home_team, away_starter, home_starter,
                 away_ops_split, home_ops_split, matchup_summary, lineup_confirmed, lineup_status, home_catcher, away_catcher)
                VALUES (:data_date, :game_time, :game_id, :away_team, :home_team, :away_starter, :home_starter,
                        :away_ops_split, :home_ops_split, :matchup_summary, :lineup_confirmed, :lineup_status, :home_catcher, :away_catcher)
                """,
                matchup,
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO build_meta
            (run_id, data_date, started_at, completed_at, build_state, model_safe, summary, blocking_issues, degraded_issues)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cfg.data_date,
                utc_now_iso(),
                utc_now_iso(),
                "FAILED" if blocking else ("DEGRADED" if degraded else "READY"),
                0 if (blocking or degraded) else 1,
                f"games={coverage.get('games_built', 0)}",
                json.dumps(blocking),
                json.dumps(degraded),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_tmp


def _replace_with_retry(src: Path, dst: Path, attempts: int = 8, base_sleep: float = 0.15) -> None:
    """
    Windows/OneDrive can briefly lock files and make os.replace fail with WinError 5.
    Retry first, then fall back to direct copy as a last resort.
    """
    last_exc: Optional[Exception] = None
    for idx in range(max(1, attempts)):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(base_sleep * (idx + 1))
    try:
        data = src.read_bytes()
        dst.write_bytes(data)
        try:
            src.unlink()
        except OSError:
            pass
        return
    except Exception:
        if last_exc is not None:
            raise last_exc
        raise


def atomic_swap(src: Path, dst: Path) -> None:
    _replace_with_retry(src, dst)


def persist_run_meta(cfg: BuilderConfig, readiness: Dict[str, Any]) -> None:
    tmp = cfg.meta_path.with_suffix(cfg.meta_path.suffix + ".tmp")
    tmp.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")
    try:
        _replace_with_retry(tmp, cfg.meta_path)
    except Exception as exc:
        # Metadata is diagnostic; do not fail the whole build on lock contention.
        LOG.warning("persist_run_meta replace failed (%s): %s", cfg.meta_path, exc)


def archive_stale_workspace_readiness(cfg: BuilderConfig) -> None:
    """
    Prevent stale workspace mlb_readiness.json from shadowing runtime truth.
    """
    try:
        root = Path.cwd().resolve()
        runtime_target = cfg.readiness_path.resolve()
        local_file = root / "mlb_readiness.json"
        if not local_file.exists():
            return
        if local_file.resolve() == runtime_target:
            return
        stale_name = root / f"mlb_readiness.stale_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        _replace_with_retry(local_file, stale_name)
        LOG.info("Archived stale workspace readiness file: %s -> %s", local_file, stale_name)
    except Exception as exc:
        LOG.warning("archive_stale_workspace_readiness failed: %s", exc)


def build(cfg: BuilderConfig) -> int:
    cfg.base_dir.mkdir(parents=True, exist_ok=True)
    _seed_primary_db_from_legacy(cfg.base_dir)
    run_id = f"mlb-{cfg.data_date}-{uuid.uuid4().hex[:10]}"
    readiness_store = ReadinessStore(cfg.base_dir, cfg.readiness_name)
    state = ReadinessState(
        league="MLB",
        run_id=run_id,
        data_date=cfg.data_date,
        build_state="RUNNING",
        db_path=str(cfg.db_path),
        temp_db_path=str(cfg.tmp_db_path),
        lock_path=str(cfg.lock_path),
        meta={"builder": "mlb_pregame_builder.py", "allow_degraded": cfg.allow_degraded},
    )
    readiness_store.write(state)

    with SingleRunLock(cfg.lock_path):
        bundle, sources = collect_sources(cfg)
        blocking, degraded, coverage_dict = validate_bundle(bundle)

        if blocking and not cfg.allow_degraded:
            coverage = make_coverage(**coverage_dict)
            state.build_state = "FAILED"
            state = finalize_state(state, sources=sources, coverage=coverage, blocking_issues=blocking, degraded_issues=degraded)
            readiness_store.write(state)
            persist_run_meta(cfg, state.to_dict())
            archive_stale_workspace_readiness(cfg)
            return 2

        if blocking and cfg.allow_degraded:
            state.build_state = "DEGRADED"
            degraded = degraded + blocking
            blocking = []
        else:
            state.build_state = "READY" if not degraded else "DEGRADED"

        tmp_used = cfg.tmp_db_path
        try:
            tmp_used = write_temp_db(cfg, bundle, run_id, coverage_dict, blocking, degraded, tmp_db_path=cfg.tmp_db_path)
        except (sqlite3.OperationalError, PermissionError, OSError) as io_exc:
            msg = str(io_exc).lower()
            if ("disk i/o error" not in msg) and ("access is denied" not in msg) and ("permission denied" not in msg):
                raise
            tmp_used = Path(tempfile.gettempdir()) / f"mlb_pregame_tmp_{os.getpid()}_{uuid.uuid4().hex[:6]}.db"
            LOG.warning("Primary temp DB path failed (%s). Retrying in local temp path: %s", cfg.tmp_db_path, tmp_used)
            tmp_used = write_temp_db(cfg, bundle, run_id, coverage_dict, blocking, degraded, tmp_db_path=tmp_used)
        coverage = make_coverage(**coverage_dict)
        atomic_swap(tmp_used, cfg.db_path)
        state.temp_db_path = str(tmp_used)
        if blocking:
            state.build_state = "FAILED"
        elif degraded:
            state.build_state = "DEGRADED"
        else:
            state.build_state = "READY"
        state = finalize_state(state, sources=sources, coverage=coverage, blocking_issues=blocking, degraded_issues=degraded)
        readiness_store.write(state)
        persist_run_meta(cfg, state.to_dict())
        archive_stale_workspace_readiness(cfg)
        return 0 if state.model_safe else 1


def parse_args(argv: Optional[List[str]] = None) -> BuilderConfig:
    parser = argparse.ArgumentParser(description="Atomic MLB pregame DB builder")
    parser.add_argument("--base-dir", default=str(_runtime_base_dir_default()))
    parser.add_argument("--date", default=None)
    parser.add_argument("legacy_date", nargs="?", default=None)
    parser.add_argument("--allow-degraded", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    selected_date = str(args.date or args.legacy_date or date.today())
    return BuilderConfig(
        base_dir=Path(args.base_dir).resolve(),
        data_date=selected_date,
        allow_degraded=bool(args.allow_degraded),
        verbose=bool(args.verbose),
    )


def main(argv: Optional[List[str]] = None) -> int:
    cfg = parse_args(argv)
    configure_logging(cfg.verbose)
    try:
        return build(cfg)
    except Exception as exc:
        LOG.exception("Build failed")
        store = ReadinessStore(cfg.base_dir, cfg.readiness_name)
        state = ReadinessState(
            league="MLB",
            run_id=f"mlb-{cfg.data_date}-fatal",
            data_date=cfg.data_date,
            build_state="FAILED",
            model_safe=False,
            db_path=str(cfg.db_path),
            temp_db_path=str(cfg.tmp_db_path),
            lock_path=str(cfg.lock_path),
            blocking_issues=[str(exc)],
            summary="FAILED fatal builder exception",
        )
        store.write(state)
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
