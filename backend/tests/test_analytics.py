import analytics
import config
import pytest


def test_local_summary_calculates_contract_metrics(monkeypatch):
    flights = [
        {"lng": 78.401, "lat": 17.401, "status": "requested",
         "created_at": "2026-10-10T10:00:00+00:00", "decision": None},
        {"location": {"type": "Point", "coordinates": [78.409, 17.409]}, "status": "approved",
         "created_at": "2026-10-10T10:00:00Z", "decision": {"at": "2026-10-10T10:20:00Z"}},
        {"lng": 78.421, "lat": 17.421, "status": "approved",
         "created_at": "2026-10-10T10:00:00Z", "decision": {"at": "2026-10-10T10:40:00Z"}},
    ]
    breaches = [
        {"zone_id": "Z-1", "zone_name": "Airport"},
        {"zone_id": "Z-1", "zone_name": "Airport"},
        {"zone_id": "Z-2", "name": "Prison"},
    ]
    monkeypatch.setattr(analytics.runtime, "all_", lambda name: flights if name == "flights" else breaches)
    monkeypatch.setattr(analytics.store, "all_zones_geojson", lambda: {"features": [1, 2]})

    result = analytics._local_summary()

    assert result["zones"] == 2
    assert result["heatmap"] == [
        {"cell": [78.4, 17.4], "count": 2},
        {"cell": [78.42, 17.42], "count": 1},
    ]
    assert result["flights_by_status"] == {"approved": 2, "requested": 1}
    assert result["median_decision_minutes"] == 30
    assert result["breaches_by_zone"][0] == {"zone_id": "Z-1", "name": "Airport", "count": 2}


def test_flight_pipeline_contains_required_mongodb_stages():
    pipeline = analytics.flight_summary_pipeline()
    facet = next(stage["$facet"] for stage in pipeline if "$facet" in stage)

    assert "heatmap" in facet and "statuses" in facet and "decisions" in facet
    assert any("$group" in stage for branch in facet.values() for stage in branch)
    assert any("$bucket" in stage for stage in facet["decision_time_buckets"])
    assert pipeline[-1]["$merge"]["into"] == "analytics_flight_summary"


def test_breach_pipeline_groups_and_materializes():
    pipeline = analytics.breach_summary_pipeline()

    assert any("$group" in stage for stage in pipeline)
    assert pipeline[-1]["$merge"]["into"] == "analytics_breaches_by_zone"


@pytest.mark.skipif(not config.USE_MONGO, reason="MongoDB integration test")
def test_mongodb_summary_executes_materialization_pipelines():
    db = analytics.get_db()
    db.flights.delete_many({})
    db.breaches.delete_many({})
    db.analytics_flight_summary.delete_many({})
    db.analytics_breaches_by_zone.delete_many({})
    db.flights.insert_many([
        {"flight_id": "F-A", "lng": 78.401, "lat": 17.401, "status": "requested",
         "created_at": "2026-10-10T10:00:00Z", "decision": None},
        {"flight_id": "F-B", "location": {"type": "Point", "coordinates": [78.409, 17.409]},
         "status": "approved", "created_at": "2026-10-10T10:00:00Z",
         "decision": {"at": "2026-10-10T10:20:00Z"}},
    ])
    db.breaches.insert_many([
        {"zone_id": "Z-1", "zone_name": "Airport"},
        {"zone_id": "Z-1", "zone_name": "Airport"},
    ])

    try:
        result = analytics._mongo_summary()

        assert result["heatmap"] == [{"cell": [78.4, 17.4], "count": 2}]
        assert result["flights_by_status"] == {"approved": 1, "requested": 1}
        assert result["median_decision_minutes"] == 20
        assert result["breaches_by_zone"] == [{"zone_id": "Z-1", "name": "Airport", "count": 2}]
    finally:
        db.flights.delete_many({"flight_id": {"$in": ["F-A", "F-B"]}})
        db.breaches.delete_many({"zone_id": "Z-1"})
        db.analytics_flight_summary.delete_many({})
        db.analytics_breaches_by_zone.delete_many({})
