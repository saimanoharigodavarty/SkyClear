"""Fetch mapped Hyderabad sites from Overpass and convert them to SkyClear zones.

OpenStreetMap describes physical features; it does not decide their legal drone status. Only
airport and military features receive the existing rule mappings. Other categories deliberately
have no rule_ids, causing the verdict engine to return cannot_determine inside them until an
official regulation is verified.

Run from the repository root:
    python ingestion/osm_zones.py
    python ingestion/osm_zones.py --input path/to/overpass.json
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from geo import circle  # noqa: E402

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HYDERABAD_BBOX = (17.10, 78.10, 17.80, 78.80)  # south, west, north, east
OUTPUT = ROOT / "data" / "zones_osm_hyderabad.geojson"
RAW_CACHE = ROOT / "data" / "osm_hyderabad_raw.json"
ATTRIBUTION = "OpenStreetMap contributors, ODbL 1.0"

# These are physical-site categories, not legal conclusions.
CATEGORIES = {
    "airport": {"rule_ids": ["R-001", "R-001B"], "point_radius_km": 3.0},
    "military": {"rule_ids": ["R-002"], "point_radius_km": 0.5},
    "prison": {"rule_ids": [], "point_radius_km": 0.25},
    "government_context": {"rule_ids": [], "point_radius_km": 0.15},
    "power": {"rule_ids": [], "point_radius_km": 0.30},
    "stadium": {"rule_ids": [], "point_radius_km": 0.25},
}


def overpass_query(bbox=HYDERABAD_BBOX):
    south, west, north, east = bbox
    box = f"({south},{west},{north},{east})"
    return f"""[out:json][timeout:120];
(
  nwr[\"aeroway\"=\"aerodrome\"]{box};
  nwr[\"landuse\"=\"military\"]{box};
  nwr[\"military\"]{box};
  nwr[\"amenity\"=\"prison\"]{box};
  nwr[\"office\"=\"government\"]{box};
  nwr[\"government\"]{box};
  nwr[\"power\"=\"plant\"]{box};
  nwr[\"leisure\"=\"stadium\"]{box};
);
out center geom;"""


def fetch(url=OVERPASS_URL):
    response = requests.post(
        url,
        data={"data": overpass_query()},
        headers={"User-Agent": "SkyClear-hackathon-zone-ingestion/1.0"},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def category(tags):
    if tags.get("landuse") == "military" or "military" in tags:
        return "military"
    if tags.get("aeroway") == "aerodrome":
        return "airport"
    if tags.get("amenity") == "prison":
        return "prison"
    if tags.get("power") == "plant":
        return "power"
    if tags.get("leisure") == "stadium":
        return "stadium"
    if tags.get("office") == "government" or "government" in tags:
        return "government_context"
    return None


def _point(element):
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _ring(points):
    coordinates = [[float(p["lon"]), float(p["lat"])] for p in points if "lat" in p and "lon" in p]
    if len(coordinates) < 3:
        return None
    if coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])
    return coordinates if len(coordinates) >= 4 else None


def geometries(element, zone_type):
    """Return (geometry, derivation) pairs; relations can produce multiple outer polygons."""
    direct = _ring(element.get("geometry", []))
    if direct:
        return [({"type": "Polygon", "coordinates": [direct]}, "osm_boundary")]
    outer = []
    for member in element.get("members", []):
        if member.get("role") in ("", "outer"):
            ring = _ring(member.get("geometry", []))
            if ring:
                outer.append(({"type": "Polygon", "coordinates": [ring]}, "osm_outer_boundary"))
    if outer:
        return outer
    point = _point(element)
    if point:
        radius = CATEGORIES[zone_type]["point_radius_km"]
        return [(circle(point[0], point[1], radius), f"derived_{radius:g}km_point_buffer")]
    return []


def convert(payload, fetched_at=None):
    fetched_at = fetched_at or datetime.now(timezone.utc).date().isoformat()
    features = []
    seen = set()
    for element in payload.get("elements", []):
        key = (element.get("type"), element.get("id"))
        if key in seen:
            continue
        seen.add(key)
        tags = element.get("tags", {})
        zone_type = category(tags)
        if not zone_type:
            continue
        shapes = geometries(element, zone_type)
        for part, (geometry, derivation) in enumerate(shapes, start=1):
            osm_ref = f"{element['type']}/{element['id']}"
            suffix = f"-{part}" if len(shapes) > 1 else ""
            name = tags.get("name:en") or tags.get("name") or tags.get("official_name") or f"Unnamed {zone_type} site"
            features.append({
                "type": "Feature",
                "properties": {
                    "zone_id": f"Z-OSM-{element['type'][0].upper()}{element['id']}{suffix}",
                    "name": name,
                    "zone_type": zone_type,
                    "rule_ids": CATEGORIES[zone_type]["rule_ids"],
                    "source": f"{ATTRIBUTION}; https://www.openstreetmap.org/{osm_ref}; fetched {fetched_at}",
                    "source_id": osm_ref,
                    "legal_status": "rule_mapped" if CATEGORIES[zone_type]["rule_ids"] else "unverified_context",
                    "geometry_derivation": derivation,
                },
                "geometry": geometry,
            })
    features.sort(key=lambda f: f["properties"]["zone_id"])
    return {"type": "FeatureCollection", "features": features}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Use saved Overpass JSON instead of the network")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if args.input:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        payload = fetch()
        RAW_CACHE.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    result = convert(payload)
    args.output.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    counts = {}
    for feature in result["features"]:
        kind = feature["properties"]["zone_type"]
        counts[kind] = counts.get(kind, 0) + 1
    print(f"wrote {len(result['features'])} OSM zones to {args.output}")
    print("categories:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))


if __name__ == "__main__":
    main()
