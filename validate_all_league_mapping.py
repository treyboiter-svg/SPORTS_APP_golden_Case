from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import pandas as pd

import stats_sos_integration as s


BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "diagnostics"
LEAGUES = ("NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL")


def _latest_matchups_file(league: str) -> Path | None:
    cands = sorted((BASE / "stats_output").glob(f"Matchups_{league}_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _token_from_name(path: Path) -> str:
    m = re.search(r"_(\d{8})\.xlsx$", path.name)
    return m.group(1) if m else ""


def _safe_cov_num(cov_raw: str) -> float:
    cov_raw = str(cov_raw or "").strip()
    if "/" not in cov_raw:
        return 0.0
    try:
        a, b = cov_raw.split("/", 1)
        aa = max(0.0, float(a))
        bb = max(1.0, float(b))
        return aa / bb
    except Exception:
        return 0.0


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_token = datetime.now().strftime("%Y%m%d")
    rows: list[dict] = []

    for lg in LEAGUES:
        f = _latest_matchups_file(lg)
        if not f:
            rows.append(
                {
                    "league": lg,
                    "status": "FAIL",
                    "reason": "NO_MATCHUPS_FILE",
                }
            )
            continue

        game_token = _token_from_name(f)
        matchup_rows = s._extract_matchup_rows(lg, game_date=game_token)  # uses exact-date file
        if not matchup_rows:
            rows.append(
                {
                    "league": lg,
                    "status": "FAIL",
                    "file": f.name,
                    "game_token": game_token,
                    "reason": "MATCHUPS_ROWS_EMPTY",
                }
            )
            continue

        for rec in matchup_rows:
            away = str(rec.get("away_team", "") or "").strip()
            home = str(rec.get("home_team", "") or "").strip()
            sheet = str(rec.get("sheet", "") or "").strip()
            cov_raw = str(rec.get("STATS_COVERAGE", "") or "").strip()
            no_stats = str(rec.get("NO STATS", "") or "").strip().upper()
            pairs = s._all_numeric_stat_diffs(rec)
            stats_metric_count = len(pairs)
            cov_num = _safe_cov_num(cov_raw)

            sos_block = s._extract_sos_game_block(lg, away, home, game_date=game_token)
            sos_metrics = len(dict((sos_block or {}).get("metrics") or {}))

            stats_ok = (stats_metric_count > 0) and (no_stats != "FAILED")
            status = "PASS" if stats_ok else "FAIL"
            reason = ""
            if not stats_ok:
                if no_stats == "FAILED":
                    reason = "NO_STATS_FAILED"
                elif stats_metric_count <= 0:
                    reason = "NO_NUMERIC_STATS_PARSED"
                else:
                    reason = "UNKNOWN_STATS_FAIL"

            rows.append(
                {
                    "league": lg,
                    "status": status,
                    "reason": reason,
                    "file": f.name,
                    "game_token": game_token,
                    "sheet": sheet,
                    "away": away,
                    "home": home,
                    "stats_coverage_cell": cov_raw,
                    "stats_coverage_num": cov_num,
                    "no_stats_flag": no_stats,
                    "stats_metric_count": stats_metric_count,
                    "sos_metric_count": sos_metrics,
                }
            )

    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"all_league_full_mapping_audit_{run_token}.csv"
    out_latest = OUT_DIR / "all_league_full_mapping_audit_latest.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    df.to_csv(out_latest, index=False, encoding="utf-8-sig")

    summary = (
        df.groupby(["league", "status"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values(["league", "status"])
    )
    out_summary = OUT_DIR / f"all_league_full_mapping_summary_{run_token}.csv"
    out_summary_latest = OUT_DIR / "all_league_full_mapping_summary_latest.csv"
    summary.to_csv(out_summary, index=False, encoding="utf-8-sig")
    summary.to_csv(out_summary_latest, index=False, encoding="utf-8-sig")

    print(f"AUDIT={out_csv}")
    print(f"SUMMARY={out_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

