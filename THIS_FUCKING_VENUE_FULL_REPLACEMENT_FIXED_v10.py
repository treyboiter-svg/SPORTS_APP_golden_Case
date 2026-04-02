# VERSION: v9 — 2026-04-01
# Run: python THIS_FUCKING_VENUE_FULL_REPLACEMENT_FIXED_v9.py

import re
import time
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim

# =========================
# CONSTANTS
# =========================

HEADERS = {"User-Agent": "Mozilla/5.0"}
CACHE_FILE = "geo_cache.json"
ELEVATION_API = "https://api.open-elevation.com/api/v1/lookup"

geolocator = Nominatim(user_agent="sports_pipeline_full_final")

WIKI_FBS_STADIUMS = "https://en.wikipedia.org/wiki/List_of_NCAA_Division_I_FBS_football_stadiums"
WIKI_NCAA_BBALL_ARENAS = "https://en.wikipedia.org/wiki/List_of_NCAA_Division_I_basketball_arenas"

MLB_ORIENT_AL = "https://www.baseball-almanac.com/stadium/ballpark_NSEW_AL.shtml"
MLB_ORIENT_NL = "https://www.baseball-almanac.com/stadium/ballpark_NSEW_NL.shtml"


# =========================
# HARD GEO OVERRIDES
# =========================
# Key format: "league|team|venue"
#
# IMPORTANT — ALL elevation values below are stored in METERS.
# A single conversion loop at the bottom of this block converts them to feet
# in-place exactly once. Do NOT apply any further m→ft conversion anywhere else
# in the code (enrich_geo generic-override path previously did this, which was
# the root-cause double-conversion bug producing ~10.76x inflated elevations
# for every NCAA FBS, NCAA D1 MBB, NHL, and MLB override).

GEO_OVERRIDES = {
    # ---------- NFL ----------
    "NFL|Arizona Cardinals|State Farm Stadium": {
        "lat": 33.5277957, "lon": -112.2626719, "elevation": 323.0
    },
    "NFL|Atlanta Falcons|Mercedes-Benz Stadium": {
        "lat": 33.7554123, "lon": -84.4008493, "elevation": 313.0
    },
    "NFL|Baltimore Ravens|M&T Bank Stadium": {
        "lat": 39.2779734, "lon": -76.6226651, "elevation": 21.0
    },
    "NFL|Buffalo Bills|Highmark Stadium": {
        "lat": 42.7737334, "lon": -78.7868798, "elevation": 233.0
    },
    "NFL|Carolina Panthers|Bank of America Stadium": {
        "lat": 35.225774, "lon": -80.8528276, "elevation": 228.0
    },
    "NFL|Chicago Bears|Soldier Field": {
        "lat": 41.8623356, "lon": -87.6176477, "elevation": 190.0
    },
    "NFL|Cincinnati Bengals|Paycor Stadium": {
        "lat": 39.0954645, "lon": -84.5160488, "elevation": 154.0
    },
    "NFL|Cleveland Browns|Huntington Bank Field": {
        "lat": 41.5060559, "lon": -81.6997118, "elevation": 195.0
    },
    "NFL|Dallas Cowboys|AT&T Stadium": {
        "lat": 32.7478503, "lon": -97.0928337, "elevation": 177.0
    },
    "NFL|Denver Broncos|Empower Field at Mile High": {
        "lat": 39.743952, "lon": -105.0192228, "elevation": 1596.0
    },
    "NFL|Detroit Lions|Ford Field": {
        "lat": 42.3399567, "lon": -83.0456166, "elevation": 186.0
    },
    "NFL|Green Bay Packers|Lambeau Field": {
        "lat": 44.5013, "lon": -88.0622, "elevation": 207.0
    },
    "NFL|Houston Texans|NRG Stadium": {
        "lat": 29.6848581, "lon": -95.4108015, "elevation": 15.0
    },
    "NFL|Indianapolis Colts|Lucas Oil Stadium": {
        "lat": 39.7590621, "lon": -86.1638376, "elevation": 216.0
    },
    "NFL|Jacksonville Jaguars|EverBank Stadium": {
        "lat": 30.3239811, "lon": -81.6373046, "elevation": 6.0
    },
    "NFL|Kansas City Chiefs|Arrowhead Stadium": {
        "lat": 39.0489, "lon": -94.4839, "elevation": 273.0
    },
    "NFL|Las Vegas Raiders|Allegiant Stadium": {
        "lat": 36.102678, "lon": -115.1782239, "elevation": 610.0   # corrected: LV ~2001ft/610m (was 653)
    },
    "NFL|Los Angeles Chargers|SoFi Stadium": {
        "lat": 33.9534074, "lon": -118.3390098, "elevation": 45.0
    },
    "NFL|Los Angeles Rams|SoFi Stadium": {
        "lat": 33.9534074, "lon": -118.3390098, "elevation": 45.0
    },
    "NFL|Miami Dolphins|Hard Rock Stadium": {
        "lat": 25.9579032, "lon": -80.2388497, "elevation": 13.0
    },
    "NFL|Minnesota Vikings|U.S. Bank Stadium": {
        "lat": 44.9751097, "lon": -93.2593387, "elevation": 257.0
    },
    "NFL|New England Patriots|Gillette Stadium": {
        "lat": 42.0908879, "lon": -71.2641731, "elevation": 83.0
    },
    "NFL|New Orleans Saints|Caesars Superdome": {
        "lat": 29.9510489, "lon": -90.0823076, "elevation": 30.0
    },
    "NFL|New York Giants|MetLife Stadium": {
        "lat": 40.8135071, "lon": -74.0743442, "elevation": 9.0
    },
    "NFL|New York Jets|MetLife Stadium": {
        "lat": 40.8135071, "lon": -74.0743442, "elevation": 9.0
    },
    "NFL|Philadelphia Eagles|Lincoln Financial Field": {
        "lat": 39.9009099, "lon": -75.1674892, "elevation": 13.0
    },
    "NFL|Pittsburgh Steelers|Acrisure Stadium": {
        "lat": 40.4467166, "lon": -80.0157199, "elevation": 219.0
    },
    "NFL|San Francisco 49ers|Levi's Stadium": {
        "lat": 37.4029867, "lon": -121.9696489, "elevation": 1.0
    },
    "NFL|Seattle Seahawks|Lumen Field": {
        "lat": 47.5953459, "lon": -122.3316443, "elevation": 14.0
    },
    "NFL|Tampa Bay Buccaneers|Raymond James Stadium": {
        "lat": 27.9759793, "lon": -82.5033545, "elevation": 22.0
    },
    "NFL|Tennessee Titans|Nissan Stadium": {
        "lat": 36.1665236, "lon": -86.7713148, "elevation": 144.0
    },
    "NFL|Washington Commanders|Northwest Stadium": {
        "lat": 38.9076875, "lon": -76.8644869, "elevation": 76.0
    },

    # ---------- NBA ----------
    "NBA|Atlanta Hawks|State Farm Arena": {
        "lat": 33.7573698, "lon": -84.3963848, "elevation": 331.0
    },
    "NBA|Boston Celtics|TD Garden": {
        "lat": 42.3662986, "lon": -71.0621622, "elevation": 9.0
    },
    "NBA|Brooklyn Nets|Barclays Center": {
        "lat": 40.6825106, "lon": -73.9752519, "elevation": 11.0
    },
    "NBA|Charlotte Hornets|Spectrum Center": {
        "lat": 35.225098, "lon": -80.8391541, "elevation": 223.0
    },
    "NBA|Chicago Bulls|United Center": {
        "lat": 41.8806831, "lon": -87.6741851, "elevation": 196.0
    },
    "NBA|Cleveland Cavaliers|Rocket Arena": {   # corrected name
        "lat": 41.4966862, "lon": -81.6885754, "elevation": 208.0
    },
    "NBA|Dallas Mavericks|American Airlines Center": {
        "lat": 32.7904894, "lon": -96.810283, "elevation": 134.0
    },
    "NBA|Denver Nuggets|Ball Arena": {
        "lat": 39.7486838, "lon": -105.007544, "elevation": 1603.0
    },
    "NBA|Detroit Pistons|Little Caesars Arena": {
        "lat": 42.3409774, "lon": -83.0549545, "elevation": 184.0
    },
    "NBA|Golden State Warriors|Chase Center": {
        "lat": 37.7679001, "lon": -122.3874223, "elevation": 0.0    # sea level / near-zero
    },
    "NBA|Houston Rockets|Toyota Center": {
        "lat": 29.7507473, "lon": -95.3622315, "elevation": 23.0
    },
    "NBA|Indiana Pacers|Gainbridge Fieldhouse": {
        "lat": 39.7639331, "lon": -86.1555024, "elevation": 224.0
    },
    "NBA|Los Angeles Clippers|Intuit Dome": {
        "lat": 33.9442586, "lon": -118.3421719, "elevation": 29.0
    },
    "NBA|Los Angeles Lakers|Crypto.com Arena": {
        "lat": 34.0429979, "lon": -118.2671352, "elevation": 88.0
    },
    "NBA|Memphis Grizzlies|FedExForum": {
        "lat": 35.1382401, "lon": -90.0506946, "elevation": 75.0
    },
    "NBA|Miami Heat|Kaseya Center": {
        "lat": 25.7813596, "lon": -80.1879435, "elevation": 12.0
    },
    "NBA|Milwaukee Bucks|Fiserv Forum": {
        "lat": 43.0450096, "lon": -87.9174871, "elevation": 183.0
    },
    "NBA|Minnesota Timberwolves|Target Center": {
        "lat": 44.9795917, "lon": -93.2759828, "elevation": 272.0
    },
    "NBA|New Orleans Pelicans|Smoothie King Center": {
        "lat": 29.9490393, "lon": -90.082069, "elevation": 6.0
    },
    "NBA|New York Knicks|Madison Square Garden": {
        "lat": 40.7505129, "lon": -73.9935159, "elevation": 22.0
    },
    "NBA|Oklahoma City Thunder|Paycom Center": {
        "lat": 35.4633961, "lon": -97.5150815, "elevation": 366.0
    },
    "NBA|Orlando Magic|Kia Center": {
        "lat": 28.5392867, "lon": -81.3838892, "elevation": 33.0
    },
    "NBA|Philadelphia 76ers|Xfinity Mobile Arena": {   # corrected name
        "lat": 39.9011004, "lon": -75.1720165, "elevation": 19.0
    },
    "NBA|Phoenix Suns|Mortgage Matchup Center": {           # corrected name
        "lat": 33.4460392, "lon": -112.0711013, "elevation": 334.0
    },
    "NBA|Portland Trail Blazers|Moda Center": {
        "lat": 45.5315787, "lon": -122.6668337, "elevation": 33.0
    },
    "NBA|Sacramento Kings|Golden 1 Center": {
        "lat": 38.5801405, "lon": -121.4995008, "elevation": 17.0
    },
    "NBA|San Antonio Spurs|Frost Bank Center": {
        "lat": 29.4269205, "lon": -98.4375058, "elevation": 197.0
    },
    "NBA|Toronto Raptors|Scotiabank Arena": {
        "lat": 43.6434338, "lon": -79.3790777, "elevation": 81.0
    },
    "NBA|Utah Jazz|Delta Center": {
        "lat": 40.7683274, "lon": -111.9010551, "elevation": 1318.0
    },
    "NBA|Washington Wizards|Capital One Arena": {
        "lat": 38.8981883, "lon": -77.0209378, "elevation": 22.0
    },

    # ---------- NHL ----------
    "NHL|Tampa Bay Lightning|Amalie Arena": {
        "lat": 27.9428, "lon": -82.4519, "elevation": 2.0
    },

    # ---------- MLB ----------
    "MLB|Chicago White Sox|Guaranteed Rate Field": {
        "lat": 41.83, "lon": -87.6339, "elevation": 182.0
    },
}

