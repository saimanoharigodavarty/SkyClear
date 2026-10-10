"""Build data/zones.geojson from OurAirports, Hyderabad OSM sites and manual fixtures.

Run: python backend/build_zones.py [path/to/airports.csv]
Without an argument it downloads https://davidmegginson.github.io/ourairports-data/airports.csv.

Airport zones are circles around the airport reference point. The radius is an approximation
(derived data) and must be verified against official airspace maps before real use.
"""
import csv
import io
import json
import sys
import urllib.request

import config
from geo import circle

URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
RADIUS_KM = {"large_airport": 5.0, "medium_airport": 5.0, "small_airport": 3.0}
MILITARY = {"VODG", "VOHK"}  # Air Force sites near Hyderabad: Dundigul, Hakimpet
SOURCE = "OurAirports, circle of {r:g} km around the airport (derived, verify)"


def load_rows(path):
    if path:
        text = open(path, encoding="utf-8").read()
    else:
        text = urllib.request.urlopen(URL, timeout=60).read().decode("utf-8")
    return csv.DictReader(io.StringIO(text))


def build(path=None):
    features = []
    for r in load_rows(path):
        if r["iso_country"] != "IN" or r["type"] not in RADIUS_KM:
            continue
        military = r["ident"] in MILITARY
        if r["type"] == "small_airport" and r["scheduled_service"] != "yes" and not military:
            continue
        km = RADIUS_KM[r["type"]]
        lat, lng = float(r["latitude_deg"]), float(r["longitude_deg"])
        features.append({
            "type": "Feature",
            "properties": {"zone_id": f"Z-{r['ident']}", "name": r["name"], "zone_type": "military" if military else "airport",
                           "rule_ids": ["R-002"] if military else ["R-001", "R-001B"], "source": SOURCE.format(r=km)},
            "geometry": circle(lat, lng, km),
        })
    osm_path = config.DATA_DIR / "zones_osm_hyderabad.geojson"
    osm = json.load(open(osm_path, encoding="utf-8"))["features"] if osm_path.exists() else []
    # OurAirports remains the single aerodrome source; OSM supplies the other mapped site categories.
    osm = [f for f in osm if f["properties"]["zone_type"] != "airport"]
    manual = json.load(open(config.DATA_DIR / "zones_manual.geojson", encoding="utf-8"))["features"]
    return {"type": "FeatureCollection", "features": features + osm + manual}


if __name__ == "__main__":
    fc = build(sys.argv[1] if len(sys.argv) > 1 else None)
    with open(config.DATA_DIR / "zones.geojson", "w", encoding="utf-8") as f:
        json.dump(fc, f, separators=(",", ":"))
    print(f"wrote {len(fc['features'])} zones")
