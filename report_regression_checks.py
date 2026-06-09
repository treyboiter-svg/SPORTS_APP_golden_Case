#!/usr/bin/env python3
import json
import math
import os
import sqlite3
from pathlib import Path

import cre_integration
from odds_data import boydsbets_injury_scraper as injury


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_empty_team_matching():
    assert_true(cre_integration._fuzzy_team_match("", "Boston Red Sox") is False, "CRE empty-name match bug regressed")
    if hasattr(injury, "get_injuries"):
        rows = injury.get_injuries("MLB", "", auto_fetch=False)
        assert_true(len(rows) == 0, "Injury blank-team filter regressed")
    else:
        rep = injury.get_injury_report(sport="MLB", team="", game_date=None)
        assert_true(isinstance(rep, dict), "Injury report API returned non-dict")
        assert_true(len(rep.get("injuries") or []) == 0, "Injury blank-team filter regressed")


def test_strict_venue_json():
    p = Path("US_SPORTS_VENUES_MASTER_CORRECTED_V2.json")
    txt = p.read_text(encoding="utf-8")
    assert_true("NaN" not in txt, "Venue JSON contains NaN token")
    rows = json.loads(txt)
    need = {"MLB", "NFL", "NCAAF", "NCAAFB"}
    for r in rows:
        if str(r.get("league", "")).upper() in need:
            od = r.get("orientation_deg")
            assert_true(isinstance(od, (int, float)) and math.isfinite(od), "Missing orientation in scoped league")


def test_runtime_context_db():
    local = os.environ.get("LOCALAPPDATA")
    assert_true(bool(local), "LOCALAPPDATA missing")
    gc = Path(local) / "SportsPhysicsEngine" / "game_context.db"
    assert_true(gc.exists(), "runtime game_context.db missing")
    con = sqlite3.connect(gc)
    cur = con.cursor()
    cur.execute("select name from sqlite_master where type='table' and name='game_context'")
    assert_true(cur.fetchone() is not None, "game_context table missing")
    n = cur.execute("select count(*) from game_context where ou_result in ('OVER','UNDER')").fetchone()[0]
    con.close()
    assert_true(n > 0, "No calibrated OVER/UNDER rows in runtime game_context")


def main():
    test_empty_team_matching()
    test_strict_venue_json()
    test_runtime_context_db()
    print("PASS report_regression_checks")


if __name__ == "__main__":
    main()