# ---------- NCAA FBS overrides ----------
GEO_OVERRIDES.update({
    "NCAA FBS|UCF|Acrisure Bounce House": {
        "lat": 28.6073409, "lon": -81.1972969, "elevation": 26.0
    },
    "NCAA FBS|UNLV|Allegiant Stadium": {
        "lat": 36.102678, "lon": -115.1782239, "elevation": 610.0   # corrected: LV ~610m
    },
    "NCAA FBS|Boston College|Alumni Stadium": {
        "lat": 42.3352147, "lon": -71.1665884, "elevation": 61.0
    },
    "NCAA FBS|Liberty|Arthur L. Williams Stadium": {
        "lat": 37.354423, "lon": -79.191066, "elevation": 268.0
    },
    "NCAA FBS|Kansas State|Bill Snyder Family Football Stadium": {
        "lat": 39.1992982, "lon": -96.5928842, "elevation": 337.0
    },
    "NCAA FBS|Georgia Tech|Bobby Dodd Stadium at Hyundai Field": {
        "lat": 33.7723973, "lon": -84.392792, "elevation": 293.0
    },
    "NCAA FBS|Virginia|Carl Smith Center, Home of David A. Harrison III Field at Scott Stadium": {
        "lat": 38.0330105, "lon": -78.5137153, "elevation": 192.0
    },
    "NCAA FBS|Southern Miss|Carlisle-Faulkner Field at M.M. Roberts Stadium": {
        "lat": 31.3299189, "lon": -89.3355119, "elevation": 54.0
    },
    "NCAA FBS|Arizona|Casino Del Sol Stadium": {
        "lat": 32.2279, "lon": -110.9488, "elevation": 730.0
    },
    "NCAA FBS|Mississippi State|Davis Wade Stadium at Scott Field": {
        "lat": 33.4552849, "lon": -88.7931263, "elevation": 107.0
    },
    "NCAA FBS|Arkansas|Donald W. Reynolds Razorback Stadium, Frank Broyles Field": {
        "lat": 36.070833, "lon": -94.178056, "elevation": 415.0
    },
    "NCAA FBS|Sam Houston|Elliott T. Bowers Stadium": {
        "lat": 30.7139779, "lon": -95.5503797, "elevation": 107.0
    },
    "NCAA FBS|Air Force|Falcon Stadium": {
        "lat": 38.9989324, "lon": -104.8438457, "elevation": 2014.0
    },
    "NCAA FBS|Clemson|Frank Howard Field at Clemson Memorial Stadium": {
        "lat": 34.6781027, "lon": -82.8439835, "elevation": 228.0
    },
    "NCAA FBS|Arizona State|Frank Kush Field, Home of the ASU Sun Devils/ Mountain America Stadium": {
        "lat": 33.4261935, "lon": -111.9326858, "elevation": 364.0
    },
    "NCAA FBS|Western Kentucky|Houchens Industries–L. T. Smith Stadium at Jimmy Feix Field": {
        "lat": 37.0030249, "lon": -86.4566264, "elevation": 187.0
    },
    "NCAA FBS|Florida Atlantic|Howard Schnellenberger Field at Flagler Credit Union Stadium": {
        "lat": 26.3724353, "lon": -80.1049632, "elevation": 7.0
    },
    "NCAA FBS|Akron|InfoCision Stadium–Summa Field": {
        "lat": 41.0729865, "lon": -81.5082532, "elevation": 312.0
    },
    "NCAA FBS|Houston|John O'Quinn Field at Space City Financial Stadium": {
        "lat": 29.722527, "lon": -95.349349, "elevation": 16.0
    },
    "NCAA FBS|Old Dominion|Kornblau Field at S.B. Ballard Stadium": {
        "lat": 36.8866527, "lon": -76.3058854, "elevation": 9.0
    },
    "NCAA FBS|Nebraska|Memorial Stadium, Tom Osborne Field": {
        "lat": 40.82076, "lon": -96.7059796, "elevation": 363.0
    },
    "NCAA FBS|UConn|Pratt & Whitney Stadium at Rentschler Field": {
        "lat": 41.7440226, "lon": -72.6121701, "elevation": 42.0
    },
    "NCAA FBS|Tulsa|Skelly Field at H. A. Chapman Stadium": {
        "lat": 36.1478578, "lon": -95.94555, "elevation": 227.0
    },
    "NCAA FBS|Buffalo|UB Stadium": {
        "lat": 43.0013418, "lon": -78.7811361, "elevation": 196.0
    },
    "NCAA FBS|Mississippi|Vaught–Hemingway Stadium at Hollingsworth Field": {
        "lat": 34.3626675, "lon": -89.5389714, "elevation": 94.0
    },
    "NCAA FBS|Troy|Veterans Memorial Stadium at Larry Blakeney Field": {
        "lat": 31.8014829, "lon": -85.9574207, "elevation": 132.0
    },
    "NCAA FBS|East Carolina|Bagwell Field at Dowdy–Ficklen Stadium": {
        "lat": 35.6015, "lon": -77.3663, "elevation": 13.0
    },
    "NCAA FBS|Tulane|Benson Field at Yulman Stadium": {
        "lat": 29.944, "lon": -90.1142, "elevation": 8.0
    },
    "NCAA FBS|Army|Blaik Field at Michie Stadium": {
        "lat": 41.396, "lon": -73.9629, "elevation": 112.0
    },
    "NCAA FBS|Florida State|Bobby Bowden Field at Doak S. Campbell Stadium": {
        "lat": 30.4389, "lon": -84.3048, "elevation": 22.0
    },
    "NCAA FBS|Northern Illinois|Brigham Field at Huskie Stadium": {
        "lat": 41.9341, "lon": -88.7774, "elevation": 270.0
    },
    "NCAA FBS|Duke|Brooks Field at Wallace Wade Stadium": {
        "lat": 35.9972, "lon": -78.938, "elevation": 125.0
    },
    "NCAA FBS|Jacksonville State|Burgess–Snow Field at AmFirst Stadium": {
        "lat": 33.8147, "lon": -85.7612, "elevation": 211.0
    },
    "NCAA FBS|Texas State|Jim Wacker Field at UFCU Stadium": {
        "lat": 29.8953, "lon": -97.9331, "elevation": 179.0
    },
    "NCAA FBS|Central Michigan|Kramer/Deromedi Field at Kelly/Shorts Stadium": {
        "lat": 43.5803, "lon": -84.7686, "elevation": 233.0
    },
    "NCAA FBS|Kentucky|Kroger Field at C.M. Newton Grounds": {
        "lat": 38.0227, "lon": -84.5058, "elevation": 299.0
    },
    "NCAA FBS|Virginia Tech|Lane Stadium/Worsham Field": {
        "lat": 37.2192, "lon": -80.4189, "elevation": 634.0
    },
    "NCAA FBS|Charlotte|McColl–Richardson Field at Jerry Richardson Stadium": {
        "lat": 35.3091, "lon": -80.7327, "elevation": 231.0
    },
    "NCAA FBS|Indiana|Merchants Bank Field at Memorial Stadium": {
        "lat": 39.1809, "lon": -86.5253, "elevation": 229.0
    },
    "NCAA FBS|Utah State|Merlin Olsen Field at Maverik Stadium": {
        "lat": 41.7639, "lon": -111.809, "elevation": 1413.0
    },
    "NCAA FBS|Auburn|Pat Dye Field at Jordan–Hare Stadium": {
        "lat": 32.6026, "lon": -85.489, "elevation": 212.0
    },
    "NCAA FBS|Ohio|Frank Solich Field at Peden Stadium": {
        "lat": 39.3239, "lon": -82.1036, "elevation": 211.0
    },
    "NCAA FBS|Alabama|Saban Field at Bryant–Denny Stadium": {
        "lat": 33.2084, "lon": -87.5504, "elevation": 68.0
    },
    "NCAA FBS|Colorado State|Sonny Lubick Field at Canvas Stadium": {
        "lat": 40.573, "lon": -105.086, "elevation": 1521.0
    },
    "NCAA FBS|Florida|Steve Spurrier-Florida Field at Ben Hill Griffin Stadium": {
        "lat": 29.6499, "lon": -82.3481, "elevation": 31.0
    },
    "NCAA FBS|NC State|Wayne Day Family Field at Carter–Finley Stadium": {
        "lat": 35.8004, "lon": -78.719, "elevation": 123.0
    },
    "NCAA FBS|NIU|Brigham Field at Huskie Stadium": {
        "lat": 41.9341, "lon": -88.7774, "elevation": 270.0
    },
})

