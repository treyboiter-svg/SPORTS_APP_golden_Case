#!/usr/bin/env python3
"""
referees_daily_unified.py

Runs NFL/NBA/NHL referee scrapers, parses outputs, adds team IDs via JSON alias map.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from game_resolver import build_resolvers_from_schedule_dir, make_game_id, write_unresolved_csv, check_unresolved_threshold


# ===========================
# Team normalization helpers
# ===========================
def _abbr(s: str) -> str:
    """Strip to uppercase letters only."""
    s = (s or "").upper().strip()
    s = re.sub(r"[^A-Z]", "", s)
    return s


def norm_token(s: str) -> str:
    """Normalize team token for matching (lowercase alphanumeric)."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.strip()
    s = s.replace("’", "'").replace("`", "'")
    s = s.replace(".", "").replace("&", "and").replace("'", "")
    s = re.sub(r"\b(\d{1,2})-(\d{1,2})\b", r"\1\2", s)  # "13-0" -> "130"
    s = re.sub(r"[^A-Za-z0-9]", "", s)
    return s.lower()


def _promotable_duplicate_match(match: Any) -> Optional[Dict[str, Any]]:
    """
    Promote resolver outputs where ambiguity is artificial:
    best and second candidates point to the SAME game_id.
    """
    try:
        if not match:
            return None
        conf = float(getattr(match, "confidence", 0.0) or 0.0)
        if conf < 0.90:
            return None
        diag = getattr(match, "diagnostics", None)
        if not isinstance(diag, dict):
            return None
        best = diag.get("best") if isinstance(diag.get("best"), dict) else {}
        second = diag.get("second") if isinstance(diag.get("second"), dict) else {}
        best_game = best.get("game") if isinstance(best.get("game"), dict) else {}
        second_game = second.get("game") if isinstance(second.get("game"), dict) else {}
        best_gid = str(best_game.get("game_id") or "").strip()
        second_gid = str(second_game.get("game_id") or "").strip()
        if not best_gid:
            return None
        if second_gid and second_gid != best_gid:
            return None
        away = str(best_game.get("away_team") or "").strip()
        home = str(best_game.get("home_team") or "").strip()
        if not away or not home:
            return None
        return {"game_id": best_gid, "away_team": away, "home_team": home}
    except Exception:
        return None


def canon_league(x: str) -> str:
    """Normalize league token."""
    if not isinstance(x, str):
        return ""
    u = x.strip().upper()
    if u in ("NCAABB", "NCAA-BB", "NCAAMBB", "NCAA BB"):
        return "NCAAB"
    if u in ("NCAAFB", "NCAA-FB", "NCAA FB"):
        return "NCAAF"
    return u


def matchup_key(away_token: str, home_token: str) -> str:
    """Create matchup key from tokens (AWAY@HOME in uppercase letters only)."""
    return f"{_abbr(away_token)}@{_abbr(home_token)}"


def split_matchup_key(k: str) -> Tuple[str, str]:
    """Split matchup key back into (away_abbr, home_abbr)."""
    if not k or "@" not in str(k):
        return ("", "")
    a, h = str(k).split("@", 1)
    return (_abbr(a), _abbr(h))


