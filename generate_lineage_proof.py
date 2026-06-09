#!/usr/bin/env python3
"""
Generate binary proof artifacts for source -> output -> ingest mapping.

Outputs:
  diagnostics/lineage_proof_summary_<TOKEN>.csv
  diagnostics/lineage_proof_per_game_<TOKEN>.csv
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from stats_sos_integration import get_stats_sos_model_signal


BASE = Path(__file__).resolve().parent
STATS_DIR = BASE / "stats_output"
SOS_DIR = BASE / "sos_data"
OUT_DIR = BASE / "diagnostics"
OUT_DIR.mkdir(exist_ok=True)

LEAGUES = ("NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_token() -> str:
    pat = re.compile(r"StatsStatus_[A-Z0-9]+_(\d{8})\.json$")
    tokens: list[str] = []
    for p in STATS_DIR.glob("StatsStatus_*_*.json"):
        m = pat.search(p.name)
        if m:
            tokens.append(m.group(1))
    if not tokens:
        return datetime.now().strftime("%Y%m%d")
    return sorted(tokens)[-1]


def _mtime_iso(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
    except Exception:
        return ""


def run(token: str | None = None) -> tuple[Path, Path]:
    tok = str(token or _latest_token())
    per_game_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for lg in LEAGUES:
        stats_marker_path = STATS_DIR / f"StatsStatus_{lg}_{tok}.json"
        sos_marker_path = SOS_DIR / f"SOSStatus_{lg}_{tok}.json"
        matchups_path = STATS_DIR / f"Matchups_{lg}_{tok}.xlsx"
        rawstats_path = STATS_DIR / f"RawStats_{lg}_{tok}.xlsx"

        stats_marker = _read_json(stats_marker_path)
        sos_marker = _read_json(sos_marker_path)
        stats_status = str(stats_marker.get("status", "MISSING")).upper()
        sos_status = str(sos_marker.get("status", "MISSING")).upper()
        games_found = int(stats_marker.get("games_found", 0) or 0)

        stats_ok = 0
        sos_ok = 0
        total_games = 0

        if matchups_path.exists() and games_found > 0:
            xls = pd.ExcelFile(matchups_path)
            for sheet in xls.sheet_names:
                df = pd.read_excel(matchups_path, sheet_name=sheet)
                cols = list(df.columns)
                away = str(cols[1]).strip() if len(cols) > 1 else ""
                home = str(cols[2]).strip() if len(cols) > 2 else ""
                total_games += 1
                sig = get_stats_sos_model_signal(lg.lower(), away, home, game_date=tok)
                metric_count = int(sig.get("stats_metric_count") or 0)
                stats_source_empty = bool(sig.get("stats_source_empty"))
                stats_mapped = bool(metric_count > 0 and not stats_source_empty)
                sos_mapped = bool(float(sig.get("sos_coverage") or 0.0) > 0.0 or sos_status == "NO_GAMES")
                if stats_mapped:
                    stats_ok += 1
                if sos_mapped:
                    sos_ok += 1

                reason_parts: list[str] = []
                if not stats_mapped:
                    reason_parts.append("STATS_MAP_FAIL")
                if not sos_mapped:
                    reason_parts.append("SOS_MAP_FAIL")

                per_game_rows.append(
                    {
                        "token": tok,
                        "league": lg,
                        "sheet": sheet,
                        "away": away,
                        "home": home,
                        "stats_status": stats_status,
                        "sos_status": sos_status,
                        "stats_marker_file": stats_marker_path.name if stats_marker_path.exists() else "",
                        "sos_marker_file": sos_marker_path.name if sos_marker_path.exists() else "",
                        "matchups_file": matchups_path.name,
                        "rawstats_file": rawstats_path.name if rawstats_path.exists() else "",
                        "stats_mapped": stats_mapped,
                        "sos_mapped": sos_mapped,
                        "stats_metric_count": metric_count,
                        "stats_source_empty": stats_source_empty,
                        "stats_score": sig.get("stats_score"),
                        "sos_score": sig.get("sos_score"),
                        "expected_total": sig.get("expected_total"),
                        "reason": "|".join(reason_parts),
                        "stats_marker_updated_at": str(stats_marker.get("updated_at", "")),
                        "sos_marker_updated_at": str(sos_marker.get("updated_at", "")),
                    }
                )
        else:
            per_game_rows.append(
                {
                    "token": tok,
                    "league": lg,
                    "sheet": "",
                    "away": "",
                    "home": "",
                    "stats_status": stats_status,
                    "sos_status": sos_status,
                    "stats_marker_file": stats_marker_path.name if stats_marker_path.exists() else "",
                    "sos_marker_file": sos_marker_path.name if sos_marker_path.exists() else "",
                    "matchups_file": matchups_path.name if matchups_path.exists() else "",
                    "rawstats_file": rawstats_path.name if rawstats_path.exists() else "",
                    "stats_mapped": False,
                    "sos_mapped": False,
                    "stats_metric_count": 0,
                    "stats_source_empty": True,
                    "stats_score": None,
                    "sos_score": None,
                    "expected_total": None,
                    "reason": "NO_GAMES_OR_NO_MATCHUP_FILE",
                    "stats_marker_updated_at": str(stats_marker.get("updated_at", "")),
                    "sos_marker_updated_at": str(sos_marker.get("updated_at", "")),
                }
            )

        summary_rows.append(
            {
                "token": tok,
                "league": lg,
                "stats_status": stats_status,
                "sos_status": sos_status,
                "games_found": games_found,
                "matchups_file_exists": matchups_path.exists(),
                "matchups_file_mtime": _mtime_iso(matchups_path),
                "stats_marker_file_exists": stats_marker_path.exists(),
                "stats_marker_mtime": _mtime_iso(stats_marker_path),
                "sos_marker_file_exists": sos_marker_path.exists(),
                "sos_marker_mtime": _mtime_iso(sos_marker_path),
                "games_audited": total_games,
                "stats_mapped_ok_games": stats_ok,
                "sos_mapped_ok_games": sos_ok,
            }
        )

    per_game_df = pd.DataFrame(per_game_rows)
    summary_df = pd.DataFrame(summary_rows)

    per_game_out = OUT_DIR / f"lineage_proof_per_game_{tok}.csv"
    summary_out = OUT_DIR / f"lineage_proof_summary_{tok}.csv"
    per_game_df.to_csv(per_game_out, index=False)
    summary_df.to_csv(summary_out, index=False)
    return summary_out, per_game_out


if __name__ == "__main__":
    s, p = run()
    print(f"SUMMARY={s}")
    print(f"PER_GAME={p}")
