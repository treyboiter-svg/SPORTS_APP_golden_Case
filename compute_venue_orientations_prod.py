import json
import math
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import requests
from shapely.geometry import Polygon, MultiPolygon

# ---------------------------------------------------------
# Config: paths, behavior, thresholds
# ---------------------------------------------------------

INPUT_JSON = "US_SPORTS_VENUES_MASTER.json"
OUTPUT_JSON = "US_SPORTS_VENUES_MASTER_oriented.json"

# ALWAYS recompute, ignore any previous orientation_* fields
FORCE_RERUN = True

# Overpass endpoints – main + alternative. [web:44]
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

OVERPASS_TIMEOUT = 90          # seconds per HTTP request
OVERPASS_MAX_RETRIES = 5       # per venue, across endpoints
INITIAL_RADIUS_METERS = 300
MAX_RADIUS_METERS = 800
RADIUS_STEP_METERS = 250

BASE_SLEEP_SECONDS = 3.0       # base sleep between venues
RETRY_BASE_SLEEP_SECONDS = 10  # starting backoff on 429/504

# Confidence thresholds
CONF_OK = 0.7
CONF_REVIEW = 0.4

# Hard distance caps (meters) – beyond this we treat as failed
MAX_DISTANCE_ACCEPT = 250.0

# ---------------------------------------------------------
# League/tag config
# ---------------------------------------------------------

LEAGUE_OSM_CONFIG = {
    "NFL": {
        "primary_sports": ["american_football"],
        "secondary_sports": ["football", "soccer"],
    },
    "NCAA FBS": {
        "primary_sports": ["american_football"],
        "secondary_sports": ["football", "soccer"],
    },
    "MLB": {
        "primary_sports": ["baseball"],
        "secondary_sports": [],
    },
    "NHL": {
        "primary_sports": ["ice_hockey"],
        "secondary_sports": ["hockey"],
    },
    "NBA": {
        "primary_sports": ["basketball"],
        "secondary_sports": [],
    },
    "NCAA D1 MBB": {
        "primary_sports": ["basketball"],
        "secondary_sports": [],
    },
}

DEFAULT_OSM_CONFIG = {
    "primary_sports": [],
    "secondary_sports": [],
}

# ---------------------------------------------------------
# Data structures
# ---------------------------------------------------------

@dataclass
class GeometryCandidate:
    geom: Polygon
    tags: Dict[str, Any]
    distance_m: float
    source: str   # 'pitch', 'stadium', 'building', 'other'
    aspect_ratio: float

@dataclass
class OrientationResult:
    orientation_deg: Optional[float]
    orientation_label: Optional[str]
    confidence: float
    status: str               # 'ok', 'review', 'failed'
    source: Optional[str]
    notes: str

# ---------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def bearing_deg(dx: float, dy: float) -> float:
    angle_rad = math.atan2(dx, dy)  # north-based bearing
    angle_deg = math.degrees(angle_rad)
    return (angle_deg + 360.0) % 360.0

def label_from_bearing(angle: float) -> str:
    directions = [
        ("N", 0),
        ("NE", 45),
        ("E", 90),
        ("SE", 135),
        ("S", 180),
        ("SW", 225),
        ("W", 270),
        ("NW", 315),
    ]
    best = min(
        directions,
        key=lambda d: min(abs(angle - d[1]), 360 - abs(angle - d[1]))
    )
    return best[0]

def polygon_aspect_ratio(poly: Polygon) -> float:
    minx, miny, maxx, maxy = poly.bounds
    dx = maxx - minx
    dy = maxy - miny
    if dx == 0 or dy == 0:
        return 1.0
    long_side = max(dx, dy)
    short_side = min(dx, dy)
    return long_side / short_side

def polygon_orientation_pca(poly: Polygon) -> Optional[float]:
    coords = np.array(poly.exterior.coords)
    if coords.shape[0] < 3:
        return None
    lat0 = np.mean(coords[:, 1])
    cos_lat0 = math.cos(math.radians(lat0))
    xs = (coords[:, 0] - coords[:, 0].mean()) * cos_lat0
    ys = coords[:, 1] - coords[:, 1].mean()
    pts = np.column_stack([xs, ys])
    cov = np.cov(pts.T)
    eigvals, eigvecs = np.linalg.eig(cov)
    idx = np.argmax(eigvals)
    vx, vy = eigvecs[:, idx]
    return bearing_deg(vx, vy)

