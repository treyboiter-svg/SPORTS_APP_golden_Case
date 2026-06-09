from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json

import pandas as pd

from odds_data.referee_signal_engine import get_referee_signal


BASE = Path(__file__).resolve().parent
ODDS_DIR = BASE / "odds_data"
STATS_DIR = BASE / "stats_output"
OUT_DIR = BASE / "diagnostics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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


def _pick_col(df: pd.DataFrame, cands: list[str]) -> str:
    m = {str(c).strip().lower(): c for c in df.columns}
    for c in cands:
        if c.lower() in m:
            return str(m[c.lower()])
    return ""


def _classify(result: dict[str, Any]) -> tuple[str, str]:
    names = list(result.get("ref_names") or [])
    detail = str(result.get("detail") or "").strip()
    src_state = str(result.get("source_state") or "").strip().upper()
    dlow = detail.lower()

    if names:
        return "MATCHED", ""
    if src_state == "UNSUPPORTED":
        return "UNSUPPORTED", "OFFICIALS_SOURCE_UNSUPPORTED"
    if "not published upstream" in dlow:
        return "NOT_PUBLISHED_UPSTREAM", "OFFICIALS_NOT_PUBLISHED_UPSTREAM"
    if src_state in {"MISSING", "EMPTY", "UNKNOWN"}:
        return src_state or "SOURCE_UNKNOWN", f"OFFICIALS_SOURCE_{src_state or 'UNKNOWN'}"
    if "file unavailable" in dlow:
        return "SOURCE_MISSING", "OFFICIALS_FILE_UNAVAILABLE"
    if "file present but empty" in dlow:
        return "SOURCE_EMPTY", "OFFICIALS_FILE_EMPTY"
    return "ASSIGNMENT_MISSING", "OFFICIALS_ASSIGNMENT_MISSING"


def run(token: str | None = None) -> tuple[Path, Path]:
    tok = str(token or _today_token())
    rows: list[dict[str, Any]] = []

    for sport in SPORTS:
        stats_marker = _read_json(STATS_DIR / f"StatsStatus_{sport}_{tok}.json")
        stats_status = str(stats_marker.get("status", "")).upper().strip()
        odds_file = ODDS_DIR / f"Odds_{sport}_{tok}.xlsx"

        if not odds_file.exists():
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "stats_status": stats_status or "MISSING",
                    "officials_status": "NO_GAMES" if stats_status == "NO_GAMES" else "ODDS_MISSING",
                    "issue_code": "" if stats_status == "NO_GAMES" else "ODDS_FILE_MISSING",
                    "ref_count": 0,
                    "ref_names": "",
                    "detail": "no games marker" if stats_status == "NO_GAMES" else "odds workbook missing",
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
                    "stats_status": stats_status or "MISSING",
                    "officials_status": "ODDS_READ_FAILED",
                    "issue_code": f"ODDS_READ_FAILED:{type(e).__name__}",
                    "ref_count": 0,
                    "ref_names": "",
                    "detail": str(e)[:200],
                }
            )
            continue

        away_col = _pick_col(df, ["Away_Team", "Away Team", "Away"])
        home_col = _pick_col(df, ["Home_Team", "Home Team", "Home"])
        if not away_col or not home_col:
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": -1,
                    "away": "",
                    "home": "",
                    "stats_status": stats_status or "MISSING",
                    "officials_status": "ODDS_SCHEMA_INVALID",
                    "issue_code": "ODDS_SCHEMA_MISSING_AWAY_HOME",
                    "ref_count": 0,
                    "ref_names": "",
                    "detail": "away/home columns missing",
                }
            )
            continue

        for i, rec in df.iterrows():
            away = str(rec.get(away_col, "") or "").strip()
            home = str(rec.get(home_col, "") or "").strip()
            if stats_status == "NO_GAMES":
                rows.append(
                    {
                        "token": tok,
                        "sport": sport,
                        "source_file": str(odds_file),
                        "source_row": int(i),
                        "away": away,
                        "home": home,
                        "stats_status": stats_status or "MISSING",
                        "officials_status": "NO_GAMES",
                        "issue_code": "",
                        "ref_count": 0,
                        "ref_names": "",
                        "detail": "stats marker reports NO_GAMES for this league/date",
                    }
                )
                continue
            if not away or not home:
                rows.append(
                    {
                        "token": tok,
                        "sport": sport,
                        "source_file": str(odds_file),
                        "source_row": int(i),
                        "away": away,
                        "home": home,
                        "stats_status": stats_status or "MISSING",
                        "officials_status": "ROW_MISSING_TEAM",
                        "issue_code": "ODDS_ROW_MISSING_AWAY_OR_HOME",
                        "ref_count": 0,
                        "ref_names": "",
                        "detail": "away/home empty",
                    }
                )
                continue

            result = get_referee_signal(sport=sport, game_date=tok, away_team=away, home_team=home)
            status, issue = _classify(result)
            names = list(result.get("ref_names") or [])
            rows.append(
                {
                    "token": tok,
                    "sport": sport,
                    "source_file": str(odds_file),
                    "source_row": int(i),
                    "away": away,
                    "home": home,
                    "stats_status": stats_status or "MISSING",
                    "officials_status": status,
                    "issue_code": issue,
                    "ref_count": len(names),
                    "ref_names": " | ".join(str(x) for x in names),
                    "detail": str(result.get("detail") or ""),
                }
            )

    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"officials_mapping_audit_{tok}.csv"
    out_latest = OUT_DIR / "officials_mapping_audit_latest.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    df.to_csv(out_latest, index=False, encoding="utf-8-sig")

    summary = (
        df.groupby(["sport", "officials_status"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values(["sport", "officials_status"])
    )
    out_summary = OUT_DIR / f"officials_mapping_summary_{tok}.csv"
    out_summary_latest = OUT_DIR / "officials_mapping_summary_latest.csv"
    summary.to_csv(out_summary, index=False, encoding="utf-8-sig")
    summary.to_csv(out_summary_latest, index=False, encoding="utf-8-sig")
    return out_csv, out_summary


if __name__ == "__main__":
    audit, summary = run()
    print(f"AUDIT={audit}")
    print(f"SUMMARY={summary}")