# ---------- NCAA D1 MBB overrides (V1 – original clean names) ----------
D1MBB_OVERRIDES = {
    # ACC
    "NCAA D1 MBB|Boston College|Conte Forum":           {"lat": 42.3358, "lon": -71.1673, "elevation": 61.0},
    "NCAA D1 MBB|Clemson|Littlejohn Coliseum":          {"lat": 34.6822, "lon": -82.8373, "elevation": 248.0},
    "NCAA D1 MBB|Duke|Cameron Indoor Stadium":          {"lat": 36.0004, "lon": -78.9407, "elevation": 127.0},
    "NCAA D1 MBB|Florida State|Donald L. Tucker Civic Center": {"lat": 30.4388, "lon": -84.2842, "elevation": 18.0},
    "NCAA D1 MBB|Georgia Tech|Hank McCamish Pavilion":  {"lat": 33.7757, "lon": -84.3909, "elevation": 295.0},
    "NCAA D1 MBB|Louisville|KFC Yum! Center":           {"lat": 38.2550, "lon": -85.7564, "elevation": 140.0},
    "NCAA D1 MBB|Miami (FL)|Watsco Center":             {"lat": 25.7565, "lon": -80.3762, "elevation": 3.0},
    "NCAA D1 MBB|NC State|PNC Arena":                   {"lat": 35.8033, "lon": -78.7228, "elevation": 122.0},
    "NCAA D1 MBB|North Carolina|Dean E. Smith Center":  {"lat": 35.9049, "lon": -79.0469, "elevation": 161.0},
    "NCAA D1 MBB|Notre Dame|Purcell Pavilion":          {"lat": 41.7003, "lon": -86.2387, "elevation": 237.0},
    "NCAA D1 MBB|Pittsburgh|Petersen Events Center":    {"lat": 40.4435, "lon": -79.9609, "elevation": 290.0},
    "NCAA D1 MBB|Syracuse|JMA Wireless Dome":           {"lat": 43.0362, "lon": -76.1363, "elevation": 166.0},
    "NCAA D1 MBB|Virginia|John Paul Jones Arena":       {"lat": 38.0491, "lon": -78.5101, "elevation": 180.0},
    "NCAA D1 MBB|Virginia Tech|Cassell Coliseum":       {"lat": 37.2255, "lon": -80.4231, "elevation": 646.0},
    "NCAA D1 MBB|Wake Forest|Lawrence Joel Veterans Memorial Coliseum": {"lat": 36.0991, "lon": -80.2717, "elevation": 283.0},
    # Big Ten
    "NCAA D1 MBB|Illinois|State Farm Center":           {"lat": 40.0957, "lon": -88.2378, "elevation": 217.0},
    "NCAA D1 MBB|Indiana|Simon Skjodt Assembly Hall":   {"lat": 39.1747, "lon": -86.5265, "elevation": 231.0},
    "NCAA D1 MBB|Iowa|Carver-Hawkeye Arena":            {"lat": 41.6576, "lon": -91.5614, "elevation": 225.0},
    "NCAA D1 MBB|Maryland|Xfinity Center":              {"lat": 38.9929, "lon": -76.9428, "elevation": 62.0},
    "NCAA D1 MBB|Michigan|Crisler Center":              {"lat": 42.2778, "lon": -83.7432, "elevation": 275.0},
    "NCAA D1 MBB|Michigan State|Breslin Center":        {"lat": 42.7282, "lon": -84.4787, "elevation": 281.0},
    "NCAA D1 MBB|Minnesota|Williams Arena":             {"lat": 44.9738, "lon": -93.2275, "elevation": 263.0},
    "NCAA D1 MBB|Nebraska|Pinnacle Bank Arena":         {"lat": 40.8006, "lon": -96.7188, "elevation": 358.0},
    "NCAA D1 MBB|Northwestern|Welsh-Ryan Arena":        {"lat": 42.0606, "lon": -87.6727, "elevation": 187.0},
    "NCAA D1 MBB|Ohio State|Value City Arena":          {"lat": 39.9937, "lon": -83.0220, "elevation": 241.0},
    "NCAA D1 MBB|Penn State|Bryce Jordan Center":       {"lat": 40.7979, "lon": -77.8625, "elevation": 370.0},
    "NCAA D1 MBB|Purdue|Mackey Arena":                  {"lat": 40.4278, "lon": -86.9233, "elevation": 190.0},
    "NCAA D1 MBB|Rutgers|Jersey Mike's Arena":          {"lat": 40.5238, "lon": -74.4381, "elevation": 25.0},
    "NCAA D1 MBB|Wisconsin|Kohl Center":                {"lat": 43.0716, "lon": -89.4145, "elevation": 273.0},
    # Big 12
    "NCAA D1 MBB|Baylor|Foster Pavilion":               {"lat": 31.5569, "lon": -97.1215, "elevation": 155.0},
    "NCAA D1 MBB|Cincinnati|Fifth Third Arena":         {"lat": 39.1320, "lon": -84.5183, "elevation": 209.0},
    "NCAA D1 MBB|Houston|Fertitta Center":              {"lat": 29.7218, "lon": -95.3451, "elevation": 23.0},
    "NCAA D1 MBB|Iowa State|Hilton Coliseum":           {"lat": 42.0265, "lon": -93.6458, "elevation": 295.0},
    "NCAA D1 MBB|Kansas|Allen Fieldhouse":              {"lat": 38.9540, "lon": -95.2527, "elevation": 289.0},
    "NCAA D1 MBB|Kansas State|Bramlage Coliseum":       {"lat": 39.1967, "lon": -96.5860, "elevation": 330.0},
    "NCAA D1 MBB|Oklahoma|Lloyd Noble Center":          {"lat": 35.1989, "lon": -97.4437, "elevation": 353.0},
    "NCAA D1 MBB|Oklahoma State|Gallagher-Iba Arena":   {"lat": 36.1268, "lon": -97.0661, "elevation": 286.0},
    "NCAA D1 MBB|TCU|Schollmaier Arena":                {"lat": 32.7079, "lon": -97.3634, "elevation": 194.0},
    "NCAA D1 MBB|Texas|Moody Center":                   {"lat": 30.2863, "lon": -97.7346, "elevation": 163.0},
    "NCAA D1 MBB|Texas Tech|United Supermarkets Arena": {"lat": 33.5841, "lon": -101.8777, "elevation": 985.0},
    "NCAA D1 MBB|UCF|Addition Financial Arena":         {"lat": 28.6017, "lon": -81.1960, "elevation": 23.0},
    "NCAA D1 MBB|West Virginia|WVU Coliseum":           {"lat": 39.6436, "lon": -79.9771, "elevation": 383.0},
    # SEC
    "NCAA D1 MBB|Alabama|Coleman Coliseum":             {"lat": 33.2069, "lon": -87.5505, "elevation": 68.0},
    "NCAA D1 MBB|Arkansas|Bud Walton Arena":            {"lat": 36.0681, "lon": -94.1769, "elevation": 410.0},
    "NCAA D1 MBB|Auburn|Neville Arena":                 {"lat": 32.5995, "lon": -85.4885, "elevation": 209.0},
    "NCAA D1 MBB|Florida|Exactech Arena at the Stephen C. O'Connell Center": {"lat": 29.6497, "lon": -82.3486, "elevation": 25.0},
    "NCAA D1 MBB|Georgia|Stegeman Coliseum":            {"lat": 33.9499, "lon": -83.3775, "elevation": 184.0},
    "NCAA D1 MBB|Kentucky|Rupp Arena":                  {"lat": 38.0491, "lon": -84.4972, "elevation": 294.0},
    "NCAA D1 MBB|LSU|Pete Maravich Assembly Center":    {"lat": 30.4130, "lon": -91.1782, "elevation": 14.0},
    "NCAA D1 MBB|Mississippi|The Pavilion at Ole Miss": {"lat": 34.3645, "lon": -89.5350, "elevation": 86.0},
    "NCAA D1 MBB|Mississippi State|Humphrey Coliseum":  {"lat": 33.4565, "lon": -88.7954, "elevation": 73.0},
    "NCAA D1 MBB|Missouri|Mizzou Arena":                {"lat": 38.9384, "lon": -92.3341, "elevation": 228.0},
    "NCAA D1 MBB|South Carolina|Colonial Life Arena":   {"lat": 33.9991, "lon": -81.0383, "elevation": 72.0},
    "NCAA D1 MBB|Tennessee|Thompson-Boling Arena at Food City Center": {"lat": 35.9535, "lon": -83.9276, "elevation": 290.0},
    "NCAA D1 MBB|Texas A&M|Reed Arena":                 {"lat": 30.6131, "lon": -96.3413, "elevation": 92.0},
    "NCAA D1 MBB|Vanderbilt|Memorial Gymnasium":        {"lat": 36.1449, "lon": -86.8036, "elevation": 169.0},
    # MAC
    "NCAA D1 MBB|Akron|James A. Rhodes Arena":          {"lat": 41.0750, "lon": -81.5033, "elevation": 326.0},
    "NCAA D1 MBB|Ball State|Worthen Arena":             {"lat": 40.2030, "lon": -85.4109, "elevation": 285.0},
    "NCAA D1 MBB|Bowling Green|Stroh Center":           {"lat": 41.3824, "lon": -83.6362, "elevation": 221.0},
    "NCAA D1 MBB|Buffalo|Alumni Arena":                 {"lat": 43.0004, "lon": -78.7793, "elevation": 196.0},
    "NCAA D1 MBB|Central Michigan|McGuirk Arena":       {"lat": 43.5879, "lon": -84.7748, "elevation": 234.0},
    "NCAA D1 MBB|Eastern Michigan|Convocation Center":  {"lat": 42.2519, "lon": -83.6291, "elevation": 216.0},
    "NCAA D1 MBB|Kent State|Memorial Athletic and Convocation Center": {"lat": 41.1529, "lon": -81.3503, "elevation": 325.0},
    "NCAA D1 MBB|Miami (OH)|Millett Hall":              {"lat": 39.5117, "lon": -84.7373, "elevation": 283.0},
    "NCAA D1 MBB|Northern Illinois|Convocation Center": {"lat": 41.9355, "lon": -88.7725, "elevation": 266.0},
    "NCAA D1 MBB|Ohio|Convocation Center":              {"lat": 39.3202, "lon": -82.1019, "elevation": 210.0},
    "NCAA D1 MBB|Toledo|Savage Arena":                  {"lat": 41.6614, "lon": -83.6124, "elevation": 186.0},
    "NCAA D1 MBB|Western Michigan|Kalamazoo Event Center": {"lat": 42.2934, "lon": -85.5818, "elevation": 260.0},
    # Mountain West
    "NCAA D1 MBB|Air Force|Clune Arena":                {"lat": 38.9955, "lon": -104.8452, "elevation": 2003.0},
    "NCAA D1 MBB|Boise State|ExtraMile Arena":          {"lat": 43.6117, "lon": -116.2000, "elevation": 873.0},
    "NCAA D1 MBB|Colorado State|Moby Arena":            {"lat": 40.5740, "lon": -105.0854, "elevation": 1529.0},
    "NCAA D1 MBB|Fresno State|Save Mart Center":        {"lat": 36.8134, "lon": -119.7479, "elevation": 102.0},
    "NCAA D1 MBB|Nevada|Lawlor Events Center":          {"lat": 39.5477, "lon": -119.8184, "elevation": 1398.0},
    "NCAA D1 MBB|New Mexico|The Pit":                   {"lat": 35.0797, "lon": -106.6504, "elevation": 1586.0},
    "NCAA D1 MBB|San Diego State|Viejas Arena":         {"lat": 32.7741, "lon": -117.0731, "elevation": 188.0},
    "NCAA D1 MBB|UNLV|Thomas & Mack Center":            {"lat": 36.1006, "lon": -115.1769, "elevation": 633.0},
    "NCAA D1 MBB|Utah State|Dee Glen Smith Spectrum":   {"lat": 41.7564, "lon": -111.8119, "elevation": 1399.0},
    "NCAA D1 MBB|Wyoming|Arena-Auditorium":             {"lat": 41.3153, "lon": -105.5831, "elevation": 2215.0},
    # Big East
    "NCAA D1 MBB|Butler|Hinkle Fieldhouse":             {"lat": 39.8386, "lon": -86.1702, "elevation": 232.0},
    "NCAA D1 MBB|Creighton|CHI Health Center Omaha":    {"lat": 41.2567, "lon": -95.9248, "elevation": 311.0},
    "NCAA D1 MBB|DePaul|Wintrust Arena":                {"lat": 41.8670, "lon": -87.6275, "elevation": 183.0},
    "NCAA D1 MBB|Georgetown|Capital One Arena":         {"lat": 38.8981, "lon": -77.0209, "elevation": 22.0},
    "NCAA D1 MBB|Marquette|Fiserv Forum":               {"lat": 43.0450, "lon": -87.9175, "elevation": 183.0},
    "NCAA D1 MBB|Providence|Amica Mutual Pavilion":     {"lat": 41.8262, "lon": -71.4133, "elevation": 7.0},
    "NCAA D1 MBB|Seton Hall|Prudential Center":         {"lat": 40.7337, "lon": -74.1713, "elevation": 8.0},
    "NCAA D1 MBB|St. John's (NY)|Madison Square Garden": {"lat": 40.7505, "lon": -73.9935, "elevation": 22.0},
    "NCAA D1 MBB|UConn|Harry A. Gampel Pavilion":       {"lat": 41.8068, "lon": -72.2520, "elevation": 62.0},
    "NCAA D1 MBB|Villanova|Finneran Pavilion":          {"lat": 40.0365, "lon": -75.3405, "elevation": 110.0},
    "NCAA D1 MBB|Xavier|Cintas Center":                 {"lat": 39.1537, "lon": -84.4729, "elevation": 185.0},
    # A-10
    "NCAA D1 MBB|Dayton|UD Arena":                      {"lat": 39.7501, "lon": -84.1929, "elevation": 294.0},
    "NCAA D1 MBB|Davidson|John M. Belk Arena":          {"lat": 35.4983, "lon": -80.8480, "elevation": 255.0},
    "NCAA D1 MBB|Duquesne|UPMC Cooper Fieldhouse":      {"lat": 40.4359, "lon": -79.9926, "elevation": 228.0},
    "NCAA D1 MBB|Fordham|Rose Hill Gymnasium":          {"lat": 40.8604, "lon": -73.8831, "elevation": 49.0},
    "NCAA D1 MBB|George Mason|EagleBank Arena":         {"lat": 38.8327, "lon": -77.3118, "elevation": 104.0},
    "NCAA D1 MBB|George Washington|Charles E. Smith Center": {"lat": 38.8988, "lon": -77.0479, "elevation": 20.0},
    "NCAA D1 MBB|La Salle|Tom Gola Arena":              {"lat": 40.0382, "lon": -75.1321, "elevation": 49.0},
    "NCAA D1 MBB|Massachusetts|Mullins Center":         {"lat": 42.3901, "lon": -72.5273, "elevation": 62.0},
    "NCAA D1 MBB|Rhode Island|Thomas M. Ryan Center":   {"lat": 41.4806, "lon": -71.5268, "elevation": 41.0},
    "NCAA D1 MBB|Richmond|Robins Center":               {"lat": 37.5769, "lon": -77.5376, "elevation": 71.0},
    "NCAA D1 MBB|Saint Louis|Chaifetz Arena":           {"lat": 38.6333, "lon": -90.2323, "elevation": 150.0},
    "NCAA D1 MBB|Saint Joseph's|Hagan Arena":           {"lat": 40.0038, "lon": -75.2356, "elevation": 72.0},
    "NCAA D1 MBB|VCU|Stuart C. Siegel Center":          {"lat": 37.5476, "lon": -77.4492, "elevation": 54.0},
    # WCC
    "NCAA D1 MBB|BYU|Marriott Center":                  {"lat": 40.2526, "lon": -111.6494, "elevation": 1462.0},
    "NCAA D1 MBB|Gonzaga|McCarthey Athletic Center":    {"lat": 47.6678, "lon": -117.4017, "elevation": 576.0},
    "NCAA D1 MBB|Loyola Marymount|Gersten Pavilion":    {"lat": 33.9668, "lon": -118.4191, "elevation": 65.0},
    "NCAA D1 MBB|Pacific|Spanos Center":                {"lat": 37.9810, "lon": -121.3166, "elevation": 7.0},
    "NCAA D1 MBB|Pepperdine|Firestone Fieldhouse":      {"lat": 34.0349, "lon": -118.7127, "elevation": 74.0},
    "NCAA D1 MBB|Portland|Chiles Center":               {"lat": 45.5582, "lon": -122.7268, "elevation": 55.0},
    "NCAA D1 MBB|San Diego|Jenny Craig Pavilion":       {"lat": 32.7726, "lon": -117.1897, "elevation": 119.0},
    "NCAA D1 MBB|San Francisco|War Memorial Gymnasium": {"lat": 37.7773, "lon": -122.4506, "elevation": 90.0},
    "NCAA D1 MBB|Santa Clara|Leavey Center":            {"lat": 37.3519, "lon": -121.9396, "elevation": 17.0},
    "NCAA D1 MBB|Saint Mary's (CA)|Moraga Sports Center": {"lat": 37.8374, "lon": -122.1097, "elevation": 168.0},
    # Pac-12
    "NCAA D1 MBB|Arizona|McKale Center":                {"lat": 32.2282, "lon": -110.9509, "elevation": 762.0},
    "NCAA D1 MBB|Arizona State|Desert Financial Arena": {"lat": 33.4268, "lon": -111.9297, "elevation": 364.0},
    "NCAA D1 MBB|California|Haas Pavilion":             {"lat": 37.8747, "lon": -122.2618, "elevation": 52.0},
    "NCAA D1 MBB|Colorado|CU Events Center":            {"lat": 40.0044, "lon": -105.2650, "elevation": 1630.0},
    "NCAA D1 MBB|Oregon|Matthew Knight Arena":          {"lat": 44.0510, "lon": -123.0732, "elevation": 133.0},
    "NCAA D1 MBB|Oregon State|Gill Coliseum":           {"lat": 44.5635, "lon": -123.2779, "elevation": 72.0},
    "NCAA D1 MBB|Stanford|Maples Pavilion":             {"lat": 37.4330, "lon": -122.1619, "elevation": 20.0},
    "NCAA D1 MBB|UCLA|Pauley Pavilion":                 {"lat": 34.0716, "lon": -118.4498, "elevation": 109.0},
    "NCAA D1 MBB|USC|Galen Center":                     {"lat": 34.0228, "lon": -118.2851, "elevation": 66.0},
    "NCAA D1 MBB|Utah|Jon M. Huntsman Center":          {"lat": 40.7640, "lon": -111.8464, "elevation": 1378.0},
    "NCAA D1 MBB|Washington|Alaska Airlines Arena at Hec Edmundson Pavilion": {"lat": 47.6527, "lon": -122.3024, "elevation": 26.0},
    "NCAA D1 MBB|Washington State|Beasley Coliseum":    {"lat": 46.7290, "lon": -117.1583, "elevation": 796.0},
    # Big West
    "NCAA D1 MBB|Cal Poly|Mott Athletics Center":       {"lat": 35.3003, "lon": -120.6597, "elevation": 95.0},
    "NCAA D1 MBB|Cal State Fullerton|Titan Gym":        {"lat": 33.8828, "lon": -117.8855, "elevation": 47.0},
    "NCAA D1 MBB|Cal State Northridge|Premier America Credit Union Arena": {"lat": 34.2416, "lon": -118.5281, "elevation": 293.0},
    "NCAA D1 MBB|Hawaii|SimpliFi Arena at Stan Sheriff Center": {"lat": 21.2991, "lon": -157.8174, "elevation": 10.0},
    "NCAA D1 MBB|Long Beach State|Walter Pyramid":      {"lat": 33.7858, "lon": -118.1121, "elevation": 5.0},
    "NCAA D1 MBB|UC Irvine|Bren Events Center":         {"lat": 33.6453, "lon": -117.8421, "elevation": 48.0},
    "NCAA D1 MBB|UC Santa Barbara|Thunderdome":         {"lat": 34.4134, "lon": -119.8489, "elevation": 9.0},
    # Missouri Valley
    "NCAA D1 MBB|Bradley|Carver Arena":                 {"lat": 40.6908, "lon": -89.5898, "elevation": 193.0},
    "NCAA D1 MBB|Drake|Knapp Center":                   {"lat": 41.6033, "lon": -93.6434, "elevation": 278.0},
    "NCAA D1 MBB|Evansville|Ford Center":               {"lat": 37.9716, "lon": -87.5733, "elevation": 119.0},
    "NCAA D1 MBB|Illinois State|Redbird Arena":         {"lat": 40.5077, "lon": -88.9894, "elevation": 273.0},
    "NCAA D1 MBB|Indiana State|Hulman Center":          {"lat": 39.4688, "lon": -87.4144, "elevation": 156.0},
    "NCAA D1 MBB|Missouri State|JQH Arena":             {"lat": 37.1905, "lon": -93.2923, "elevation": 418.0},
    "NCAA D1 MBB|Murray State|CFSB Center":             {"lat": 36.6094, "lon": -88.3139, "elevation": 167.0},
    "NCAA D1 MBB|Northern Iowa|McLeod Center":          {"lat": 42.5145, "lon": -92.4617, "elevation": 265.0},
    "NCAA D1 MBB|Southern Illinois|Banterra Center":    {"lat": 37.7244, "lon": -89.1745, "elevation": 133.0},
    "NCAA D1 MBB|Valparaiso|Athletics-Recreation Center": {"lat": 41.4647, "lon": -87.0455, "elevation": 234.0},
    # CAA
    "NCAA D1 MBB|Charleston|TD Arena":                  {"lat": 32.7908, "lon": -79.9441, "elevation": 6.0},
    "NCAA D1 MBB|Delaware|Bob Carpenter Center":        {"lat": 39.6770, "lon": -75.7490, "elevation": 29.0},
    "NCAA D1 MBB|Drexel|Daskalakis Athletic Center":    {"lat": 39.9548, "lon": -75.1835, "elevation": 10.0},
    "NCAA D1 MBB|Elon|Schar Center":                    {"lat": 36.1015, "lon": -79.5104, "elevation": 196.0},
    "NCAA D1 MBB|Hofstra|David S. Mack Sports and Exhibition Complex": {"lat": 40.7155, "lon": -73.5989, "elevation": 5.0},
    "NCAA D1 MBB|James Madison|Atlantic Union Bank Center": {"lat": 38.4370, "lon": -78.8743, "elevation": 461.0},
    "NCAA D1 MBB|Monmouth|OceanFirst Bank Center":      {"lat": 40.3148, "lon": -74.0700, "elevation": 5.0},
    "NCAA D1 MBB|Northeastern|Cabot Center":            {"lat": 42.3367, "lon": -71.0880, "elevation": 8.0},
    "NCAA D1 MBB|Stony Brook|Island Federal Arena":     {"lat": 40.9147, "lon": -73.1194, "elevation": 36.0},
    "NCAA D1 MBB|Towson|SECU Arena":                    {"lat": 39.4023, "lon": -76.5993, "elevation": 90.0},
    "NCAA D1 MBB|UNC Wilmington|Trask Coliseum":        {"lat": 34.2261, "lon": -77.8799, "elevation": 12.0},
    "NCAA D1 MBB|William & Mary|Kaplan Arena":          {"lat": 37.2709, "lon": -76.7143, "elevation": 10.0},
    # Horizon
    "NCAA D1 MBB|Cleveland State|Wolstein Center":      {"lat": 41.5015, "lon": -81.6747, "elevation": 186.0},
    "NCAA D1 MBB|Detroit Mercy|Calihan Hall":           {"lat": 42.3562, "lon": -83.0731, "elevation": 184.0},
    "NCAA D1 MBB|Green Bay|Resch Center":               {"lat": 44.4923, "lon": -88.0604, "elevation": 184.0},
    "NCAA D1 MBB|Milwaukee|UWM Panther Arena":          {"lat": 43.0430, "lon": -87.9091, "elevation": 186.0},
    "NCAA D1 MBB|Wright State|Nutter Center":           {"lat": 39.7895, "lon": -84.0541, "elevation": 303.0},
    "NCAA D1 MBB|Youngstown State|Beeghly Center":      {"lat": 41.0993, "lon": -80.6434, "elevation": 323.0},
    # MEAC
    "NCAA D1 MBB|Coppin State|Physical Education Complex": {"lat": 39.3406, "lon": -76.6650, "elevation": 51.0},
    "NCAA D1 MBB|Delaware State|Memorial Hall":         {"lat": 39.1582, "lon": -75.5266, "elevation": 18.0},
    "NCAA D1 MBB|Howard|Burr Gymnasium":                {"lat": 38.9224, "lon": -77.0197, "elevation": 38.0},
    "NCAA D1 MBB|Norfolk State|Echols Hall":            {"lat": 36.8490, "lon": -76.2834, "elevation": 5.0},
    "NCAA D1 MBB|North Carolina A&T|Corbett Sports Center": {"lat": 36.0754, "lon": -79.7808, "elevation": 269.0},
    "NCAA D1 MBB|North Carolina Central|McDougald-McLendon Arena": {"lat": 35.9775, "lon": -78.9044, "elevation": 103.0},
    "NCAA D1 MBB|South Carolina State|Smith-Hammond-Middleton Memorial Center": {"lat": 33.4967, "lon": -80.8548, "elevation": 57.0},
    # Ivy
    "NCAA D1 MBB|Brown|Pizzitola Sports Center":        {"lat": 41.8293, "lon": -71.4029, "elevation": 22.0},
    "NCAA D1 MBB|Columbia|Levien Gymnasium":            {"lat": 40.8072, "lon": -73.9631, "elevation": 32.0},
    "NCAA D1 MBB|Cornell|Newman Arena":                 {"lat": 42.4450, "lon": -76.4816, "elevation": 314.0},
    "NCAA D1 MBB|Dartmouth|Leede Arena":                {"lat": 43.7044, "lon": -72.2989, "elevation": 174.0},
    "NCAA D1 MBB|Harvard|Lavietes Pavilion":            {"lat": 42.3656, "lon": -71.1270, "elevation": 11.0},
    "NCAA D1 MBB|Penn|Palestra":                        {"lat": 39.9508, "lon": -75.1958, "elevation": 18.0},
    "NCAA D1 MBB|Princeton|Jadwin Gymnasium":           {"lat": 40.3468, "lon": -74.6584, "elevation": 30.0},
    "NCAA D1 MBB|Yale|John J. Lee Amphitheater":        {"lat": 41.3127, "lon": -72.9268, "elevation": 8.0},
    # MAAC
    "NCAA D1 MBB|Canisius|KeyBank Center":              {"lat": 42.8759, "lon": -78.8763, "elevation": 182.0},
    "NCAA D1 MBB|Fairfield|Webster Bank Arena":         {"lat": 41.1793, "lon": -73.1834, "elevation": 4.0},
    "NCAA D1 MBB|Iona|Hynes Athletics Center":          {"lat": 40.9297, "lon": -73.7842, "elevation": 35.0},
    "NCAA D1 MBB|Manhattan|Draddy Gymnasium":           {"lat": 40.8659, "lon": -73.9000, "elevation": 57.0},
    "NCAA D1 MBB|Marist|McCann Center":                 {"lat": 41.7119, "lon": -73.9128, "elevation": 33.0},
    "NCAA D1 MBB|Niagara|Gallagher Center":             {"lat": 43.0989, "lon": -79.0563, "elevation": 174.0},
    "NCAA D1 MBB|Quinnipiac|TD Bank Sports Center":     {"lat": 41.3987, "lon": -72.8946, "elevation": 46.0},
    "NCAA D1 MBB|Rider|Alumni Gymnasium":               {"lat": 40.3303, "lon": -74.6583, "elevation": 32.0},
    "NCAA D1 MBB|Saint Peter's|Yanitelli Center":       {"lat": 40.7226, "lon": -74.0578, "elevation": 3.0},
    "NCAA D1 MBB|Siena|Times Union Center":             {"lat": 42.6919, "lon": -73.7543, "elevation": 54.0},
    # Patriot
    "NCAA D1 MBB|American|Bender Arena":                {"lat": 38.9346, "lon": -77.0858, "elevation": 72.0},
    "NCAA D1 MBB|Army|Christl Arena":                   {"lat": 41.3908, "lon": -73.9546, "elevation": 145.0},
    "NCAA D1 MBB|Boston University|Case Gymnasium":     {"lat": 42.3545, "lon": -71.1189, "elevation": 4.0},
    "NCAA D1 MBB|Bucknell|Sojka Pavilion":              {"lat": 40.9560, "lon": -76.8843, "elevation": 170.0},
    "NCAA D1 MBB|Colgate|Cotterell Court":              {"lat": 42.8188, "lon": -75.5304, "elevation": 418.0},
    "NCAA D1 MBB|Holy Cross|Hart Center":               {"lat": 42.2413, "lon": -71.8124, "elevation": 292.0},
    "NCAA D1 MBB|Lafayette|Kirby Sports Center":        {"lat": 40.6968, "lon": -75.2197, "elevation": 135.0},
    "NCAA D1 MBB|Lehigh|Stabler Arena":                 {"lat": 40.6204, "lon": -75.3766, "elevation": 103.0},
    "NCAA D1 MBB|Navy|Alumni Hall":                     {"lat": 38.9843, "lon": -76.4826, "elevation": 3.0},
    # America East
    "NCAA D1 MBB|Albany (NY)|SEFCU Arena":              {"lat": 42.6860, "lon": -73.8286, "elevation": 89.0},
    "NCAA D1 MBB|Binghamton|Events Center":             {"lat": 42.0895, "lon": -75.9723, "elevation": 261.0},
    "NCAA D1 MBB|Hartford|XL Center":                   {"lat": 41.7658, "lon": -72.6836, "elevation": 27.0},
    "NCAA D1 MBB|Maine|Cross Insurance Center":         {"lat": 44.8010, "lon": -68.7783, "elevation": 39.0},
    "NCAA D1 MBB|New Hampshire|Lundholm Gymnasium":     {"lat": 43.1384, "lon": -70.9374, "elevation": 28.0},
    "NCAA D1 MBB|UMBC|RAC Arena":                       {"lat": 39.2549, "lon": -76.7120, "elevation": 44.0},
    "NCAA D1 MBB|UMass Lowell|Tsongas Center":          {"lat": 42.6435, "lon": -71.3272, "elevation": 21.0},
    "NCAA D1 MBB|Vermont|Patrick Gymnasium":            {"lat": 44.4763, "lon": -73.1974, "elevation": 99.0},
    # SWAC
    "NCAA D1 MBB|Alcorn State|Davey Whitney Complex":   {"lat": 31.8884, "lon": -90.9688, "elevation": 56.0},
    "NCAA D1 MBB|Arkansas-Pine Bluff|H.O. Clemmons Arena": {"lat": 34.2286, "lon": -92.0179, "elevation": 65.0},
    "NCAA D1 MBB|Bethune-Cookman|Moore Gymnasium":      {"lat": 29.2094, "lon": -81.0519, "elevation": 7.0},
    "NCAA D1 MBB|Florida A&M|Alfred Lawson Jr. Multipurpose Center": {"lat": 30.4215, "lon": -84.2817, "elevation": 18.0},
    "NCAA D1 MBB|Grambling|Memorial Gymnasium":         {"lat": 32.7265, "lon": -92.7166, "elevation": 76.0},
    "NCAA D1 MBB|Jackson State|Lee E. Williams Athletics and Assembly Center": {"lat": 32.2965, "lon": -90.2110, "elevation": 88.0},
    "NCAA D1 MBB|Mississippi Valley State|Harrison HPER Complex": {"lat": 33.4507, "lon": -90.4062, "elevation": 43.0},
    "NCAA D1 MBB|Prairie View A&M|Delco Center":        {"lat": 30.0882, "lon": -95.9824, "elevation": 79.0},
    "NCAA D1 MBB|Southern|F.G. Clark Activity Center":  {"lat": 30.5196, "lon": -91.1397, "elevation": 17.0},
    "NCAA D1 MBB|Texas Southern|Health and Physical Education Arena": {"lat": 29.7224, "lon": -95.3598, "elevation": 17.0},
}

