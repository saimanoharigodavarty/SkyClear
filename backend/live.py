"""Live airspace and simulation control. OWNER: Thanvi (stream 3). Contracts: 3, 4.

Provides live drone positions (/live/drones), SSE event stream (/live/stream),
and fleet simulation control endpoints (/sim/fleet, /sim/status, /sim/scenarios/vip).
"""
import asyncio
from datetime import datetime, timezone
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
from simulator.fleet import get_fleet_simulator

router = APIRouter(prefix="/live")
sim_router = APIRouter(prefix="/sim")


def get_current_user(authorization: Optional[str] = None, token_param: Optional[str] = None):
    """Optional auth for live streams and drone filtering."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    elif token_param:
        token = token_param.strip()
    if token:
        try:
            return runtime.user_for_token(token)
        except Exception:
            return None
    return None


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

    # Auto-start simulator if not running so live view immediately has active drones
    if not sim.is_running:
        sim.start(count=100)

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
    user = get_current_user(authorization)
    if user and user.get("role") not in ("official", "admin"):
        raise HTTPException(403, "official access only")

    sim = get_fleet_simulator()
    sim.start(count=req.count, bbox=req.bbox, seed=req.seed, speed_x=req.speed_x or 1.0)
    return {"ok": True, "count": req.count, "running": True}


@sim_router.delete("/fleet")
async def stop_fleet(authorization: Optional[str] = Header(default=None)):
    """Stop and remove simulated drones (Contract 4)."""
    user = get_current_user(authorization)
    if user and user.get("role") not in ("official", "admin"):
        raise HTTPException(403, "official access only")

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
    """Publish a notice crossing running drones to produce live breaches (Contract 4)."""
    user = get_current_user(authorization)
    if user and user.get("role") not in ("official", "admin"):
        raise HTTPException(403, "official access only")

    sim = get_fleet_simulator()
    if not sim.is_running:
        sim.start(count=50)

    result = sim.inject_vip_scenario()
    return result
