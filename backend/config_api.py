"""What the front end needs to know, so nothing about the place is typed into the UI.

/config.js   a script that sets window.SKYCLEAR (loaded before the app code)
/config      the same as JSON
/examples    real spots and a route built from the zones in the database, for the "try an example" buttons
OWNER: Nikhil (stream 1).
"""
import json

from fastapi import APIRouter
from fastapi.responses import Response

import config
from pipeline import store

router = APIRouter()


def public_config():
    r = config.REGION
    import runtime
    has_admin = any(u["role"] == "official" and not u.get("authority_id") for u in runtime.all_("users"))
    return {"city": r["name"], "center": r["center"], "zoom": r["zoom"], "searchViewbox": r["search_viewbox"], "countryCode": r["country_code"],
            "droneClasses": config.DRONE_CLASSES, "otpChannel": config.OTP_CHANNEL, "llm": config.USE_LLM,
            # No secrets here: only whether first-time setup is needed and whether generated development logins exist on this machine.
            "needsAdmin": not has_admin, "devLogins": (config.DATA_DIR / "demo_credentials.txt").exists()}


@router.get("/config")
def get_config():
    return public_config()


@router.get("/config.js")
def config_js():
    return Response("window.SKYCLEAR = " + json.dumps(public_config()) + ";", media_type="application/javascript", headers={"Cache-Control": "no-store"})


def _center(geometry):
    ring = geometry["coordinates"][0]
    return sum(y for _, y in ring) / len(ring), sum(x for x, _ in ring) / len(ring)


@router.get("/examples")
def examples():
    """One real spot per kind of zone, one clear spot, and a route across the first airport zone."""
    feats = store.all_zones_geojson()["features"]
    center = config.REGION["center"]
    out, seen, route = [], set(), None
    for f in sorted(feats, key=lambda f: abs(_center(f["geometry"])[0] - center[0]) + abs(_center(f["geometry"])[1] - center[1])):
        p = f["properties"]
        lat, lng = _center(f["geometry"])
        if not (abs(lat - center[0]) < 0.6 and abs(lng - center[1]) < 0.6):
            continue  # only places in this city
        if p["zone_type"] not in seen:
            seen.add(p["zone_type"])
            out.append({"label": p["name"], "kind": p["zone_type"], "lat": round(lat, 5), "lng": round(lng, 5), "droneClass": "nano" if p["zone_type"] == "park" else None})
        if route is None and p["zone_type"] == "airport":
            route = [[round(lat - 0.09, 5), round(lng, 5)], [round(lat + 0.09, 5), round(lng, 5)]]
    for dlat, dlng in [(0, 0), (0.03, 0.03), (-0.03, 0.03), (0.03, -0.03), (-0.05, 0), (0, 0.05)]:
        lat, lng = center[0] + dlat, center[1] + dlng
        if not any(z["inside"] for z in store.zones_near(lat, lng)):
            out.append({"label": "An open area", "kind": "clear", "lat": round(lat, 5), "lng": round(lng, 5), "droneClass": None})
            break
    return {"spots": out, "route": route}
