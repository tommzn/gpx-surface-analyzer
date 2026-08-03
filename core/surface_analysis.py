"""
GPX Surface Analysis - Kernlogik
===================================

Gemeinsam genutztes Modul: berechnet den prozentualen Anteil verschiedener
Wegoberflaechen (Asphalt, Schotter, unbefestigt, ...) entlang einer
GPX-Route, basierend auf OpenStreetMap/Overpass-Daten.

Wird sowohl vom MCP-Server (mcp-server/server.py) als auch vom
Claude-Skill-Skript (claude-skill/scripts/analyze_surface.py) importiert,
damit die Logik nur an EINER Stelle gepflegt werden muss.

Funktionsweise:
1. GPX parsen -> Track-Punkte extrahieren
2. Bounding Box der gesamten Route berechnen (+ Puffer)
3. EINE Overpass-Abfrage: alle Wege (highway=*) in dieser Bounding Box holen,
   inkl. Geometrie und surface/highway-Tags
4. Fuer jedes Track-Segment den naechstgelegenen OSM-Weg per
   Punkt-zu-Liniensegment-Distanz finden (mit einfachem Grid-Index fuer Speed)
5. Streckenlaengen pro Oberflaechenkategorie aufsummieren und Prozente
   berechnen

Voraussetzung: Internetzugriff auf overpass-api.de (kein API-Key noetig).
"""

import math
import time
from collections import defaultdict
from typing import Optional

import gpxpy
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "gpx-surface-analyzer/1.0 (personal cycling analysis tool)"

# HTTP-Statuscodes, bei denen ein erneuter Versuch sinnvoll ist (transiente
# Server-/Rate-Limit-Fehler des oeffentlichen Overpass-Servers). Andere
# Fehler (z.B. ConnectionError, weil der Host in einer Sandbox nicht
# erreichbar ist) werden bewusst NICHT retried, da ein erneuter Versuch
# dort nichts aendert.
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_S = 5.0

# Puffer (Grad) rund um die Route bei der Overpass-Abfrage.
# ~0.003 Grad entspricht grob 300m - deckt GPS-Ungenauigkeiten ab.
BBOX_PADDING_DEG = 0.003

# Ab welcher Entfernung (Meter) ein Track-Punkt NICHT mehr einem Weg
# zugeordnet wird.
MAX_MATCH_DISTANCE_M = 30.0

# Kantenlaenge der Grid-Zellen (Grad) fuer den raeumlichen Index.
GRID_CELL_DEG = 0.005

# Klassifizierung roher OSM surface-Werte in grobe Kategorien
SURFACE_CATEGORIES = {
    "asphalt": "asphalt",
    "paved": "asphalt",
    "concrete": "asphalt",
    "concrete:plates": "asphalt",
    "concrete:lanes": "asphalt",
    "paving_stones": "pflaster",
    "sett": "pflaster",
    "cobblestone": "pflaster",
    "metal": "sonstig_befestigt",
    "wood": "sonstig_befestigt",
    "compacted": "schotter",
    "fine_gravel": "schotter",
    "gravel": "schotter",
    "pebblestone": "schotter",
    "unpaved": "unbefestigt",
    "ground": "unbefestigt",
    "dirt": "unbefestigt",
    "earth": "unbefestigt",
    "grass": "unbefestigt",
    "sand": "unbefestigt",
    "mud": "unbefestigt",
    "woodchips": "unbefestigt",
}

# Fallback-Klassifizierung anhand des highway-Tags, falls surface fehlt.
HIGHWAY_FALLBACK = {
    "cycleway": "asphalt",
    "residential": "asphalt",
    "primary": "asphalt",
    "secondary": "asphalt",
    "tertiary": "asphalt",
    "unclassified": "asphalt",
    "living_street": "asphalt",
    "service": "asphalt",
    "track": "schotter",
    "path": "unbefestigt",
    "bridleway": "unbefestigt",
    "footway": "pflaster",
}


# ---------------------------------------------------------------------------
# Geometrie-Hilfsfunktionen
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanz zwischen zwei Koordinaten in Metern (Great-Circle)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _local_xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    """Grobe lokale Projektion (Meter) fuer schnelle Kurzdistanz-Berechnung."""
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(ref_lat))
    return lon * m_per_deg_lon, lat * m_per_deg_lat


def point_segment_distance_m(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """Kuerzeste Distanz von Punkt P zum Liniensegment A-B, in Metern."""
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
    return "unbekannt"


# ---------------------------------------------------------------------------
# GPX parsen
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
# Overpass-Abfrage
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
# Raeumlicher Grid-Index fuer schnelles Nearest-Segment-Matching
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
# Oeffentliche Hauptfunktion
# ---------------------------------------------------------------------------

def analyze_gpx_surface(gpx_text: str) -> dict:
    """
    Analysiert eine GPX-Route und berechnet den prozentualen Anteil
    verschiedener Wegoberflaechen.

    Args:
        gpx_text: Vollstaendiger Inhalt einer GPX-Datei als String.

    Returns:
        Dict mit total_distance_km, matched_distance_km,
        surface_percentages und unmatched_percent (oder "error").
    """
    points = parse_gpx_points(gpx_text)
    if len(points) < 2:
        return {"error": "GPX enthaelt weniger als 2 Track-Punkte, keine Analyse moeglich."}

    bbox = build_bbox(points, BBOX_PADDING_DEG)
    ways = fetch_ways_in_bbox(bbox)
    if not ways:
        return {"error": "Keine OSM-Wege in der Bounding Box der Route gefunden."}

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
        return {"error": "Route hat eine Gesamtlaenge von 0m."}

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