GEO_OVERRIDES.update(D1MBB_OVERRIDES)

# ---------- D1MBB V2 – exact Wikipedia venue strings from run logs ----------
D1MBB_OVERRIDES_V2 = {
    "NCAA D1 MBB|Notre Dame|Purcell Pavilion at Edmund P. Joyce Center": {"lat": 41.7003, "lon": -86.2387, "elevation": 237.0},
    "NCAA D1 MBB|Binghamton|Binghamton University Events Center":         {"lat": 42.0895, "lon": -75.9723, "elevation": 261.0},
    "NCAA D1 MBB|New Hampshire|Lundholm Gym":                             {"lat": 43.1356, "lon": -70.9379, "elevation": 28.0},
    "NCAA D1 MBB|Bryant|Chace Athletic Center":                           {"lat": 41.8745, "lon": -71.5200, "elevation": 105.0},
    "NCAA D1 MBB|UMBC|Chesapeake Employers Insurance Arena":              {"lat": 39.2617, "lon": -76.7499, "elevation": 110.0},
    "NCAA D1 MBB|Vermont|Patrick Gym":                                    {"lat": 44.4763, "lon": -73.1974, "elevation": 99.0},
    "NCAA D1 MBB|Charlotte|Dale F. Halton Arena":                         {"lat": 35.3043, "lon": -80.7351, "elevation": 234.0},
    "NCAA D1 MBB|East Carolina|Williams Arena at Minges Coliseum":        {"lat": 35.6115, "lon": -77.3685, "elevation": 13.0},
    "NCAA D1 MBB|North Texas|UNT Coliseum":                               {"lat": 33.2137, "lon": -97.1478, "elevation": 193.0},
    "NCAA D1 MBB|Tulane|Devlin Fieldhouse":                               {"lat": 29.9406, "lon": -90.1188, "elevation": 5.0},
    "NCAA D1 MBB|Austin Peay|F&M Bank Arena":                            {"lat": 36.5319, "lon": -87.3534, "elevation": 165.0},
    "NCAA D1 MBB|Eastern Kentucky|Baptist Health Arena":                  {"lat": 37.7348, "lon": -84.2944, "elevation": 295.0},
    "NCAA D1 MBB|Florida Gulf Coast|Alico Arena":                         {"lat": 26.6273, "lon": -81.8510, "elevation": 5.0},
    "NCAA D1 MBB|North Florida|UNF Arena":                                {"lat": 30.2754, "lon": -81.5065, "elevation": 10.0},
    "NCAA D1 MBB|Queens|Curry Arena":                                     {"lat": 35.1867, "lon": -80.8386, "elevation": 236.0},
    "NCAA D1 MBB|La Salle|John Glaser Arena":                             {"lat": 40.0382, "lon": -75.1321, "elevation": 49.0},
    "NCAA D1 MBB|Loyola Chicago|Joseph J. Gentile Arena":                 {"lat": 41.9980, "lon": -87.6540, "elevation": 188.0},
    "NCAA D1 MBB|St. Bonaventure|Reilly Center":                          {"lat": 42.0834, "lon": -78.4851, "elevation": 455.0},
    "NCAA D1 MBB|Montana|Dahlberg Arena":                                 {"lat": 46.8621, "lon": -113.9844, "elevation": 972.0},
    "NCAA D1 MBB|Northern Colorado|Bank of Colorado Arena":               {"lat": 40.4086, "lon": -104.6908, "elevation": 1433.0},
    "NCAA D1 MBB|Sacramento State|Hornets Nest":                          {"lat": 38.5547, "lon": -121.4191, "elevation": 15.0},
    "NCAA D1 MBB|Gardner\u2013Webb|Paul Porter Arena":                    {"lat": 35.3433, "lon": -81.6079, "elevation": 271.0},
    "NCAA D1 MBB|High Point|Nido & Mariana Qubein Arena and Conference Center": {"lat": 35.9546, "lon": -80.0030, "elevation": 258.0},
    "NCAA D1 MBB|Longwood|Joan Perry Brock Center":                       {"lat": 37.2983, "lon": -78.3985, "elevation": 147.0},
    "NCAA D1 MBB|Presbyterian|Templeton Physical Education Center":       {"lat": 34.4791, "lon": -81.8829, "elevation": 183.0},
    "NCAA D1 MBB|USC Upstate|G. B. Hodge Center":                         {"lat": 34.9354, "lon": -81.9241, "elevation": 247.0},
    "NCAA D1 MBB|Cal Poly|Robert A. Mott Athletics Center":               {"lat": 35.3003, "lon": -120.6597, "elevation": 95.0},
    "NCAA D1 MBB|Long Beach State|LBS Financial Credit Union Pyramid":    {"lat": 33.7858, "lon": -118.1121, "elevation": 5.0},
    "NCAA D1 MBB|UC Davis|University Credit Union Center":                {"lat": 38.5388, "lon": -121.7600, "elevation": 17.0},
    "NCAA D1 MBB|UC Riverside|UC Riverside Student Recreation Center":    {"lat": 33.9738, "lon": -117.3281, "elevation": 305.0},
    "NCAA D1 MBB|UC San Diego|LionTree Arena":                            {"lat": 32.8839, "lon": -117.2376, "elevation": 126.0},
    "NCAA D1 MBB|Campbell|John W. Pope, Jr. Convocation Center":          {"lat": 35.3912, "lon": -78.6648, "elevation": 43.0},
    "NCAA D1 MBB|Hampton|Hampton Convocation Center":                     {"lat": 37.0243, "lon": -76.3357, "elevation": 5.0},
    "NCAA D1 MBB|Northeastern men|Matthews Arena":                        {"lat": 42.3407, "lon": -71.0895, "elevation": 8.0},
    "NCAA D1 MBB|Towson|TU Arena":                                        {"lat": 39.4023, "lon": -76.5993, "elevation": 90.0},
    "NCAA D1 MBB|Kennesaw State|KSU Convocation Center":                  {"lat": 34.0310, "lon": -84.5750, "elevation": 330.0},
    "NCAA D1 MBB|Missouri State|Great Southern Bank Arena":               {"lat": 37.2070, "lon": -93.2768, "elevation": 421.0},
    "NCAA D1 MBB|Western Kentucky|E. A. Diddle Arena":                    {"lat": 36.9837, "lon": -86.4683, "elevation": 152.0},
    "NCAA D1 MBB|IU Indy|The Jungle":                                     {"lat": 39.7755, "lon": -86.1726, "elevation": 220.0},
    "NCAA D1 MBB|IU Indy|James T. Morris Arena":                          {"lat": 39.7755, "lon": -86.1726, "elevation": 220.0},
    "NCAA D1 MBB|Oakland|OU Credit Union O\u2019rena":                    {"lat": 42.6724, "lon": -83.2146, "elevation": 299.0},
    "NCAA D1 MBB|Purdue Fort Wayne|Hilliard Gates Sports Center":         {"lat": 41.1310, "lon": -85.1278, "elevation": 243.0},
    "NCAA D1 MBB|Fairfield|Leo D. Mahoney Arena":                         {"lat": 41.1597, "lon": -73.2312, "elevation": 31.0},
    "NCAA D1 MBB|Marist|McCann Arena":                                    {"lat": 41.7089, "lon": -73.9117, "elevation": 33.0},
    "NCAA D1 MBB|Merrimack|Hammel Court":                                 {"lat": 42.7031, "lon": -71.1309, "elevation": 55.0},
    "NCAA D1 MBB|Mount St. Mary's|Knott Arena":                           {"lat": 39.7100, "lon": -77.3191, "elevation": 247.0},
    "NCAA D1 MBB|Sacred Heart|William H. Pitt Center":                    {"lat": 41.1644, "lon": -73.2448, "elevation": 33.0},
    "NCAA D1 MBB|Saint Peter's|Run Baby Run Arena":                       {"lat": 40.7175, "lon": -74.0632, "elevation": 3.0},
    "NCAA D1 MBB|Maryland Eastern Shore|Hytche Athletic Center":          {"lat": 38.1975, "lon": -75.6929, "elevation": 12.0},
    "NCAA D1 MBB|Morgan State|Talmadge L. Hill Field House":              {"lat": 39.3421, "lon": -76.5838, "elevation": 66.0},
    "NCAA D1 MBB|North Carolina Central|McDougald\u2013McLendon Arena":   {"lat": 35.9782, "lon": -78.9043, "elevation": 103.0},
    "NCAA D1 MBB|South Carolina State|SHM Memorial Center":              {"lat": 33.4967, "lon": -80.8548, "elevation": 57.0},
    "NCAA D1 MBB|Fresno State|Save Mart Center at Fresno State":          {"lat": 36.8134, "lon": -119.7479, "elevation": 102.0},
    "NCAA D1 MBB|Grand Canyon|Global Credit Union Arena":                 {"lat": 33.5050, "lon": -112.1150, "elevation": 340.0},
    "NCAA D1 MBB|San Jose State|Provident Credit Union Event Center":     {"lat": 37.3343, "lon": -121.8827, "elevation": 32.0},
    "NCAA D1 MBB|Central Connecticut|William H. Detrick Gymnasium":       {"lat": 41.6818, "lon": -72.8718, "elevation": 56.0},
    "NCAA D1 MBB|Chicago State|Emil and Patricia Jones Convocation Center": {"lat": 41.7196, "lon": -87.6105, "elevation": 184.0},
    "NCAA D1 MBB|Fairleigh Dickinson|Bogota Savings Bank Center":         {"lat": 40.8896, "lon": -74.0437, "elevation": 6.0},
    "NCAA D1 MBB|Le Moyne|Le Moyne Events Center":                        {"lat": 43.0602, "lon": -76.0745, "elevation": 130.0},
    "NCAA D1 MBB|New Haven|Jeffery P. Hazell Athletics Center":           {"lat": 41.2764, "lon": -72.9659, "elevation": 15.0},
    "NCAA D1 MBB|Lindenwood|Robert F. Hyland Performance Arena":          {"lat": 38.7781, "lon": -90.4890, "elevation": 148.0},
    "NCAA D1 MBB|Morehead State|Ellis Johnson Arena":                     {"lat": 38.1850, "lon": -83.4313, "elevation": 283.0},
    "NCAA D1 MBB|Southern Indiana|Liberty Arena, Home of the Screaming Eagles": {"lat": 37.9635, "lon": -87.7052, "elevation": 127.0},
    "NCAA D1 MBB|Tennessee-Martin|Kathleen and Tom Elam Center":          {"lat": 36.3468, "lon": -88.8519, "elevation": 112.0},
    "NCAA D1 MBB|Boston University|Case Gym":                             {"lat": 42.3478, "lon": -71.1057, "elevation": 8.0},
    "NCAA D1 MBB|Holy Cross|Hart Center at the Luth Athletics Complex":   {"lat": 42.2413, "lon": -71.8124, "elevation": 292.0},
    "NCAA D1 MBB|Loyola (Maryland)|Reitz Arena":                          {"lat": 39.3623, "lon": -76.6195, "elevation": 50.0},
    "NCAA D1 MBB|Ole Miss|The Sandy and John Black Pavilion at Ole Miss":  {"lat": 34.3654, "lon": -89.5303, "elevation": 86.0},
    "NCAA D1 MBB|East Tennessee State|Freedom Hall Civic Center":         {"lat": 36.3026, "lon": -82.3610, "elevation": 476.0},
    "NCAA D1 MBB|UNC Greensboro|First Horizon Coliseum":                  {"lat": 36.0681, "lon": -79.8100, "elevation": 274.0},
    "NCAA D1 MBB|Western Carolina|Liston B. Ramsey Regional Activity Center": {"lat": 35.3098, "lon": -83.1900, "elevation": 661.0},
    "NCAA D1 MBB|East Texas A&M|The Field House":                         {"lat": 33.2381, "lon": -95.9080, "elevation": 154.0},
    "NCAA D1 MBB|Houston Christian|Sharp Gymnasium":                      {"lat": 29.7253, "lon": -95.5406, "elevation": 23.0},
    "NCAA D1 MBB|Lamar|Neches Federal Credit Union Arena at the Montagne Center": {"lat": 30.0866, "lon": -94.1355, "elevation": 14.0},
    "NCAA D1 MBB|McNeese|Townsley Law Arena":                             {"lat": 30.2177, "lon": -93.2003, "elevation": 7.0},
    "NCAA D1 MBB|Texas A&M-Corpus Christi|American Bank Center Arena":    {"lat": 27.8006, "lon": -97.3964, "elevation": 5.0},
    "NCAA D1 MBB|UTRGV|UTRGV Fieldhouse":                                 {"lat": 26.3022, "lon": -98.1750, "elevation": 55.0},
    "NCAA D1 MBB|South Dakota State|First Bank and Trust Arena":          {"lat": 44.3126, "lon": -96.7984, "elevation": 506.0},
    "NCAA D1 MBB|Georgia Southern|Jack and Ruth Ann Hill Convocation Center": {"lat": 32.4189, "lon": -81.8000, "elevation": 62.0},
    "NCAA D1 MBB|Louisiana\u2013Monroe|Fant\u2013Ewing Coliseum":         {"lat": 32.5290, "lon": -92.0699, "elevation": 29.0},
    "NCAA D1 MBB|Alabama A&M|Alabama A&M Events Center":                  {"lat": 34.7840, "lon": -86.5685, "elevation": 222.0},
    "NCAA D1 MBB|Arkansas-Pine Bluff|K. L. Johnson Complex":              {"lat": 34.2286, "lon": -92.0179, "elevation": 65.0},
    "NCAA D1 MBB|Florida A&M|Al Lawson Center":                           {"lat": 30.4215, "lon": -84.2817, "elevation": 18.0},
    "NCAA D1 MBB|Grambling|Fredrick C. Hobdy Assembly Center":            {"lat": 32.7265, "lon": -92.7166, "elevation": 76.0},
    "NCAA D1 MBB|Prairie View A&M|William J. Nicks Building":             {"lat": 30.0882, "lon": -95.9824, "elevation": 79.0},
    "NCAA D1 MBB|Southern|F. G. Clark Activity Center":                   {"lat": 30.5196, "lon": -91.1397, "elevation": 17.0},
    "NCAA D1 MBB|Saint Mary's|University Credit Union Pavilion":          {"lat": 37.8374, "lon": -122.1097, "elevation": 168.0},
    "NCAA D1 MBB|San Francisco|The Sobrato Center":                       {"lat": 37.7773, "lon": -122.4506, "elevation": 90.0},
    "NCAA D1 MBB|California Baptist|Fowler Events Center":                {"lat": 33.9395, "lon": -117.4107, "elevation": 336.0},
    "NCAA D1 MBB|Southern Utah|America First Event Center":               {"lat": 37.6845, "lon": -113.0594, "elevation": 1726.0},
    "NCAA D1 MBB|Cal State Bakersfield|Dignity Health Arena":             {"lat": 35.3728, "lon": -119.0175, "elevation": 116.0},
    "NCAA D1 MBB|Nevada (men)|Grand Sierra Resort Arena":                 {"lat": 39.5299, "lon": -119.8159, "elevation": 1361.0},
    "NCAA D1 MBB|Oakland|OU Credit Union O'rena":                         {"lat": 42.6724, "lon": -83.2146, "elevation": 299.0},
}

