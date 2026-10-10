"""Guard alerts: anyone on the local network can open the guard page and hear a siren when a drone enters a declared area.

An official declares the area as a notice (a red zone with a time window). When the simulator or a real tracker records a breach of that notice,
the breach reaches this public stream through the same MongoDB change stream the officers use. Only the area name, the kind and the time are sent,
never a pilot, flight or drone identity.
OWNER: Nikhil (stream 2A).
"""
import asyncio
import json
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import events
import runtime
from security import require

router = APIRouter()
_open = 0
MAX_LISTENERS = 300
PER_ADDRESS = 25  # one device or one Wi-Fi network cannot use up every listener slot
_by_ip = {}


_warned = {}  # (drone, area) -> time of the last "approaching" signal
WARN_EVERY_S = 20


def announce_warning(drone_key, zone_text, notices):
    """A drone is about to enter a declared area (the geofence look-ahead): tell the guard devices once every 20 seconds per drone and area.
    Only declared areas (notices) are announced, not ordinary restricted zones."""
    name = re.sub(r"\s*\(ETA.*\)\s*$", "", zone_text or "").strip()
    if not name or name not in {n.get("title") for n in notices or []}:
        return False
    k = (drone_key, name)
    if time.monotonic() - _warned.get(k, 0) < WARN_EVERY_S:
        return False
    if len(_warned) > 2000:
        _warned.clear()
    _warned[k] = time.monotonic()
    events.emit("guard_warning", "insert", {"area": name, "ts": runtime.now_iso()})
    return True


def alert_for(ev, area=None):
    """The public form of an event, or None. `area` limits it to one declared area by name."""
    if ev["coll"] == "guard_warning":
        d = ev["doc"]
        if area and d.get("area", "").strip().lower() != area.strip().lower():
            return None
        return {"area": d.get("area"), "kind": "approaching", "ts": d.get("ts")}
    if ev["coll"] == "guard_test":
        d = ev["doc"]
        return {"area": d.get("area") or "Test", "kind": "test", "ts": d.get("ts")}
    if ev["coll"] != "breaches" or ev["op"] != "insert":
        return None
    d = ev["doc"]
    if d.get("kind") != "notice":
        return None
    if area and d.get("name", "").strip().lower() != area.strip().lower():
        return None
    return {"area": d.get("name"), "kind": "intrusion", "ts": d.get("ts")}


@router.get("/guard/stream")
async def guard_stream(request: Request, area: Optional[str] = Query(default=None, max_length=120)):
    global _open
    ip = request.client.host if request.client else "x"
    if _open >= MAX_LISTENERS or _by_ip.get(ip, 0) >= PER_ADDRESS:
        raise HTTPException(503, "too many listeners")
    _by_ip[ip] = _by_ip.get(ip, 0) + 1
    loop = asyncio.get_running_loop()
    aq: asyncio.Queue = asyncio.Queue(maxsize=100)

    def put(ev):
        try:
            aq.put_nowait(ev)
        except asyncio.QueueFull:
            pass
    push = events.subscribe(lambda ev: loop.call_soon_threadsafe(put, ev))
    _open += 1

    async def gen():
        global _open
        try:
            yield f"event: ready\ndata: {json.dumps({'area': area})}\n\n"
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(aq.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                out = alert_for(ev, area)
                if out:
                    yield f"event: alert\ndata: {json.dumps(out, default=str)}\n\n"
        finally:
            events.unsubscribe(push)
            _open -= 1
            _by_ip[ip] = max(0, _by_ip.get(ip, 1) - 1)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/guard/test")
def guard_test(area: Optional[str] = None, user=Depends(require("official"))):
    """An official sets off the siren on every listening device, to check that it works."""
    events.emit("guard_test", "insert", {"area": area or "Test alert", "ts": runtime.now_iso()})
    runtime.audit(user, "guard_test", area or "all areas", "Siren test")
    return {"ok": True, "listeners": _open}


class PushSub(BaseModel):
    endpoint: str = Field(max_length=600)
    keys: dict
    area: Optional[str] = Field(default=None, max_length=120)


@router.get("/guard/push-key")
def guard_push_key():
    """The public key the browser needs to subscribe. Public by design."""
    import push
    return {"key": push.public_key()}


@router.post("/guard/push-subscribe")
def guard_push_subscribe(body: PushSub, request: Request):
    import push
    from auth import rate_limit
    rate_limit("push:" + (request.client.host if request.client else "x"), 20, 60)
    try:
        push.save_subscription({"endpoint": body.endpoint, "keys": body.keys}, body.area)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@router.post("/guard/push-unsubscribe")
def guard_push_unsubscribe(body: PushSub):
    import push
    push.remove_subscription(body.endpoint)
    return {"ok": True}


@router.get("/guard/status")
def guard_status():
    return {"listeners": _open}
