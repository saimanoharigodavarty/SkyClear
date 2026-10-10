"""FastAPI app. Contract: see API.md. Run: uvicorn main:app --reload (from backend/)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from explain import NEXT_STEPS, explain
from analytics import router as analytics_router
from bridge import router as bridge_router
from live import router as live_router
from zones_api import router as zones_router
from pipeline import evaluate, get_drone, parse_when, store
import runtime
from sim import sample_route, summarize_route

app = FastAPI(title="SkyClear")
app.include_router(bridge_router)
app.include_router(zones_router)
app.include_router(live_router)
app.include_router(analytics_router)
runtime.seed_official()


class CheckRequest(BaseModel):
    lat: float
    lng: float
    drone_id: str
    datetime: Optional[str] = None


@app.get("/health")
def health():
    return {"ok": True, "mongo": config.USE_MONGO, "llm": config.USE_LLM, "ollama_url": config.OLLAMA_URL if config.USE_LLM else None}


@app.get("/drones")
def drones():
    return store.all_drones()


@app.post("/check")
def check(req: CheckRequest):
    drone = get_drone(req.drone_id)
    verdict, near, notices, used = evaluate(req.lat, req.lng, drone, parse_when(req.datetime))
    extra = store.search_rules(f"{drone['class']} drone {' '.join(z['zone_type'] for z in near if z['inside'])}", k=3) \
        if config.USE_LLM and hasattr(store, "search_rules") else []
    summary, cited_ids, source = explain(verdict, near, notices, used, drone=drone, extra_rules=extra)
    by_id = {r["rule_id"]: r for r in [*extra, *used]}
    return {
        "verdict": verdict,
        "summary": summary,
        "zones": [{k: z[k] for k in ("zone_id", "name", "zone_type", "distance_km", "geometry")} for z in near],
        "notices": [{k: n[k] for k in ("notice_id", "title", "starts_at", "ends_at", "geometry")} for n in notices],
        "citations": [{"rule_id": i, "text": by_id[i]["text"], "source": by_id[i]["source"]} for i in cited_ids if i in by_id],
        "explained_by": source,
        "next_steps": NEXT_STEPS[verdict],
        "data_last_updated": config.DATA_LAST_UPDATED,
        "disclaimer": config.DISCLAIMER,
    }


class Waypoint(BaseModel):
    lat: float
    lng: float


class RouteRequest(BaseModel):
    drone_id: str
    waypoints: list[Waypoint]
    speed_mps: float = 10.0
    datetime: Optional[str] = None


@app.post("/simulate/route")
def simulate_route(req: RouteRequest):
    """Simulated flight: check the route every ~100 m with the same engine as /check."""
    if len(req.waypoints) < 2:
        raise HTTPException(422, "need at least 2 waypoints")
    drone = get_drone(req.drone_id)
    start = parse_when(req.datetime)
    pts = sample_route([(w.lat, w.lng) for w in req.waypoints], req.speed_mps)
    for p in pts:
        verdict, near, notices, used = evaluate(p["lat"], p["lng"], drone, start + timedelta(seconds=p["t_s"]))
        p["verdict"] = verdict
        p["zones"] = [z["name"] for z in near if z["inside"]] + [n["title"] for n in notices]
        p["rule_ids"] = [r["rule_id"] for r in used]
    return {"drone": drone, "samples": pts, "summary": summarize_route(pts),
            "data_last_updated": config.DATA_LAST_UPDATED, "disclaimer": config.DISCLAIMER}


# Must be last: serves the frontend at the same origin as the API.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
