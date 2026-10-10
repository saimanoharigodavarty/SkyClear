"""The live event channel: one server-sent-events stream per browser, fed by MongoDB change streams (see events.py).

A pilot receives their own alerts and the status of their own flights. An official receives breaches, notices and the flights in their scope.
The page then asks the normal API for details, so what a person may see is still decided by the API, not by this channel.
OWNER: Nikhilkumarpanigrahi (stream 2A).
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import events
import routing
from live import get_current_user
from security import require_admin

router = APIRouter()


def shape(ev, user):
    """What this person is told about an event, or None. Only minimal fields, never another pilot's data."""
    coll, doc, role = ev["coll"], ev["doc"], user["role"]
    if coll == "notices":
        return "notice", {"notice_id": doc.get("notice_id"), "title": doc.get("title"), "status": doc.get("status")}
    if role == "pilot":
        if coll == "notifications" and doc.get("user_id") == user["user_id"]:
            return "alert", doc
        if coll == "flights" and doc.get("pilot_id") == user["user_id"]:
            return "flight", {"flight_id": doc.get("flight_id"), "status": doc.get("status")}
        return None
    if role == "official":
        if coll == "breaches":
            return "breach", doc
        if coll == "flights" and routing.visible_to(user, doc):
            return "flight", {"flight_id": doc.get("flight_id"), "status": doc.get("status")}
    return None


@router.get("/events")
async def event_stream(request: Request, authorization: Optional[str] = Header(default=None), token: Optional[str] = Query(default=None)):
    """Server-sent events. A browser EventSource cannot send headers, so the token may come in the query string."""
    user = get_current_user(authorization, token)
    if user is None:
        raise HTTPException(401, "sign in required")
    loop = asyncio.get_running_loop()
    aq: asyncio.Queue = asyncio.Queue(maxsize=500)
    push = events.subscribe(lambda ev: loop.call_soon_threadsafe(_put, aq, ev))

    async def gen():
        try:
            yield f"event: ready\ndata: {json.dumps({'mode': events.status['mode']})}\n\n"
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(aq.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                out = shape(ev, user)
                if out:
                    yield f"event: {out[0]}\ndata: {json.dumps(out[1], default=str)}\n\n"
        finally:
            events.unsubscribe(push)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _put(q, ev):
    try:
        q.put_nowait(ev)
    except asyncio.QueueFull:
        pass


@router.get("/events/status")
def event_status(admin=Depends(require_admin)):
    """How events are being produced right now, for the admin's Insights tab."""
    return {**events.status, "watching": list(events.status["watching"])}
