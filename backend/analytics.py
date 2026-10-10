"""Authority analytics. OWNER: Manohari (stream 4). Contract: docs/CONTRACTS.md.

MongoDB computes the dashboard metrics server-side and materializes them for
fast dashboard/Atlas Charts reads. The JSON store keeps the same API usable in
the zero-dependency development mode.
"""
from datetime import datetime
from statistics import median

from fastapi import APIRouter, Depends

import config
import runtime
from bridge import require
from db import get_db
from pipeline import store

router = APIRouter(prefix="/analytics")

GRID_DEGREES = 0.01  # roughly 1.1 km north/south at Hyderabad
DECISION_BUCKETS = [0, 5, 15, 30, 60, 120, 1_000_000]


def _date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _local_summary():
    flights = runtime.all_("flights")
    cells = {}
    statuses = {}
    decision_minutes = []
    for flight in flights:
        location = flight.get("location", {}).get("coordinates", [])
        lng = location[0] if len(location) >= 2 else flight.get("lng")
        lat = location[1] if len(location) >= 2 else flight.get("lat")
        if isinstance(lng, (int, float)) and isinstance(lat, (int, float)):
            cell = (round((lng // GRID_DEGREES) * GRID_DEGREES, 2),
                    round((lat // GRID_DEGREES) * GRID_DEGREES, 2))
            cells[cell] = cells.get(cell, 0) + 1
        status = flight.get("status")
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        created = _date(flight.get("created_at"))
        decided = _date((flight.get("decision") or {}).get("at"))
        if created and decided:
            decision_minutes.append((decided - created).total_seconds() / 60)

    try:
        breaches = runtime.all_("breaches")
    except KeyError:  # The local runtime gains this collection with stream 3.
        breaches = []
    breach_counts = {}
    for breach in breaches:
        zone_id = breach.get("zone_id")
        if not zone_id:
            continue
        key = (zone_id, breach.get("zone_name") or breach.get("name") or zone_id)
        breach_counts[key] = breach_counts.get(key, 0) + 1

    return {
        "zones": len(store.all_zones_geojson()["features"]),
        "heatmap": [{"cell": list(cell), "count": count}
                    for cell, count in sorted(cells.items())],
        "breaches_by_zone": [
            {"zone_id": key[0], "name": key[1], "count": count}
            for key, count in sorted(breach_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "median_decision_minutes": round(median(decision_minutes), 2) if decision_minutes else None,
        "flights_by_status": dict(sorted(statuses.items())),
    }


def flight_summary_pipeline():
    """Build one materialized flight summary using $facet, $bucket, $group and $merge."""
    def as_date(field):
        return {"$convert": {"input": field, "to": "date", "onError": None, "onNull": None}}

    decision_minutes = {"$divide": [{"$subtract": ["$_decision_at", "$_created_at"]}, 60_000]}
    return [
        {"$set": {
            "_lng": {"$ifNull": [{"$arrayElemAt": ["$location.coordinates", 0]}, "$lng"]},
            "_lat": {"$ifNull": [{"$arrayElemAt": ["$location.coordinates", 1]}, "$lat"]},
            "_created_at": as_date("$created_at"),
            "_decision_at": as_date("$decision.at"),
        }},
        {"$facet": {
            "heatmap": [
                {"$match": {"_lng": {"$type": "number"}, "_lat": {"$type": "number"}}},
                {"$group": {
                    "_id": {
                        "lng": {"$round": [{"$multiply": [
                            {"$floor": {"$divide": ["$_lng", GRID_DEGREES]}}, GRID_DEGREES]}, 2]},
                        "lat": {"$round": [{"$multiply": [
                            {"$floor": {"$divide": ["$_lat", GRID_DEGREES]}}, GRID_DEGREES]}, 2]},
                    },
                    "count": {"$sum": 1},
                }},
                {"$project": {"_id": 0, "cell": ["$_id.lng", "$_id.lat"], "count": 1}},
                {"$sort": {"count": -1}},
            ],
            "statuses": [
                {"$match": {"status": {"$type": "string"}}},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ],
            "decisions": [
                {"$match": {"_created_at": {"$ne": None}, "_decision_at": {"$ne": None}}},
                {"$project": {"minutes": decision_minutes}},
                {"$group": {"_id": None, "median": {"$median": {"input": "$minutes", "method": "approximate"}}}},
            ],
            "decision_time_buckets": [
                {"$match": {"_created_at": {"$ne": None}, "_decision_at": {"$ne": None}}},
                {"$project": {"minutes": decision_minutes}},
                {"$bucket": {"groupBy": "$minutes", "boundaries": DECISION_BUCKETS,
                             "default": "other", "output": {"count": {"$sum": 1}}}},
            ],
        }},
        {"$project": {
            "_id": {"$literal": "current"},
            "heatmap": 1,
            "flights_by_status": {"$arrayToObject": {"$map": {
                "input": "$statuses", "as": "item", "in": {"k": "$$item._id", "v": "$$item.count"}
            }}},
            "median_decision_minutes": {"$ifNull": [{"$arrayElemAt": ["$decisions.median", 0]}, None]},
            "decision_time_buckets": 1,
            "generated_at": "$$NOW",
        }},
        {"$merge": {"into": "analytics_flight_summary", "on": "_id",
                    "whenMatched": "replace", "whenNotMatched": "insert"}},
    ]


def breach_summary_pipeline():
    """Group breach events by zone and materialize one document per zone."""
    return [
        {"$match": {"zone_id": {"$type": "string"}}},
        {"$group": {
            "_id": "$zone_id",
            "name": {"$first": {"$ifNull": ["$zone_name", {"$ifNull": ["$name", "$zone_id"]}]}},
            "count": {"$sum": 1},
        }},
        {"$project": {"_id": 1, "zone_id": "$_id", "name": 1, "count": 1, "generated_at": "$$NOW"}},
        {"$merge": {"into": "analytics_breaches_by_zone", "on": "_id",
                    "whenMatched": "replace", "whenNotMatched": "insert"}},
    ]


def _mongo_summary():
    db = get_db()
    list(db.flights.aggregate(flight_summary_pipeline()))
    list(db.breaches.aggregate(breach_summary_pipeline()))
    flight = db.analytics_flight_summary.find_one({"_id": "current"}, {"_id": 0}) or {}
    breaches = list(db.analytics_breaches_by_zone.find(
        {}, {"_id": 0, "zone_id": 1, "name": 1, "count": 1}).sort("count", -1))
    return {
        "zones": db.zones.count_documents({}),
        "heatmap": flight.get("heatmap", []),
        "breaches_by_zone": breaches,
        "median_decision_minutes": flight.get("median_decision_minutes"),
        "flights_by_status": flight.get("flights_by_status", {}),
    }


@router.get("/summary")
def summary(_user=Depends(require("official"))):
    return _mongo_summary() if config.USE_MONGO else _local_summary()
