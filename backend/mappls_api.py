"""Optional server-side Mappls place search.

Mappls is used only to help a pilot choose a map location. It is never an
airspace authority and its results never create a restriction or a verdict.
"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Query

import config

router = APIRouter()
_ELOC = re.compile(r"^[A-Za-z0-9]{3,32}$")


def _get_json(url):
    try:
        with urlopen(url, timeout=5) as response:  # nosec B310: fixed HTTPS Mappls hosts only
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Mappls is unavailable") from exc


def _params(**items):
    return urlencode({key: value for key, value in items.items() if value is not None and value != ""})


@router.get("/places/search")
def place_search(q: str = Query(min_length=2, max_length=45), lat: float | None = None, lng: float | None = None):
    """Return Mappls suggestions. No key, airspace status or safety claim is returned."""
    if not config.MAPPLS_API_KEY:
        return []
    location = f"{lat},{lng}" if lat is not None and lng is not None else None
    url = "https://search.mappls.com/search/places/autosuggest/json?" + _params(
        query=q.strip(), location=location, region="IND", access_token=config.MAPPLS_API_KEY,
    )
    try:
        data = _get_json(url)
    except RuntimeError:
        return []  # the frontend retains its public-search fallback
    locations = [*data.get("suggestedLocations", []), *data.get("userAddedLocations", [])]
    return [{
        "name": item.get("placeName") or item.get("name") or "Unnamed place",
        "address": item.get("placeAddress") or item.get("address") or "",
        "eloc": item.get("eLoc") or item.get("eloc"),
        "provider": "Mappls place search — not airspace data",
    } for item in locations[:6] if item.get("eLoc") or item.get("eloc")]


@router.get("/places/{eloc}")
def place_detail(eloc: str):
    """Resolve a selected Mappls eLoc to coordinates without disclosing the static key."""
    if not config.MAPPLS_API_KEY:
        raise HTTPException(503, "Mappls place search is not configured")
    if not _ELOC.fullmatch(eloc):
        raise HTTPException(422, "invalid Mappls place ID")
    url = "https://place.mappls.com/O2O/entity/place-details/" + eloc + "?" + _params(access_token=config.MAPPLS_API_KEY)
    try:
        item = _get_json(url)
        lat, lng = float(item["latitude"]), float(item["longitude"])
    except (RuntimeError, KeyError, TypeError, ValueError):
        raise HTTPException(502, "Mappls did not return coordinates for this place")
    return {"name": item.get("name") or item.get("poi") or eloc, "address": item.get("address") or "",
            "lat": lat, "lng": lng, "provider": "Mappls place search — not airspace data"}
