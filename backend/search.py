"""Step 1 and 2: geo search and rule search.

Two stores with the same interface:
  LocalStore reads the JSON files in data/ (default, no database needed, used for tests).
  MongoStore uses MongoDB geospatial, vector and text search. OWNER: data/search teammate.
"""
import json
from datetime import datetime

import config
import runtime
from embeddings import embed
from geo import distance_to_polygon_km, point_in_polygon

RULES_SEARCH_INDEX = "rules_search"
RULES_VECTOR_INDEX = "rules_vector"
ZONES_SEARCH_INDEX = "zones_autocomplete"


def _load(name):
    with open(config.DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _touches_box(geometry, w, s, e, n):
    """Cheap test: the polygon's own bounding box overlaps the query box."""
    xs = [x for x, _ in geometry["coordinates"][0]]
    ys = [y for _, y in geometry["coordinates"][0]]
    return not (max(xs) < w or min(xs) > e or max(ys) < s or min(ys) > n)


def _center(geometry):
    ring = geometry["coordinates"][0]
    return {"lat": round(sum(y for _, y in ring) / len(ring), 5), "lng": round(sum(x for x, _ in ring) / len(ring), 5)}


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

    def search_zones(self, q, limit=8):
        """Find zones by name. Simple substring match here. MongoStore should use Atlas Search autocomplete."""
        q = q.strip().lower()
        hits = [f["properties"] | {"center": _center(f["geometry"])} for f in self.zones if q in f["properties"]["name"].lower()]
        return hits[:limit]

    def zones_in_bbox(self, w, s, e, n):
        box = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
        feats = [f for f in self.zones if _touches_box(f["geometry"], w, s, e, n)]
        return {"type": "FeatureCollection", "features": feats}

    def active_notices(self):
        return self.notices + [n for n in runtime.all_("notices") if n["status"] == "active"]

    def all_zones_geojson(self):
        return {"type": "FeatureCollection", "features": self.zones}

    def all_drones(self):
        return self.drones


class MongoStore(LocalStore):
    """MongoDB: 2dsphere geo queries, metadata-filtered rules, and vector, text and hybrid rule search."""

    def __init__(self):
        from db import get_db
        self.db = get_db()

    @staticmethod
    def _clean(doc):
        doc = dict(doc)
        doc.pop("_id", None)
        doc.pop("embedding", None)
        return doc

    def get_drone(self, drone_id):
        d = self.db.drones.find_one({"drone_id": drone_id}, {"_id": 0})
        return d

    def all_drones(self):
        return list(self.db.drones.find({"owner_id": {"$exists": False}}, {"_id": 0, "origin": 0}))

    def all_zones_geojson(self):
        feats = []
        for z in self.db.zones.find({}, {"_id": 0}):
            geom = z.pop("geometry")
            feats.append({"type": "Feature", "properties": z, "geometry": geom})
        return {"type": "FeatureCollection", "features": feats}

    def search_zones(self, q, limit=8):
        """Fuzzy search-as-you-type over zone names using MongoDB Search autocomplete."""
        pipeline = [
            {"$search": {"index": ZONES_SEARCH_INDEX, "autocomplete": {
                "query": q.strip(), "path": "name", "tokenOrder": "sequential",
                "fuzzy": {"maxEdits": 1, "prefixLength": 1, "maxExpansions": 32},
            }}},
            {"$limit": limit},
            {"$project": {"_id": 0}},
        ]
        found = self.db.zones.aggregate(pipeline)
        return [{**{k: v for k, v in z.items() if k != "geometry"}, "center": _center(z["geometry"])} for z in found]

    def zones_in_bbox(self, w, s, e, n):
        box = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
        feats = []
        for z in self.db.zones.find({"geometry": {"$geoIntersects": {"$geometry": box}}}, {"_id": 0}):
            geom = z.pop("geometry")
            feats.append({"type": "Feature", "properties": z, "geometry": geom})
        return {"type": "FeatureCollection", "features": feats}

    def zones_near(self, lat, lng, radius_km=config.NEARBY_KM):
        """Return containing and nearby zones ordered by MongoDB's spherical distance."""
        pipeline = [
            {"$geoNear": {
                "near": {"type": "Point", "coordinates": [lng, lat]},
                "key": "geometry",
                "distanceField": "distance_m",
                "maxDistance": radius_km * 1000,
                "spherical": True,
            }},
            {"$project": {"_id": 0}},
        ]
        out = []
        for zone in self.db.zones.aggregate(pipeline):
            distance_m = zone.pop("distance_m")
            out.append({**zone, "inside": distance_m <= 0.01, "distance_km": round(distance_m / 1000, 2)})
        return out

    def notices_at(self, lat, lng, when):
        point = {"type": "Point", "coordinates": [lng, lat]}
        out = []
        for n in self.db.notices.find({"status": "active", "area": {"$geoIntersects": {"$geometry": point}}}, {"_id": 0}):
            if datetime.fromisoformat(n["starts_at"]) <= when <= datetime.fromisoformat(n["ends_at"]):
                out.append({**n, "geometry": n["area"]})
        return out

    def active_notices(self):
        return list(self.db.notices.find({"status": "active"}, {"_id": 0}))

    def rules_for(self, zone_types, drone_class, query=""):
        """Every rule that matches the zone type and drone class. The verdict needs all of them, not a top-k."""
        found = self.db.rules.find({"zone_type": {"$in": list(zone_types)}, "drone_classes": drone_class}, {"_id": 0, "embedding": 0})
        return list(found)

    def search_rules(self, query, k=5, mode="hybrid"):
        """Rank rule passages for a plain-language question.

        mode "text"   Atlas Search (Lucene) keyword search
        mode "vector" Atlas Vector Search on the embeddings
        mode "hybrid" both, merged inside MongoDB with $rankFusion. Falls back to text alone when there are no embeddings,
                      for example when the Ollama laptop is not reachable.
        """
        if mode == "text":
            return self._text(query, k)
        vec = embed([query], "query")
        if not vec:
            return [] if mode == "vector" else self._text(query, k)
        if mode == "vector":
            return self._vector(vec[0], k)
        return self._hybrid(query, vec[0], k)

    def _search_stage(self, query):
        return {"$search": {"index": RULES_SEARCH_INDEX, "text": {"query": query, "path": "text"}}}

    def _vector_stage(self, vec, limit):
        return {"$vectorSearch": {"index": RULES_VECTOR_INDEX, "path": "embedding", "queryVector": vec, "numCandidates": max(50, limit * 10), "limit": limit}}

    def _vector(self, vec, limit):
        return list(self.db.rules.aggregate([self._vector_stage(vec, limit),
                                             {"$project": {"_id": 0, "embedding": 0, "score": {"$meta": "vectorSearchScore"}}}]))

    def _text(self, query, limit):
        try:
            found = list(self.db.rules.aggregate([self._search_stage(query), {"$limit": limit},
                                                  {"$project": {"_id": 0, "embedding": 0, "score": {"$meta": "searchScore"}}}]))
        except Exception as e:  # the search index is still building or missing: use the plain text index
            print(f"[search] Atlas Search not ready ({type(e).__name__}), using the text index")
            found = []
        if found:
            return found
        return list(self.db.rules.aggregate([{"$match": {"$text": {"$search": query}}}, {"$addFields": {"score": {"$meta": "textScore"}}},
                                             {"$sort": {"score": -1}}, {"$limit": limit}, {"$project": {"_id": 0, "embedding": 0}}]))

    def _hybrid(self, query, vec, k):
        """Reciprocal rank fusion of vector and keyword results, done by MongoDB ($rankFusion)."""
        pipeline = [{"$rankFusion": {"input": {"pipelines": {
                        "vector": [self._vector_stage(vec, k * 3)],
                        "text": [self._search_stage(query), {"$limit": k * 3}]}},
                     "combination": {"weights": {"vector": 1, "text": 1}}}},
                    {"$limit": k}, {"$project": {"_id": 0, "embedding": 0}}]
        try:
            found = list(self.db.rules.aggregate(pipeline))
        except Exception as e:  # rankFusion unavailable or an index is still building
            print(f"[search] hybrid search failed ({type(e).__name__}), merging in code instead")
            found = []
        return found or self._merge(self._vector(vec, k * 3), self._text(query, k * 3), k)

    @staticmethod
    def _merge(a, b, k):
        score, byid = {}, {}
        for lst in (a, b):
            for rank, r in enumerate(lst):
                score[r["rule_id"]] = score.get(r["rule_id"], 0) + 1 / (60 + rank)
                byid[r["rule_id"]] = r
        return [{**byid[i], "score": round(s, 5)} for i, s in sorted(score.items(), key=lambda x: -x[1])][:k]
def get_store():
    return MongoStore() if config.USE_MONGO else LocalStore()
