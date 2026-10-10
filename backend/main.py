"""FastAPI app. Contract: see API.md. Run: uvicorn main:app --reload (from backend/)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from explain import NEXT_STEPS, explain
from analytics import router as analytics_router
from ask import router as ask_router
from auth import router as auth_router, setup_indexes as auth_indexes
import bridge
from bridge import router as bridge_router
from config_api import router as config_router
from events_api import router as events_router
from live import router as live_router, sim_router
from mappls_api import router as mappls_router
from verification import router as verification_router
from zones_api import router as zones_router
from pipeline import evaluate, get_drone, parse_when, store
import routing
import runtime
from sim import sample_route, summarize_route

app = FastAPI(title="SkyClear")


@app.on_event("startup")
def _start_change_streams():
    import events
    events.start_watchers()  # MongoDB change streams feed the live event channel (does nothing without MongoDB)


@app.on_event("startup")
def _close_interrupted_flights():
    """The simulator lives in memory, so after a restart no drone is really flying. End those flights instead of leaving them 'flying' forever."""
    for f in runtime.all_("flights"):
        if f.get("status") == "flying":
            runtime.update("flights", "flight_id", f["flight_id"], {"status": "completed", "flight_log": {**(f.get("flight_log") or {}), "interrupted": True, "ended_at": runtime.now_iso()}})


@app.on_event("startup")
async def _attach_simulator():
    """Give the simulator the server's event loop, so a flight launched from any request can start the 1 Hz loop."""
    import asyncio
    from simulator.fleet import get_fleet_simulator
    get_fleet_simulator().attach_loop(asyncio.get_running_loop())


@app.on_event("startup")
def _warm_up_model():
    import llm
    llm.warm_up()  # loads the model on the Ollama laptop in the background (does nothing when USE_LLM=0)
# Bearer tokens, no cookies, so a page opened from a file can still talk to the API in development.
app.add_middleware(GZipMiddleware, minimum_size=1000)  # zone maps are large JSON: gzip makes them several times smaller
import metrics  # noqa: E402
app.add_middleware(metrics.Middleware)
app.include_router(metrics.router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(config_router)
app.include_router(events_router)
app.include_router(ask_router)
from simulator.fleet import get_fleet_simulator as _fleet_sim  # noqa: E402
_fleet_sim().on_landed = bridge.complete_flight
_fleet_sim().on_breach = bridge.on_drone_breach
app.include_router(auth_router)
app.include_router(bridge_router)
app.include_router(zones_router)
app.include_router(mappls_router)
app.include_router(live_router)
app.include_router(sim_router)
app.include_router(analytics_router)
app.include_router(verification_router)
routing.setup()
auth_indexes()


class CheckRequest(BaseModel):
    lat: float
    lng: float
    drone_id: str
    datetime: Optional[str] = None
    explain: bool = True  # False: answer at once with the plain explanation. The page then asks again with True to get the AI wording


@app.get("/health")
def health():
    return {"ok": True, "mongo": config.USE_MONGO, "llm": config.USE_LLM, "ollama_url": config.OLLAMA_URL if config.USE_LLM else None}


@app.get("/health/llm")
def health_llm():
    """For the UI: is the language model connected? Never fails, a missing model just means plain answers."""
    import llm
    s = llm.status()
    return {k: s[k] for k in ("enabled", "reachable", "llm_model_ready", "embed_model_ready")}


@app.get("/drones")
def drones():
    return store.all_drones()


@app.post("/check")
def check(req: CheckRequest):
    drone = get_drone(req.drone_id)
    verdict, near, notices, used = evaluate(req.lat, req.lng, drone, parse_when(req.datetime))
    use_ai = config.USE_LLM and req.explain
    extra = store.search_rules(f"{drone['class']} drone {' '.join(z['zone_type'] for z in near if z['inside'])}", k=3) \
        if use_ai and hasattr(store, "search_rules") else []
    summary, cited_ids, source = explain(verdict, near, notices, used, drone=drone if use_ai else None, extra_rules=extra)
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
    active_geoms = [z["geometry"] for z in store.all_zones_geojson().get("features", [])] + \
                   [n.get("geometry") or n.get("area") for n in store.active_notices() if n.get("geometry") or n.get("area")]
    pts = sample_route([(w.lat, w.lng) for w in req.waypoints], req.speed_mps, geometries=active_geoms)
    for p in pts:
        verdict, near, notices, used = evaluate(p["lat"], p["lng"], drone, start + timedelta(seconds=p["t_s"]))
        p["verdict"] = verdict
        p["zones"] = [z["name"] for z in near if z["inside"]] + [n["title"] for n in notices]
        p["rule_ids"] = [r["rule_id"] for r in used]
    return {"drone": drone, "samples": pts, "summary": summarize_route(pts),
            "data_last_updated": config.DATA_LAST_UPDATED, "disclaimer": config.DISCLAIMER}


# Must be last: serves the frontend at the same origin as the API.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

