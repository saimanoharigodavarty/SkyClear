"""Live airspace and simulation control. OWNER: Thanvi (stream 3). Contracts: 3, 4.

Provides live drone positions (/live/drones), SSE event stream (/live/stream),
and fleet simulation control endpoints (/sim/fleet, /sim/status, /sim/scenarios/vip).
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Ensure root is in sys.path so simulator is importable from backend/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
import runtime
from security import decode_access
from simulator.fleet import get_fleet_simulator

router = APIRouter(prefix="/live")
sim_router = APIRouter(prefix="/sim")


def get_current_user(authorization: Optional[str] = None, token_param: Optional[str] = None):
    """Who is asking, from the JWT. None for a visitor. (A browser EventSource cannot send headers, so the stream also takes ?token=.)"""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    elif token_param:
        token = token_param.strip()
    if not token:
        return None
    try:
        claims = decode_access(token)
    except HTTPException:
        return None
    return next((u for u in runtime.all_("users") if u["user_id"] == claims["sub"]), None)


def require_official(authorization: Optional[str]):
    """Fleet controls are for officials. A missing, expired or pilot token is refused."""
    user = get_current_user(authorization)
    if user is None:
        raise HTTPException(401, "sign in required")
    if user.get("role") != "official":
        raise HTTPException(403, "official access only")
    return user


# ---- Contract 3: Live Airspace ----

@router.get("/drones")
async def live_drones(bbox: str = Query(default=""), authorization: Optional[str] = Header(default=None)):
    """Latest position of every simulated drone in the box (Contract 3)."""
    sim = get_fleet_simulator()

    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x.strip()) for x in bbox.split(",")]
        except Exception:
            bbox_list = None

    user = get_current_user(authorization)
    return sim.get_drones(bbox=bbox_list, user=user)


@router.get("/stream")
async def live_stream(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
):
    """Server-sent events streaming positions, breaches, alerts, and pings (Contract 3)."""
    sim = get_fleet_simulator()
    user = get_current_user(authorization, token)
    user_id = user.get("user_id") if user else None

    queue = sim.subscribe_events()

    async def event_generator():
        try:
            # Initial ping to establish connection
            yield f"event: ping\ndata: {json.dumps({'ok': True})}\n\n"

            # Check change stream / unread notifications for signed-in user
            if user_id:
                try:
                    all_notifs = runtime.all_("notifications")
                    user_notifs = [n for n in all_notifs if n.get("user_id") == user_id and not n.get("read")]
                    for n in user_notifs[-5:]:
                        yield f"event: alert\ndata: {json.dumps(n)}\n\n"
                except Exception:
                    pass

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    ev_type = event.get("event", "ping")
                    data = event.get("data", {})

                    # If alert event, verify it belongs to user
                    if ev_type == "alert" and user_id and data.get("user_id") != user_id:
                        continue

                    yield f"event: {ev_type}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {json.dumps({'ok': True})}\n\n"
        finally:
            sim.unsubscribe_events(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---- Contract 4: Simulation Control ----

class FleetRequest(BaseModel):
    count: int = Field(default=100, ge=1, le=1000)
    bbox: Optional[list[float]] = None
    seed: Optional[int] = 1
    speed_x: Optional[float] = 1.0


@sim_router.post("/fleet")
async def start_fleet(req: FleetRequest, authorization: Optional[str] = Header(default=None)):
    """Start or reconfigure simulated fleet (Contract 4)."""
    require_official(authorization)
    sim = get_fleet_simulator()
    sim.start(count=req.count, bbox=req.bbox, seed=req.seed, speed_x=req.speed_x or 1.0)
    return {"ok": True, "count": req.count, "running": True}


@sim_router.delete("/fleet")
async def stop_fleet(authorization: Optional[str] = Header(default=None)):
    """Stop and remove simulated drones (Contract 4)."""
    require_official(authorization)
    sim = get_fleet_simulator()
    sim.stop()
    return {"ok": True, "running": False}


@sim_router.get("/status")
async def sim_status():
    """Return fleet simulation status (Contract 4)."""
    sim = get_fleet_simulator()
    return sim.get_status()


@sim_router.post("/scenarios/vip")
async def inject_vip_scenario(authorization: Optional[str] = Header(default=None)):
    """Publish a VIP restriction over the drones that are flying now (Contract 4).

    It goes through the normal notice path (the same as an official publishing one), so pilots with flights there are alerted,
    conflicting permits are listed, and the geofence engine raises breaches on the next tick.
    """
    user = require_official(authorization)
    import bridge
    sim = get_fleet_simulator()
    if not sim.drones:
        sim.start(count=30)
    lat, lng = sim.vip_center()
    now = datetime.now(timezone.utc)
    notice = bridge.create_notice("VIP movement (simulated scenario)", "Temporary restriction for an official movement.", lat, lng, 1.5,
                                  now.isoformat(timespec="seconds"), (now + timedelta(hours=3)).isoformat(timespec="seconds"), user["name"])
    return {"ok": True, "notice_id": notice["notice_id"], "title": notice["title"], "affected_drones": sum(1 for d in sim.drones if _inside(d, notice)),
            "affected_flights": notice["affected_flights"], "conflicting_permits": notice["conflicting_permits"]}


class DrillIn(BaseModel):
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    polygon: Optional[list[list[float]]] = None  # a drawn boundary, [lng, lat] corners, used instead of a circle
    radius_m: float = Field(default=120, ge=30, le=2000)
    title: str = Field(default="Protected area drill", min_length=3, max_length=80)
    approach_m: float = Field(default=600, ge=150, le=3000)
    speed_mps: float = Field(default=12, ge=3, le=25)


@sim_router.post("/scenarios/intruder")
async def inject_intruder_scenario(body: DrillIn, authorization: Optional[str] = Header(default=None)):
    """A drill: declare an area as a restriction (a normal notice) and send one simulated drone toward it from a distance.
    The drone flies in, so the breach, the officer's feed and the guard alerts all happen through the real path."""
    user = require_official(authorization)
    import bridge
    import math
    import secrets
    from simulator.kinematics import DroneKinematics
    now = datetime.now(timezone.utc)
    if body.polygon is None and (body.lat is None or body.lng is None):
        raise HTTPException(422, "give a centre or draw the boundary")
    try:
        notice = bridge.create_notice(body.title, "Drill: a simulated drone is sent toward this area.", body.lat, body.lng, body.radius_m / 1000,
                                      now.isoformat(timespec="seconds"), (now + timedelta(hours=2)).isoformat(timespec="seconds"), user["name"], actor=user, polygon=body.polygon)
    except ValueError as e:
        raise HTTPException(422, str(e))
    body.lat, body.lng = notice["center"]["lat"], notice["center"]["lng"]  # for a drawn boundary the drone flies at its middle
    bearing = math.radians(secrets.randbelow(360))
    dlat = lambda m, b: m * math.cos(b) / 111320.0  # noqa: E731
    dlng = lambda m, b: m * math.sin(b) / (111320.0 * max(0.1, math.cos(math.radians(body.lat))))  # noqa: E731
    start = (body.lat + dlat(body.approach_m, bearing), body.lng + dlng(body.approach_m, bearing))
    far = (body.lat - dlat(body.approach_m, bearing), body.lng - dlng(body.approach_m, bearing))
    drone = DroneKinematics(drone_id="DRILL-" + secrets.token_hex(2).upper(), flight_id="F-" + secrets.token_hex(3).upper(), initial_lat=start[0], initial_lng=start[1],
                            initial_alt_m=50.0, speed_mps=body.speed_mps, battery_pct=95.0, waypoints=[(body.lat, body.lng, 50.0), (far[0], far[1], 50.0)], owner_id=None, is_approved=False)
    sim = get_fleet_simulator()
    with sim._lock:
        sim.drones.append(drone)
        sim.is_running = True
    sim._ensure_task()
    return {"ok": True, "notice_id": notice["notice_id"], "title": notice["title"], "drone_id": drone.drone_id,
            "arrives_in_s": round(body.approach_m / body.speed_mps)}


def _inside(drone, notice):
    from geo import point_in_polygon
    return point_in_polygon(drone.lng, drone.lat, notice["area"])


@router.get("/breaches")
async def recent_breaches(limit: int = Query(default=20, ge=1, le=100), authorization: Optional[str] = Header(default=None)):
    """The latest geofence breaches, newest first. Officials only."""
    require_official(authorization)
    if config.USE_MONGO:
        from db import get_db
        rows = list(get_db().breaches.find({}, {"_id": 0}).sort("ts", -1).limit(limit))
    else:
        rows = sorted(runtime.all_("breaches"), key=lambda b: b.get("ts", ""), reverse=True)[:limit]
    return {"breaches": rows}