GEO_OVERRIDES.update(D1MBB_OVERRIDES_V2)

# ---------- D1MBB V3 – remaining hard fails from run 3 log ----------
D1MBB_OVERRIDES_V3 = {
    "NCAA D1 MBB|Boston College|Conte Forum":           {"lat": 42.3358, "lon": -71.1673, "elevation": 61.0},
    "NCAA D1 MBB|Clemson|Littlejohn Coliseum":          {"lat": 34.6822, "lon": -82.8373, "elevation": 248.0},
    "NCAA D1 MBB|Georgia Tech|Hank McCamish Pavilion":  {"lat": 33.7757, "lon": -84.3909, "elevation": 295.0},
    "NCAA D1 MBB|Florida Atlantic|FAU Arena":           {"lat": 26.3724, "lon": -80.1050, "elevation": 5.0},
    "NCAA D1 MBB|Duquesne|UPMC Cooper Fieldhouse":      {"lat": 40.4359, "lon": -79.9926, "elevation": 228.0},
    "NCAA D1 MBB|George Mason|EagleBank Arena":         {"lat": 38.8327, "lon": -77.3118, "elevation": 104.0},
    "NCAA D1 MBB|Villanova|Finneran Pavilion":          {"lat": 40.0365, "lon": -75.3405, "elevation": 110.0},
    "NCAA D1 MBB|Washington|Alaska Airlines Arena at Hec Edmundson Pavilion": {"lat": 47.6527, "lon": -122.3024, "elevation": 26.0},
    "NCAA D1 MBB|Cal State Fullerton|Titan Gym":        {"lat": 33.8828, "lon": -117.8855, "elevation": 47.0},
    "NCAA D1 MBB|Cal State Northridge|Premier America Credit Union Arena": {"lat": 34.2416, "lon": -118.5281, "elevation": 293.0},
    "NCAA D1 MBB|Drexel|Daskalakis Athletic Center":    {"lat": 39.9548, "lon": -75.1835, "elevation": 10.0},
    "NCAA D1 MBB|North Carolina A&T|Corbett Sports Center": {"lat": 36.0754, "lon": -79.7808, "elevation": 269.0},
    "NCAA D1 MBB|Oakland|OU Credit Union O'rena":       {"lat": 42.6724, "lon": -83.2146, "elevation": 299.0},
    "NCAA D1 MBB|Brown|Pizzitola Sports Center":        {"lat": 41.8293, "lon": -71.4029, "elevation": 22.0},
    "NCAA D1 MBB|Columbia|Levien Gymnasium":            {"lat": 40.8072, "lon": -73.9631, "elevation": 32.0},
    "NCAA D1 MBB|Cornell|Newman Arena":                 {"lat": 42.4450, "lon": -76.4816, "elevation": 314.0},
    "NCAA D1 MBB|Dartmouth|Leede Arena":                {"lat": 43.7044, "lon": -72.2989, "elevation": 174.0},
    "NCAA D1 MBB|Harvard|Lavietes Pavilion":            {"lat": 42.3656, "lon": -71.1270, "elevation": 11.0},
    "NCAA D1 MBB|Yale|John J. Lee Amphitheater":        {"lat": 41.3127, "lon": -72.9268, "elevation": 8.0},
    "NCAA D1 MBB|Rider|Alumni Gymnasium":               {"lat": 40.3303, "lon": -74.6583, "elevation": 32.0},
    "NCAA D1 MBB|Buffalo|Alumni Arena":                 {"lat": 43.0004, "lon": -78.7793, "elevation": 196.0},
    "NCAA D1 MBB|Air Force|Clune Arena":                {"lat": 38.9955, "lon": -104.8452, "elevation": 2003.0},
    "NCAA D1 MBB|Eastern Illinois|Lantz Arena":         {"lat": 39.4834, "lon": -88.1760, "elevation": 200.0},
    "NCAA D1 MBB|Army|Christl Arena":                   {"lat": 41.3908, "lon": -73.9546, "elevation": 145.0},
    "NCAA D1 MBB|Bucknell|Sojka Pavilion":              {"lat": 40.9560, "lon": -76.8843, "elevation": 170.0},
    "NCAA D1 MBB|Colgate|Cotterell Court":              {"lat": 42.8188, "lon": -75.5304, "elevation": 418.0},
    "NCAA D1 MBB|Navy|Alumni Hall":                     {"lat": 38.9843, "lon": -76.4826, "elevation": 3.0},
    "NCAA D1 MBB|Auburn|Neville Arena":                 {"lat": 32.5995, "lon": -85.4885, "elevation": 209.0},
    "NCAA D1 MBB|Florida|Exactech Arena at the Stephen C. O'Connell Center": {"lat": 29.6497, "lon": -82.3486, "elevation": 25.0},
    "NCAA D1 MBB|Mississippi State|Humphrey Coliseum":  {"lat": 33.4565, "lon": -88.7954, "elevation": 73.0},
    "NCAA D1 MBB|Alcorn State|Davey Whitney Complex":   {"lat": 31.8884, "lon": -90.9688, "elevation": 56.0},
    "NCAA D1 MBB|Bethune-Cookman|Moore Gymnasium":      {"lat": 29.2094, "lon": -81.0519, "elevation": 7.0},
    "NCAA D1 MBB|Mississippi Valley State|Harrison HPER Complex": {"lat": 33.4507, "lon": -90.4062, "elevation": 43.0},
    "NCAA D1 MBB|Texas Southern|Health and Physical Education Arena": {"lat": 29.7224, "lon": -95.3598, "elevation": 17.0},
    "NCAA D1 MBB|Western Michigan|Kalamazoo Event Center": {"lat": 42.2934, "lon": -85.5818, "elevation": 260.0},
}

