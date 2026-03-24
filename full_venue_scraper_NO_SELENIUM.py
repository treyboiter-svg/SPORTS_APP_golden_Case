# full_venue_scraper_NO_SELENIUM.py

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import json
import osmnx as ox
import numpy as np

# ====== API KEYS ======
OPENCAGE_KEY = "589b88f9d5b141989f396c5584530a93"
GOOGLE_ELEV_KEY = "1084e87f28a57d118642798f37fd7b16"

headers = {
    "User-Agent": "Mozilla/5.0"
}

# ====== HELPERS ======
def get_soup(url):
    r = requests.get(url, headers=headers)
    return BeautifulSoup(r.text, "html.parser")

def geocode(address):
    try:
        url = f"https://api.opencagedata.com/geocode/v1/json?q={address}&key={OPENCAGE_KEY}"
        r = requests.get(url).json()
        if r["results"]:
            return r["results"][0]["geometry"]["lat"], r["results"][0]["geometry"]["lng"]
    except:
        pass
    return None, None

def get_elevation(lat, lon):
    try:
        url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={GOOGLE_ELEV_KEY}"
        r = requests.get(url).json()
        return r["results"][0]["elevation"] * 3.28084
    except:
        return 0

def compute_orientation(lat, lon):
    try:
        gdf = ox.geometries_from_point((lat, lon), tags={"building": "stadium"}, dist=150)
        polys = gdf[gdf.geometry.type == "Polygon"]
        if polys.empty:
            return 0

        poly = max(polys.geometry, key=lambda p: p.area)
        coords = np.array(poly.exterior.coords)

        max_len = 0
        best_angle = 0

        for i in range(len(coords)-1):
            p1, p2 = coords[i], coords[i+1]
            length = np.linalg.norm(np.array(p2) - np.array(p1))

            if length > max_len:
                max_len = length
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                angle = np.degrees(np.arctan2(dx, dy))
                if angle < 0:
                    angle += 360
                best_angle = angle

        return round(best_angle, 1)

    except:
        return 0

# ====== SCRAPERS ======
def scrape_mlb():
    soup = get_soup("https://www.baseball-almanac.com/stadium/stadium1a1.shtml")
    venues = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if cells:
            name = cells[0].get_text(strip=True)
            if name:
                venues.append({"name": name, "sport": "Baseball"})
    return venues

def scrape_wiki(url, sport):
    soup = get_soup(url)
    venues = []
    for table in soup.select("table.wikitable"):
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if cells:
                name = cells[0].get_text(strip=True)
                if name:
                    venues.append({"name": name, "sport": sport})
    return venues

# ====== COLLECT ======
all_venues = []
all_venues += scrape_mlb()
all_venues += scrape_wiki("https://en.wikipedia.org/wiki/List_of_current_National_Football_League_stadiums", "Football")
all_venues += scrape_wiki("https://en.wikipedia.org/wiki/List_of_National_Basketball_Association_arenas", "Basketball")
all_venues += scrape_wiki("https://en.wikipedia.org/wiki/List_of_National_Hockey_League_arenas", "Hockey")
all_venues += scrape_wiki("https://en.wikipedia.org/wiki/List_of_NCAA_Division_I_FBS_football_stadiums", "Football")
all_venues += scrape_wiki("https://en.wikipedia.org/wiki/List_of_NCAA_Division_I_basketball_arenas", "Basketball")

# ====== PROCESS ======
processed = []
seen = set()

for v in all_venues:
    if v["name"] in seen:
        continue
    seen.add(v["name"])

    print(f"Processing: {v['name']}")

    lat, lon = geocode(v["name"])
    if lat is None:
        continue

    elevation = get_elevation(lat, lon)
    orientation = compute_orientation(lat, lon)

    processed.append({
        "name": v["name"],
        "sport": v["sport"],
        "lat": lat,
        "lon": lon,
        "elevation_ft": round(elevation),
        "orientation_deg": orientation
    })

# ====== SAVE ======
df = pd.DataFrame(processed)
df.to_csv("venues_full.csv", index=False)

with open("venues_full.json", "w") as f:
    json.dump({"venues": processed}, f, indent=4)

print("DONE — NO SELENIUM, NO CRASHES")