# ===========================
# JSON alias map loader
# ===========================
def load_json_alias_map(json_path: Path) -> Dict[Tuple[str, str], str]:
    if not json_path.exists():
        print(f"[WARN] JSON alias map not found: {json_path}")
        return {}

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Could not parse JSON alias map: {e}")
        return {}

    mapping: Dict[Tuple[str, str], str] = {}
    for league_raw, entries in data.items():
        league = canon_league(league_raw)
        if league not in ("NFL", "NBA", "NHL", "MLB", "NCAAB", "NCAAF"):
            continue
        if not isinstance(entries, dict):
            continue
        for entry_key, entry_val in entries.items():
            # Legacy layout: {"norm_token": "Canonical Name"}
            if isinstance(entry_val, str):
                _nk = norm_token(entry_key)
                if _nk:
                    mapping[(league, _nk)] = entry_val
                continue

            # Current layout: {"Team Name": {"canonical_name": "...", "aliases": [...]}}
            if isinstance(entry_val, dict):
                canonical_name = str(entry_val.get("canonical_name") or entry_key).strip()
                alias_values = []
                alias_values.append(entry_key)
                alias_values.append(canonical_name)
                for alias in (entry_val.get("aliases") or []):
                    alias_values.append(str(alias or "").strip())
                for alias in alias_values:
                    _nk = norm_token(alias)
                    if _nk:
                        mapping[(league, _nk)] = canonical_name
                continue

            # Fallback: best-effort token from key itself.
            _nk = norm_token(entry_key)
            if _nk:
                mapping[(league, _nk)] = str(entry_key).strip()
    return mapping


def add_ids(df: pd.DataFrame, league: str, alias_map: Dict[Tuple[str, str], str]) -> pd.DataFrame:
    if df.empty:
        return df
    league = canon_league(league)

    away_ids = []
    home_ids = []
    away_tokens = []
    home_tokens = []

    for _, row in df.iterrows():
        a_tok = norm_token(str(row.get("Away") or row.get("away_team") or ""))
        h_tok = norm_token(str(row.get("Home") or row.get("home_team") or ""))

        away_tokens.append(a_tok)
        home_tokens.append(h_tok)

        away_ids.append(alias_map.get((league, a_tok), "UNKNOWN"))
        home_ids.append(alias_map.get((league, h_tok), "UNKNOWN"))

    out = df.copy()
    insert_at = 0
    if "Game" in out.columns:
        insert_at = out.columns.get_loc("Game") + 1
    elif "game" in out.columns:
        insert_at = out.columns.get_loc("game") + 1

    if insert_at == 0:
        insert_at = 1

    if "away_token" not in out.columns:
        out.insert(insert_at, "away_token", away_tokens)
        insert_at += 1
    if "home_token" not in out.columns:
        out.insert(insert_at, "home_token", home_tokens)
        insert_at += 1

    out.insert(insert_at, "away_id", away_ids)
    out.insert(insert_at + 1, "home_id", home_ids)

    return out


# ===========================
# Runner helper
# ===========================
def run_py(cmd: List[str]):
    # Root cause of "No module named 'webdriver_manager'" when called as subprocess:
    # subprocess.run without env= gets a stripped environment that doesn't include
    # the active virtualenv's site-packages.  Passing os.environ.copy() explicitly
    # propagates the PYTHONPATH / venv activation state to the child process.
    # cwd=Path(__file__).parent ensures scripts are resolved relative to this file's
    # directory regardless of what CWD the caller had.
    child_env = os.environ.copy()
    # Desktop/runtime environments may inject dead localhost proxies (127.0.0.1:9),
    # which silently break requests/curl_cffi in referee producers.
    for _k in list(child_env.keys()):
        if "proxy" in _k.lower():
            child_env.pop(_k, None)
    child_env["NO_PROXY"] = "*"

    result = subprocess.run(
        [sys.executable] + cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
        cwd=Path(__file__).parent,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"FAILED: {' '.join(cmd)}")


