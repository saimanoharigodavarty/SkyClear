import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))
import osm_zones


def test_query_contains_each_supported_physical_site_category():
    query = osm_zones.overpass_query()
    for fragment in ('"aeroway"="aerodrome"', '"landuse"="military"', '"amenity"="prison"',
                     '"office"="government"', '"power"="plant"', '"leisure"="stadium"'):
        assert fragment in query


def test_convert_preserves_osm_identity_attribution_and_real_boundary():
    payload = {"elements": [{
        "type": "way", "id": 42,
        "tags": {"amenity": "prison", "name": "Example Prison"},
        "geometry": [
            {"lat": 17.4, "lon": 78.4}, {"lat": 17.4, "lon": 78.5},
            {"lat": 17.5, "lon": 78.5}, {"lat": 17.4, "lon": 78.4},
        ],
    }]}
    feature = osm_zones.convert(payload, fetched_at="2026-10-10")["features"][0]
    props = feature["properties"]
    assert props["zone_id"] == "Z-OSM-W42"
    assert props["source_id"] == "way/42"
    assert "OpenStreetMap contributors, ODbL 1.0" in props["source"]
    assert props["legal_status"] == "unverified_context"
    assert props["rule_ids"] == []
    assert feature["geometry"]["type"] == "Polygon"


def test_unverified_point_site_uses_a_labelled_derived_buffer():
    payload = {"elements": [{
        "type": "node", "id": 7, "lat": 17.4, "lon": 78.4,
        "tags": {"power": "plant", "name": "Example Plant"},
    }]}
    feature = osm_zones.convert(payload, fetched_at="2026-10-10")["features"][0]
    assert feature["properties"]["geometry_derivation"] == "derived_0.3km_point_buffer"
    assert feature["properties"]["legal_status"] == "unverified_context"


def test_airport_and_military_keep_existing_rule_mappings():
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": 17.4, "lon": 78.4, "tags": {"aeroway": "aerodrome"}},
        {"type": "node", "id": 2, "lat": 17.5, "lon": 78.5, "tags": {"landuse": "military"}},
    ]}
    by_type = {f["properties"]["zone_type"]: f for f in osm_zones.convert(payload)["features"]}
    assert by_type["airport"]["properties"]["rule_ids"] == ["R-001", "R-001B"]
    assert by_type["military"]["properties"]["rule_ids"] == ["R-002"]


def test_checked_in_osm_dataset_has_at_least_300_attributed_hyderabad_sites():
    path = Path(__file__).resolve().parents[2] / "data" / "zones_osm_hyderabad.geojson"
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert len(data["features"]) >= 300
    assert all("OpenStreetMap contributors, ODbL 1.0" in f["properties"]["source"] for f in data["features"])
    assert all(f["properties"]["source_id"] for f in data["features"])
