"""Step 1 and 2: geo search and rule search.

Two stores with the same interface:
  LocalStore reads the JSON files in data/ (default, no database needed, used for tests).
  MongoStore uses MongoDB geospatial, vector and text search. OWNER: data/search teammate.
"""
import json
from datetime import datetime

import config
import runtime
from geo import distance_to_polygon_km, point_in_polygon


def _load(name):
    with open(config.DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class LocalStore:
    def __init__(self):
        self.zones = _load("zones.geojson")["features"]
        self.rules = _load("rules.json")
        self.notices = _load("notices.json")
        self.drones = _load("drones.json")

    def get_drone(self, drone_id):
        found = next((d for d in self.drones if d["drone_id"] == drone_id), None)
        return found or next((d for d in runtime.all_("drones") if d["drone_id"] == drone_id), None)

    def zones_near(self, lat, lng, radius_km=config.NEARBY_KM):
        """Zones containing the point or within radius_km. Each item: zone dict + inside + distance_km."""
        out = []
        for f in self.zones:
            dist = distance_to_polygon_km(lat, lng, f["geometry"])
            if dist <= radius_km:
                out.append({**f["properties"], "geometry": f["geometry"],
                            "inside": dist == 0.0, "distance_km": round(dist, 2)})
        return sorted(out, key=lambda z: z["distance_km"])

    def notices_at(self, lat, lng, when: datetime):
        """Notices that contain the point and are active at `when`."""
        out = []
        published = [n for n in runtime.all_("notices") if n["status"] == "active"]
        for n in self.notices + published:
            starts = datetime.fromisoformat(n["starts_at"])
            ends = datetime.fromisoformat(n["ends_at"])
            if starts <= when <= ends and point_in_polygon(lng, lat, n["area"]):
                out.append({**n, "geometry": n["area"]})
        return out

    def rules_for(self, zone_types, drone_class, query=""):
        """Metadata-filtered rules. MongoStore also ranks them by vector + keyword search using `query`."""
        return [r for r in self.rules if r["zone_type"] in zone_types and drone_class in r["drone_classes"]]

    def all_zones_geojson(self):
        return {"type": "FeatureCollection", "features": self.zones}

    def all_drones(self):
        return self.drones


class MongoStore(LocalStore):
    """TODO (data/search owner): override the methods above with MongoDB queries.

    zones_near   -> $geoNear / $geoIntersects on zones.geometry (2dsphere)
    notices_at   -> $geoIntersects on notices.area plus starts_at/ends_at filter
    rules_for    -> $vectorSearch on rules.embedding + text search on rules.text, filtered by
                    zone_type and drone_classes, then merged (hybrid)
    Until then it falls back to the local JSON behaviour so the app keeps working.
    """

    def __init__(self):
        super().__init__()
        from pymongo import MongoClient
        self.db = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)[config.MONGO_DB]


def get_store():
    return MongoStore() if config.USE_MONGO else LocalStore()
