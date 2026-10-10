"""FastAPI app. Contract: see API.md. Run: uvicorn main:app --reload (from backend/)."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from explain import NEXT_STEPS, explain
from search import get_store
from verdict import decide

app = FastAPI(title="SkyClear")
store = get_store()


class CheckRequest(BaseModel):
    lat: float
    lng: float
    drone_id: str
    datetime: Optional[str] = None


@app.get("/health")
def health():
    return {"ok": True, "mongo": config.USE_MONGO, "llm": config.USE_LLM}


@app.get("/drones")
def drones():
    return store.all_drones()


@app.get("/zones")
def zones():
    return store.all_zones_geojson()


@app.post("/check")
def check(req: CheckRequest):
    drone = store.get_drone(req.drone_id)
    if drone is None:
        raise HTTPException(404, f"unknown drone_id {req.drone_id}")
    when = datetime.fromisoformat(req.datetime.replace("Z", "+00:00")) if req.datetime else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    near = store.zones_near(req.lat, req.lng)
    notices = store.notices_at(req.lat, req.lng, when)
    zone_types = {z["zone_type"] for z in near if z["inside"]} | ({"notice"} if notices else set())
    rules = store.rules_for(zone_types, drone["class"], query=f"{drone['class']} drone {' '.join(zone_types)}")
    by_type = {}
    for r in rules:
        by_type.setdefault(r["zone_type"], []).append(r)

    verdict, used = decide(req.lat, req.lng, drone["class"], near, notices, by_type)
    summary, cited_ids = explain(verdict, near, notices, used)
    return {
        "verdict": verdict,
        "summary": summary,
        "zones": [{k: z[k] for k in ("zone_id", "name", "zone_type", "distance_km", "geometry")} for z in near],
        "notices": [{k: n[k] for k in ("notice_id", "title", "starts_at", "ends_at", "geometry")} for n in notices],
        "citations": [{"rule_id": r["rule_id"], "text": r["text"], "source": r["source"]}
                      for r in used if r["rule_id"] in cited_ids],
        "next_steps": NEXT_STEPS[verdict],
        "data_last_updated": config.DATA_LAST_UPDATED,
        "disclaimer": config.DISCLAIMER,
    }


# Must be last: serves the frontend at the same origin as the API.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
