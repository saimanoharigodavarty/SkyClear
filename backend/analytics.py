"""Authority analytics with MongoDB aggregation pipelines. OWNER: stream 4. Contract: docs/CONTRACTS.md.

TODO (stream 4): heatmap of planned flights by area, breaches per zone, median time to decision.
"""
from fastapi import APIRouter

from pipeline import store

router = APIRouter(prefix="/analytics")


@router.get("/summary")
def summary():
    return {"zones": len(store.all_zones_geojson()["features"]), "heatmap": [], "breaches_by_zone": [], "median_decision_minutes": None}
