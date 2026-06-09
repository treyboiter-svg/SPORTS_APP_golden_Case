#!/usr/bin/env python3
"""
nhl_referees_scraper.py
Uses curl_cffi (Chrome TLS impersonation) + RSS feed to find post.
Scrapes REFEREES only. Linespersons and birthplace excluded.

Install: pip install curl_cffi beautifulsoup4 lxml
"""
from __future__ import annotations

import argparse
import io
import random
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    raise SystemExit("pip install curl_cffi")
try:
    from bs4 import BeautifulSoup
except ImportError:
    raise SystemExit("pip install beautifulsoup4 lxml")

# ---------------------------------------------------------------------------
# Module-level scrape date — set by scrape_nhl_referees() so the fallback
# heuristic inside abbr_from_fullname() can write the diagnostics file.
# ---------------------------------------------------------------------------
_SCRAPE_DATE: "date | None" = None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://scoutingtherefs.com"
RSS_URL  = (
    "https://scoutingtherefs.com"
    "/category/tonights-officials/nhl-tonights-officials/feed/"
)

IMPERSONATE_POOL = ["chrome110", "chrome107", "chrome104", "chrome101"]

LABEL_MAP = {
    "goals/gm":             "goals_per_g",
    "pp opp/gm":            "pp_opp_per_g",
    "ppg/gm":               "ppg_per_g",
    "penl/gm":              "penl_per_g",
    "pim/gm":               "pim_per_g",
    "% of penl on home":    "home_penl_pct",
    "% pp opp for home":    "home_pp_opp_pct",
    "penl diff.":           "penl_diff",
    "penl diff.*":          "penl_diff",
    "home win %":           "home_win_pct",
    "home rec.":            "home_rec",
    "ot/so games":          "ot_so_pct",
    "games '25-26":         "games_current",
    "games '24-25":         "games_prior",
    "career games (rs/po)": "career_games",
    "first nhl game":       "first_nhl_game",
}

NAME_NUM_RE = re.compile(r"#\d+")
GAME_RE     = re.compile(
    r"^(.+?)\s+(?:at|vs\.?|@)\s+(.+?)(?:\s+\d{1,2}:\d{2}\s*[AP]M.*)?$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def make_session(impersonate: str) -> cffi_requests.Session:
    s = cffi_requests.Session(impersonate=impersonate)
    s.headers.update({
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "DNT":                       "1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":             "max-age=0",
    })
    return s


def fetch(session: cffi_requests.Session, url: str,
          retries: int = 4, base_wait: float = 5.0) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=25, allow_redirects=True)
            print(f"    HTTP {resp.status_code}  {url}")
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429:
                wait = base_wait * (2 ** (attempt - 1)) + random.uniform(1, 3)
                print(f"    429 Rate limited. Waiting {wait:.0f}s...")
                time.sleep(wait)
                continue
            print(f"    Non-200 ({resp.status_code}) on attempt {attempt}")
        except Exception as e:
            _msg = str(e).lower()
            if ("ssl" in _msg and "certificate" in _msg) or "curl: (60)" in _msg:
                try:
                    resp = session.get(url, timeout=25, allow_redirects=True, verify=False)
                    print(f"    HTTP {resp.status_code}  {url} (ssl-fallback)")
                    if resp.status_code == 200:
                        return resp.text
                except Exception:
                    pass
            wait = base_wait + random.uniform(1, 3)
            print(f"    Error attempt {attempt}: {e}. Waiting {wait:.0f}s...")
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower().rstrip("*"))


def parse_stat_value(raw: str) -> str:
    if not isinstance(raw, str):
        raw = str(raw) if raw is not None else ""
    raw = raw.strip()
    if not raw or raw.lower() in ("nan", "none", "-"):
        return ""
    current = raw.split("|")[0].strip()
    return re.sub(r"\s*\(\d+\)", "", current).strip()



