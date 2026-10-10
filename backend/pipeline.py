"""Shared pipeline pieces: the store and the single-point evaluation used by /check, simulation and flights."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from search import get_store
from verdict import decide

store = get_store()

# Local timezone for coverage area (IST, UTC+05:30) (A6 fix)
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))


def parse_when(value):
    """Parse datetime. When timezone offset is missing, defaults to local timezone (A6 fix)."""
    if not value:
        return datetime.now(LOCAL_TZ)
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=LOCAL_TZ)


def get_drone(drone_id):
    drone = store.get_drone(drone_id)
    if drone is None:
        raise HTTPException(404, f"unknown drone_id {drone_id}")
    return drone


def evaluate(lat, lng, drone, when, alt_m=None):
    """Run the whole pipeline for one point. Returns (verdict, near, notices, used_rules)."""
    near = store.zones_near(lat, lng)
    notices = store.notices_at(lat, lng, when)
    zone_types = {z["zone_type"] for z in near if z["inside"]} | ({"notice"} if notices else set())
    rules = store.rules_for(zone_types, drone["class"], query=f"{drone['class']} drone {' '.join(zone_types)}")
    by_type = {}
    for r in rules:
        by_type.setdefault(r["zone_type"], []).append(r)
    verdict, used = decide(lat, lng, drone["class"], near, notices, by_type, alt_m=alt_m, when=when)
    return verdict, near, notices, used