def _league_has_active_slate(league: str, run_date: date, base_dir: Optional[Path] = None) -> bool:
    """
    Determine whether a league should be treated as in-slate for officials export.
    Priority:
    1) stats_output/StatsStatus_<LEAGUE>_<YYYYMMDD>.json
    2) odds_data/Odds_<LEAGUE>_<YYYYMMDD>.xlsx presence/non-empty
    """
    _lg = str(league or "").upper().strip()
    if not _lg:
        return False
    _base = base_dir or Path(__file__).resolve().parent
    _token = run_date.strftime("%Y%m%d")

    _stats_marker = _base / "stats_output" / f"StatsStatus_{_lg}_{_token}.json"
    if _stats_marker.exists():
        try:
            _m = json.loads(_stats_marker.read_text(encoding="utf-8"))
            _status = str(_m.get("status", "")).upper().strip()
            if _status == "NO_GAMES":
                return False
            _games = 0
            for _k in ("games_found", "games", "game_count"):
                try:
                    if _m.get(_k) is not None:
                        _games = max(_games, int(str(_m.get(_k)).strip()))
                except Exception:
                    continue
            if _games > 0:
                return True
        except Exception:
            pass

    _odds_file = _base / "odds_data" / f"Odds_{_lg}_{_token}.xlsx"
    if (not _odds_file.exists()) or _odds_file.stat().st_size <= 0:
        return False
    try:
        _df = pd.read_excel(_odds_file, nrows=25, dtype=str)
        if _df is None or _df.empty:
            return False
        if "Away_Team" in _df.columns and "Home_Team" in _df.columns:
            _away = _df["Away_Team"].fillna("").astype(str).replace({"nan": "", "NaN": "", "<NA>": ""}).str.strip()
            _home = _df["Home_Team"].fillna("").astype(str).replace({"nan": "", "NaN": "", "<NA>": ""}).str.strip()
            return bool((_away.ne("") & _home.ne("")).any())
        return True
    except Exception:
        # If the odds workbook exists but cannot be read, treat as active to avoid false off-slate skips.
        return True


# ===========================
# Parser helpers
# ===========================
def parse_nfl(path: Path, run_date: date) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Date"] = run_date.isoformat()
    return df


def parse_nba(path: Path, run_date: date) -> pd.DataFrame:
    df = pd.read_excel(path)
    # NBA exporter often emits city-vs-city text in `Game` but does not provide
    # explicit Away/Home columns. Derive them here so ID resolution and
    # schedule matching can canonicalize teams instead of falling back to UNKNOWN.
    if "Away" not in df.columns and "Home" not in df.columns and "Game" in df.columns:
        away_vals: List[str] = []
        home_vals: List[str] = []
        for game_val in df.get("Game", pd.Series(dtype=str)):
            game_str = str(game_val or "").strip()
            away_t, home_t = "", ""
            if "@" in game_str:
                parts = game_str.split("@", 1)
                away_t = parts[0].strip()
                home_t = parts[1].strip()
            else:
                parts = re.split(r"(?i)\s+vs\.?\s+|\s+at\s+", game_str, maxsplit=1)
                if len(parts) == 2:
                    away_t = parts[0].strip()
                    home_t = parts[1].strip()
            away_vals.append(away_t)
            home_vals.append(home_t)
        df["Away"] = away_vals
        df["Home"] = home_vals

    df["Date"] = run_date.isoformat()
    return df


