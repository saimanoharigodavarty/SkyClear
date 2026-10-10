"""Live airspace: simulated drone positions, breaches, event stream. OWNER: stream 3 (simulation). Contract: docs/CONTRACTS.md.

Stub that already answers with the right shape so the frontend can be built against it.
TODO (stream 3): read the telemetry time-series collection, run the geofence engine, stream breaches from a MongoDB change stream.
"""
import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/live")


@router.get("/drones")
def live_drones(bbox: str = ""):
    """Latest position of every simulated drone in the box. Empty until the simulator is built."""
    return {"drones": [], "as_of": None}


@router.get("/stream")
async def live_stream():
    """Server-sent events: event types are ping, position, breach, alert. Only ping for now."""
    async def gen():
        while True:
            yield f"event: ping\ndata: {json.dumps({'ok': True})}\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(gen(), media_type="text/event-stream")