# Standard 3-letter abbreviation lookup keyed by LOWERCASE normalized team name.
# This replaces the broken abbr_from_fullname() heuristic which took the first
# 3 letters of the last word: "Los Angeles Kings" → "KIN" (not the standard "LAK").
# Every code it produced was non-standard and unrecognized by game_resolver.
# Full-name matches are tried first; fallback strips articles and tries again.
_NHL_NAME_TO_ABBR: dict[str, str] = {
    "anaheim ducks":           "ANA", "ducks":          "ANA",
    "boston bruins":           "BOS", "bruins":         "BOS",
    "buffalo sabres":          "BUF", "sabres":         "BUF",
    "calgary flames":          "CGY", "flames":         "CGY",
    "carolina hurricanes":     "CAR", "hurricanes":     "CAR",
    "chicago blackhawks":      "CHI", "blackhawks":     "CHI",
    "colorado avalanche":      "COL", "avalanche":      "COL",
    "columbus blue jackets":   "CBJ", "blue jackets":   "CBJ",
    "dallas stars":            "DAL", "stars":          "DAL",
    "detroit red wings":       "DET", "red wings":      "DET",
    "edmonton oilers":         "EDM", "oilers":         "EDM",
    "florida panthers":        "FLA", "panthers":       "FLA",
    "los angeles kings":       "LAK", "kings":          "LAK",
    "minnesota wild":          "MIN", "wild":           "MIN",
    "montreal canadiens":      "MTL", "canadiens":      "MTL",
    "nashville predators":     "NSH", "predators":      "NSH",
    "new jersey devils":       "NJD", "devils":         "NJD",
    "new york islanders":      "NYI", "islanders":      "NYI",
    "new york rangers":        "NYR", "rangers":        "NYR",
    "ottawa senators":         "OTT", "senators":       "OTT",
    "philadelphia flyers":     "PHI", "flyers":         "PHI",
    "pittsburgh penguins":     "PIT", "penguins":       "PIT",
    "san jose sharks":         "SJS", "sharks":         "SJS",
    "seattle kraken":          "SEA", "kraken":         "SEA",
    "st. louis blues":         "STL", "st louis blues": "STL", "blues": "STL",
    "tampa bay lightning":     "TBL", "lightning":      "TBL",
    "toronto maple leafs":     "TOR", "maple leafs":    "TOR",
    "utah mammoth":            "UTA", "mammoth":        "UTA",
    "utah hockey club":        "UTA",
    "vancouver canucks":       "VAN", "canucks":        "VAN",
    "vegas golden knights":    "VGK", "golden knights": "VGK",
    "washington capitals":     "WSH", "capitals":       "WSH",
    "winnipeg jets":           "WPG", "jets":           "WPG",
}


