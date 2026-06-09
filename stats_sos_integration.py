"""
Stats + SOS integration backed by on-disk status markers.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable
import re

import pandas as pd

log = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_STATS_DIR = _BASE_DIR / "stats_output"
_SOS_DIR = _BASE_DIR / "sos_data"
_LEAGUES = ("MLB", "NBA", "NHL", "NFL", "NCAAB", "NCAAF")


def _allow_latest_fallback() -> bool:
    """
    Strict-by-default: do not use stale historical artifacts when a target-date
    file is missing. Set OVERLINE_ALLOW_STALE_FALLBACK=1 to re-enable fallback.
    """
    return str(os.environ.get("OVERLINE_ALLOW_STALE_FALLBACK", "0") or "").strip().lower() in {
        "1", "true", "yes", "on", "y"
    }


def _date_token(game_date: Any = None) -> str:
    if game_date is None:
        return datetime.now().strftime("%Y%m%d")
    s = str(game_date).strip()
    if not s:
        return datetime.now().strftime("%Y%m%d")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except Exception:
            continue
    return datetime.now().strftime("%Y%m%d")


def _norm_league(sport: Any) -> str:
    return str(sport or "").strip().upper()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception as exc:
        log.warning("Failed reading %s: %s", path, exc)
        return {}


def _stats_marker(league: str, game_date: Any = None) -> Dict[str, Any]:
    token = _date_token(game_date)
    primary_path = _STATS_DIR / f"StatsStatus_{league}_{token}.json"
    data = _read_json(primary_path)
    if data:
        return data
    if not _allow_latest_fallback():
        return {}
    candidates = sorted(_STATS_DIR.glob(f"StatsStatus_{league}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        data = _read_json(p)
        if data:
            return data
    return {}


def _sos_marker(league: str, game_date: Any = None) -> Dict[str, Any]:
    token = _date_token(game_date)
    primary_path = _SOS_DIR / f"SOSStatus_{league}_{token}.json"
    data = _read_json(primary_path)
    if data:
        return data
    if not _allow_latest_fallback():
        return {}
    candidates = sorted(_SOS_DIR.glob(f"SOSStatus_{league}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        data = _read_json(p)
        if data:
            return data
    return {}


def _ok_status(status: str) -> bool:
    return str(status or "").strip().upper() in {"READY", "NO_GAMES"}


def _state_from_marker(marker: Dict[str, Any], kind: str) -> str:
    if not marker:
        return f"{kind}_MISSING"
    raw = str(marker.get("status", "")).strip().upper()
    if raw == "READY":
        return f"{kind}_READY"
    if raw == "NO_GAMES":
        return f"{kind}_NO_GAMES"
    return f"{kind}_BLOCKED"


def _readiness_for_league(league: str, game_date: Any = None) -> Dict[str, Any]:
    lg = _norm_league(league)
    sm = _stats_marker(lg, game_date=game_date)
    om = _sos_marker(lg, game_date=game_date)
    sm_status = str(sm.get("status", "")).strip().upper()
    om_status = str(om.get("status", "")).strip().upper()
    s_ok = _ok_status(sm.get("status"))
    o_ok = _ok_status(om.get("status"))

    stats_state = _state_from_marker(sm, "STATS")
    sos_state = _state_from_marker(om, "SOS")
    if sm_status == "NO_GAMES" and om_status == "NO_GAMES":
        readiness_state = "NO_GAMES"
        dep = "NO_GAMES"
    elif s_ok and o_ok:
        readiness_state = "READY"
        dep = "READY"
    else:
        readiness_state = "BLOCKED"
        dep = "BLOCKED"
    issues = []
    if not sm:
        issues.append("stats_marker_missing")
    if not om:
        issues.append("sos_marker_missing")
    if sm and not s_ok:
        issues.append(f"stats_status_{str(sm.get('status', 'unknown')).lower()}")
    if om and not o_ok:
        issues.append(f"sos_status_{str(om.get('status', 'unknown')).lower()}")
    detail = "; ".join(issues) if issues else "ok"
    return {
        "league": lg,
        "readiness_state": readiness_state,
        "stats_state": stats_state,
        "sos_state": sos_state,
        "detail": detail,
        "dependency_status": dep,
        "issues": issues,
        "stats_status": str(sm.get("status", "")),
        "sos_status": str(om.get("status", "")),
        "stats_marker": sm,
        "sos_marker": om,
    }


def _safe_int(v: Any) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "null", "n/a", "na"}:
        return None
    s = s.replace("%", "").replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _canon_team(name: Any) -> str:
    s = str(name or "").strip().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
        "st louis": "st louis",
        "st. louis": "st louis",
        "avs": "colorado avalanche",
        "avalanche": "colorado avalanche",
        "wild": "minnesota wild",
        "canadiens": "montreal canadiens",
        "habs": "montreal canadiens",
        "hurricanes": "carolina hurricanes",
        "canes": "carolina hurricanes",
        "golden knights": "vegas golden knights",
        "knights": "vegas golden knights",
        "sabres": "buffalo sabres",
        "oilers": "edmonton oilers",
        "ducks": "anaheim ducks",
        "hurricanes": "carolina hurricanes",
        "montreal": "montreal canadiens",
        "carolina": "carolina hurricanes",
        "colorado": "colorado avalanche",
        "vegas": "vegas golden knights",
        "buffalo": "buffalo sabres",
        "edmonton": "edmonton oilers",
        "anaheim": "anaheim ducks",
    }
    return aliases.get(s, s)


def _extract_matchup_rows(league: str, game_date: Any = None) -> list[dict[str, Any]]:
    token = _date_token(game_date)
    path = _STATS_DIR / f"Matchups_{league}_{token}.xlsx"
    if not path.exists():
        if not _allow_latest_fallback():
            return []
        cands = sorted(_STATS_DIR.glob(f"Matchups_{league}_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        path = cands[0] if cands else path
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        xls = pd.ExcelFile(path)
        for sheet in xls.sheet_names:
            df = pd.read_excel(path, sheet_name=sheet)
            if df is None or df.empty or len(df.columns) < 3:
                continue
            c0, c1, c2 = list(df.columns)[:3]
            away = str(c1).strip()
            home = str(c2).strip()
            rec: dict[str, Any] = {"away_team": away, "home_team": home, "sheet": sheet}
            for _, row in df.iterrows():
                k = str(row.get(c0, "")).strip()
                if not k:
                    continue
                rec[k] = row.get(c1)
                rec[f"home__{k}"] = row.get(c2)
            out.append(rec)
    except Exception as exc:
        log.warning("Failed reading matchup workbook %s: %s", path, exc)
    return out


def _load_rawstats_df(league: str, game_date: Any = None) -> pd.DataFrame:
    token = _date_token(game_date)
    path = _STATS_DIR / f"RawStats_{league}_{token}.xlsx"
    if not path.exists():
        if not _allow_latest_fallback():
            return pd.DataFrame()
        cands = sorted(_STATS_DIR.glob(f"RawStats_{league}_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        path = cands[0] if cands else path
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_excel(path)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    first_col = str(df.columns[0])
    if first_col != "Team":
        df = df.rename(columns={first_col: "Team"})
    return df


_NBA_NICK_TO_CITY = {
    "cavaliers": "cleveland",
    "knicks": "new york",
    "thunder": "okla city",
    "warriors": "golden state",
    "spurs": "san antonio",
    "lakers": "la lakers",
    "clippers": "la clippers",
    "blazers": "portland",
    "trail blazers": "portland",
    "sixers": "philadelphia",
    "76ers": "philadelphia",
}


def _find_rawstats_team_row(df: pd.DataFrame, team_name: Any, league: str) -> pd.Series | None:
    if df is None or df.empty or "Team" not in df.columns:
        return None
    target = _canon_team(team_name)
    for _, row in df.iterrows():
        if _canon_team(row.get("Team")) == target:
            return row
    if str(league).upper() == "NBA":
        mapped = _NBA_NICK_TO_CITY.get(target, "")
        if mapped:
            for _, row in df.iterrows():
                if _canon_team(row.get("Team")) == mapped:
                    return row
    tt = {t for t in target.split() if t}
    best = None
    best_score = 0.0
    for _, row in df.iterrows():
        cur = _canon_team(row.get("Team"))
        ct = {t for t in cur.split() if t}
        score = (len(tt & ct) / max(1, len(tt))) if tt else 0.0
        if score > best_score:
            best_score = score
            best = row
    if best is not None and best_score >= 0.5:
        return best
    return None


def _rawstats_matchup_fallback(league: str, away_team: Any, home_team: Any, game_date: Any = None) -> dict[str, Any]:
    df = _load_rawstats_df(league, game_date=game_date)
    if df is None or df.empty:
        return {}
    away_row = _find_rawstats_team_row(df, away_team, league)
    home_row = _find_rawstats_team_row(df, home_team, league)
    if away_row is None or home_row is None:
        return {}
    out: dict[str, Any] = {"away_team": away_team, "home_team": home_team, "sheet": f"{league}_RAWSTATS_FALLBACK"}
    for c in df.columns:
        if str(c) == "Team":
            continue
        out[str(c)] = away_row.get(c)
        out[f"home__{str(c)}"] = home_row.get(c)
    return out


def _meta_stat_key(k: str) -> bool:
    s = str(k or "").strip().lower()
    if not s:
        return True
    if s in {"date", "time (et)", "stats_source", "stats_coverage", "no stats"}:
        return True
    if s.startswith("---"):
        return True
    return False


def _all_numeric_stat_diffs(match: dict[str, Any]) -> list[tuple[str, float, float]]:
    """
    Return list of (metric, away_val, home_val) for all numeric paired matchup stats.
    """
    out: list[tuple[str, float, float]] = []
    if not isinstance(match, dict) or not match:
        return out
    for k, away_raw in list(match.items()):
        if k.startswith("home__"):
            continue
        if _meta_stat_key(k):
            continue
        hk = f"home__{k}"
        if hk not in match:
            continue
        av = _to_float(away_raw)
        hv = _to_float(match.get(hk))
        if av is None or hv is None:
            continue
        out.append((str(k), float(av), float(hv)))
    return out


def _stats_score_from_all_metrics(match: dict[str, Any]) -> tuple[float, list[str], int]:
    """
    Build stats_score from every numeric scraped stat pair in the matchup sheet.
    """
    pairs = _all_numeric_stat_diffs(match)
    if not pairs:
        return 0.0, [], 0
    contribs: list[float] = []
    factors: list[str] = []
    for metric, av, hv in pairs:
        m = metric.lower()
        denom = max(1.0, abs(av) + abs(hv))
        diff = (av - hv) / denom
        # For "opponent*" style stats, lower is better; invert signal.
        if "opponent" in m or "against" in m:
            diff = -diff
        contribs.append(diff)
    score = float(sum(contribs) / max(1, len(contribs)))
    score = max(-1.0, min(1.0, score * 4.0))
    factors.append(f"stats_metrics_used:{len(pairs)}")
    return score, factors, len(pairs)


def _pick_matchup_record(rows: list[dict[str, Any]], away_team: Any, home_team: Any) -> dict[str, Any]:
    if not rows:
        return {}
    a = _canon_team(away_team)
    h = _canon_team(home_team)
    # exact canonical match first
    for r in rows:
        ra = _canon_team(r.get("away_team"))
        rh = _canon_team(r.get("home_team"))
        if ra == a and rh == h:
            return r
    # fallback: token containment
    for r in rows:
        ra = _canon_team(r.get("away_team"))
        rh = _canon_team(r.get("home_team"))
        if a and h and (a in ra or ra in a) and (h in rh or rh in h):
            return r
    # fallback: token-overlap best match (handles short names like "Mets", "Avs", etc.)
    def _tok(s: str) -> set[str]:
        return {t for t in str(s or "").split() if t}
    at = _tok(a)
    ht = _tok(h)
    best = {}
    best_score = -1.0
    for r in rows:
        ra = _canon_team(r.get("away_team"))
        rh = _canon_team(r.get("home_team"))
        rat = _tok(ra)
        rht = _tok(rh)
        a_score = (len(at & rat) / max(1, len(at))) if at else 0.0
        h_score = (len(ht & rht) / max(1, len(ht))) if ht else 0.0
        score = a_score + h_score
        if score > best_score:
            best_score = score
            best = r
    if best and best_score >= 1.0:
        return best
    return {}


def _extract_sos_game_block(league: str, away_team: Any, home_team: Any, game_date: Any = None) -> dict[str, Any]:
    token = _date_token(game_date)
    path = _SOS_DIR / f"SOS_{league}_{token}.xlsx"
    if not path.exists():
        if not _allow_latest_fallback():
            return {}
        cands = sorted(_SOS_DIR.glob(f"SOS_{league}_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        path = cands[0] if cands else path
    if not path.exists():
        return {}
    try:
        df = pd.read_excel(path, sheet_name="Matchup Comparisons")
    except Exception:
        return {}
    a = _canon_team(away_team)
    h = _canon_team(home_team)
    # Primary path: parse metric rows keyed by game_id.
    try:
        metric_rows = []
        for _, rr in df.iterrows():
            vals = [str(v).strip() for v in rr.tolist()]
            if len(vals) < 5:
                continue
            metric = vals[0]
            game_id = vals[4]
            if not game_id or game_id.lower() in {"nan", "none"}:
                continue
            gid = _canon_team(game_id.replace(":", " ").replace("@", " "))
            if a and h and a in gid and h in gid and metric.lower() not in {"metric", "nan"}:
                metric_rows.append(vals)
        if metric_rows:
            block = {"metrics": {}, "advantage_counts": {"away": 0, "home": 0, "even": 0}}
            for vals in metric_rows:
                metric = vals[0]
                away_val = _to_float(vals[1])
                home_val = _to_float(vals[2])
                adv = vals[3].strip().lower()
                block["metrics"][metric] = {"away": away_val, "home": home_val, "advantage": vals[3]}
                advn = _canon_team(adv)
                if "even" in advn:
                    block["advantage_counts"]["even"] += 1
                elif a and a in advn:
                    block["advantage_counts"]["away"] += 1
                elif h and h in advn:
                    block["advantage_counts"]["home"] += 1
            return block
    except Exception:
        pass
    # normalize rows to text lists
    rows = []
    for _, rr in df.iterrows():
        vals = [str(v).strip() for v in rr.tolist()]
        vals = [v for v in vals if v and v.lower() != "nan"]
        rows.append(vals)
    a = _canon_team(away_team)
    h = _canon_team(home_team)
    start = -1
    for i, vals in enumerate(rows):
        line = " ".join(vals).lower()
        if "@" in line and a and h and (a in _canon_team(line) and h in _canon_team(line)):
            start = i
            break
    if start < 0:
        return {}
    block: dict[str, Any] = {"metrics": {}, "advantage_counts": {"away": 0, "home": 0, "even": 0}}
    i = start + 1
    while i < len(rows):
        vals = rows[i]
        if not vals:
            i += 1
            continue
        if "@" in " ".join(vals).lower() and i > start + 1:
            break
        if len(vals) >= 4 and vals[0].lower() != "metric":
            metric = vals[0]
            away_val = _to_float(vals[1])
            home_val = _to_float(vals[2])
            adv = vals[3].strip().lower()
            block["metrics"][metric] = {"away": away_val, "home": home_val, "advantage": vals[3]}
            if "even" in adv:
                block["advantage_counts"]["even"] += 1
            elif _canon_team(away_team) in _canon_team(adv):
                block["advantage_counts"]["away"] += 1
            elif _canon_team(home_team) in _canon_team(adv):
                block["advantage_counts"]["home"] += 1
        i += 1
    return block


def _derived_coverage(rd: Dict[str, Any]) -> float:
    """
    Derive a real numeric coverage from status markers instead of defaulting to 0.
    """
    sm = dict(rd.get("stats_marker") or {})
    om = dict(rd.get("sos_marker") or {})
    if str(rd.get("readiness_state", "")).upper() != "READY":
        return 0.0

    explicit_cov = sm.get("coverage")
    try:
        if explicit_cov is not None:
            return max(0.0, min(1.0, float(explicit_cov)))
    except Exception:
        pass

    stats_games = max(0, _safe_int(sm.get("games_found") or sm.get("games") or sm.get("game_count")))
    sos_games = max(0, _safe_int(om.get("games_matched") or om.get("games_found") or om.get("games")))
    if stats_games > 0 and sos_games > 0:
        return max(0.0, min(1.0, float(min(stats_games, sos_games)) / float(max(stats_games, 1))))
    if stats_games > 0:
        return 1.0
    return 0.0


def get_stats_for_matchup(sport=None, away_team=None, home_team=None, **kw):
    lg = _norm_league(sport)
    rd = _readiness_for_league(lg, game_date=(kw or {}).get("game_date"))
    matchup_rows = _extract_matchup_rows(lg, game_date=(kw or {}).get("game_date"))
    match = _pick_matchup_record(matchup_rows, away_team, home_team)
    cov_raw = str(match.get("STATS_COVERAGE") or "").strip()
    cov_num = None
    if "/" in cov_raw:
        try:
            a, b = cov_raw.split("/", 1)
            aa = max(0.0, float(a))
            bb = max(1.0, float(b))
            cov_num = max(0.0, min(1.0, aa / bb))
        except Exception:
            cov_num = None
    return {
        "away": away_team,
        "home": home_team,
        "league": lg,
        "status": "READY" if rd.get("readiness_state") == "READY" else "BLOCKED",
        "source": "stats_status_marker",
        "detail": rd.get("detail", ""),
        "coverage": cov_num,
        "matchup_stats": match,
    }


def get_sos_from_file(sport=None, **kw):
    lg = _norm_league(sport)
    rd = _readiness_for_league(lg, game_date=(kw or {}).get("game_date"))
    away_team = (kw or {}).get("away_team")
    home_team = (kw or {}).get("home_team")
    block = _extract_sos_game_block(lg, away_team, home_team, game_date=(kw or {}).get("game_date"))
    return {
        "league": lg,
        "status": "READY" if rd.get("readiness_state") == "READY" else "BLOCKED",
        "source": "sos_status_marker",
        "detail": rd.get("detail", ""),
        "marker": rd.get("sos_marker", {}),
        "matchup_sos": block,
    }


def get_stats_sos_model_signal(sport=None, away_team=None, home_team=None, **kw):
    lg = _norm_league(sport)
    game_date = (kw or {}).get("game_date")
    rd = _readiness_for_league(lg, game_date=game_date)
    if rd.get("readiness_state") != "READY":
        return {
            "score": 0.0,
            "coverage": 0.0,
            "expected_total": None,
            "stats_score": 0.0,
            "sos_score": 0.0,
            "stats_coverage": 0.0,
            "sos_coverage": 0.0,
            "factors": [],
            "status": "BLOCKED",
            "error": rd.get("detail", "blocked"),
        }
    # Real stats/SOS signal from scraped matchup and SOS artifacts.
    matchup_rows = _extract_matchup_rows(lg, game_date=game_date)
    match = _pick_matchup_record(matchup_rows, away_team, home_team)
    sos = _extract_sos_game_block(lg, away_team, home_team, game_date=game_date)
    _cov = _derived_coverage(rd)
    _no_stats_flag = str(match.get("NO STATS") or "").strip().upper()
    if (not bool(match)) or _no_stats_flag == "FAILED":
        fb_match = _rawstats_matchup_fallback(lg, away_team, home_team, game_date=game_date)
        if fb_match:
            match = fb_match
    _stat_cov_raw = str(match.get("STATS_COVERAGE") or "").strip()
    stats_cov = 0.0
    if "/" in _stat_cov_raw:
        try:
            a, b = _stat_cov_raw.split("/", 1)
            stats_cov = max(0.0, min(1.0, float(a) / max(1.0, float(b))))
        except Exception:
            stats_cov = 0.0
    sos_cov = _cov
    if stats_cov <= 0.0:
        stats_cov = _cov

    expected_total = None
    sos_score = 0.0
    stats_score = 0.0
    factors = []
    stats_source_empty = False
    _no_stats_flag = str(match.get("NO STATS") or "").strip().upper()
    if _no_stats_flag == "FAILED":
        stats_source_empty = True
    # Expected total model per sport from matchup stat sheet.
    if lg == "MLB":
        ar = _to_float(match.get("runs-per-game"))
        hr = _to_float(match.get("home__runs-per-game"))
        aor = _to_float(match.get("opponent-runs-per-game"))
        hor = _to_float(match.get("home__opponent-runs-per-game"))
        vals = [v for v in (ar, hr, aor, hor) if v is not None]
        if len(vals) >= 2:
            expected_total = float(sum(vals) / 2.0)
            if ar is not None and hr is not None:
                factors.append(f"mlb_rpg:{ar:.2f}/{hr:.2f}")
            # stats-side matchup differential (offense minus opponent suppression)
            if None not in (ar, hr, aor, hor):
                stats_score = ((ar - hor) - (hr - aor)) / 10.0
    elif lg in {"NBA", "NCAAB"}:
        appg = _to_float(match.get("points-per-game"))
        hppg = _to_float(match.get("home__points-per-game"))
        aopp = _to_float(match.get("opponent-points-per-game"))
        hopp = _to_float(match.get("home__opponent-points-per-game"))
        vals = [v for v in (appg, hppg, aopp, hopp) if v is not None]
        if len(vals) >= 2:
            expected_total = float(sum(vals) / 2.0)
            factors.append("hoops_ppg_oppg_blend")
            if None not in (appg, hppg, aopp, hopp):
                stats_score = ((appg - hopp) - (hppg - aopp)) / 25.0
    elif lg == "NHL":
        ag = _to_float(match.get("goals-per-game"))
        hg = _to_float(match.get("home__goals-per-game"))
        aog = _to_float(match.get("opponent-goals-per-game"))
        hog = _to_float(match.get("home__opponent-goals-per-game"))
        vals = [v for v in (ag, hg, aog, hog) if v is not None]
        if len(vals) >= 2:
            expected_total = float(sum(vals) / 2.0)
            factors.append("nhl_gpg_oppg_blend")
            if None not in (ag, hg, aog, hog):
                stats_score = ((ag - hog) - (hg - aog)) / 6.0

    # All-stats score from every numeric scraped stat pair (separate from SOS).
    _all_stats_score, _all_stats_factors, _stats_metric_count = _stats_score_from_all_metrics(match)
    if _stats_metric_count > 0:
        stats_score = _all_stats_score
        factors.extend(_all_stats_factors)
    elif stats_source_empty:
        factors.append("stats_source_empty")
    else:
        factors.append("stats_numeric_pairs_missing")

    # SOS directional signal from advantage counts.
    adv = dict((sos or {}).get("advantage_counts") or {})
    away_adv = int(adv.get("away", 0) or 0)
    home_adv = int(adv.get("home", 0) or 0)
    total_adv = max(1, away_adv + home_adv + int(adv.get("even", 0) or 0))
    sos_score = (away_adv - home_adv) / float(total_adv)
    sos_score = max(-1.0, min(1.0, sos_score))
    if away_adv or home_adv:
        factors.append(f"sos_adv:{away_adv}-{home_adv}")

    # Composite keeps backward compatibility for existing caller.
    score = max(-1.0, min(1.0, (0.65 * stats_score) + (0.35 * sos_score)))

    return {
        "score": score,
        "coverage": max(stats_cov, sos_cov),
        "expected_total": expected_total,
        "stats_score": stats_score,
        "sos_score": sos_score,
        "stats_coverage": stats_cov,
        "sos_coverage": sos_cov,
        "stats_metric_count": _stats_metric_count,
        "stats_source_empty": stats_source_empty,
        "factors": factors or ["stats_sos_ready_contract_valid"],
        "status": "READY",
        "error": "",
    }


def _txt_write(txt: Any, line: str, tag: str = "value") -> None:
    try:
        txt.insert("end", str(line), tag)
    except Exception:
        try:
            txt.insert("end", str(line))
        except Exception:
            pass


def _txt_sep(txt: Any, width: int = 58, char: str = "-") -> None:
    c = str(char or "-")
    _txt_write(txt, f"{c[0] * width}\n", "sep")


def _fmt_stat_val(v: Any) -> str:
    if v is None:
        return "N/A"
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return "N/A"
    return s


def _pretty_metric_name(name: Any) -> str:
    s = str(name or "").strip()
    if not s:
        return "N/A"
    s = s.replace("home__", "")
    s = s.replace("--", "/")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _resolve_render_args(*a, **kw) -> tuple[Any, str, Any, Any, Any]:
    txt = None
    sport = kw.get("sport")
    away_team = kw.get("away_team")
    home_team = kw.get("home_team")
    game_date = kw.get("game_date")

    if a:
        txt = a[0]
    if sport is None and len(a) > 1:
        sport = a[1]
    if away_team is None and len(a) > 2:
        away_team = a[2]
    if home_team is None and len(a) > 3:
        home_team = a[3]
    if game_date is None and len(a) > 4:
        game_date = a[4]
    return txt, _norm_league(sport), away_team, home_team, game_date


def render_stats_sos_block(*a, **kw):
    txt, lg, away_team, home_team, game_date = _resolve_render_args(*a, **kw)
    rd = _readiness_for_league(lg, game_date=game_date) if lg else {"readiness_state": "BLOCKED"}
    if txt is None:
        return {"status": rd.get("readiness_state", "BLOCKED"), "league": lg}

    _txt_write(txt, "\n  TEAM STATS INTEGRATION (SCRAPES)\n", "section")
    _txt_sep(txt)

    matchup_rows = _extract_matchup_rows(lg, game_date=game_date)
    match = _pick_matchup_record(matchup_rows, away_team, home_team)
    no_stats_flag = str((match or {}).get("NO STATS") or "").strip().upper()
    stats_cov = str((match or {}).get("STATS_COVERAGE") or "").strip()

    if (not match) or no_stats_flag == "FAILED":
        fb_match = _rawstats_matchup_fallback(lg, away_team, home_team, game_date=game_date)
        if fb_match:
            match = fb_match
            if not stats_cov:
                stats_cov = "RAWSTATS_FALLBACK"

    sig = get_stats_sos_model_signal(
        sport=lg,
        away_team=away_team,
        home_team=home_team,
        game_date=game_date,
    )
    stats_metric_count = int(sig.get("stats_metric_count") or 0)

    _txt_write(txt, "  Source: stats_output/Matchups_* and stats_output/RawStats_*\n", "label")
    _txt_write(txt, f"  League: {lg or 'N/A'}\n", "label")
    _txt_write(txt, f"  Matchup sheet: {_fmt_stat_val((match or {}).get('sheet'))}\n", "label")
    _txt_write(txt, f"  STATS_COVERAGE: {_fmt_stat_val(stats_cov or 'N/A')}\n", "label")
    _txt_write(txt, f"  NO STATS flag: {_fmt_stat_val(no_stats_flag or 'NONE')}\n", "label")
    _txt_write(txt, f"  Numeric metrics parsed: {stats_metric_count}\n", "label")
    _txt_write(txt, f"  Stats score: {float(sig.get('stats_score') or 0.0):.4f}\n", "label")

    pairs = _all_numeric_stat_diffs(match or {})
    if pairs:
        _txt_write(txt, f"\n  Mapped team stats (away | home) - all {len(pairs)} metrics:\n", "label")
        for metric, av, hv in pairs:
            _m = _pretty_metric_name(metric)
            _txt_write(txt, f"   - {_m}: {av} | {hv}\n", "value")
    else:
        _txt_write(txt, "\n  No numeric team stat pairs found for this matchup.\n", "warn")

    _txt_write(txt, "\n  SOS CONTEXT (SOS_SCRAPER)\n", "section")
    _txt_sep(txt)
    sos = _extract_sos_game_block(lg, away_team, home_team, game_date=game_date)
    adv = dict((sos or {}).get("advantage_counts") or {})
    away_adv = int(adv.get("away", 0) or 0)
    home_adv = int(adv.get("home", 0) or 0)
    even_adv = int(adv.get("even", 0) or 0)
    _txt_write(txt, "  Source: sos_data/SOS_*\n", "label")
    _txt_write(txt, f"  SOS score: {float(sig.get('sos_score') or 0.0):.4f}\n", "label")
    _txt_write(txt, f"  Advantage counts (away/home/even): {away_adv}/{home_adv}/{even_adv}\n", "label")
    _metrics = dict((sos or {}).get("metrics") or {})
    if _metrics:
        _txt_write(txt, f"\n  SOS metrics (all {len(_metrics)}):\n", "label")
        for m_name, m_obj in list(_metrics.items()):
            _m = _pretty_metric_name(m_name)
            av = _fmt_stat_val((m_obj or {}).get("away"))
            hv = _fmt_stat_val((m_obj or {}).get("home"))
            advs = _fmt_stat_val((m_obj or {}).get("advantage"))
            _txt_write(txt, f"   - {_m}: {av} | {hv}  (adv: {advs})\n", "value")
    else:
        _txt_write(txt, "\n  No SOS metric block matched this game.\n", "warn")

    readiness = rd.get("readiness_state", "BLOCKED")
    _txt_write(txt, f"\n  Readiness: {readiness}\n", "label")
    if rd.get("detail"):
        _txt_write(txt, f"  Detail: {rd.get('detail')}\n", "label")

    return {
        "status": readiness,
        "league": lg,
        "stats_metric_count": stats_metric_count,
        "stats_coverage": stats_cov or "",
        "no_stats_flag": no_stats_flag,
        "sos_metric_count": len(_metrics),
    }


def add_stats_fetch_button(*a, **kw):
    if len(a) < 6:
        return None
    parent, _win, txt, sport, away_team, home_team = a[:6]
    status_callback = (kw or {}).get("status_callback")
    game_date = (kw or {}).get("game_date")
    try:
        from tkinter import ttk  # type: ignore
    except Exception:
        return None

    def _on_fetch() -> None:
        try:
            render_stats_sos_block(
                txt, sport, away_team, home_team, game_date,
            )
            if callable(status_callback):
                status_callback("Stats/SOS panel refreshed from scraper artifacts.")
        except Exception as exc:
            if callable(status_callback):
                status_callback(f"Stats/SOS refresh failed: {exc}")

    try:
        btn = ttk.Button(parent, text="Fetch Stats + SOS", command=_on_fetch)
        btn.pack(side="left", padx=(6, 0))
        return btn
    except Exception:
        return None


def invalidate_stats_cache(*a, **kw):
    return None


def invalidate_sos_cache(*a, **kw):
    return None


def get_league_readiness(*a, **kw):
    league = None
    if a:
        league = a[0]
    if league is None:
        league = (kw or {}).get("sport") or (kw or {}).get("league")
    return _readiness_for_league(_norm_league(league), game_date=(kw or {}).get("game_date"))


def get_all_league_readiness(*a, **kw):
    leagues: Iterable[str] = ()
    if a:
        first = a[0]
        if isinstance(first, (list, tuple, set)):
            leagues = [str(x) for x in first]
    if not leagues:
        leagues = (kw or {}).get("leagues") or _LEAGUES
    out: Dict[str, Dict[str, Any]] = {}
    _game_date = (kw or {}).get("game_date")
    for lg in leagues:
        n = _norm_league(lg)
        if not n:
            continue
        out[n] = _readiness_for_league(n, game_date=_game_date)
    return out