GEO_OVERRIDES.update(D1MBB_OVERRIDES_V3)


# =========================
# SINGLE ONE-TIME ELEVATION CONVERSION: meters → feet
# =========================
# This loop runs ONCE at import time. Every elevation value above is stored in
# meters; after this loop they are all in feet. Do NOT apply any further m→ft
# multiplication anywhere else in this file.

for _key, _val in GEO_OVERRIDES.items():
    if "elevation" in _val and _val["elevation"] is not None:
        _val["elevation"] = round(_val["elevation"] * 3.28084, 2)


# =========================
# CACHE
# =========================

try:
    with open(CACHE_FILE, "r") as f:
        CACHE = json.load(f)
except Exception:
    CACHE = {}


def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(CACHE, f, indent=2)


# =========================
# UTILITIES
# =========================

def clean(text):
    # Guard: pandas NaN is a float; bool(float('nan')) == True so the old
    # "if not text" check did NOT catch it, causing TypeError in re.sub().
    if text is None or not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    text = re.sub(r"\[.*?\]", "", text)
    return text.strip() or None


STATE_ABBR = {
    "alabama":"AL","alaska":"AK","arizona":"AZ","arkansas":"AR","california":"CA","colorado":"CO",
    "connecticut":"CT","delaware":"DE","florida":"FL","georgia":"GA","hawaii":"HI","idaho":"ID",
    "illinois":"IL","indiana":"IN","iowa":"IA","kansas":"KS","kentucky":"KY","louisiana":"LA",
    "maine":"ME","maryland":"MD","massachusetts":"MA","michigan":"MI","minnesota":"MN","mississippi":"MS",
    "missouri":"MO","montana":"MT","nebraska":"NE","nevada":"NV","new hampshire":"NH","new jersey":"NJ",
    "new mexico":"NM","new york":"NY","north carolina":"NC","north dakota":"ND","ohio":"OH","oklahoma":"OK",
    "oregon":"OR","pennsylvania":"PA","rhode island":"RI","south carolina":"SC","south dakota":"SD",
    "tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT","virginia":"VA","washington":"WA",
    "west virginia":"WV","wisconsin":"WI","wyoming":"WY","district of columbia":"DC","d.c.":"DC","dc":"DC",
    "ontario":"ON","quebec":"QC","alberta":"AB","british columbia":"BC","manitoba":"MB","saskatchewan":"SK",
    "nova scotia":"NS","new brunswick":"NB","newfoundland and labrador":"NL","prince edward island":"PE"
}
CANADA_PROVINCES = {"ontario","quebec","alberta","british columbia","manitoba","saskatchewan","nova scotia","new brunswick","newfoundland and labrador","prince edward island"}
VENUE_WORDS = ("stadium","arena","field","center","centre","park","dome","forum","coliseum","pavilion","gymnasium","ballpark")

def infer_country_from_state(state, country=None):
    s = clean(state)
    c = clean(country)
    if c:
        cl = c.lower()
        if 'canada' in cl:
            return 'Canada'
        if cl in {'usa','us','united states','united states of america'}:
            return 'USA'
    if s and s.lower() in CANADA_PROVINCES:
        return 'Canada'
    return c or 'USA'

def normalize_state_value(state):
    s = clean(state)
    if not s:
        return s
    sl = s.lower().replace('.', '')
    for k, v in STATE_ABBR.items():
        if sl == k.replace('.', ''):
            return v
    if len(s) == 2:
        return s.upper()
    if sl == 'dc':
        return 'DC'
    return s

def normalize_team_text_fields(league, team, venue, city, state, country):
    venue = clean(venue)
    city = clean(city)
    state = clean(state)
    country = infer_country_from_state(state, country)

    if venue and not city and state:
        parts = [p.strip() for p in venue.split(',')]
        if len(parts) >= 3:
            maybe_state = clean(parts[-1])
            maybe_city = clean(parts[-2])
            base = clean(', '.join(parts[:-2]))
            if maybe_state and maybe_city and base:
                venue, city, state = base, maybe_city, maybe_state

    if venue and city and state:
        tail = f'{city}, {state}'
        if venue.endswith(tail):
            venue = clean(venue[:-len(tail)].rstrip(', '))
        elif venue.endswith(f'{city} {state}'):
            venue = clean(venue[:-(len(city)+1+len(state))].rstrip(', '))
        elif venue.endswith(city) and any(w in venue.lower() for w in VENUE_WORDS):
            maybe = clean(venue[:-len(city)].rstrip(', '))
            if maybe and any(w in maybe.lower() for w in VENUE_WORDS):
                venue = maybe

    state = normalize_state_value(state)
    country = infer_country_from_state(state, country)
    return venue, city, state, country

def validate_master_integrity(df):
    problems = []
    for idx, row in df.iterrows():
        city = clean(row.get("city"))
        venue = clean(row.get("venue"))
        state = clean(row.get("state"))
        country = infer_country_from_state(state, row.get("country"))

        CITY_WHITELIST = {
            "orchard park", "university park", "college park", "winter park", "menlo park",
            "overland park", "hyde park", "park city", "cedar park", "oak park", "park ridge",
            "smithfield", "fairfield", "bakersfield", "springfield", "bloomfield", "greenfield",
            "deerfield", "mansfield", "sheffield", "chesterfield", "plainfield", "wakefield",
            "westfield", "northfield", "southfield", "brookfield", "campbellfield", "garfield",
        }

        if city and any(w in city.lower() for w in VENUE_WORDS) and city.lower() not in CITY_WHITELIST:
            problems.append((idx, row.get("league"), row.get("team"), "city_contains_venue_text", venue, city, state, country))
        if venue and state and re.search(r",?\s*" + re.escape(state) + r"$", venue):
            problems.append((idx, row.get("league"), row.get("team"), "venue_ends_with_state", venue, city, state, country))
        if state and state.upper() in {"ON", "QC", "AB", "BC", "MB", "SK", "NS", "NB", "NL", "PE"} and country != "Canada":
            problems.append((idx, row.get("league"), row.get("team"), "canadian_state_non_canada", venue, city, state, country))

    if problems:
        print("[VALIDATION] Potential integrity issues found:")
        for p in problems[:50]:
            print(p)
        raise RuntimeError(f"Integrity validation failed with {len(problems)} issue(s).")
    return df

def fetch_soup(url, label=""):
    print(f"[FETCH] {label} -> {url}")
    time.sleep(0.7)
    r = requests.get(url, headers=HEADERS, timeout=20)
    print(f"[FETCH] {label} status {r.status_code}")
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def is_planned_or_unknown_venue(name):
    if not isinstance(name, str) or not name:
        return False
    n = name.lower()
    return (
        any(kw in n for kw in ["future", "planned", "on-campus", "new aloha", "future south florida"])
        or n.startswith("new ")
    )


def is_womens_team_or_venue(team, venue):
    s = (str(team) + " " + str(venue)).lower()
    return any(w in s for w in [" women", "women's", "wbb", " (women", "women's"])


