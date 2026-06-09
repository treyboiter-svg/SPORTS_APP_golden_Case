#!/usr/bin/env python3
from __future__ import annotations

import json
import re
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


def _today_token() -> str:
    return datetime.now().strftime("%Y%m%d")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str:
    m = {str(c).strip().lower(): c for c in df.columns}
    for k in candidates:
        if k.lower() in m:
            return str(m[k.lower()])
    return ""


def run(token: str | None = None) -> Path:
    tok = str(token or _today_token())
    rows: list[dict[str, Any]] = []
    for sport in SPORTS:
        odds_file = ODDS_DIR / f"Odds_{sport}_{tok}.xlsx"
        stats_marker = _read_json(STATS_DIR / f"StatsStatus_{sport}_{tok}.json")
        sos_marker = _read_json(SOS_DIR / f"SOSStatus_{sport}_{tok}.json")
        stats_status = str(stats_marker.get("status", "MISSING")).upper()
        sos_status = str(sos_marker.get("status", "MISSING")).upper()
        if stats_status == "NO_GAMES" and sos_status == "NO_GAMES":
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "time": "",
                    "stats_status": stats_status,
                    "sos_status": sos_status,
                    "stats_metric_count": 0,
                    "stats_source_empty": True,
                    "stats_coverage": 0.0,
                    "sos_coverage": 0.0,
                    "stats_score": 0.0,
                    "sos_score": 0.0,
                    "mapped_ok": True,
                    "reason": "NO_GAMES",
                }
            )
            continue

        if not odds_file.exists():
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "time": "",
                    "stats_status": stats_status,
                    "sos_status": sos_status,
                    "stats_metric_count": 0,
                    "stats_source_empty": True,
                    "stats_coverage": 0.0,
                    "sos_coverage": 0.0,
                    "stats_score": 0.0,
                    "sos_score": 0.0,
                    "mapped_ok": False,
                    "reason": "ODDS_FILE_MISSING",
                }
            )
            continue

        try:
            df = pd.read_excel(odds_file)
        except Exception as e:
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "time": "",
                    "stats_status": stats_status,
                    "sos_status": sos_status,
                    "stats_metric_count": 0,
                    "stats_source_empty": True,
                    "stats_coverage": 0.0,
                    "sos_coverage": 0.0,
                    "stats_score": 0.0,
                    "sos_score": 0.0,
                    "mapped_ok": False,
                    "reason": f"ODDS_READ_FAILED:{type(e).__name__}",
                }
            )
            continue

        away_col = _pick_col(df, ["Away_Team", "Away Team", "Away"])
        home_col = _pick_col(df, ["Home_Team", "Home Team", "Home"])
        time_col = _pick_col(df, ["Time", "Game Time", "Date", "DateTime"])
        total_col = _pick_col(df, ["Total", "OU_Line", "O/U", "Over/Under"])
        if not away_col or not home_col:
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "time": "",
                    "stats_status": stats_status,
                    "sos_status": sos_status,
                    "stats_metric_count": 0,
                    "stats_source_empty": True,
                    "stats_coverage": 0.0,
                    "sos_coverage": 0.0,
                    "stats_score": 0.0,
                    "sos_score": 0.0,
                    "mapped_ok": False,
                    "reason": "ODDS_SCHEMA_MISSING_AWAY_HOME",
                }
            )
            continue

        for i, row in df.iterrows():
            away = str(row.get(away_col, "") or "").strip()
            home = str(row.get(home_col, "") or "").strip()
            tval = str(row.get(time_col, "") or "").strip() if time_col else ""
            total = row.get(total_col) if total_col else None
            if not away or not home:
                rows.append(
                    {
                        "token": tok,
                        "sport": sport,
                        "source_file": str(odds_file),
                        "source_row": int(i),
                        "away": away,
                        "home": home,
                        "time": tval,
                        "stats_status": stats_status,
                        "sos_status": sos_status,
                        "stats_metric_count": 0,
                        "stats_source_empty": True,
                        "stats_coverage": 0.0,
                        "sos_coverage": 0.0,
                        "stats_score": 0.0,
                        "sos_score": 0.0,
                        "mapped_ok": False,
                        "reason": "ROW_MISSING_AWAY_OR_HOME",
                    }
                )
                continue

            sig = get_stats_sos_model_signal(
                sport=sport,
                away_team=away,
                home_team=home,
                game_date=tok,
                ou_line=total,
            )
            metric_count = int(sig.get("stats_metric_count") or 0)
            stats_source_empty = bool(sig.get("stats_source_empty"))
            stats_cov = float(sig.get("stats_coverage") or 0.0)
            sos_cov = float(sig.get("sos_coverage") or 0.0)
            mapped_ok = bool(metric_count > 0 and not stats_source_empty)
            reason = ""
            if not mapped_ok:
                if stats_status == "NO_GAMES":
                    reason = "STATS_MARKER_NO_GAMES"
                elif stats_status != "READY":
                    reason = f"STATS_MARKER_{stats_status}"
                else:
                    reason = "MATCHUP_STATS_NOT_MAPPED"
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": int(i),
                    "away": away,
                    "home": home,
                    "time": tval,
                    "stats_status": stats_status,
                    "sos_status": sos_status,
                    "stats_metric_count": metric_count,
                    "stats_source_empty": stats_source_empty,
                    "stats_coverage": stats_cov,
                    "sos_coverage": sos_cov,
                    "stats_score": float(sig.get("stats_score") or 0.0),
                    "sos_score": float(sig.get("sos_score") or 0.0),
                    "mapped_ok": mapped_ok,
                    "reason": reason,
                }
            )

    out = OUT_DIR / f"ui_path_mapping_audit_{tok}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


if __name__ == "__main__":
    p = run()
    print(f"AUDIT={p}")
