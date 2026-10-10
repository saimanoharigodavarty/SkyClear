"""Zones API. OWNER: stream 4 (MongoDB data and RAG). Contract: docs/CONTRACTS.md.

GET /zones                      all zones (small areas only)
GET /zones?bbox=w,s,e,n         only zones that touch the box, this is what the map calls on every pan and zoom
"""
from typing import Optional

from fastapi import APIRouter, HTTPException

from pipeline import store

router = APIRouter()


@router.get("/zones")
def zones(bbox: Optional[str] = None):
    if bbox is None:
        return store.all_zones_geojson()
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be west,south,east,north")
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise HTTPException(422, "bbox out of range")
    return store.zones_in_bbox(w, s, e, n)
