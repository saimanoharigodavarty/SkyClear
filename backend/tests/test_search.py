import search


class FakeCollection:
    def __init__(self, results=()):
        self.results = list(results)
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return iter(self.results)


class FakeDb:
    def __init__(self, rules=(), zones=()):
        self.rules = FakeCollection(rules)
        self.zones = FakeCollection(zones)


def store_with(db):
    store = search.MongoStore.__new__(search.MongoStore)
    store.db = db
    return store


def test_text_rule_search_uses_mongodb_search():
    db = FakeDb(rules=[{"rule_id": "R-1"}])
    found = store_with(db).search_rules("airport permission", k=3, mode="text")
    assert found == [{"rule_id": "R-1"}]
    first = db.rules.pipelines[0][0]["$search"]
    assert first == {"index": "rules_search", "text": {"query": "airport permission", "path": "text"}}


def test_hybrid_rule_search_runs_rank_fusion_inside_mongodb():
    db = FakeDb(rules=[{"rule_id": "R-1"}])
    original = search.embed
    search.embed = lambda texts, kind: [[0.1, 0.2]]
    try:
        found = store_with(db).search_rules("airport permission", k=3, mode="hybrid")
    finally:
        search.embed = original
    assert found == [{"rule_id": "R-1"}]
    fusion = db.rules.pipelines[0][0]["$rankFusion"]["input"]["pipelines"]
    assert fusion["vector"][0]["$vectorSearch"]["index"] == "rules_vector"
    assert fusion["text"][0]["$search"]["index"] == "rules_search"


def test_hybrid_rule_search_falls_back_to_search_without_embedding():
    db = FakeDb(rules=[{"rule_id": "R-1"}])
    original = search.embed
    search.embed = lambda texts, kind: []
    try:
        store_with(db).search_rules("airport permission", k=3, mode="hybrid")
    finally:
        search.embed = original
    assert "$search" in db.rules.pipelines[0][0]
    assert all("$rankFusion" not in stage for stage in db.rules.pipelines[0])


def test_zone_search_uses_fuzzy_autocomplete_and_preserves_contract():
    zone = {"zone_id": "Z-1", "name": "Begumpet Airport", "zone_type": "airport", "source": "OSM",
            "geometry": {"type": "Polygon", "coordinates": [[[78.4, 17.4], [78.5, 17.4], [78.4, 17.5], [78.4, 17.4]]]}}
    db = FakeDb(zones=[zone])
    found = store_with(db).search_zones("begm", limit=8)
    autocomplete = db.zones.pipelines[0][0]["$search"]["autocomplete"]
    assert autocomplete["fuzzy"]["maxEdits"] == 1
    assert found[0]["zone_id"] == "Z-1"
    assert found[0]["center"] == {"lat": 17.425, "lng": 78.425}
    assert "geometry" not in found[0]


def test_nearby_zones_use_geonear_distance_and_preserve_contract():
    zone = {"zone_id": "Z-1", "name": "Example", "zone_type": "airport", "distance_m": 1234.5,
            "geometry": {"type": "Polygon", "coordinates": [[[78.4, 17.4], [78.5, 17.4], [78.4, 17.5], [78.4, 17.4]]]}}
    db = FakeDb(zones=[zone])
    found = store_with(db).zones_near(17.4, 78.4, radius_km=7)
    geo = db.zones.pipelines[0][0]["$geoNear"]
    assert geo["near"] == {"type": "Point", "coordinates": [78.4, 17.4]}
    assert geo["key"] == "geometry"
    assert geo["maxDistance"] == 7000
    assert geo["spherical"] is True
    assert found[0]["distance_km"] == 1.23
    assert found[0]["inside"] is False
    assert "distance_m" not in found[0]
