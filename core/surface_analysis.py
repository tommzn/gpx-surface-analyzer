"""
GPX Surface Analysis - Core Logic
===================================

Shared module: computes the percentage breakdown of road surface types
(asphalt, gravel, unpaved, cobblestone, ...) along a GPX route, based on
OpenStreetMap data via the public Overpass API.

Used by both the MCP server (mcp-server/server.py) and the Claude skill
script (claude-skill/scripts/analyze_surface.py) so the logic lives in
exactly ONE place.

How it works:
1. Parse GPX -> extract track points
2. Compute bounding box of the entire route (+ padding)
3. ONE Overpass query: fetch all ways (highway=*) in that bounding box,
   including geometry and surface/highway tags
4. For each track segment find the nearest OSM way via point-to-line-segment
   distance (with a simple grid index for speed)
5. Sum up segment lengths per surface category and return percentages

Requires: outbound HTTPS access to overpass-api.de (no API key needed).
"""

import math
import time
from collections import defaultdict
from typing import Optional

import gpxpy
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "gpx-surface-analyzer/1.0 (personal cycling analysis tool)"

# HTTP status codes that warrant a retry (transient server/rate-limit errors
# from the public Overpass server). Other errors (e.g. ConnectionError when
# the host is unreachable in a sandbox) are intentionally NOT retried, since
# retrying won't help there.
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_S = 5.0

# Padding (degrees) added around the route for the Overpass query.
# ~0.003 degrees is roughly 300m — covers GPS inaccuracies.
BBOX_PADDING_DEG = 0.003

# Maximum distance (metres) at which a track point is still matched to a way.
MAX_MATCH_DISTANCE_M = 30.0

# Side length of grid cells (degrees) for the spatial index.
GRID_CELL_DEG = 0.005

# Map raw OSM surface tag values to broad categories.
SURFACE_CATEGORIES = {
    "asphalt": "asphalt",
    "paved": "asphalt",
    "concrete": "asphalt",
    "concrete:plates": "asphalt",
    "concrete:lanes": "asphalt",
    "paving_stones": "cobblestone",
    "sett": "cobblestone",
    "cobblestone": "cobblestone",
    "metal": "other_paved",
    "wood": "other_paved",
    "compacted": "gravel",
    "fine_gravel": "gravel",
    "gravel": "gravel",
    "pebblestone": "gravel",
    "unpaved": "unpaved",
    "ground": "unpaved",
    "dirt": "unpaved",
    "earth": "unpaved",
    "grass": "unpaved",
    "sand": "unpaved",
    "mud": "unpaved",
    "woodchips": "unpaved",
}

# Fallback classification based on the highway tag when surface tag is missing.
HIGHWAY_FALLBACK = {
    "cycleway": "asphalt",
    "residential": "asphalt",
    "primary": "asphalt",
    "secondary": "asphalt",
    "tertiary": "asphalt",
    "unclassified": "asphalt",
    "living_street": "asphalt",
    "service": "asphalt",
    "track": "gravel",
    "path": "unpaved",
    "bridleway": "unpaved",
    "footway": "cobblestone",
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _local_xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    """Rough local projection (metres) for fast short-distance calculations."""
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(ref_lat))
    return lon * m_per_deg_lon, lat * m_per_deg_lat


