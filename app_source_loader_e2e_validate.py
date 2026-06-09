#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from stats_sos_integration import get_stats_sos_model_signal

BASE = Path(__file__).resolve().parent
ODDS_DIR = BASE / "odds_data"
STATS_DIR = BASE / "stats_output"
SOS_DIR = BASE / "sos_data"
OUT_DIR = BASE / "diagnostics"
OUT_DIR.mkdir(exist_ok=True)

SPORTS = ("NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL")


def _token() -> str:
    return datetime.now().strftime("%Y%m%d")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ok(status: str) -> bool:
    return str(status or "").strip().upper() in {"READY", "NO_GAMES"}


def _pick_col(df: pd.DataFrame, names: list[str]) -> str:
    m = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in m:
            return str(m[n.lower()])
    return ""


def run(tok: str | None = None) -> Path:
    day = str(tok or _token())
    rows: list[dict[str, Any]] = []
    for sport in SPORTS:
        sm = _read_json(STATS_DIR / f"StatsStatus_{sport}_{day}.json")
        om = _read_json(SOS_DIR / f"SOSStatus_{sport}_{day}.json")
        ss = str(sm.get("status", "MISSING")).upper()
        os = str(om.get("status", "MISSING")).upper()
        if ss == "NO_GAMES" and os == "NO_GAMES":
            rows.append(
                {
                    "date_token": day,
                    "sport": sport,
                    "source_file": str(ODDS_DIR / f"Odds_{sport}_{day}.xlsx"),
                    "stats_status": ss,
                    "sos_status": os,
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "mapped_ok": True,
                    "stats_metric_count": 0,
                    "reason": "NO_GAMES",
                }
            )
            continue
        ready = bool(_ok(ss) and _ok(os))
        odds_file = ODDS_DIR / f"Odds_{sport}_{day}.xlsx"

        if not ready:
            rows.append(
                {
                    "date_token": day,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "stats_status": ss,
                    "sos_status": os,
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "mapped_ok": False,
                    "stats_metric_count": 0,
                    "reason": "LEAGUE_NOT_READY",
                }
            )
            continue
        if not odds_file.exists():
            rows.append(
                {
                    "date_token": day,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "stats_status": ss,
                    "sos_status": os,
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "mapped_ok": False,
                    "stats_metric_count": 0,
                    "reason": "ODDS_TODAY_FILE_MISSING",
                }
            )
            continue
        try:
            df = pd.read_excel(odds_file)
        except Exception as e:
            rows.append(
                {
                    "date_token": day,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "stats_status": ss,
                    "sos_status": os,
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "mapped_ok": False,
                    "stats_metric_count": 0,
                    "reason": f"ODDS_READ_FAILED:{type(e).__name__}",
                }
            )
            continue

        away_col = _pick_col(df, ["Away_Team", "Away Team", "Away"])
        home_col = _pick_col(df, ["Home_Team", "Home Team", "Home"])
        total_col = _pick_col(df, ["Total", "OU_Line", "O/U", "Over/Under"])
        if not away_col or not home_col:
            rows.append(
                {
                    "date_token": day,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "stats_status": ss,
                    "sos_status": os,
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "mapped_ok": False,
                    "stats_metric_count": 0,
                    "reason": "ODDS_SCHEMA_MISSING_AWAY_HOME",
                }
            )
            continue

        for i, r in df.iterrows():
            away = str(r.get(away_col, "") or "").strip()
            home = str(r.get(home_col, "") or "").strip()
            if not away or not home:
                continue
            total = r.get(total_col) if total_col else None
            sig = get_stats_sos_model_signal(sport=sport, away_team=away, home_team=home, game_date=day, ou_line=total)
            mc = int(sig.get("stats_metric_count") or 0)
            se = bool(sig.get("stats_source_empty"))
            ok = bool(mc > 0 and not se)
            rows.append(
                {
                    "date_token": day,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "stats_status": ss,
                    "sos_status": os,
                    "source_row": int(i),
                    "away": away,
                    "home": home,
                    "mapped_ok": ok,
                    "stats_metric_count": mc,
                    "stats_source_empty": se,
                    "stats_score": float(sig.get("stats_score") or 0.0),
                    "sos_score": float(sig.get("sos_score") or 0.0),
                    "reason": "" if ok else "TEAM_STATS_NOT_MAPPED",
                }
            )

    out = OUT_DIR / f"app_source_loader_e2e_{day}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


if __name__ == "__main__":
    p = run()
    print(f"E2E={p}")
