import os
import re
from datetime import datetime

import pandas as pd
import pytz
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.scoresandodds.com"
SPORTS = ["nfl", "nba", "mlb", "ncaab", "ncaaf", "nhl"]
BET_TYPES = ["spread", "total", "moneyline"]

HEADLESS = os.getenv("HEADLESS", "1") != "0"
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "0"))

ET_TZ = pytz.timezone("America/New_York")


def clean_team_name(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"\s*\d{1,2}(?:-\d{1,2}){0,2}-?\s*$", "", s)
    s = re.sub(r"\s+\d+$", "", s)
    # Remove trailing handedness markers without dropping team name tokens.
    s = re.sub(r"\s*\(([RL])\)\s*$", "", s)
    s = re.sub(r"\s+([RL])\s*$", "", s)
    s = re.sub(r"[^A-Za-z0-9\.\-' ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _to_float_or_none(raw):
    if raw is None:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(raw))
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def is_today_game(game_time_str: str, assume_today_if_no_date: bool = False) -> bool:
    try:
        now_et = datetime.now(ET_TZ).date()
        s = (game_time_str or "").strip().lower()

        if "today" in s:
            return True

        m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", s)
        if m:
            mm = int(m.group(1))
            dd = int(m.group(2))
            return (mm == now_et.month) and (dd == now_et.day)

        return assume_today_if_no_date
    except Exception:
        return False


