"""Send each permission request to the responsible authority. Contract 12, docs/PERMITS_AND_VERIFICATION.md.

Order: owner of the most restrictive zone the flight touches, then the authority whose jurisdiction contains
the spot, then the nearest office. In MongoDB mode the two geo steps are $geoIntersects and $geoNear.
"""
import json
from datetime import datetime, timedelta, timezone

import config
import runtime
from geo import circle, haversine_km, point_in_polygon

_PRIORITY = ["military", "airport", "government", "park"]   # most restrictive first
_data = None


def _raw():
    global _data
    if _data is None:
        with open(config.DATA_DIR / "authorities.json", encoding="utf-8") as f:
            _data = json.load(f)
    return _data


def _build():
    out = []
    for a in _raw()["authorities"]:
        o = a["office"]
        out.append({**a, "office": {"type": "Point", "coordinates": [o["lng"], o["lat"]]},
                    "jurisdiction": circle(o["lat"], o["lng"], a["radius_km"])})
    return out


def setup():
    """Idempotent: load the authorities (MongoDB mode builds the geo indexes). Accounts are created with manage.py, never here."""
    if config.USE_MONGO:
        from db import get_db
        db = get_db()
        for a in _build():
            db.authorities.replace_one({"authority_id": a["authority_id"]}, a, upsert=True)
        db.authorities.create_index([("jurisdiction", "2dsphere")])
        db.authorities.create_index([("office", "2dsphere")])


def all_authorities():
    if config.USE_MONGO:
        from db import get_db
        return list(get_db().authorities.find({}, {"_id": 0}))
    return _build()


def public(a):
    return {"authority_id": a["authority_id"], "name": a["name"], "type": a["type"], "sla_minutes": a["sla_minutes"],
            "office": {"lat": a["office"]["coordinates"][1], "lng": a["office"]["coordinates"][0]}}


def get(authority_id):
    return next((a for a in all_authorities() if a["authority_id"] == authority_id), None)


def _containing(lat, lng, among):
    """Authorities (limited to the ids in `among`) whose jurisdiction contains the point."""
    if config.USE_MONGO:
        from db import get_db
        point = {"type": "Point", "coordinates": [lng, lat]}
        found = get_db().authorities.find({"authority_id": {"$in": list(among)}, "jurisdiction": {"$geoIntersects": {"$geometry": point}}}, {"_id": 0})
        return list(found)
    return [a for a in _build() if a["authority_id"] in among and point_in_polygon(lng, lat, a["jurisdiction"])]


def _nearest(lat, lng, among):
    if config.USE_MONGO:
        from db import get_db
        point = {"type": "Point", "coordinates": [lng, lat]}
        res = list(get_db().authorities.aggregate([
            {"$geoNear": {"near": point, "distanceField": "dist_m", "key": "office", "query": {"authority_id": {"$in": list(among)}}}},
            {"$limit": 1}, {"$project": {"_id": 0}}]))
        return (res[0], res[0]["dist_m"] / 1000) if res else (None, None)
    best = min((a for a in _build() if a["authority_id"] in among),
               key=lambda a: haversine_km(lat, lng, a["office"]["coordinates"][1], a["office"]["coordinates"][0]), default=None)
    return (best, haversine_km(lat, lng, best["office"]["coordinates"][1], best["office"]["coordinates"][0])) if best else (None, None)


def route(lat, lng, inside_zones):
    """Return {authority, reason, distance_km, also_notified} or None when no authority is known."""
    auths = {a["authority_id"]: a for a in all_authorities()}
    explicit = _raw()["zone_authority"]
    ranked = sorted(inside_zones, key=lambda z: _PRIORITY.index(z["zone_type"]) if z["zone_type"] in _PRIORITY else 99)

    def owners_of(z):
        if z["zone_id"] in explicit:
            return [explicit[z["zone_id"]]]
        return [i for i, a in auths.items() if z["zone_type"] in a["handles"]]

    primary = None
    for z in ranked:
        owners = owners_of(z)
        if not owners:
            continue
        if len(owners) == 1:
            primary = (auths[owners[0]], "zone_owner", None)
        else:
            inside = _containing(lat, lng, owners)
            if inside:
                primary = (inside[0], "zone_owner", None)
            else:
                near, km = _nearest(lat, lng, owners)
                primary = (near, "nearest_office", km)
        break
    if primary is None:
        non_hq = [i for i, a in auths.items() if a["handles"]]
        inside = _containing(lat, lng, non_hq) or _containing(lat, lng, list(auths))
        if inside:
            primary = (inside[0], "jurisdiction", None)
        else:
            near, km = _nearest(lat, lng, list(auths))
            primary = (near, "nearest_office", km) if near else None
    if primary is None or primary[0] is None:
        return None
    a, reason, km = primary
    others = []
    for z in ranked:
        for o in owners_of(z):
            if o != a["authority_id"] and o not in others:
                others.append(o)
    return {"authority": public(a), "reason": reason, "distance_km": None if km is None else round(km, 1), "also_notified": others}


def scope_for(user):
    """Authority ids an official may see, or None for an admin who sees everything."""
    aid = user.get("authority_id")
    if not aid:
        return None
    return {aid} | {a["authority_id"] for a in all_authorities() if a.get("parent_id") == aid}


def overdue(flight, now=None):
    """A pending request older than its authority's response time."""
    if flight.get("status") != "requested" or not flight.get("authority_id"):
        return False
    a = get(flight["authority_id"])
    if not a:
        return False
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(flight["created_at"]) > timedelta(minutes=a["sla_minutes"])


def visible_to(user, flight):
    """Officials see their own authority's requests. Children's overdue requests escalate to the parent."""
    aid = user.get("authority_id")
    if not aid:
        return True
    if flight.get("authority_id") == aid:
        return True
    child = get(flight.get("authority_id") or "")
    return bool(child and child.get("parent_id") == aid and overdue(flight))
