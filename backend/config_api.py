"""What the front end needs to know, so nothing about the place is typed into the UI.

/config.js   a script that sets window.SKYCLEAR (loaded before the app code)
/config      the same as JSON
/examples    real spots and a route built from the zones in the database, for the "try an example" buttons
OWNER: Nikhil (stream 1).
"""
import json
import socket

from fastapi import APIRouter, Request
from fastapi.responses import Response

import config
from pipeline import store

router = APIRouter()


def public_config():
    r = config.REGION
    import runtime
    has_admin = any(u["role"] == "official" and not u.get("authority_id") for u in runtime.all_("users"))
    return {"city": r["name"], "center": r["center"], "zoom": r["zoom"], "searchViewbox": r["search_viewbox"], "countryCode": r["country_code"],
            "droneClasses": config.DRONE_CLASSES, "otpChannel": config.OTP_CHANNEL, "llm": config.USE_LLM, "googleClientId": config.GOOGLE_CLIENT_ID,
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


def _rule_zone_types():
    """Zone types we hold a rule for. A spot in any other zone can only be answered with "can't determine"."""
    if hasattr(store, "rules"):
        return {r["zone_type"] for r in store.rules}
    return set(store.db.rules.distinct("zone_type"))


@router.get("/examples")
def examples():
    """One real spot per kind of zone that we can answer for, one clear spot, and a route across the first airport zone."""
    answerable = _rule_zone_types()
    feats = [f for f in store.all_zones_geojson()["features"] if f["properties"]["zone_type"] in answerable]
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


@router.get("/lan")
def lan(request: Request):
    """This computer's address on the local network, so the big screen can put a QR code a phone can open (localhost would not work from a phone)."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent, this only asks the system which network address it would use
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    port = request.url.port or 8000
    return {"urls": [f"http://{ip}:{port}" for ip in ips if not ip.startswith("127.")], "port": port}