def _best_effort_click_market(page, bet_type: str) -> None:
    label = {"spread": "Spread", "total": "Total", "moneyline": "Moneyline"}[bet_type]
    selectors = [
        f"a:has-text('{label}')",
        f"button:has-text('{label}')",
        f"li:has-text('{label}')",
        f"[data-market='{bet_type}']",
        f"[data-bet-type='{bet_type}']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=1500)
                page.wait_for_timeout(250)
                return
        except Exception:
            continue


def parse_odds_table(html: str, sport: str, bet_type: str):
    soup = BeautifulSoup(html, "html.parser")

    tbody_prefix = f"odds-table-{bet_type}--"
    tbody = soup.find("tbody", id=lambda x: x and tbody_prefix in x)
    if not tbody:
        return []

    games = []
    current_game = None
    rows = tbody.find_all("tr", recursive=False)

    for row in rows:
        time_cell = row.find("td", class_="game-time")
        if time_cell:
            if current_game and current_game["teams"]:
                games.append(current_game)

            time_txt = time_cell.get_text(strip=True)
            current_game = {
                "sport": sport,
                "time": time_txt,
                "is_today": is_today_game(time_txt),
                "teams": [],
            }

        team_cell = row.find("td", class_="game-team")
        if team_cell and current_game:
            team = {}
            name_span = team_cell.find("span", class_="team-name")
            if name_span:
                team["name"] = clean_team_name(name_span.get_text(" ", strip=True))

            odds_cells = row.find_all("td", class_="game-odds")
            books = []
            for idx, cell in enumerate(odds_cells):
                book = {"index": idx}
                val = cell.find("span", class_="data-value")
                ml = cell.find("span", class_="data-moneyline")
                if val:
                    book["value"] = val.get_text(strip=True)
                if ml:
                    book["moneyline"] = ml.get_text(strip=True)
                if ("value" in book) or ("moneyline" in book):
                    books.append(book)

            team["books"] = books
            current_game["teams"].append(team)

    if current_game and current_game["teams"]:
        games.append(current_game)

    return [g for g in games if g.get("is_today", False)]


def scrape_sport(sport: str):
    sport = str(sport or "").strip().lower()
    url = f"{BASE_URL}/{sport}/odds"
    print(f"\n{sport.upper()} - Loading {url}")

    results = {bt: [] for bt in BET_TYPES}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            for bt in BET_TYPES:
                _best_effort_click_market(page, bt)
                page.wait_for_timeout(400)
                html = page.content()
                results[bt] = parse_odds_table(html, sport, bt)

        except Exception as e:
            print(f"  Error loading/parsing {sport}: {e}")

        finally:
            browser.close()

    count = max((len(results.get(bt, [])) for bt in BET_TYPES), default=0)
    print(f"  Found {count} games for today")
    return results, count


def save_excel(sport_data, sport: str, output_dir: str):
    # Blend old/new: accept dict market-map (current) or tabular inputs.
    if isinstance(sport_data, pd.DataFrame):
        df = sport_data.copy()
    elif isinstance(sport_data, list):
        df = pd.DataFrame(sport_data)
    else:
        spreads = dict(sport_data or {}).get("spread", [])
        totals = dict(sport_data or {}).get("total", [])
        mls = dict(sport_data or {}).get("moneyline", [])

        def key(game):
            if len(game.get("teams", [])) < 2:
                return None
            away = clean_team_name(game["teams"][0].get("name", ""))
            home = clean_team_name(game["teams"][1].get("name", ""))
            t = (game.get("time") or "").strip()
            return (t, away.lower(), home.lower())

        spread_map = {key(g): g for g in spreads if key(g)}
        total_map = {key(g): g for g in totals if key(g)}
        ml_map = {key(g): g for g in mls if key(g)}
        all_keys = set(spread_map.keys()) | set(total_map.keys()) | set(ml_map.keys())

        rows = []
        for k in sorted(all_keys):
            if not k:
                continue
            g_spread = spread_map.get(k)
            g_total = total_map.get(k)
            g_ml = ml_map.get(k)
            g_any = g_spread or g_total or g_ml
            if not g_any or len(g_any.get("teams", [])) < 2:
                continue
            away, home = g_any["teams"][0], g_any["teams"][1]
            t, _, _ = k

            row = {
                "Time": t,
                "Date": datetime.now(ET_TZ).strftime("%Y-%m-%d"),
                "Away_Team": away.get("name", ""),
                "Home_Team": home.get("name", ""),
                "Away_Spread": next((b["value"] for b in (g_spread["teams"][0].get("books", []) if g_spread else []) if "value" in b), ""),
                "Home_Spread": next((b["value"] for b in (g_spread["teams"][1].get("books", []) if g_spread else []) if "value" in b), ""),
            }

            if g_total and len(g_total.get("teams", [])) >= 2:
                away_tot_raw = next((b["value"] for b in g_total["teams"][0].get("books", []) if "value" in b), "")
                home_tot_raw = next((b["value"] for b in g_total["teams"][1].get("books", []) if "value" in b), "")
                tot_num = _to_float_or_none(away_tot_raw) or _to_float_or_none(home_tot_raw)
                row["Total"] = tot_num if tot_num is not None else (away_tot_raw or home_tot_raw or "")
                row["OU_Line"] = tot_num if tot_num is not None else ""
                row["ou_line"] = row["OU_Line"]
                row["market_total"] = row["OU_Line"]
                row["over_odds"] = next((b["moneyline"] for b in g_total["teams"][0].get("books", []) if "moneyline" in b), "")
                row["under_odds"] = next((b["moneyline"] for b in g_total["teams"][1].get("books", []) if "moneyline" in b), "")
            else:
                row["Total"] = ""
                row["OU_Line"] = ""
                row["ou_line"] = ""
                row["market_total"] = ""
                row["over_odds"] = ""
                row["under_odds"] = ""

            if g_ml and len(g_ml.get("teams", [])) >= 2:
                row["Away_ML"] = next((b["moneyline"] for b in g_ml["teams"][0].get("books", []) if "moneyline" in b), "")
                row["Home_ML"] = next((b["moneyline"] for b in g_ml["teams"][1].get("books", []) if "moneyline" in b), "")
            else:
                row["Away_ML"] = ""
                row["Home_ML"] = ""

            row["Away"] = row["Away_Team"]
            row["Home"] = row["Home_Team"]
            row["away_team"] = row["Away_Team"]
            row["home_team"] = row["Home_Team"]
            row["game_date"] = datetime.now(ET_TZ).strftime("%Y%m%d")
            row["league"] = str(sport or "").upper()

            rows.append(row)

        if not rows:
            return None
        df = pd.DataFrame(rows)

    ts = datetime.now(ET_TZ).strftime("%Y%m%d")
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"Odds_{str(sport).upper()}_{ts}.xlsx")
    df.to_excel(filename, index=False)
    print(f"  Saved: {filename}")
    return filename


def main():
    output_dir = "odds_data"
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("ODDS SCRAPER (Blended Compatibility)")
    print("=" * 60)

    for sport in SPORTS:
        data, count = scrape_sport(sport)
        if count > 0:
            save_excel(data, sport, output_dir)
        else:
            print(f"  No games/odds for {sport} today.")


if __name__ == "__main__":
    main()