def point_segment_distance_m(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """Shortest distance from point P to line segment A-B, in metres."""
    ref_lat = p_lat
    px, py = _local_xy(p_lat, p_lon, ref_lat)
    ax, ay = _local_xy(a_lat, a_lon, ref_lat)
    bx, by = _local_xy(b_lat, b_lon, ref_lat)

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def classify_surface(tags: dict) -> str:
    surface = tags.get("surface")
    if surface in SURFACE_CATEGORIES:
        return SURFACE_CATEGORIES[surface]
    highway = tags.get("highway")
    if highway in HIGHWAY_FALLBACK:
        return HIGHWAY_FALLBACK[highway]
    return "unknown"


# ---------------------------------------------------------------------------
# GPX parsing
# ---------------------------------------------------------------------------

def parse_gpx_points(gpx_text: str) -> list[tuple[float, float]]:
    gpx = gpxpy.parse(gpx_text)
    points: list[tuple[float, float]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points.append((pt.latitude, pt.longitude))
    if not points:
        for route in gpx.routes:
            for pt in route.points:
                points.append((pt.latitude, pt.longitude))
    return points


# ---------------------------------------------------------------------------
# Overpass query
# ---------------------------------------------------------------------------

def build_bbox(points: list[tuple[float, float]], padding: float) -> tuple[float, float, float, float]:
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (
        min(lats) - padding,  # south
        min(lons) - padding,  # west
        max(lats) + padding,  # north
        max(lons) + padding,  # east
    )


def fetch_ways_in_bbox(bbox: tuple[float, float, float, float]) -> list[dict]:
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:60];
    (
      way["highway"]({south},{west},{north},{east});
    );
    out geom tags;
    """

    data = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES:
                raise
            retry_after = e.response.headers.get("Retry-After") if e.response is not None else None
            if retry_after is not None:
                try:
                    wait_s = float(retry_after)
                except ValueError:
                    wait_s = RETRY_BACKOFF_BASE_S * (2 ** attempt)
            else:
                wait_s = RETRY_BACKOFF_BASE_S * (2 ** attempt)
            time.sleep(wait_s)

    ways = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        coords = [(node["lat"], node["lon"]) for node in el["geometry"]]
        if len(coords) < 2:
            continue
        ways.append({"tags": el.get("tags", {}), "coords": coords})
    return ways


# ---------------------------------------------------------------------------
# Spatial grid index for fast nearest-segment matching
# ---------------------------------------------------------------------------

def build_grid_index(ways: list[dict], cell_deg: float) -> dict:
    grid: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for way_idx, way in enumerate(ways):
        coords = way["coords"]
        for seg_idx in range(len(coords) - 1):
            a = coords[seg_idx]
            b = coords[seg_idx + 1]
            for lat, lon in (a, b):
                cell = (int(lat // cell_deg), int(lon // cell_deg))
                key = (way_idx, seg_idx)
                if key not in grid[cell]:
                    grid[cell].append(key)
    return grid


def find_nearest_surface(
    lat: float, lon: float,
    ways: list[dict],
    grid: dict,
    cell_deg: float,
    max_dist_m: float,
) -> Optional[dict]:
    base_cell = (int(lat // cell_deg), int(lon // cell_deg))
    candidates: set[tuple[int, int]] = set()
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            candidates.update(grid.get((base_cell[0] + dlat, base_cell[1] + dlon), []))

    best_dist = float("inf")
    best_tags = None
    for way_idx, seg_idx in candidates:
        coords = ways[way_idx]["coords"]
        a_lat, a_lon = coords[seg_idx]
        b_lat, b_lon = coords[seg_idx + 1]
        d = point_segment_distance_m(lat, lon, a_lat, a_lon, b_lat, b_lon)
        if d < best_dist:
            best_dist = d
            best_tags = ways[way_idx]["tags"]

    if best_tags is not None and best_dist <= max_dist_m:
        return best_tags
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_gpx_surface(gpx_text: str) -> dict:
    """
    Analyse a GPX route and compute the percentage breakdown of road surface types.

    Args:
        gpx_text: Full content of a GPX file as a string.

    Returns:
        Dict with total_distance_km, matched_distance_km,
        surface_percentages and unmatched_percent (or "error").
    """
    points = parse_gpx_points(gpx_text)
    if len(points) < 2:
        return {"error": "GPX contains fewer than 2 track points — cannot analyse."}

    bbox = build_bbox(points, BBOX_PADDING_DEG)
    ways = fetch_ways_in_bbox(bbox)
    if not ways:
        return {"error": "No OSM ways found within the bounding box of the route."}

    grid = build_grid_index(ways, GRID_CELL_DEG)

    distance_by_category: dict[str, float] = defaultdict(float)
    unmatched_distance = 0.0
    total_distance = 0.0

    for i in range(len(points) - 1):
        lat1, lon1 = points[i]
        lat2, lon2 = points[i + 1]
        seg_len = haversine_m(lat1, lon1, lat2, lon2)
        if seg_len == 0:
            continue
        total_distance += seg_len

        mid_lat = (lat1 + lat2) / 2
        mid_lon = (lon1 + lon2) / 2
        tags = find_nearest_surface(
            mid_lat, mid_lon, ways, grid, GRID_CELL_DEG, MAX_MATCH_DISTANCE_M
        )
        if tags is None:
            unmatched_distance += seg_len
        else:
            category = classify_surface(tags)
            distance_by_category[category] += seg_len

    if total_distance == 0:
        return {"error": "Route has a total length of 0 m."}

    surface_percentages = {
        cat: round(dist / total_distance * 100, 1)
        for cat, dist in sorted(distance_by_category.items(), key=lambda kv: -kv[1])
    }

    return {
        "total_distance_km": round(total_distance / 1000, 2),
        "matched_distance_km": round((total_distance - unmatched_distance) / 1000, 2),
        "surface_percentages": surface_percentages,
        "unmatched_percent": round(unmatched_distance / total_distance * 100, 1),
    }
