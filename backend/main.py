"""FastAPI app. Contract: see API.md. Run: uvicorn main:app --reload (from backend/)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from explain import NEXT_STEPS, explain
from search import get_store
from sim import sample_route, summarize_route
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


def evaluate(lat, lng, drone, when):
    """Run the whole pipeline for one point. Returns (verdict, near, notices, used_rules)."""
    near = store.zones_near(lat, lng)
    notices = store.notices_at(lat, lng, when)
    zone_types = {z["zone_type"] for z in near if z["inside"]} | ({"notice"} if notices else set())
    rules = store.rules_for(zone_types, drone["class"], query=f"{drone['class']} drone {' '.join(zone_types)}")
    by_type = {}
    for r in rules:
        by_type.setdefault(r["zone_type"], []).append(r)
    verdict, used = decide(lat, lng, drone["class"], near, notices, by_type)
    return verdict, near, notices, used


def parse_when(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def get_drone(drone_id):
    drone = store.get_drone(drone_id)
    if drone is None:
        raise HTTPException(404, f"unknown drone_id {drone_id}")
    return drone


@app.post("/check")
def check(req: CheckRequest):
    drone = get_drone(req.drone_id)
    verdict, near, notices, used = evaluate(req.lat, req.lng, drone, parse_when(req.datetime))
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
