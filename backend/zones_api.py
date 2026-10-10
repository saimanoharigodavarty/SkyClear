"""Zones API. OWNER: Manohari (stream 4, MongoDB data and RAG). Contract: docs/CONTRACTS.md.

GET /zones                      all zones (small areas only)
GET /zones?bbox=w,s,e,n         only zones that touch the box, this is what the map calls on every pan and zoom
GET /zones/search?q=            search box by zone name
"""
from typing import Optional

from fastapi import APIRouter, HTTPException

import time

from pipeline import store

router = APIRouter()


_cache = {}  # zones change rarely: the same request within 5 seconds is answered from memory


def _cached(key, make):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < 5:
        return hit[1]
    if len(_cache) > 300:
        _cache.clear()
    out = make()
    _cache[key] = (time.monotonic(), out)
    return out


@router.get("/zones")
def zones(bbox: Optional[str] = None):
    if bbox is None:
        return _cached("all", store.all_zones_geojson)
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be west,south,east,north")
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise HTTPException(422, "bbox out of range")
    return _cached((round(w, 3), round(s, 3), round(e, 3), round(n, 3)), lambda: store.zones_in_bbox(w, s, e, n))


@router.get("/zones/search")
def zones_search(q: str):
    """Search box: zones whose name matches q, each with a map centre. Contract 8."""
    if len(q.strip()) < 2:
        return []
    return store.search_zones(q)