def parse_nhl(path: Path, run_date: date) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    dfs = []
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        if df.empty:
            continue
        # BUG 2 FIX: Only set Game column from sheet name when the data has no
        # Game column of its own. The original code unconditionally did
        # `df["Game"] = sheet` — if the NHL refs source file has one combined
        # sheet named "ALL" with a "Game" column containing per-game matchup
        # strings like "LAK @ BOS", that line OVERWRITES the good game data with
        # 'ALL'. Every row then gets Game='ALL', the game_id resolver finds no
        # matching Schedule entry for a game named 'ALL', and 26/26 NHL ref rows
        # remain unresolved. Preserving the existing column avoids the overwrite.
        if "Game" not in df.columns:
            df["Game"] = sheet
        dfs.append(df)
    if not dfs:
        print(f"[WARN] parse_nhl: all sheets in {path.name} are empty, returning empty DataFrame")
        return pd.DataFrame()
    df_all = pd.concat(dfs, ignore_index=True, sort=False)

    # Extract Away/Home team columns from the Game matchup string if they are absent.
    # The NHL refs scraper may write "LAK @ BOS", "LAK vs BOS", etc. in the Game column.
    # Without Away/Home columns the game_id resolver cannot link rows to scheduled games.
    if "Away" not in df_all.columns and "Home" not in df_all.columns:
        _away_list: list = []
        _home_list: list = []
        _SEPARATORS = (" @ ", " vs ", " vs. ", "_vs_", " at ", " - ", "_@_", "@")
        for game_val in df_all.get("Game", pd.Series(dtype=str)):
            game_str = str(game_val or "").strip()
            away_t, home_t = "", ""
            for sep in _SEPARATORS:
                if sep in game_str:
                    parts = game_str.split(sep, 1)
                    away_t = parts[0].strip()
                    home_t = parts[1].strip()
                    break
            _away_list.append(away_t)
            _home_list.append(home_t)
        df_all["Away"] = _away_list
        df_all["Home"] = _home_list
        parsed_rows = df_all["Away"].str.strip().ne("").sum()
        if parsed_rows == 0:
            print(f"[WARN] parse_nhl: could not extract Away/Home from Game column in {path.name}. "
                  f"Unique Game values: {df_all['Game'].unique().tolist()[:10]}. "
                  f"NHL game_id resolution will fail. "
                  f"Check nhl_referees_scraper.py output format — expected 'AWAY @ HOME' or 'AWAY vs HOME'.")
        else:
            print(f"[INFO] parse_nhl: extracted Away/Home from Game column "
                  f"({parsed_rows}/{len(df_all)} rows successfully parsed).")

    df_all["Date"] = run_date.isoformat()
    return df_all


def parse_mlb(path: Path, run_date: date) -> pd.DataFrame:
    """Parse MLB umpire report. Handles both CSV and XLSX formats.
    MLB umpires are not always posted; caller must guard file existence."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported format for MLB refs: {path}")
    df["Date"] = run_date.isoformat()
    return df


def _xlsx_total_rows(path: Path) -> int:
    try:
        if (not path.exists()) or path.stat().st_size <= 0:
            return 0
        xl = pd.ExcelFile(path)
        total = 0
        for sheet in xl.sheet_names:
            try:
                total += int(len(xl.parse(sheet)))
            except Exception:
                continue
        return total
    except Exception:
        return 0


def _stamp_league_columns(df: pd.DataFrame, league: str) -> pd.DataFrame:
    """Ensure unified workbook always has canonical league/sport columns."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    out["league"] = str(league).upper().strip()
    out["sport"] = str(league).upper().strip()
    return out


