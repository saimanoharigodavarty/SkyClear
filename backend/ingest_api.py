"""Real tracker input: a Remote ID receiver, a radar feed or a ground station posts the position of any drone it sees.

The position goes through the same geofence as the simulator. Entering a restricted zone or a declared area records a breach in MongoDB,
and from there the officer's feed and the guard alerts react exactly as they do for a simulated drone.
Each tracker has its own secret key (shown once, stored only as a hash), so a position cannot be injected without one.
OWNER: Nikhil (stream 2A).
"""
import hashlib
import secrets
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import config
import runtime
from pipeline import store
from security import require_admin
from simulator.geofence import GeofenceEngine

router = APIRouter()
_last = {}  # (tracker_id, drone_ref, breach name) -> time, one breach per entry, not one per position report
DEDUPE_S = 60


def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def create_tracker(name, actor=None):
    """Make a tracker and return (record, key). The key is returned once and never stored."""
    key = "trk_" + secrets.token_urlsafe(24)
    rec = {"tracker_id": runtime.new_id("TR"), "name": name.strip(), "key_hash": _hash(key), "active": True, "created_at": runtime.now_iso()}
    runtime.insert("trackers", rec)
    if actor is not None:
        runtime.audit(actor, "tracker_created", rec["tracker_id"], rec["name"])
    return {k: v for k, v in rec.items() if k != "key_hash"}, key


def tracker_for(key):
    if not key:
        return None
    h = _hash(key)
    return next((t for t in runtime.all_("trackers") if t.get("active") and secrets.compare_digest(t["key_hash"], h)), None)


class TrackerIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)


class PositionIn(BaseModel):
    drone_ref: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._:-]+$")  # the id the tracker sees, for example a Remote ID serial
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    alt_m: float = Field(default=0, ge=0, le=6000)
    speed_mps: float = Field(default=0, ge=0, le=150)
    heading_deg: float = Field(default=0, ge=0, le=360)


@router.post("/admin/trackers")
def new_tracker(body: TrackerIn, admin=Depends(require_admin)):
    rec, key = create_tracker(body.name, actor=admin)
    return {**rec, "key": key, "note": "Copy this key now. It is not shown again."}


@router.get("/admin/trackers")
def list_trackers(admin=Depends(require_admin)):
    return [{k: v for k, v in t.items() if k != "key_hash"} for t in runtime.all_("trackers")]


@router.post("/admin/trackers/{tracker_id}/revoke")
def revoke_tracker(tracker_id: str, admin=Depends(require_admin)):
    t = runtime.update("trackers", "tracker_id", tracker_id, {"active": False})
    if not t:
        raise HTTPException(404, "tracker not found")
    runtime.audit(admin, "tracker_revoked", tracker_id, t["name"])
    return {"ok": True}


@router.post("/ingest/position")
def ingest_position(body: PositionIn, x_tracker_key: Optional[str] = Header(default=None)):
    from auth import rate_limit
    tracker = tracker_for(x_tracker_key)
    if tracker is None:
        raise HTTPException(401, "a valid tracker key is required")
    rate_limit("ingest:" + tracker["tracker_id"], 600, 60)
    now = datetime.now(timezone.utc)
    drone = SimpleNamespace(drone_id=body.drone_ref, flight_id=f"T-{body.drone_ref}", lat=body.lat, lng=body.lng, alt_m=body.alt_m, speed_mps=body.speed_mps,
                            heading_deg=body.heading_deg, status="ok", zone=None, alt_limit_m=None, is_approved=False, permit_area=None, permit_start=None, permit_end=None)
    db = None
    if config.USE_MONGO:
        from db import get_db
        db = get_db()
    engine = GeofenceEngine(db=db, store=store)
    status, zone, breach = engine.evaluate_drone(drone, store.all_zones_geojson().get("features", []), store.active_notices(), now_dt=now)
    recorded = False
    if breach:
        key = (tracker["tracker_id"], body.drone_ref, breach["name"])
        if time.monotonic() - _last.get(key, 0) > DEDUPE_S:
            _last[key] = time.monotonic()
            breach["source"] = "tracker:" + tracker["tracker_id"]
            engine.log_breach(breach)
            recorded = True
        if len(_last) > 5000:
            _last.clear()
    if db is not None:
        try:
            db.telemetry.insert_one({"ts": now, "drone_id": body.drone_ref, "flight_id": drone.flight_id, "position": {"type": "Point", "coordinates": [body.lng, body.lat]},
                                     "alt_m": body.alt_m, "speed_mps": body.speed_mps, "heading_deg": body.heading_deg, "battery_pct": None, "source": "tracker"})
        except Exception:
            pass  # a failed history write must not hide the breach
    return {"status": status, "zone": zone, "breach_recorded": recorded}
