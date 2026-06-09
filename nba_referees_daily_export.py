#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
import certifi
from bs4 import BeautifulSoup

NBA_URL = "https://official.nba.com/referee-assignments/"
ODDS_SHARK_URL = "https://www.oddsshark.com/nba/referee-handicapping-statistics"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def fetch_soup(url: str) -> BeautifulSoup:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, verify=certifi.where())
    except requests.exceptions.SSLError:
        # Last-resort compatibility path for broken local trust stores.
        r = requests.get(url, headers=HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    return BeautifulSoup(r.content, "html.parser")


def _pick_assignments_table(nba_soup: BeautifulSoup):
    """
    official.nba.com currently renders multiple tables; the first is often header-only.
    Select the first table that contains assignment headers and at least one data row.
    """
    for table in nba_soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True).lower() for c in header_cells]
        if not headers:
            continue
        if "game" in headers and any(h in headers for h in ("crew chief", "referee", "umpire")):
            return table
    return None


def extract_refs_nba(nba_soup: BeautifulSoup) -> List[Dict[str, Any]]:
    games_data: List[Dict[str, Any]] = []
    table = _pick_assignments_table(nba_soup)
    if table is None:
        return games_data

    rows = table.find_all("tr")
    header_cells = rows[0].find_all(["th", "td"])
    headers = [c.get_text(strip=True) for c in header_cells]
    idx = {h.strip().lower(): i for i, h in enumerate(headers)}

    game_i = idx.get("game")
    if game_i is None:
        return games_data

    role_map = [
        ("crew chief", "Crew Chief"),
        ("referee", "Referee"),
        ("umpire", "Umpire"),
        ("alternate", "Alternate"),
    ]
    for row in rows[1:]:
        cols = row.find_all(["th", "td"])
        if not cols:
            continue
        vals = [c.get_text(strip=True) for c in cols]
        if game_i >= len(vals):
            continue
        game = vals[game_i]
        if not game:
            continue
        for key, role in role_map:
            i = idx.get(key)
            if i is None or i >= len(vals):
                continue
            name = re.sub(r"\s*\(\#\d+\)", "", vals[i]).strip()
            if not name:
                continue
            games_data.append({"Game": game, "Role": role, "Name": name})
    return games_data


def extract_ref_stats(odds_soup: BeautifulSoup) -> Dict[str, Dict[str, Any]]:
    table = odds_soup.find("table")
    if not table:
        return {}

    header_row = table.find("thead") or table.find("tr")
    headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])] if header_row else []

    body = table.find("tbody") or table
    rows = body.find_all("tr")[1:]

    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        cols = row.find_all(["td", "th"])
        if len(cols) < 2:
            continue

        name = cols[0].get_text(strip=True)
        if not name:
            continue

        vals = [c.get_text(strip=True) for c in cols]
        if headers and len(headers) == len(vals):
            out[name] = dict(zip(headers, vals))
        else:
            out[name] = {f"col_{i}": v for i, v in enumerate(vals)}

    return out


def build_df(run_date: date, games_data: List[Dict[str, Any]], ref_stats: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    run_date_str = run_date.strftime("%Y-%m-%d")
    rows: List[Dict[str, Any]] = []

    for g in games_data:
        name = g.get("Name", "")
        stats = ref_stats.get(name, {})
        row = {"Date": run_date_str, "Game": g.get("Game", ""), "Role": g.get("Role", ""), "Name": name}
        for k, v in stats.items():
            if str(k).strip().lower() == "name":
                continue
            row[k] = v
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today local)")
    ap.add_argument("--outdir", default="ref_output")
    ap.add_argument("--require-rows", action="store_true", help="Fail if 0 rows (recommended for automation).")
    args = ap.parse_args()

    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now().date()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"nba_referee_report_{run_date.strftime('%Y%m%d')}.xlsx"

    nba_soup = fetch_soup(NBA_URL)
    odds_soup = fetch_soup(ODDS_SHARK_URL)

    games_data = extract_refs_nba(nba_soup)
    ref_stats = extract_ref_stats(odds_soup)
    df = build_df(run_date, games_data, ref_stats)

    if args.require_rows and df.empty:
        raise RuntimeError("NBA referee export produced 0 rows (assignments table missing/blocked/changed).")

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="NBA Referee Report")

    print(f"WROTE {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