def get_elevation(lat, lon):
    if lat is None or lon is None:
        return None
    try:
        time.sleep(0.3)
        r = requests.get(ELEVATION_API, params={"locations": f"{lat},{lon}"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        elev_meters = data["results"][0]["elevation"]
        elev_feet = elev_meters * 3.28084 if elev_meters is not None else None
        return round(elev_feet, 2) if elev_feet is not None else None
    except Exception as e:
        print(f"[ELEV-ERROR] ({lat}, {lon}): {e}")
        return None


def get_geo(location_str, venue_name=None):
    if not location_str:
        return {"lat": None, "lon": None, "elevation": None, "geocode_status": "fail"}

    if location_str in CACHE:
        c = CACHE[location_str]
        return {
            "lat": c.get("lat"),
            "lon": c.get("lon"),
            "elevation": c.get("elevation"),
            "geocode_status": c.get("geocode_status", "ok"),
        }

    if venue_name and is_planned_or_unknown_venue(venue_name):
        print(f"[GEO-SKIP-PLANNED] {location_str}")
        res = {"lat": None, "lon": None, "elevation": None, "geocode_status": "planned_or_unknown"}
        CACHE[location_str] = res
        save_cache()
        return res

    def _do(q):
        print(f"[GEO] Geocoding: {q}")
        time.sleep(1.0)
        return geolocator.geocode(q, timeout=20)

    try:
        g = _do(location_str)
        if not g:
            print(f"[GEO-FAIL] {location_str}")
            res = {"lat": None, "lon": None, "elevation": None, "geocode_status": "fail"}
            CACHE[location_str] = res
            save_cache()
            return res

        lat, lon = g.latitude, g.longitude
        elev = get_elevation(lat, lon)
        res = {"lat": lat, "lon": lon, "elevation": elev, "geocode_status": "ok"}
        CACHE[location_str] = res
        save_cache()
        print(f"[GEO-OK] {location_str} -> ({lat}, {lon}, {elev})")
        return res
    except Exception as e:
        print(f"[GEO-ERROR] {location_str}: {e}")
        res = {"lat": None, "lon": None, "elevation": None, "geocode_status": "error"}
        CACHE[location_str] = res
        save_cache()
        return res


def strip_trailing_city_state(venue, city, state):
    if not isinstance(venue, str) or not isinstance(city, str) or not isinstance(state, str):
        return venue if isinstance(venue, str) else None
    if not venue.strip() or not city.strip() or not state.strip():
        return venue

    original = venue
    v = re.sub(r"\s+,", ",", venue.strip())
    c = city.strip()
    s = state.strip()

    tail1 = f"{c}, {s}"
    tail2 = f"{c} , {s}"

    for tail in (tail1, tail2):
        if v.endswith(tail):
            cut = len(v) - len(tail)
            base = v[:cut].rstrip(", ").strip()
            if base:
                print(f"[STRIP-NFL] '{original}' -> '{base}' (city='{c}', state='{s}')")
                return base

    return v


def enrich_geo(df):
    # ---- NUCLEAR NaN DEFENSE: replace ALL NaN/None in string columns ----
    # pandas stores missing cells as float NaN. Every string operation
    # (.strip, re.sub, etc.) explodes on float. Kill them ALL here, once.
    str_cols = ['venue', 'city', 'state', 'country', 'team', 'league']
    for _col in str_cols:
        if _col in df.columns:
            df[_col] = df[_col].where(df[_col].apply(lambda x: isinstance(x, str)), other=None)

    df = df.copy()
    for col in ["lat", "lon", "elevation", "geocode_status"]:
        if col not in df.columns:
            df[col] = None

    geo_ok = geo_fail = geo_planned = geo_error = geo_override = 0

    # Build a team-only index for NFL/NBA. Wikipedia infoboxes often mangle the
    # venue field (e.g. "Soldier Field Chicago, Illinois"), so key lookups on
    # league|team|venue can fail. Since every NFL/NBA team has a hard override,
    # match by league|team only.
    # Also store the canonical venue name from the key so we can fix venue=NULL rows.
    nfl_nba_by_team = {}
    for _k, _v in GEO_OVERRIDES.items():
        _parts = _k.split("|", 2)
        if len(_parts) == 3 and _parts[0] in ("NFL", "NBA"):
            nfl_nba_by_team[f"{_parts[0]}|{_parts[1]}"] = {**_v, "_venue_name": _parts[2]}

    df = df.copy()
    for idx in df.index:
        row = df.loc[idx]
        league = row["league"]
        team = row["team"]
        venue = row["venue"]
        city = row["city"] if "city" in row.index else None
        state = row["state"] if "state" in row.index else None
        country = row["country"] if "country" in row.index else None

        # --- NFL/NBA team override (team-key lookup; no second m→ft conversion) ---
        if league in ("NFL", "NBA"):
            team_key = f"{league}|{team}"
            if team_key in nfl_nba_by_team:
                used = nfl_nba_by_team[team_key]
                lat  = used["lat"]
                lon  = used["lon"]
                elev = used.get("elevation")
                # Canonical venue name stored in the override key
                canonical_venue = used.get("_venue_name")

                if elev is None and lat is not None and lon is not None:
                    elev = get_elevation(lat, lon)

                venue = venue if isinstance(venue, str) else None
                city  = city  if isinstance(city,  str) else None
                state = state if isinstance(state, str) else None

                # FIX: always write canonical venue from GEO_OVERRIDES key
                if canonical_venue:
                    df.at[idx, "venue"] = canonical_venue
                elif venue:
                    clean_v = strip_trailing_city_state(venue, city, state)
                    df.at[idx, "venue"] = clean_v

                # FIX: if city field contains the venue name as a prefix, strip it
                # e.g. "Soldier Field Chicago" -> "Chicago"
                final_venue = df.at[idx, "venue"]
                if isinstance(city, str) and isinstance(final_venue, str):
                    if city.startswith(final_venue):
                        city = city[len(final_venue):].lstrip(", ").strip()
                        df.at[idx, "city"] = city
                    elif city.lower().startswith(final_venue.lower()):
                        city = city[len(final_venue):].lstrip(", ").strip()
                        df.at[idx, "city"] = city

                df.at[idx, "lat"] = lat
                df.at[idx, "lon"] = lon
                df.at[idx, "elevation"] = elev
                df.at[idx, "geocode_status"] = "override"
                geo_override += 1
                print(f"[GEO-OVERRIDE] {league}|{team}|{df.at[idx, 'venue']} -> ({lat}, {lon}, {elev})")
                continue

        # --- Generic override for any other key in GEO_OVERRIDES ---
        key = f"{league}|{team}|{venue}"
        if key in GEO_OVERRIDES:
            used = GEO_OVERRIDES[key]
            lat  = used["lat"]
            lon  = used["lon"]
            # FIX (root-cause): elevation is ALREADY in feet from the one-time
            # conversion loop at module level. Do NOT multiply by 3.28084 again;
            # the original code did so here, producing ~10.76x inflated values
            # for every NCAA FBS, NCAA D1 MBB, NHL, and MLB override entry.
            elev = used.get("elevation")

            clean_venue, clean_city, clean_state, clean_country = normalize_team_text_fields(league, team, venue, city, state, country)
            df.at[idx, "venue"] = clean_venue
            df.at[idx, "city"] = clean_city
            df.at[idx, "state"] = clean_state
            df.at[idx, "country"] = clean_country
            df.at[idx, "lat"] = lat
            df.at[idx, "lon"] = lon
            df.at[idx, "elevation"] = elev
            df.at[idx, "geocode_status"] = "override"
            geo_override += 1
            print(f"[GEO-OVERRIDE] {key} -> ({lat}, {lon}, {elev})")
            continue

        # --- Planned/unknown venues ---
        if is_planned_or_unknown_venue(venue):
            df.at[idx, "lat"] = None
            df.at[idx, "lon"] = None
            df.at[idx, "elevation"] = None
            df.at[idx, "geocode_status"] = "planned_or_unknown"
            geo_planned += 1
            print(f"[GEO-PLANNED] {league} {team} {venue}")
            continue

        # --- Fallback geocoding ---
        venue, city, state, country = normalize_team_text_fields(league, team, venue, city, state, country)
        country = infer_country_from_state(state, country)
        df.at[idx, "venue"] = venue
        df.at[idx, "city"] = city
        df.at[idx, "state"] = state
        df.at[idx, "country"] = country
        parts = []
        if venue:
            parts.append(venue)
        if city:
            parts.append(city)
        if state:
            parts.append(state)
        if country:
            parts.append(country)
        loc_str = ", ".join(parts) if parts else None

        geo = get_geo(loc_str, venue_name=venue)
        status = geo["geocode_status"]
        if status == "ok":
            geo_ok += 1
        elif status == "fail":
            geo_fail += 1
        elif status == "planned_or_unknown":
            geo_planned += 1
        else:
            geo_error += 1

        df.at[idx, "lat"] = geo["lat"]
        df.at[idx, "lon"] = geo["lon"]
        df.at[idx, "elevation"] = geo["elevation"]
        df.at[idx, "geocode_status"] = status

    print(f"[GEO-SUMMARY] ok={geo_ok}, fail={geo_fail}, planned={geo_planned}, error={geo_error}, override={geo_override}")
    # SAFETY NET: Any NFL/NBA team still with venue=None after main override pass
    for idx2 in df.index:
        if df.at[idx2, "league"] in ("NFL", "NBA"):
            if not isinstance(df.at[idx2, "venue"], str) or not df.at[idx2, "venue"]:
                team_key2 = f"{df.at[idx2, 'league']}|{df.at[idx2, 'team']}"
                if team_key2 in nfl_nba_by_team:
                    cv = nfl_nba_by_team[team_key2].get("_venue_name")
                    if cv:
                        df.at[idx2, "venue"] = cv
                        print(f"[SAFETY-NET] Set venue for {team_key2} -> {cv}")
                    raw_city = df.at[idx2, "city"]
                    if isinstance(raw_city, str) and isinstance(cv, str) and raw_city.startswith(cv):
                        df.at[idx2, "city"] = raw_city[len(cv):].lstrip(", ").strip()
                        print(f"[SAFETY-NET] Fixed city for {team_key2} -> {df.at[idx2, 'city']}")

    return df


def assert_no_unexpected_fails(df):
    # NaN guard — float NaN in venue/city/state columns crashes .apply() string ops
    df = df.copy()
    for _c in ['venue', 'city', 'state', 'team', 'league']:
        if _c in df.columns:
            df[_c] = df[_c].where(df[_c].apply(lambda x: isinstance(x, str)), other=None)
    bad = df[
        (df["geocode_status"] == "fail")
        & df["city"].notna()
        & df["state"].notna()
        & (~df["venue"].apply(is_planned_or_unknown_venue))
    ]
    if not bad.empty:
        print("[HARD-FAIL] Unresolved venues remain:")
        print(bad[["league", "team", "venue", "city", "state"]].to_string())
        raise RuntimeError("Unresolved geocodes remain; add to GEO_OVERRIDES or fix parsing.")
    return df


# =========================
# INFOBOX SCRAPING
# =========================

def parse_venue_and_location_from_text(venue_text):
    if not isinstance(venue_text, str) or not venue_text.strip():
        return None, None, None
    txt = venue_text.strip()
    m = re.search(r"\(([^()]+)\)", txt)
    if m:
        inside = clean(m.group(1))
        parts = [p.strip() for p in inside.split(",")]
        city = parts[0] if parts else None
        state = parts[1] if len(parts) > 1 else None
        v_clean = clean(re.sub(r"\([^()]*\)", "", txt))
        return v_clean, city, state
    parts = [p.strip() for p in txt.split(",")]
    if len(parts) >= 2:
        city = parts[-2]
        state = parts[-1]
        venue_candidate = ", ".join(parts[:-2]).strip()
        if not venue_candidate:
            venue_candidate = txt
        return venue_candidate, city, state
    return txt, None, None


def scrape_team_infobox(team, league):
    url = f"https://en.wikipedia.org/wiki/{team.replace(' ', '_')}"
    label = f"{league}:{team}"
    print(f"[INFOBOX] {label} -> {url}")
    soup = fetch_soup(url, label)

    infobox = soup.find("table", {"class": "infobox"})
    if not infobox:
        print(f"[INFOBOX-NOBOX] {label}")
        return None

    venue_raw = None
    location_raw = None

    for row in infobox.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue
        key = th.get_text(strip=True).lower()
        value_text = clean(td.get_text(" ", strip=True))
        if any(k in key for k in ["arena", "stadium", "ballpark", "home arena", "home stadium", "ground", "home ground", "venue", "home field", "home venue"]):
            if venue_raw is None:
                venue_raw = value_text
        if "location" in key and location_raw is None:
            location_raw = value_text

    city = state = None
    country = "USA"
    venue = venue_raw

    if location_raw:
        parts = [p.strip() for p in location_raw.split(",")]
        if len(parts) == 1:
            city = parts[0]
        elif len(parts) == 2:
            city, state = parts
        elif len(parts) >= 3:
            city = parts[0]
            state = parts[1]
            country = parts[-1]

    if venue_raw and (not venue or (isinstance(city, str) and any(vw in city.lower() for vw in VENUE_WORDS))):
        parsed_venue, parsed_city, parsed_state = parse_venue_and_location_from_text(venue_raw)
        if parsed_venue and not venue:
            venue = parsed_venue
        if parsed_city and (not city or any(vw in str(city).lower() for vw in VENUE_WORDS)):
            city = parsed_city
        if parsed_state and not state:
            state = parsed_state
    elif not location_raw:
        venue, city, state = parse_venue_and_location_from_text(venue_raw)

    if league in ("NFL", "NBA"):
        venue = strip_trailing_city_state(venue, city, state)

    venue, city, state, country = normalize_team_text_fields(league, team, venue, city, state, country)
    print(f"[INFOBOX-OK] {label} -> venue={venue}, city={city}, state={state}")
    return {
        "league": league,
        "team": team,
        "venue": venue,
        "city": city,
        "state": state,
        "country": country,
        "orientation": None,
    }


# =========================
# LEAGUE LOADERS
# =========================

NFL_TEAMS = [
    "Arizona Cardinals", "Atlanta Falcons", "Baltimore Ravens", "Buffalo Bills",
    "Carolina Panthers", "Chicago Bears", "Cincinnati Bengals", "Cleveland Browns",
    "Dallas Cowboys", "Denver Broncos", "Detroit Lions", "Green Bay Packers",
    "Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars", "Kansas City Chiefs",
    "Las Vegas Raiders", "Los Angeles Chargers", "Los Angeles Rams", "Miami Dolphins",
    "Minnesota Vikings", "New England Patriots", "New Orleans Saints", "New York Giants",
    "New York Jets", "Philadelphia Eagles", "Pittsburgh Steelers", "San Francisco 49ers",
    "Seattle Seahawks", "Tampa Bay Buccaneers", "Tennessee Titans", "Washington Commanders"
]

NBA_TEAMS = [
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
    "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
    "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
    "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
    "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
    "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors",
    "Utah Jazz", "Washington Wizards"
]


def load_from_infobox(team_list, league):
    rows = []
    fails = []
    print(f"[LEAGUE] {league} starting...")
    for t in team_list:
        row = scrape_team_infobox(t, league)
        if row:
            rows.append(row)
        else:
            fails.append((league, t))
    df = pd.DataFrame(rows)
    print(f"[LEAGUE] {league} done. Success={len(df)}, Fail={len(fails)}")
    return df, fails


def load_nfl():
    return load_from_infobox(NFL_TEAMS, "NFL")


def load_nba():
    return load_from_infobox(NBA_TEAMS, "NBA")


NHL_TEAM_ARENA = {
    "Anaheim Ducks": ("Honda Center", "Anaheim", "California", "USA"),
    "Arizona Coyotes": ("Mullett Arena", "Tempe", "Arizona", "USA"),
    "Boston Bruins": ("TD Garden", "Boston", "Massachusetts", "USA"),
    "Buffalo Sabres": ("KeyBank Center", "Buffalo", "New York", "USA"),
    "Calgary Flames": ("Scotiabank Saddledome", "Calgary", "Alberta", "Canada"),
    "Carolina Hurricanes": ("PNC Arena", "Raleigh", "North Carolina", "USA"),
    "Chicago Blackhawks": ("United Center", "Chicago", "Illinois", "USA"),
    "Colorado Avalanche": ("Ball Arena", "Denver", "Colorado", "USA"),
    "Columbus Blue Jackets": ("Nationwide Arena", "Columbus", "Ohio", "USA"),
    "Dallas Stars": ("American Airlines Center", "Dallas", "Texas", "USA"),
    "Detroit Red Wings": ("Little Caesars Arena", "Detroit", "Michigan", "USA"),
    "Edmonton Oilers": ("Rogers Place", "Edmonton", "Alberta", "Canada"),
    "Florida Panthers": ("Amerant Bank Arena", "Sunrise", "Florida", "USA"),
    "Los Angeles Kings": ("Crypto.com Arena", "Los Angeles", "California", "USA"),
    "Minnesota Wild": ("Xcel Energy Center", "St. Paul", "Minnesota", "USA"),
    "Montreal Canadiens": ("Bell Centre", "Montreal", "Quebec", "Canada"),
    "Nashville Predators": ("Bridgestone Arena", "Nashville", "Tennessee", "USA"),
    "New Jersey Devils": ("Prudential Center", "Newark", "New Jersey", "USA"),
    "New York Islanders": ("UBS Arena", "Elmont", "New York", "USA"),
    "New York Rangers": ("Madison Square Garden", "New York", "New York", "USA"),
    "Ottawa Senators": ("Canadian Tire Centre", "Ottawa", "Ontario", "Canada"),
    "Philadelphia Flyers": ("Wells Fargo Center", "Philadelphia", "Pennsylvania", "USA"),
    "Pittsburgh Penguins": ("PPG Paints Arena", "Pittsburgh", "Pennsylvania", "USA"),
    "San Jose Sharks": ("SAP Center", "San Jose", "California", "USA"),
    "Seattle Kraken": ("Climate Pledge Arena", "Seattle", "Washington", "USA"),
    "St. Louis Blues": ("Enterprise Center", "St. Louis", "Missouri", "USA"),
    "Tampa Bay Lightning": ("Amalie Arena", "Tampa", "Florida", "USA"),
    "Toronto Maple Leafs": ("Scotiabank Arena", "Toronto", "Ontario", "Canada"),
    "Vancouver Canucks": ("Rogers Arena", "Vancouver", "British Columbia", "Canada"),
    "Vegas Golden Knights": ("T-Mobile Arena", "Paradise", "Nevada", "USA"),
    "Washington Capitals": ("Capital One Arena", "Washington", "D.C.", "USA"),
    "Winnipeg Jets": ("Canada Life Centre", "Winnipeg", "Manitoba", "Canada"),
    "Utah Mammoth": ("Delta Center", "Salt Lake City", "Utah", "USA"),
}


def load_nhl():
    print("[LEAGUE] NHL starting (hard mapping)...")
    rows = []
    for team, (venue, city, state, country) in NHL_TEAM_ARENA.items():
        rows.append({
            "league": "NHL",
            "team": team,
            "venue": venue,
            "city": city,
            "state": state,
            "country": country,
            "orientation": None,
        })
    df = pd.DataFrame(rows)
    print(f"[LEAGUE] NHL done. Rows={len(df)}")
    return df, []


MLB_TEAM_BALLPARK_CITY_STATE = {
    "Arizona Diamondbacks": ("Chase Field", "Phoenix", "Arizona"),
    "Atlanta Braves": ("Truist Park", "Cumberland", "Georgia"),
    "Baltimore Orioles": ("Oriole Park at Camden Yards", "Baltimore", "Maryland"),
    "Boston Red Sox": ("Fenway Park", "Boston", "Massachusetts"),
    "Chicago Cubs": ("Wrigley Field", "Chicago", "Illinois"),
    "Chicago White Sox": ("Guaranteed Rate Field", "Chicago", "Illinois"),
    "Cincinnati Reds": ("Great American Ball Park", "Cincinnati", "Ohio"),
    "Cleveland Guardians": ("Progressive Field", "Cleveland", "Ohio"),
    "Colorado Rockies": ("Coors Field", "Denver", "Colorado"),
    "Detroit Tigers": ("Comerica Park", "Detroit", "Michigan"),
    "Houston Astros": ("Minute Maid Park", "Houston", "Texas"),
    "Kansas City Royals": ("Kauffman Stadium", "Kansas City", "Missouri"),
    "Los Angeles Angels": ("Angel Stadium", "Anaheim", "California"),
    "Los Angeles Dodgers": ("Dodger Stadium", "Los Angeles", "California"),
    "Miami Marlins": ("loanDepot park", "Miami", "Florida"),
    "Milwaukee Brewers": ("American Family Field", "Milwaukee", "Wisconsin"),
    "Minnesota Twins": ("Target Field", "Minneapolis", "Minnesota"),
    "New York Mets": ("Citi Field", "Queens", "New York"),
    "New York Yankees": ("Yankee Stadium", "Bronx", "New York"),
    "Oakland Athletics": ("Sutter Health Park", "West Sacramento", "California"),
    "Philadelphia Phillies": ("Citizens Bank Park", "Philadelphia", "Pennsylvania"),
    "Pittsburgh Pirates": ("PNC Park", "Pittsburgh", "Pennsylvania"),
    "San Diego Padres": ("Petco Park", "San Diego", "California"),
    "San Francisco Giants": ("Oracle Park", "San Francisco", "California"),
    "Seattle Mariners": ("T-Mobile Park", "Seattle", "Washington"),
    "St. Louis Cardinals": ("Busch Stadium", "St. Louis", "Missouri"),
    "Tampa Bay Rays": ("Tropicana Field", "St. Petersburg", "Florida"),
    "Texas Rangers": ("Globe Life Field", "Arlington", "Texas"),
    "Toronto Blue Jays": ("Rogers Centre", "Toronto", "Ontario"),
    "Washington Nationals": ("Nationals Park", "Washington", "D.C."),
}


def parse_mlb_orientation(url, league_tag):
    print(f"[MLB-ORIENT] {league_tag} from {url}")
    soup = fetch_soup(url, f"MLB-ORIENT-{league_tag}")
    tables = soup.find_all("table")
    mapping = {}
    for table in tables:
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            stadium = clean(tds[0].get_text(" ", strip=True))
            orientation = clean(tds[2].get_text(" ", strip=True))
            if stadium and orientation:
                mapping[stadium.lower()] = orientation
    print(f"[MLB-ORIENT] {league_tag} entries={len(mapping)}")
    return mapping


def load_mlb():
    print("[LEAGUE] MLB starting...")
    rows = []
    for team, (venue, city, state) in MLB_TEAM_BALLPARK_CITY_STATE.items():
        rows.append({
            "league": "MLB",
            "team": team,
            "venue": venue,
            "city": city,
            "state": state,
            "country": "USA" if state != "Ontario" else "Canada",
            "orientation": None,
        })
    df = pd.DataFrame(rows)

    al_map = parse_mlb_orientation(MLB_ORIENT_AL, "AL")
    nl_map = parse_mlb_orientation(MLB_ORIENT_NL, "NL")
    all_map = {**al_map, **nl_map}

    def match_orientation(v):
        if not v:
            return None
        key = v.lower()
        if key in all_map:
            return all_map[key]
        key2 = re.sub(r"\b(park|field|stadium|ballpark)\b", "", key).strip()
        for name, o in all_map.items():
            base = re.sub(r"\b(park|field|stadium|ballpark)\b", "", name).strip()
            if base == key2:
                return o
        return None

    df["orientation"] = df["venue"].apply(match_orientation)
    print("[LEAGUE] MLB done.")
    return df, []


def load_ncaa_fbs():
    print("[LEAGUE] NCAA FBS starting...")
    soup = fetch_soup(WIKI_FBS_STADIUMS, "NCAA-FBS")
    tables = soup.find_all("table", {"class": "wikitable"})
    rows = []
    for table in tables:
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if not tds:
                continue
            data = [clean(td.get_text(" ", strip=True)) for td in tds]
            if len(data) < len(headers):
                data += [None] * (len(headers) - len(data))
            row_map = dict(zip(headers, data))
            team = row_map.get("team") or row_map.get("school") or row_map.get("university")
            venue = row_map.get("stadium") or row_map.get("name")
            city = row_map.get("city")
            state = row_map.get("state") or row_map.get("location")
            if not team or not venue:
                continue
            rows.append({
                "league": "NCAA FBS",
                "team": team,
                "venue": venue,
                "city": city,
                "state": state,
                "country": "USA",
                "orientation": None,
            })
    df = pd.DataFrame(rows)
    print(f"[LEAGUE] NCAA FBS done. Rows={len(df)}")
    return df, []


def load_ncaa_basketball():
    print("[LEAGUE] NCAA D1 MBB starting...")
    soup = fetch_soup(WIKI_NCAA_BBALL_ARENAS, "NCAA-D1-MBB")
    tables = soup.find_all("table", {"class": "wikitable"})
    rows = []
    for table in tables:
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if not tds:
                continue
            data = [clean(td.get_text(" ", strip=True)) for td in tds]
            if len(data) < len(headers):
                data += [None] * (len(headers) - len(data))
            row_map = dict(zip(headers, data))
            team = row_map.get("team") or row_map.get("school") or row_map.get("university")
            venue = row_map.get("arena") or row_map.get("name")
            city = row_map.get("city")
            state = row_map.get("state") or row_map.get("location")
            if not team or not venue:
                continue
            rows.append({
                "league": "NCAA D1 MBB",
                "team": team,
                "venue": venue,
                "city": city,
                "state": state,
                "country": "USA",
                "orientation": None,
            })
    df = pd.DataFrame(rows)
    print(f"[LEAGUE] NCAA D1 MBB done. Rows={len(df)}")
    return df, []


def run():
    all_frames = []
    all_failures = []

    nfl_df, nfl_fail = load_nfl()
    all_frames.append(nfl_df)
    all_failures.extend(nfl_fail)

    nba_df, nba_fail = load_nba()
    all_frames.append(nba_df)
    all_failures.extend(nba_fail)

    nhl_df, nhl_fail = load_nhl()
    all_frames.append(nhl_df)
    all_failures.extend(nhl_fail)

    mlb_df, mlb_fail = load_mlb()
    all_frames.append(mlb_df)
    all_failures.extend(mlb_fail)

    fbs_df, fbs_fail = load_ncaa_fbs()
    all_frames.append(fbs_df)
    all_failures.extend(fbs_fail)

    mbb_df, mbb_fail = load_ncaa_basketball()
    all_frames.append(mbb_df)
    all_failures.extend(mbb_fail)

    master = pd.concat(all_frames, ignore_index=True)

    # NUCLEAR NaN DEFENSE at concat-time — kills float NaN in all string cols
    # before ANY downstream function (normalize, enrich_geo, etc.) touches them.
    _str_cols = ['venue', 'city', 'state', 'country', 'team', 'league']
    for _col in _str_cols:
        if _col in master.columns:
            master[_col] = master[_col].where(
                master[_col].apply(lambda x: isinstance(x, str)), other=None
            )

    # FIX BUG #4: Disambiguate Miami (OH) vs Miami (FL) in NCAA FBS
    # Both scrape as team="Miami" — distinguish by state
    def _disambiguate_miami(row):
        if row.get("league") == "NCAA FBS" and row.get("team") == "Miami":
            state = row.get("state")
            if state == "OH":
                return "Miami (OH)"
            elif state == "FL":
                return "Miami (FL)"
        return row.get("team")
    master["team"] = master.apply(_disambiguate_miami, axis=1)

    for _idx, _row in master.iterrows():
        _v, _c, _s, _ctry = normalize_team_text_fields(_row.get("league"), _row.get("team"), _row.get("venue"), _row.get("city"), _row.get("state"), _row.get("country"))
        master.at[_idx, "venue"] = _v
        master.at[_idx, "city"] = _c
        master.at[_idx, "state"] = _s
        master.at[_idx, "country"] = _ctry

    # -----------------------------------------------------------------------
    # FIX: NFL venue=None recovery pass.
    # Wikipedia infobox for ~20 NFL teams embeds the venue name inside the
    # city field (e.g. city="AT&T Stadium Arlington", venue=None).
    # Pull the correct venue name from GEO_OVERRIDES using the team key.
    # -----------------------------------------------------------------------
    for _idx, _row in master.iterrows():
        if _row.get("league") == "NFL" and not _row.get("venue") and _row.get("city"):
            # Search GEO_OVERRIDES for any key matching "NFL|<team>|*"
            _team = _row.get("team", "")
            _found_venue = None
            for _key in GEO_OVERRIDES:
                _parts = _key.split("|")
                if len(_parts) == 3 and _parts[0] == "NFL" and _parts[1] == _team:
                    _found_venue = _parts[2]
                    break
            if _found_venue:
                # Also fix city: remove the venue name prefix that got baked in
                _raw_city = master.at[_idx, "city"] or ""
                if _raw_city.lower().startswith(_found_venue.lower()):
                    _clean_city = _raw_city[len(_found_venue):].strip().lstrip(",").strip()
                    if _clean_city:
                        master.at[_idx, "city"] = _clean_city
                master.at[_idx, "venue"] = _found_venue
                print(f"[NFL-VENUE-FIX] {_team} -> venue='{_found_venue}', city='{master.at[_idx, 'city']}'")

    print(f"[MASTER] Combined rows before filters and geo: {len(master)}")

    mask_w = master.apply(lambda r: is_womens_team_or_venue(r["team"], r["venue"]), axis=1)
    before = len(master)
    master = master[~mask_w].reset_index(drop=True)
    print(f"[MASTER] Dropped {before - len(master)} women's-team rows")

    master = enrich_geo(master)
    master["country"] = master.apply(lambda r: infer_country_from_state(r.get("state"), r.get("country")), axis=1)
    # NOTE: Second normalize loop intentionally removed. The geo enrichment
    # and GEO_OVERRIDES already produce correct venue/city/state values.
    # Re-running normalize_team_text_fields post-geo would overwrite
    # override-corrected values with stale scraped data.
    master = validate_master_integrity(master)
    # DROP future/placeholder venues — no valid geo, pollute downstream joins
    master = master[master["geocode_status"] != "planned_or_unknown"].reset_index(drop=True)
    master = assert_no_unexpected_fails(master)

    # -----------------------------------------------------------------------
    # OUTPUT — CSV, Excel, and JSON
    # -----------------------------------------------------------------------
    csv_path  = "US_SPORTS_VENUES_MASTER.csv"
    xlsx_path = "US_SPORTS_VENUES_MASTER.xlsx"
    json_path = "US_SPORTS_VENUES_MASTER.json"

    master.to_csv(csv_path, index=False)
    print(f"[OUTPUT] CSV  -> {csv_path}")

    try:
        master.to_excel(xlsx_path, index=False, engine="openpyxl")
        print(f"[OUTPUT] XLSX -> {xlsx_path}")
    except ImportError:
        print("[OUTPUT] WARNING: openpyxl not installed; skipping Excel output. "
              "Run: pip install openpyxl")

    master.to_json(json_path, orient="records", indent=2, force_ascii=False)
    print(f"[OUTPUT] JSON -> {json_path}")

    print(f"[MASTER] FINAL ROWS: {len(master)}")

    if all_failures:
        pd.DataFrame(all_failures, columns=["league", "team"]).to_csv(
            "SCRAPE_FAILURES.csv", index=False
        )


if __name__ == "__main__":
    run()