# ---------------------------------------------------------
# Overpass querying with retries / multiple endpoints
# ---------------------------------------------------------

def build_overpass_query(lat: float, lon: float, radius_m: float, league: str) -> str:
    cfg = LEAGUE_OSM_CONFIG.get(league, DEFAULT_OSM_CONFIG)
    primary = cfg.get("primary_sports", [])
    secondary = cfg.get("secondary_sports", [])

    def sport_filters(sports: List[str]) -> str:
        if not sports:
            return ""
        return "".join(f'["sport"="{s}"]' for s in sports)

    primary_filter = sport_filters(primary)
    secondary_filter = sport_filters(secondary)

    q = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  way["leisure"="pitch"]{primary_filter}(around:{radius_m},{lat},{lon});
  relation["leisure"="pitch"]{primary_filter}(around:{radius_m},{lat},{lon});
"""
    if secondary_filter:
        q += f"""
  way["leisure"="pitch"]{secondary_filter}(around:{radius_m},{lat},{lon});
  relation["leisure"="pitch"]{secondary_filter}(around:{radius_m},{lat},{lon});
"""
    q += f"""
  way["leisure"="stadium"](around:{radius_m},{lat},{lon});
  relation["leisure"="stadium"](around:{radius_m},{lat},{lon});
  way["leisure"="sports_centre"](around:{radius_m},{lat},{lon});
  relation["leisure"="sports_centre"](around:{radius_m},{lat},{lon});
  way["building"="stadium"](around:{radius_m},{lat},{lon});
  relation["building"="stadium"](around:{radius_m},{lat},{lon});
  way["building"="arena"](around:{radius_m},{lat},{lon});
  relation["building"="arena"](around:{radius_m},{lat},{lon});
);
out geom;
"""
    return q

def call_overpass_with_retry(query: str) -> Dict[str, Any]:
    last_err = None
    for attempt in range(OVERPASS_MAX_RETRIES):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            print(f"    Overpass attempt {attempt+1}/{OVERPASS_MAX_RETRIES} @ {endpoint}")
            resp = requests.post(
                endpoint,
                data=query.encode("utf-8"),
                timeout=OVERPASS_TIMEOUT,
                headers={"User-Agent": "venue-orientation-batch/1.0 (contact: you@example.com)"},
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            last_err = e
            if status in (429, 504):
                sleep_s = RETRY_BASE_SLEEP_SECONDS * (2 ** attempt)
                print(f"    Overpass HTTP {status}, sleeping {sleep_s:.1f}s before retry")
                time.sleep(sleep_s)
                continue
            else:
                print(f"    Overpass HTTP error {status}: {e} (no retry)")
                raise
        except Exception as e:
            last_err = e
            sleep_s = RETRY_BASE_SLEEP_SECONDS * (2 ** attempt)
            print(f"    Overpass error {e}, sleeping {sleep_s:.1f}s before retry")
            time.sleep(sleep_s)
            continue
    if last_err:
        raise last_err
    raise RuntimeError("Overpass call failed without exception")

# ---------------------------------------------------------
# Geometry extraction / ranking
# ---------------------------------------------------------

def feature_to_polygon(elem: Dict[str, Any]) -> Optional[Polygon]:
    if "geometry" not in elem:
        return None
    coords = elem["geometry"]
    if not coords:
        return None
    pts = [(c["lon"], c["lat"]) for c in coords]
    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda g: g.area)
        if not isinstance(poly, Polygon):
            return None
        return poly
    except Exception:
        return None

def classify_source(tags: Dict[str, Any]) -> str:
    if tags.get("leisure") == "pitch":
        return "pitch"
    if tags.get("leisure") in ("stadium", "sports_centre"):
        return "stadium"
    if tags.get("building") in ("stadium", "arena"):
        return "building"
    return "other"

def geometry_candidates(
    elements: List[Dict[str, Any]],
    venue_lat: float,
    venue_lon: float,
    league: str,
) -> List[GeometryCandidate]:
    cfg = LEAGUE_OSM_CONFIG.get(league, DEFAULT_OSM_CONFIG)
    primary = set(cfg.get("primary_sports", []))
    secondary = set(cfg.get("secondary_sports", []))

    candidates: List[GeometryCandidate] = []
    for elem in elements:
        tags = elem.get("tags", {})
        poly = feature_to_polygon(elem)
        if poly is None or poly.area <= 0:
            continue

        src = classify_source(tags)
        ar = polygon_aspect_ratio(poly)

        sport_tag = tags.get("sport", "")
        sports_list = [s.strip() for s in sport_tag.split(";")] if sport_tag else []

        # Sport-specific AR filtering
        if src == "pitch":
            if "baseball" not in sports_list:
                if ar < 1.15:
                    continue

        cent = poly.centroid
        d = haversine_m(venue_lat, venue_lon, cent.y, cent.x)
        if d > 400.0:
            continue

        candidates.append(
            GeometryCandidate(
                geom=poly,
                tags=tags,
                distance_m=d,
                source=src,
                aspect_ratio=ar,
            )
        )

    def rank_key(c: GeometryCandidate) -> Tuple[float, float]:
        tags = c.tags
        sport_tag = tags.get("sport", "")
        sports_list = [s.strip() for s in sport_tag.split(";")] if sport_tag else []
        sport_match_primary = bool(primary.intersection(sports_list))
        sport_match_secondary = bool(secondary.intersection(sports_list))

        base = 0.0
        if c.source == "pitch":
            base += 3.0
        elif c.source == "stadium":
            base += 2.0
        elif c.source == "building":
            base += 1.5
        else:
            base += 0.5

        if sport_match_primary:
            base += 3.0
        elif sport_match_secondary:
            base += 1.5

        aspect_reward = min(max(c.aspect_ratio - 1.0, 0.0), 3.0)
        distance_penalty = max(0.0, (c.distance_m - 80.0) / 60.0)

        score = base + aspect_reward - distance_penalty
        return (-score, c.distance_m)

    candidates.sort(key=rank_key)
    return candidates

# ---------------------------------------------------------
# Confidence scoring and orientation per venue
# ---------------------------------------------------------

def score_confidence(candidate: GeometryCandidate, angle: float, league: str) -> float:
    cfg = LEAGUE_OSM_CONFIG.get(league, DEFAULT_OSM_CONFIG)
    primary = set(cfg.get("primary_sports", []))
    secondary = set(cfg.get("secondary_sports", []))

    tags = candidate.tags
    sport_tag = tags.get("sport", "")
    sports_list = [s.strip() for s in sport_tag.split(";")] if sport_tag else []
    sport_match_primary = bool(primary.intersection(sports_list))
    sport_match_secondary = bool(secondary.intersection(sports_list))

    score = 0.0

    if candidate.source == "pitch":
        score += 0.5
    elif candidate.source == "stadium":
        score += 0.35
    elif candidate.source == "building":
        score += 0.25
    else:
        score += 0.15

    if sport_match_primary:
        score += 0.4
    elif sport_match_secondary:
        score += 0.25
    elif sport_tag:
        score += 0.1

    d = candidate.distance_m
    if d <= 60:
        score += 0.3
    elif d <= 120:
        score += 0.15
    elif d <= 200:
        score += 0.0
    else:
        score -= 0.4

    ar = candidate.aspect_ratio
    if ar >= 2.2:
        score += 0.25
    elif ar >= 1.6:
        score += 0.15
    elif ar >= 1.3:
        score += 0.05
    else:
        score -= 0.05

    if candidate.source == "building":
        if not sport_tag:
            score -= 0.2
        score = min(score, 0.6)

    return max(0.0, min(1.0, score))

def compute_orientation_for_venue(venue: Dict[str, Any]) -> OrientationResult:
    lat = venue["lat"]
    lon = venue["lon"]
    league = venue.get("league", "")

    radius = INITIAL_RADIUS_METERS
    elements: List[Dict[str, Any]] = []
    last_overpass_error: Optional[str] = None

    while radius <= MAX_RADIUS_METERS:
        print(f"  Querying Overpass at radius {radius}m")
        q = build_overpass_query(lat, lon, radius, league)
        try:
            data = call_overpass_with_retry(q)
            elements = data.get("elements", [])
            print(f"    Overpass returned {len(elements)} elements")
        except Exception as e:
            last_overpass_error = f"Overpass error at radius {radius}: {e}"
            print(f"    ERROR: {last_overpass_error}")
            break

        if elements:
            break

        radius += RADIUS_STEP_METERS
        time.sleep(BASE_SLEEP_SECONDS)

    if not elements:
        note = last_overpass_error or "No OSM elements found within search radii"
        return OrientationResult(
            orientation_deg=None,
            orientation_label=None,
            confidence=0.0,
            status="failed",
            source=None,
            notes=note,
        )

    candidates = geometry_candidates(elements, lat, lon, league)
    print(f"  Filtered down to {len(candidates)} candidate polygons")
    if not candidates:
        return OrientationResult(
            orientation_deg=None,
            orientation_label=None,
            confidence=0.0,
            status="failed",
            source=None,
            notes="No usable polygon candidates after filtering",
        )

    best = candidates[0]
    print(
        f"  Best candidate: source={best.source}, "
        f"distance_m={best.distance_m:.1f}, AR={best.aspect_ratio:.2f}, "
        f"sport_tag={best.tags.get('sport')}"
    )

    if best.distance_m > MAX_DISTANCE_ACCEPT:
        notes = f"Best candidate too far (distance_m={best.distance_m:.1f} > {MAX_DISTANCE_ACCEPT})"
        print(f"  Rejecting candidate: {notes}")
        return OrientationResult(
            orientation_deg=None,
            orientation_label=None,
            confidence=0.0,
            status="failed",
            source=best.source,
            notes=notes,
        )

    angle = polygon_orientation_pca(best.geom)
    if angle is None:
        print("  Failed to compute PCA orientation")
        return OrientationResult(
            orientation_deg=None,
            orientation_label=None,
            confidence=0.0,
            status="failed",
            source=best.source,
            notes="Failed to compute PCA orientation",
        )

    conf = score_confidence(best, angle, league)
    label = label_from_bearing(angle)

    if conf >= CONF_OK:
        status = "ok"
    elif conf >= CONF_REVIEW:
        status = "review"
    else:
        status = "failed"

    if status in ("ok", "review"):
        write_angle = round(angle, 2)
        write_label = label
    else:
        write_angle = None
        write_label = None

    print(
        f"  Orientation: raw_angle={angle:.2f}, label={label}, "
        f"confidence={conf:.3f}, status={status}"
    )

    notes_parts = [
        f"raw_angle={angle:.2f}",
        f"distance_m={best.distance_m:.1f}",
        f"aspect_ratio={best.aspect_ratio:.2f}",
        f"tags_sport={best.tags.get('sport')}",
        f"status={status}",
    ]
    notes = "; ".join(notes_parts)

    return OrientationResult(
        orientation_deg=write_angle,
        orientation_label=write_label,
        confidence=round(conf, 3),
        status=status,
        source=best.source,
        notes=notes,
    )

# ---------------------------------------------------------
# Batch driver with logging and summary
# ---------------------------------------------------------

def main():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        venues = json.load(f)

    total = len(venues)
    print(f"Loaded {total} venues from {INPUT_JSON}")

    enriched = []
    status_counts = {"ok": 0, "review": 0, "failed": 0}

    for idx, v in enumerate(venues):
        print(
            f"\n=== [{idx+1}/{total}] {v.get('league')} | "
            f"{v.get('team')} | {v.get('venue')} ==="
        )

        # Always recompute in this production run
        res = compute_orientation_for_venue(v)

        # Overwrite orientation_* fields unconditionally
        v["orientation_deg"] = res.orientation_deg
        v["orientation_label"] = res.orientation_label
        v["orientation_confidence"] = res.confidence
        v["orientation_status"] = res.status
        v["orientation_source"] = res.source
        v["orientation_notes"] = res.notes

        enriched.append(v)

        if res.status in status_counts:
            status_counts[res.status] += 1
        else:
            status_counts[res.status] = status_counts.get(res.status, 0) + 1

        time.sleep(BASE_SLEEP_SECONDS)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\nWrote enriched venues with orientations to {OUTPUT_JSON}")
    print("Summary by orientation_status:")
    for k, v in status_counts.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()