# ===========================
# Main
# ===========================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today local)")
    ap.add_argument("--outdir", default="ref_output")
    ap.add_argument("--alias-json", default="team_alias_map.json", help="Path to JSON alias map")
    ap.add_argument("--write-unmatched-csv", action="store_true", help="Write unmatched rows CSV for debugging")

    args = ap.parse_args()

    run_date: date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now().date()
    ymd = run_date.strftime("%Y%m%d")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Load alias map
    alias_json = Path(args.alias_json)
    alias_map = load_json_alias_map(alias_json)
    if not alias_map:
        print(f"[WARN] Alias map is empty from {alias_json}; IDs will be UNKNOWN")
    else:
        print(f"Loaded {len(alias_map)} alias entries from {alias_json}")

    _active = {
        "NFL": _league_has_active_slate("NFL", run_date),
        "NBA": _league_has_active_slate("NBA", run_date),
        "NHL": _league_has_active_slate("NHL", run_date),
        "MLB": _league_has_active_slate("MLB", run_date),
    }
    print(
        "[INFO] Officials active slate flags: "
        + ", ".join(f"{_lg}={'ON' if _on else 'OFF'}" for _lg, _on in _active.items())
    )

    # Run the producer scripts (allow failures for active leagues; skip off-slate leagues cleanly)
    nfl_ok = nba_ok = nhl_ok = mlb_ok = True

    if _active["NFL"]:
        try:
            run_py(["nfl_referee_stats_today.py"])
        except RuntimeError as e:
            print(f"[WARN] NFL referee export failed, continuing without NFL refs.")
            print(e)
            nfl_ok = False
    else:
        print(f"[INFO] NFL off-slate for {run_date.isoformat()}, skipping NFL referee export.")
        nfl_ok = False

    if _active["NBA"]:
        try:
            run_py(["nba_referees_daily_export.py", "--date", run_date.isoformat(), "--outdir", str(outdir), "--require-rows"])
        except RuntimeError as e:
            print(f"[WARN] NBA referee export failed or returned 0 rows, continuing without NBA refs.")
            print(e)
            nba_ok = False
    else:
        print(f"[INFO] NBA off-slate for {run_date.isoformat()}, skipping NBA referee export.")
        nba_ok = False

    if _active["NHL"]:
        try:
            run_py(["nhl_referees_scraper.py", "--date", run_date.isoformat(), "--outdir", str(outdir)])
            _nhl_path = outdir / f"nhl_referees_{ymd}.xlsx"
            if _xlsx_total_rows(_nhl_path) <= 0:
                _fallback = Path("nhl_referees_scraper_1.py")
                if _fallback.exists():
                    print("[WARN] Primary NHL scraper produced 0 rows; trying fallback nhl_referees_scraper_1.py ...")
                    try:
                        run_py([str(_fallback), "--date", run_date.isoformat(), "--outdir", str(outdir)])
                    except RuntimeError as _fb_err:
                        print(f"[WARN] Fallback NHL scraper failed: {_fb_err}")
        except RuntimeError as e:
            print(f"[WARN] NHL referee export failed, continuing without NHL refs.")
            print(e)
            nhl_ok = False
    else:
        print(f"[INFO] NHL off-slate for {run_date.isoformat()}, skipping NHL referee export.")
        nhl_ok = False

    if _active["MLB"]:
        try:
            _mlb_scraper_script = "mlb_umpire_scraper.py" if Path("mlb_umpire_scraper.py").exists() else "mlb_umpire_scraper_v2.py"
            run_py([_mlb_scraper_script, "--date", run_date.isoformat(), "--outdir", str(outdir)])
        except RuntimeError as e:
            # MLB umpires are not always posted — this is a known acceptable gap
            print(f"[INFO] MLB umpire export not available for {run_date.isoformat()}, continuing without MLB refs.")
            mlb_ok = False
    else:
        print(f"[INFO] MLB off-slate for {run_date.isoformat()}, skipping MLB umpire export.")
        mlb_ok = False

    # Parse outputs
    nfl_df = pd.DataFrame()
    nba_df = pd.DataFrame()
    nhl_df = pd.DataFrame()
    mlb_df = pd.DataFrame()

    if nfl_ok:
        try:
            nfl_df = parse_nfl(Path("nfl_referee_stats_today.csv"), run_date)
        except Exception as e:
            print(f"[WARN] Could not parse NFL referee CSV, treating as empty: {e}")
            nfl_df = pd.DataFrame()

    if nba_ok:
        try:
            nba_df = parse_nba(outdir / f"nba_referee_report_{ymd}.xlsx", run_date)
        except Exception as e:
            print(f"[WARN] Could not parse NBA referee report, treating as empty: {e}")
            nba_df = pd.DataFrame()

    if nhl_ok:
        try:
            nhl_df = parse_nhl(outdir / f"nhl_referees_{ymd}.xlsx", run_date)
        except Exception as e:
            print(f"[WARN] Could not parse NHL referees XLSX, treating as empty: {e}")
            nhl_df = pd.DataFrame()

    if mlb_ok:
        # Try both xlsx and csv output formats from mlb_umpires_daily.py
        for _mlb_cand in [
            outdir / f"mlb_umpires_{ymd}.xlsx",
            outdir / f"mlb_umpires_{ymd}.csv",
            outdir / f"mlb_referee_report_{ymd}.xlsx",
        ]:
            if _mlb_cand.exists():
                try:
                    mlb_df = parse_mlb(_mlb_cand, run_date)
                    print(f"  Loaded MLB umpires from {_mlb_cand.name}: {len(mlb_df)} rows")
                    break
                except Exception as e:
                    print(f"[WARN] Could not parse MLB umpire file {_mlb_cand.name}: {e}")
                    mlb_df = pd.DataFrame()

    # Stamp canonical league/sport columns before ID resolution and concat.
    nfl_df = _stamp_league_columns(nfl_df, "NFL")
    nba_df = _stamp_league_columns(nba_df, "NBA")
    nhl_df = _stamp_league_columns(nhl_df, "NHL")
    mlb_df = _stamp_league_columns(mlb_df, "MLB")

    # Add team IDs
    nfl_df = add_ids(nfl_df, "NFL", alias_map)
    nba_df = add_ids(nba_df, "NBA", alias_map)
    nhl_df = add_ids(nhl_df, "NHL", alias_map)
    mlb_df = add_ids(mlb_df, "MLB", alias_map)

    # Resolve game_ids from schedule
    resolvers = {}
    try:
        resolvers = build_resolvers_from_schedule_dir("stats_output", run_date.isoformat())
    except Exception as e:
        print(f"[WARN] Could not build resolvers: {e}")

    for league_name, league_df in [("NFL", nfl_df), ("NBA", nba_df), ("NHL", nhl_df), ("MLB", mlb_df)]:
        if league_df.empty:
            continue

        resolver = resolvers.get(league_name)
        game_ids = []
        canonical_aways = []
        canonical_homes = []
        unresolved_rows = []
        promoted_rows = 0

        away_col = "Away" if "Away" in league_df.columns else "away_team"
        home_col = "Home" if "Home" in league_df.columns else "home_team"
        def _official_name_from_row(_row):
            for _k in ("HP_Umpire", "Referee", "Name", "official_name", "Umpire", "umpire"):
                _v = str(_row.get(_k, "")).strip()
                if _v:
                    return _v
            return ""
        def _is_invalid_official_name(_v):
            _s = str(_v or "").strip().lower()
            return _s in {"", "nan", "none", "null", "n/a", "na"}

        for _, row in league_df.iterrows():
            raw_away = str(row.get(away_col, "")).strip()
            raw_home = str(row.get(home_col, "")).strip()
            raw_official = _official_name_from_row(row)

            if resolver and raw_away and raw_home:
                match = resolver.resolve(league_name, run_date.isoformat(), raw_away, raw_home)
                if match.matched and match.game is not None:
                    game_ids.append(match.game.game_id)
                    # Enforce resolver canonical names — replace raw scraper names
                    # with the exact names the pipeline and scheduler use, so
                    # find_matching_refs() joins succeed on first pass.
                    canonical_aways.append(match.game.away_team)
                    canonical_homes.append(match.game.home_team)
                else:
                    promoted = _promotable_duplicate_match(match)
                    if promoted:
                        game_ids.append(promoted["game_id"])
                        canonical_aways.append(promoted["away_team"])
                        canonical_homes.append(promoted["home_team"])
                        promoted_rows += 1
                        continue
                    gid = make_game_id(league_name, run_date.isoformat(), raw_away, raw_home)
                    game_ids.append(gid)
                    canonical_aways.append(raw_away)
                    canonical_homes.append(raw_home)
                    unresolved_rows.append({
                        "raw_away": raw_away,
                        "raw_home": raw_home,
                        "raw_time": "",
                        "raw_venue": "",
                        "league": league_name,
                        "date": run_date.isoformat(),
                        "confidence": match.confidence,
                        "method": match.method,
                        "diagnostics": match.diagnostics,
                        "issue": "game_id_unresolved",
                    })
            else:
                game_ids.append(make_game_id(league_name, run_date.isoformat(), raw_away, raw_home))
                canonical_aways.append(raw_away)
                canonical_homes.append(raw_home)
            if _is_invalid_official_name(raw_official):
                unresolved_rows.append({
                    "raw_away": raw_away,
                    "raw_home": raw_home,
                    "raw_time": "",
                    "raw_venue": "",
                    "league": league_name,
                    "date": run_date.isoformat(),
                    "confidence": "",
                    "method": "official_name_validation",
                    "diagnostics": {"official_raw": raw_official},
                    "issue": "official_name_invalid_null",
                })

        league_df["game_id"] = game_ids
        # Overwrite the team name columns with resolver canonical names.
        # The away_col/home_col may be "Away"/"Home" or "away_team"/"home_team"
        # depending on source; overwrite whichever column exists so the unified
        # output carries canonical names consistently.
        league_df[away_col] = canonical_aways
        league_df[home_col] = canonical_homes
        # Also ensure away_team/home_team columns exist as canonical names
        # (used by pipeline_orchestrator find_matching_refs Pass 2)
        if away_col != "away_team":
            league_df["away_team"] = canonical_aways
        if home_col != "home_team":
            league_df["home_team"] = canonical_homes

        if unresolved_rows:
            write_unresolved_csv(unresolved_rows, league_name, "refs", run_date.isoformat())

        # Game-id resolution failures are NOT referee data failures —
        # the ref data itself is intact; we only couldn't link to a Schedules game_id.
        # Log as WARNING; never crash the refs pipeline over this.
        try:
            check_unresolved_threshold(
                unresolved_count=len(unresolved_rows),
                total_count=len(league_df),
                league=league_name,
                source_name="REFS",
            )
        except Exception as _thresh_exc:
            print(f"[WARN] REFS {league_name} game_id resolution: "
                  f"{len(unresolved_rows)}/{len(league_df)} rows did not match a Schedules entry. "
                  f"Referee data is intact. ({_thresh_exc})")

        # Write per-league integrity JSON so the OU engine can check
        # data_refs_attached and neutralize the ref factor when resolution failed.
        try:
            _integrity = {
                "league": league_name,
                "date": run_date.isoformat(),
                "total_rows": len(league_df),
                "unresolved_rows": len(unresolved_rows),
                "promoted_duplicate_rows": int(promoted_rows),
            }
            _integrity_path = outdir / f"refs_integrity_{league_name}_{ymd}.json"
            _integrity_path.write_text(
                json.dumps(_integrity, indent=2),
                encoding="utf-8",
            )
            print(f"[INFO] REFS integrity: {_integrity_path.name} — "
                  f"total={len(league_df)}, unresolved={len(unresolved_rows)}")
        except Exception as _int_exc:
            print(f"[WARN] Could not write refs integrity JSON for {league_name}: {_int_exc}")

    # Concatenate
    dfs: List[pd.DataFrame] = []
    if not nfl_df.empty:
        dfs.append(nfl_df)
    if not nba_df.empty:
        dfs.append(nba_df)
    if not nhl_df.empty:
        dfs.append(nhl_df)
    if not mlb_df.empty:
        dfs.append(mlb_df)

    all_df = pd.concat(dfs, ignore_index=True, sort=False) if dfs else pd.DataFrame()

    # Write unified output

    out_path = outdir / f"referees_unified_{ymd}.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="ALL", index=False)
        nfl_df.to_excel(writer, sheet_name="NFL", index=False)
        nba_df.to_excel(writer, sheet_name="NBA", index=False)
        nhl_df.to_excel(writer, sheet_name="NHL", index=False)
        mlb_df.to_excel(writer, sheet_name="MLB", index=False)

    print(f"[OK] WROTE {out_path}")

    # Optional: write unmatched CSV for debugging
    if args.write_unmatched_csv and not all_df.empty:
        um = all_df[
            (all_df.get("away_id", "UNKNOWN") == "UNKNOWN") |
            (all_df.get("home_id", "UNKNOWN") == "UNKNOWN")
        ].copy()

        um_path = outdir / f"referees_unmatched_{ymd}.csv"
        um.to_csv(um_path, index=False)
        print(f"[OK] WROTE {um_path} ({len(um)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