def _clean_team_fullname(full: str) -> str:
    """Remove playoff/time suffixes from heading team text before abbreviation lookup."""
    s = str(full or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    # Examples: "Boston Bruins Game 4 - 2:00 PM ET", "Boston Bruins - 2:00 PM ET"
    s = re.sub(r"\s+game\s+\d+\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+[?-]\s+\d{1,2}:\d{2}\s*[AP]M.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+\d{1,2}:\d{2}\s*[AP]M.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+\([^)]*\)\s*$", "", s)
    return s.strip()


def abbr_from_fullname(full: str) -> str:
    """
    Map a full NHL team name scraped from the page heading to its standard
    3-letter abbreviation (LAK, BOS, SJS, ...).

    Lookup order:
      1. Exact lowercase match against _NHL_NAME_TO_ABBR
      2. Last-word retry (e.g., "Kings")
      3. Last-two-words retry (e.g., "Golden Knights")
      4. Heuristic fallback with warning
    """
    cleaned = _clean_team_fullname(full)
    if not cleaned:
        return "UNK"
    key = cleaned.lower()
    if key in _NHL_NAME_TO_ABBR:
        return _NHL_NAME_TO_ABBR[key]

    words = key.split()
    if words and words[-1] in _NHL_NAME_TO_ABBR:
        return _NHL_NAME_TO_ABBR[words[-1]]

    if len(words) >= 2:
        two = " ".join(words[-2:])
        if two in _NHL_NAME_TO_ABBR:
            return _NHL_NAME_TO_ABBR[two]

    fallback = re.sub(r"[^A-Za-z]", "", words[-1]).upper()[:3] if words else "UNK"
    print(
        f"    [WARN] abbr_from_fullname: no standard abbreviation for {cleaned!r} - "
        f"using heuristic fallback {fallback!r}. Add to _NHL_NAME_TO_ABBR."
    )
    try:
        _date_str = _SCRAPE_DATE.strftime("%Y%m%d") if _SCRAPE_DATE else "UNKNOWN"
        _diag_path = Path(f"nhl_missing_abbrs_{_date_str}.txt")
        with _diag_path.open("a", encoding="utf-8") as _f:
            _f.write(f"{cleaned!r} -> heuristic {fallback!r}\n")
    except Exception as _e:
        print(f"    [WARN] Could not write nhl_missing_abbrs file: {_e}")
    return fallback


# ---------------------------------------------------------------------------
# Step 1: find post URL via RSS
# ---------------------------------------------------------------------------
def find_post_url_rss(session: cffi_requests.Session, target: date) -> str | None:
    print(f"  Fetching RSS: {RSS_URL}")
    xml = fetch(session, RSS_URL, retries=4, base_wait=8.0)
    if not xml:
        print("  FAILED: could not load RSS")
        return None

    soup  = BeautifulSoup(xml, "lxml-xml")
    items = soup.find_all("item")
    print(f"  RSS items found: {len(items)}")

    yyyy   = str(target.year)
    mm     = f"{target.month:02d}"
    m_     = target.month
    d_     = target.day
    yy     = yyyy[2:]
    url_ym = f"/{yyyy}/{mm}/"
    slugs  = [f"{m_}-{d_}-{yy}", f"{m_:02d}-{d_:02d}-{yy}"]

    best_url   = None
    best_score = -1

    for item in items:
        link_tag  = item.find("link")
        title_tag = item.find("title")
        link  = link_tag.get_text(strip=True)  if link_tag  else ""
        title = title_tag.get_text(strip=True) if title_tag else ""
        if url_ym not in link:
            continue
        score = 1
        for s in slugs:
            if s in link.lower() or s in title.lower():
                score += 10
                break
        print(f"    RSS item (score={score}): {link} | {title[:60]}")
        if score > best_score:
            best_score = score
            best_url   = link

    # Require an explicit target-date hit. Otherwise we may ingest yesterday's
    # officials, which creates false unresolved game_id warnings for today's slate.
    if best_url and best_score > 1:
        print(f"  Selected: {best_url}")
    else:
        best_url = None
        print(f"  No matching RSS item for {target.isoformat()}")
        for item in items[:5]:
            lt = item.find("link")
            tt = item.find("title")
            print(f"    {lt.get_text(strip=True) if lt else '?'} | {tt.get_text(strip=True) if tt else '?'}")
    return best_url


def find_post_url_homepage(session: cffi_requests.Session, target: date) -> str | None:
    """
    Fallback when RSS is blocked/rate-limited.
    Scans homepage links for NHL officials posts and prefers a target-date match.
    """
    print("  RSS fallback: scanning homepage links...")
    html = fetch(session, BASE_URL, retries=3, base_wait=4.0)
    if not html:
        print("  FAILED: could not load homepage for fallback")
        return None

    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("a[href]"):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        if "todays-nhl-referees-and-linespersons" not in href:
            continue
        links.append(href)

    if not links:
        print("  No NHL officials links found on homepage fallback.")
        return None

    yyyy = str(target.year)
    mm = f"{target.month:02d}"
    yy = yyyy[2:]
    slug_a = f"{target.month}-{target.day}-{yy}"
    slug_b = f"{target.month:02d}-{target.day:02d}-{yy}"
    best = None
    best_score = -1

    for href in links:
        score = 1
        _h = href.lower()
        if f"/{yyyy}/{mm}/" in _h:
            score += 1
        if slug_a in _h or slug_b in _h:
            score += 8
        if score > best_score:
            best = href
            best_score = score

    if best:
        print(f"  Homepage fallback selected: {best}")
    return best


# ---------------------------------------------------------------------------
# Step 2: parse the post page
# ---------------------------------------------------------------------------
def parse_post(session: cffi_requests.Session, post_url: str) -> pd.DataFrame:
    print(f"  Loading post...")
    html = fetch(session, post_url, retries=4, base_wait=8.0)
    if not html:
        print("  FAILED: could not load post page")
        return pd.DataFrame()

    soup = BeautifulSoup(html, "lxml")

    article = (
        soup.find("div", class_="entry-content")
        or soup.find("article")
        or soup.find("div", class_="post-content")
        or soup.body
    )
    if not article:
        print("  Could not find article element")
        return pd.DataFrame()

    records       = []
    current_game  = None
    current_away  = ""
    current_home  = ""
    current_role  = "Referee"
    ref_names: list[str]       = []
    ref_stats: dict[str, dict] = {}

    def flush():
        if not current_game or not ref_names or current_role == "SKIP":
            return
        for rn in ref_names:
            row = {
                "Game":    current_game,
                "Away":    current_away,
                "Home":    current_home,
                "Role":    current_role,
                "Name":    rn,
                "Referee": rn,
            }
            row.update(ref_stats.get(rn, {}))
            records.append(row)

    # Walk ALL descendants in document order.
    # Skip elements that are children of a table (handled separately).
    # For every non-table element, check its TEXT case-insensitively for
    # section markers — this catches CSS text-transform:uppercase headings.
    for el in article.find_all(True):
        if el.name is None:
            continue

        # Don't process elements nested inside tables here — tables handle their own rows
        if el.find_parent("table"):
            continue

        # ---- TABLES ----
        if el.name == "table":
            if current_role == "SKIP":
                continue

            table_rows = []
            for tr in el.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
                if any(c.strip() for c in cells):
                    table_rows.append(cells)

            for row in table_rows:
                if not row:
                    continue
                name_cells = [
                    re.sub(r"\s*#\d+", "", c).strip()
                    for c in row if NAME_NUM_RE.search(c)
                ]
                if name_cells:
                    flush()
                    ref_names = [n for n in name_cells if n]
                    ref_stats = {n: {} for n in ref_names}
                    print(f"      Refs: {ref_names}")
                    continue
                label  = norm_label(row[0])
                mapped = LABEL_MAP.get(label)
                if not mapped:
                    continue
                for i, rn in enumerate(ref_names):
                    col = i + 1
                    if col < len(row):
                        ref_stats.setdefault(rn, {})[mapped] = parse_stat_value(row[col])
            continue

        # ---- TEXT ELEMENTS — check for section markers ----
        # Only process elements that could be headings/labels (not big containers)
        if el.name not in ("h1","h2","h3","h4","p","div","span","strong","b","em","td","th","li"):
            continue

        txt = el.get_text(" ", strip=True)
        if not txt:
            continue

        # Matchup lines can be embedded inside larger blocks; inspect newline-split
        # text first so we still detect "<Away> at <Home>" lines.
        _line_candidates = [x.strip() for x in el.get_text("\n", strip=True).split("\n") if x and x.strip()]
        _gm_line = None
        for _ln in _line_candidates[:16]:
            if GAME_RE.match(_ln):
                _gm_line = _ln
                break
        if _gm_line is None and len(txt) <= 120 and GAME_RE.match(txt):
            _gm_line = txt

        if _gm_line:
            gm = GAME_RE.match(_gm_line)
            if gm:
                flush()
                ref_names    = []
                ref_stats    = {}
                current_role = "Referee"
                current_away = abbr_from_fullname(gm.group(1))
                current_home = abbr_from_fullname(gm.group(2))
                current_game = f"{current_away}_vs_{current_home}"
                print(f"    Game: {current_game}  ({_gm_line[:70]})")
                continue

        if len(txt) > 80:
            continue

        TXT = txt.upper()

        # LINESPERSONS check — case-insensitive, catches CSS-uppercased text
        if "LINESPERSON" in TXT:
            flush()
            current_role = "SKIP"
            ref_names    = []
            ref_stats    = {}
            print(f"    [SKIP] Linespersons section: '{txt}'")
            continue

        # REFEREES section reset
        if TXT.strip() in ("REFEREES", "OFFICIALS", "REFEREE"):
            flush()
            current_role = "Referee"
            ref_names    = []
            ref_stats    = {}
            continue

    flush()

    if not records:
        print("  WARNING: 0 records. Article sample:")
        print(article.get_text("\n", strip=True)[:2000])
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # -----------------------------------------------------------------------
    # HARD FALLBACK: NHL has exactly 2 referees per game.
    # Referees always appear before linespersons on the page.
    # If heading detection still missed a LINESPERSONS section, this catches it.
    # -----------------------------------------------------------------------
    if "Game" in df.columns:
        before = len(df)
        df = df.groupby("Game", sort=False).head(2).reset_index(drop=True)
        dropped = before - len(df)
        if dropped:
            print(f"  [FALLBACK] Dropped {dropped} extra records (linespersons) via head(2) per game")

    print(f"  Parsed {len(df)} referee records")
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def scrape_nhl_referees(target: date, outdir: Path) -> Path:
    global _SCRAPE_DATE
    _SCRAPE_DATE = target
    ymd      = target.strftime("%Y%m%d")
    out_path = outdir / f"nhl_referees_{ymd}.xlsx"
    outdir.mkdir(parents=True, exist_ok=True)

    impersonate = random.choice(IMPERSONATE_POOL)
    print(f"NHL scrape for {target.isoformat()} | impersonate={impersonate}")

    session = make_session(impersonate)

    print("  Warming up...")
    fetch(session, BASE_URL, retries=2, base_wait=3.0)
    time.sleep(random.uniform(3.0, 5.0))

    post_url = find_post_url_rss(session, target)
    if not post_url:
        post_url = find_post_url_homepage(session, target)

    df = pd.DataFrame()
    if post_url:
        time.sleep(random.uniform(2.0, 4.0))
        df = parse_post(session, post_url)
    else:
        print(f"  No post found for {target.isoformat()}.")

    # If scrape produced no rows, do not clobber an existing non-empty file.
    if df.empty and out_path.exists():
        try:
            _xl = pd.ExcelFile(out_path)
            _existing_rows = 0
            for _s in _xl.sheet_names:
                _existing_rows += int(len(_xl.parse(_s)))
            if _existing_rows > 0:
                print(
                    f"  [SAFEGUARD] Keeping existing {out_path.name} with {_existing_rows} row(s); "
                    "skipping empty overwrite."
                )
                return out_path
        except Exception:
            pass

    # Write ALL sheet only
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        if df.empty:
            pd.DataFrame().to_excel(writer, sheet_name="ALL", index=False)
        else:
            df.to_excel(writer, sheet_name="ALL", index=False)

    print(f"WROTE {out_path}  ({len(df)} rows)")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date",   help="YYYY-MM-DD")
    ap.add_argument("--outdir", default="ref_output")
    args = ap.parse_args()

    run_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else datetime.now().date()
    )
    scrape_nhl_referees(run_date, Path(args.outdir))
