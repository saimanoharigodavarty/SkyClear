"""The pilot and official sides of SkyClear: accounts, drones, flight requests, official notices, alerts.

OWNER: platform teammate. Prototype auth: bearer token from /auth/login, roles "pilot" and "official".
"""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import config
import permits
import routing
import runtime
from geo import circle, point_in_polygon, ring_center_radius_km, ring_from_points
from pipeline import evaluate, get_drone, parse_when
from security import current_user, flight_claims, make_pair_token, require, require_admin

router = APIRouter()
ACTIVE_FLIGHT = ("watching", "requested", "approved", "cleared", "flying")


# ---- auth ----
# ---- pilot drones ----
def drone_class(weight_g):
    for c in config.DRONE_CLASSES:
        if weight_g <= c["max_g"]:
            return c["name"]
    return config.DRONE_CLASSES[-1]["name"]


class DroneIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    weight_g: int = Field(gt=0, le=150000)
    uin: Optional[str] = Field(default=None, max_length=40)


@router.get("/me/drones")
def my_drones(user=Depends(require("pilot"))):
    return [d for d in runtime.all_("drones") if d.get("owner_id") == user["user_id"]]


@router.post("/me/drones")
def add_drone(body: DroneIn, user=Depends(require("pilot"))):
    return runtime.insert("drones", {"drone_id": runtime.new_id("D"), "owner_id": user["user_id"],
                                     "name": body.name.strip(), "weight_g": body.weight_g,
                                     "class": drone_class(body.weight_g), "uin": body.uin,
                                     "registration": "self-declared, not verified", "verification": {"status": "unverified"}})


# ---- alerts ----
def notify(user_id, kind, title, body, severity="info", flight_id=None):
    runtime.insert("notifications", {"notification_id": runtime.new_id("A"), "user_id": user_id, "kind": kind,
                                     "title": title, "body": body, "severity": severity,
                                     "flight_id": flight_id, "created_at": runtime.now_iso(), "read": False})


@router.get("/notifications")
def notifications(user=Depends(require("pilot"))):
    mine = [n for n in runtime.all_("notifications") if n["user_id"] == user["user_id"]]
    mine.sort(key=lambda n: n["created_at"], reverse=True)
    return {"unread": sum(not n["read"] for n in mine), "items": mine[:50]}


@router.post("/notifications/read")
def read_all(user=Depends(require("pilot"))):
    runtime.mark_read(user["user_id"])
    return {"ok": True}


# ---- flights (watch a flight, or request permission for it) ----
class FlightIn(BaseModel):
    drone_id: str
    lat: float
    lng: float
    start: str
    end: str
    purpose: str = Field(default="", max_length=200)
    kind: Literal["watch", "permission"] = "watch"


def _flight_view(f):
    return {k: v for k, v in f.items()}


@router.post("/flights")
def create_flight(body: FlightIn, user=Depends(require("pilot"))):
    drone = get_drone(body.drone_id)
    if drone.get("owner_id") not in (None, user["user_id"]):
        raise HTTPException(403, "this drone is not on your account")
    start, end = parse_when(body.start), parse_when(body.end)
    if end <= start:
        raise HTTPException(422, "end must be after start")
    verdict, near, notices, used = evaluate(body.lat, body.lng, drone, start)
    routed = None
    if body.kind == "permission":
        if verdict == "prohibited":
            raise HTTPException(400, "Flying here is prohibited for this drone. Permission cannot be requested.")
        if verdict == "can_fly":
            raise HTTPException(400, "No restriction found in our data, so there is nothing to request permission for. Use Watch instead.")
        if config.REQUIRE_VERIFICATION:
            if (user.get("verification") or {}).get("status") != "verified":
                raise HTTPException(403, "pilot_not_verified: get your pilot certificate verified first (Flights tab)")
            if (drone.get("verification") or {}).get("status") != "verified":
                raise HTTPException(403, "drone_not_verified: get this drone verified first (Flights tab)")
        routed = routing.route(body.lat, body.lng, [z for z in near if z["inside"]])
        if routed is None:
            raise HTTPException(422, "no_authority_for_area: no authority is registered for this area in our data. Use the official portal.")
    flight = runtime.insert("flights", {
        "flight_id": runtime.new_id("F"), "pilot_id": user["user_id"], "pilot_name": user["name"],
        "pilot_cert": user.get("pilot_cert"), "drone_id": drone["drone_id"], "drone_name": drone["name"],
        "drone_class": drone["class"], "uin": drone.get("uin"), "lat": body.lat, "lng": body.lng,
        "start": body.start, "end": body.end, "purpose": body.purpose.strip(), "kind": body.kind,
        "status": "requested" if body.kind == "permission" else "watching", "verdict": verdict,
        "zones": [z["name"] for z in near if z["inside"]] + [n["title"] for n in notices],
        "rule_ids": [r["rule_id"] for r in used], "decision": None, "created_at": runtime.now_iso(),
        "authority_id": routed["authority"]["authority_id"] if routed else None, "routed_to": routed, "permit_id": None})
    return flight


@router.get("/flights")
def list_flights(status: Optional[str] = None, user=Depends(current_user)):
    flights = runtime.all_("flights")
    if user["role"] == "pilot":
        flights = [f for f in flights if f["pilot_id"] == user["user_id"]]
    else:
        flights = [f for f in flights if routing.visible_to(user, f)]
    if status:
        flights = [f for f in flights if f["status"] == status]
    out = []
    for f in sorted(flights, key=lambda f: f["created_at"], reverse=True):
        p = permits.view(permits.get_permit(f["permit_id"])) if f.get("permit_id") else None
        out.append({**f, "overdue": routing.overdue(f), "permit": p})
    return out


def _get_flight(flight_id):
    f = next((f for f in runtime.all_("flights") if f["flight_id"] == flight_id), None)
    if f is None:
        raise HTTPException(404, "flight not found")
    return f


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=300)
    alt_max_m: int = Field(default=60, ge=10, le=400)
    conditions: List[str] = Field(default_factory=list, max_length=10)


@router.post("/flights/{flight_id}/decision")
def decide_flight(flight_id: str, body: Decision, user=Depends(require("official"))):
    f = _get_flight(flight_id)
    if not routing.visible_to(user, f):
        raise HTTPException(403, "this request is routed to a different authority")
    if f["status"] != "requested":
        raise HTTPException(409, "this request has already been decided or cancelled")
    if body.decision == "rejected" and not body.comment.strip():
        raise HTTPException(422, "give a reason when rejecting")
    changes = {"status": body.decision, "decision": {"by": user["name"], "comment": body.comment.strip(), "at": runtime.now_iso()}}
    permit = None
    # One transaction: the permit, the new flight status, the pilot's alert and the audit entry are written together or not at all.
    with runtime.atomic():
        if body.decision == "approved":
            conditions = [c.strip() for c in body.conditions if c.strip()]
            permit = permits.issue(f, get_drone(f["drone_id"]), user, body.alt_max_m, conditions)
            changes["permit_id"] = permit["permit_id"]
        f = runtime.update("flights", "flight_id", flight_id, changes)
        word = "approved" if body.decision == "approved" else "rejected"
        extra = f" Permit {permit['permit_id']}, maximum {permit['alt_max_m']} m." if permit else ""
        notify(f["pilot_id"], "decision", f"Permission {word}",
               f"{user['name']} {word} your request {f['flight_id']}.{extra} " + (body.comment.strip() or ""),
               severity="info" if body.decision == "approved" else "high", flight_id=flight_id)
        runtime.audit(user, f"permission_{body.decision}", flight_id, (permit["permit_id"] + ". " if permit else "") + body.comment.strip())
    return {**f, "permit": permits.view(permit)}


@router.post("/flights/{flight_id}/preflight")
def preflight(flight_id: str, user=Depends(require("pilot"))):
    f = _get_flight(flight_id)
    if f["pilot_id"] != user["user_id"]:
        raise HTTPException(403, "not your flight")
    result = permits.preflight(f, user)
    changes = {"last_preflight": {k: result[k] for k in ("cleared", "reasons", "checked_at")}}
    if result["cleared"] and f["status"] in ("approved", "watching"):
        changes.update({"status": "cleared", "cleared_until": result["cleared_until"], "before_clearance": f["status"]})
    elif result["cleared"] and f["status"] == "cleared":
        changes["cleared_until"] = result["cleared_until"]
    elif not result["cleared"] and f["status"] == "cleared":
        changes.update({"status": f.get("before_clearance") or "approved", "cleared_until": None})  # clearance is lost the moment a check fails
    runtime.update("flights", "flight_id", flight_id, changes)
    return result


def _fleet():
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from simulator.fleet import get_fleet_simulator
    return get_fleet_simulator()


class LaunchIn(BaseModel):
    mode: Literal["auto", "manual"] = "auto"   # auto: flies its route. manual: flown live from the phone


@router.post("/flights/{flight_id}/launch")
def launch_flight(flight_id: str, body: LaunchIn = LaunchIn(), user=Depends(require("pilot"))):
    """Take off (simulated). Only a flight that passes preflight right now can launch."""
    f = _get_flight(flight_id)
    if f["pilot_id"] != user["user_id"]:
        raise HTTPException(403, "not your flight")
    if f["status"] == "flying":
        raise HTTPException(409, "this flight is already in the air")
    if f["status"] != "cleared":
        raise HTTPException(409, "Run preflight first. Only a cleared flight can take off.")
    result = permits.preflight(f, user)  # conditions can change between preflight and takeoff, so check again
    if not result["cleared"]:
        runtime.update("flights", "flight_id", flight_id, {"status": f.get("before_clearance") or "approved", "cleared_until": None})
        raise HTTPException(409, "Not cleared to take off: " + "; ".join(result["reasons"]))
    permit = permits.get_permit(f["permit_id"]) if f.get("permit_id") else None
    drone_id = _fleet().launch_flight(f, permit, alt_max_m=permit["alt_max_m"] if permit else 60, manual=body.mode == "manual")
    return {**runtime.update("flights", "flight_id", flight_id, {"status": "flying", "launched_at": runtime.now_iso(), "cleared_until": None, "breaches": 0, "control": body.mode}), "drone_id": drone_id}


@router.post("/flights/{flight_id}/land")
def land_flight(flight_id: str, authorization: Optional[str] = Header(default=None)):
    """Land the drone now. The pilot, or the phone paired with this flight."""
    actor = flight_claims(flight_id, authorization)
    f = _get_flight(flight_id)
    if actor["role"] != "pilot" or f["pilot_id"] != actor["user_id"]:
        raise HTTPException(403, "not your flight")
    if f["status"] not in ("flying", "recalled"):
        raise HTTPException(409, "this flight is not in the air")
    stats = _fleet().land_flight(flight_id)
    if stats is None:  # the drone already landed (for example it finished its route)
        return _get_flight(flight_id)
    return complete_flight(flight_id, "completed" if f["status"] == "flying" else "recalled", stats)


# ---- flying by phone and showing it on the big screen ----
class Sticks(BaseModel):
    fwd: float = 0.0     # -1 back to 1 forward
    right: float = 0.0   # -1 left to 1 right
    yaw: float = 0.0     # -1 turn left to 1 turn right
    climb: float = 0.0   # -1 down to 1 up


def _owner_only(flight_id, authorization):
    """The pilot who owns the flight, or the phone paired with it. Checked against the drone itself, no database read."""
    actor = flight_claims(flight_id, authorization)
    d = _fleet().get_flight_drone(flight_id)
    if d is None:
        raise HTTPException(409, "this flight is not in the air")
    if actor["role"] != "pilot" or d.owner_id != actor["user_id"]:
        raise HTTPException(403, "not your flight")
    return d


@router.post("/flights/{flight_id}/control")
def control_flight(flight_id: str, body: Sticks, authorization: Optional[str] = Header(default=None)):
    """Stick positions from the phone, sent about ten times a second. If they stop, the drone hovers."""
    d = _owner_only(flight_id, authorization)
    if not d.manual:
        raise HTTPException(409, "the drone is flying itself now (it was recalled or is returning home)")
    d.set_command(body.fwd, body.right, body.yaw, body.climb)
    return {"ok": True}


@router.post("/flights/{flight_id}/home")
def return_home(flight_id: str, authorization: Optional[str] = Header(default=None)):
    """Return home: the drone flies back to where it took off and lands."""
    _owner_only(flight_id, authorization)
    if not _fleet().return_home_flight(flight_id):
        raise HTTPException(409, "the drone is already coming home")
    return {"ok": True}


@router.post("/flights/{flight_id}/pair")
def pair_controller(flight_id: str, user=Depends(require("pilot"))):
    """A short-lived token for a phone to fly this flight. The big screen puts it in a QR code."""
    f = _get_flight(flight_id)
    if f["pilot_id"] != user["user_id"]:
        raise HTTPException(403, "not your flight")
    if f["status"] not in ("flying", "cleared", "approved", "watching"):
        raise HTTPException(409, "this flight cannot be flown now")
    return {"token": make_pair_token(user["user_id"], flight_id), "expires_in": 45 * 60}


@router.get("/flights/{flight_id}/live")
def flight_live(flight_id: str, authorization: Optional[str] = Header(default=None)):
    """Fast live view of one flight for the big screen and the phone: the drone, and its event log. Cheap on purpose, polled several times a second."""
    actor = flight_claims(flight_id, authorization)
    sim = _fleet()
    d = sim.get_flight_drone(flight_id)
    if d is not None and actor["role"] == "pilot" and d.owner_id != actor["user_id"]:
        raise HTTPException(403, "not your flight")
    snap = d.snapshot() if d is not None else None
    return {"flight_id": flight_id, "airborne": d is not None, "drone": snap, "events": sim.flight_events(flight_id)}


@router.get("/flights/{flight_id}/info")
def flight_info(flight_id: str, authorization: Optional[str] = Header(default=None)):
    """The flight itself, with its permit and where it is allowed to fly. Read once by the big screen and the phone."""
    actor = flight_claims(flight_id, authorization)
    f = _get_flight(flight_id)
    if actor["role"] == "pilot" and f["pilot_id"] != actor["user_id"]:
        raise HTTPException(403, "not your flight")
    pm = permits.view(permits.get_permit(f["permit_id"])) if f.get("permit_id") else None
    return {**f, "permit": pm, "pilot_name": f["pilot_name"]}


class Recall(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/flights/{flight_id}/recall")
def recall_flight(flight_id: str, body: Recall, user=Depends(require("official"))):
    """An officer orders a flying drone home, without touching the permit. The pilot is alerted at once."""
    f = _get_flight(flight_id)
    if not routing.visible_to(user, f) and user.get("authority_id") != f.get("authority_id") and user.get("authority_id"):
        raise HTTPException(403, "this flight belongs to a different authority")
    if f["status"] != "flying" or not _fleet().recall_flight(flight_id):
        raise HTTPException(409, "this flight is not in the air")
    with runtime.atomic():
        notify(f["pilot_id"], "recall", "Your drone has been recalled", f"{user['name']} ordered your drone home: {body.reason.strip()}. Land now.", severity="high", flight_id=flight_id)
        runtime.audit(user, "drone_recalled", flight_id, body.reason.strip())
        return runtime.update("flights", "flight_id", flight_id, {"status": "recalled", "recalled_by": user["name"], "recall_reason": body.reason.strip()})


def complete_flight(flight_id, reason, stats):
    """A flight ended: record the log and tell the pilot. Called when the drone lands, from the API or from the simulator."""
    f = next((x for x in runtime.all_("flights") if x["flight_id"] == flight_id), None)
    if f is None:
        return None
    status = "completed" if reason == "completed" else "recalled"
    done = runtime.update("flights", "flight_id", flight_id, {"status": status, "landed_at": stats["landed_at"], "flight_log": stats, "breaches": stats.get("breaches", 0)})
    n = stats.get("breaches", 0)
    notify(f["pilot_id"], "landed", "Flight ended" if status == "completed" else "Drone back home after a recall",
           f"Flight {flight_id} ended. " + (f"Your drone entered restricted airspace {n} time{'s' if n != 1 else ''}." if n else "No restricted airspace was entered."),
           severity="high" if n else "info", flight_id=flight_id)
    return done


def on_drone_breach(breach, drone):
    """A pilot's drone entered restricted airspace: tell the pilot now, and keep the count on the flight."""
    f = next((x for x in runtime.all_("flights") if x["flight_id"] == drone.flight_id), None)
    if f is None:
        return
    runtime.update("flights", "flight_id", f["flight_id"], {"breaches": drone.breach_count})
    notify(f["pilot_id"], "breach", "Your drone entered restricted airspace", f"Your drone is inside {breach['name']}. Return or land now.",
           severity="high", flight_id=f["flight_id"])


@router.get("/permits/{permit_id}")
def get_permit(permit_id: str, user=Depends(current_user)):
    p = permits.get_permit(permit_id)
    if p is None:
        raise HTTPException(404, "permit not found")
    if user["role"] == "pilot" and p["pilot_id"] != user["user_id"]:
        raise HTTPException(403, "not your permit")
    return permits.view(p)


class Revoke(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/permits/{permit_id}/revoke")
def revoke_permit(permit_id: str, body: Revoke, user=Depends(require("official"))):
    p = permits.get_permit(permit_id)
    if p is None:
        raise HTTPException(404, "permit not found")
    f = _get_flight(p["flight_id"])
    if not routing.visible_to(user, f) and user.get("authority_id") != p.get("authority_id"):
        raise HTTPException(403, "this permit belongs to a different authority")
    if p["status"] != "active":
        raise HTTPException(409, "permit is not active")
    was_flying = f["status"] == "flying"
    with runtime.atomic():  # the permit, the flight, the alert and the audit entry change together
        p = runtime.update("permits", "permit_id", permit_id, {"status": "revoked", "revoked_by": user["name"], "revoked_reason": body.reason.strip(), "revoked_at": runtime.now_iso()})
        runtime.update("flights", "flight_id", f["flight_id"], {"status": "recalled" if was_flying else "revoked", "cleared_until": None})
        notify(f["pilot_id"], "permit", f"Permit {permit_id} revoked",
               f"{user['name']} revoked your permit: {body.reason.strip()}. " + ("Your drone has been ordered home. Land now." if was_flying else "You are not cleared to fly."),
               severity="high", flight_id=f["flight_id"])
        runtime.audit(user, "permit_revoked", permit_id, body.reason.strip())
    if was_flying:
        _fleet().recall_flight(f["flight_id"])  # the order to the drone goes out only after the records are safely committed
    return permits.view(p)


@router.get("/authorities")
def authorities(user=Depends(current_user)):
    return [routing.public(a) for a in routing.all_authorities()]


@router.get("/route-preview")
def route_preview(lat: float, lng: float, user=Depends(require("pilot"))):
    """Who would review a permission request at this spot. Shown to the pilot before they ask."""
    from pipeline import store
    zones = [z for z in store.zones_near(lat, lng) if z["inside"]]
    routed = routing.route(lat, lng, zones)
    if routed is None:
        raise HTTPException(422, "no_authority_for_area: no authority is registered for this area in our data. Use the official portal.")
    return routed


@router.post("/flights/{flight_id}/cancel")
def cancel_flight(flight_id: str, user=Depends(require("pilot"))):
    f = _get_flight(flight_id)
    if f["pilot_id"] != user["user_id"]:
        raise HTTPException(403, "not your flight")
    return runtime.update("flights", "flight_id", flight_id, {"status": "cancelled"})


# ---- official notices (VIP movements, events, emergencies) ----
class NoticeIn(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    note: str = Field(default="", max_length=300)
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: Optional[float] = Field(default=None, gt=0, le=25)
    polygon: Optional[list[list[float]]] = None  # corners drawn on the map as [lng, lat], used instead of a circle
    starts_at: str
    ends_at: str


def _overlaps(flight, notice):
    fs, fe = parse_when(flight["start"]), parse_when(flight["end"])
    ns, ne = parse_when(notice["starts_at"]), parse_when(notice["ends_at"])
    return fs <= ne and ns <= fe and point_in_polygon(flight["lng"], flight["lat"], notice["area"])


def _affected(notice):
    return [f for f in runtime.all_("flights") if f["status"] in ACTIVE_FLIGHT and _overlaps(f, notice)]


def _window(n):
    s, e = parse_when(n["starts_at"]), parse_when(n["ends_at"])
    return f"{s.astimezone().strftime('%d %b %H:%M')} to {e.astimezone().strftime('%H:%M')}"


def create_notice(title, note, lat, lng, radius_km, starts_at, ends_at, published_by, actor=None, polygon=None):
    """Publish a restriction: store it, alert the pilots whose flights it touches, and list the permits it conflicts with.
    Used by the officer's form and by the simulation's VIP scenario, so both follow exactly the same path."""
    if polygon:
        ring = ring_from_points(polygon)
        lat, lng, radius_km = ring_center_radius_km(ring)
        area = {"type": "Polygon", "coordinates": [ring]}
    else:
        area = circle(lat, lng, radius_km)
    with runtime.atomic():  # the notice, every pilot's alert and the audit entry are one unit
        notice = runtime.insert("notices", {
            "notice_id": runtime.new_id("RN"), "title": title.strip(), "text": note.strip(),
            "status": "active", "origin": "official", "starts_at": starts_at, "ends_at": ends_at,
            "center": {"lat": lat, "lng": lng}, "radius_km": radius_km,
            "area": area, "shape": "polygon" if polygon else "circle",
            "source": f"Published by {published_by}", "published_by": published_by, "published_at": runtime.now_iso()})
        hit = _affected(notice)
        for f in hit:
            notify(f["pilot_id"], "notice", f"Restriction: {notice['title']}",
                   f"A restriction overlaps your flight {f['flight_id']} ({_window(notice)}). Do not fly in this area during this time unless the authority says otherwise.",
                   severity="high", flight_id=f["flight_id"])
        if actor is not None:
            runtime.audit(actor, "notice_published", notice["notice_id"], f"{notice['title']}, {'drawn boundary' if polygon else str(radius_km) + ' km'}, {len(hit)} flights alerted")
    return {**notice, "affected_flights": len(hit), "conflicting_permits": permits.conflicting_permits(notice)}


@router.post("/notices")
def publish_notice(body: NoticeIn, user=Depends(require("official"))):
    if parse_when(body.ends_at) <= parse_when(body.starts_at):
        raise HTTPException(422, "end must be after start")
    if body.polygon is None and (body.lat is None or body.lng is None or body.radius_km is None):
        raise HTTPException(422, "give a centre and radius, or draw the boundary")
    try:
        return create_notice(body.title, body.note, body.lat, body.lng, body.radius_km, body.starts_at, body.ends_at, user["name"], actor=user, polygon=body.polygon)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/notices/{notice_id}/cancel")
def cancel_notice(notice_id: str, user=Depends(require("official"))):
    n = next((n for n in runtime.all_("notices") if n["notice_id"] == notice_id), None)
    if n is None:
        raise HTTPException(404, "notice not found")
    if n["status"] != "active":
        raise HTTPException(409, "notice is not active")
    hit = _affected(n)
    with runtime.atomic():
        n = runtime.update("notices", "notice_id", notice_id, {"status": "cancelled"})
        for f in hit:
            notify(f["pilot_id"], "notice", f"Cancelled: {n['title']}",
                   f"The restriction that overlapped your flight {f['flight_id']} was cancelled. Re-check before you fly.",
                   severity="info", flight_id=f["flight_id"])
        runtime.audit(user, "notice_cancelled", notice_id, n["title"])
    return {**n, "affected_flights": len(hit)}


@router.get("/notices")
def list_notices(user=Depends(current_user)):
    items = [n for n in runtime.all_("notices") if n.get("origin") == "official"]
    if user["role"] != "official":
        items = [n for n in items if n["status"] == "active"]
    out = []
    for n in sorted(items, key=lambda n: n["published_at"], reverse=True):
        out.append({**n, "affected_flights": len(_affected(n)) if n["status"] == "active" else 0})
    return out


@router.get("/notices/active")
def active_notices():
    """Active restrictions for the map. Prototype: public. See PRODUCT.md C6 about sensitivity."""
    from pipeline import store
    now = parse_when(None)
    out = []
    for n in store.active_notices():
        if parse_when(n["ends_at"]) >= now:
            out.append({k: n.get(k) for k in ("notice_id", "title", "starts_at", "ends_at", "source")} | {"area": n["area"]})
    return out


@router.get("/audit")
def audit_log(limit: int = 50, admin=Depends(require_admin)):
    """What officials did, newest first. Administrators only. Entries are only ever added, never changed."""
    rows = sorted(runtime.all_("audit_log"), key=lambda a: a["ts"], reverse=True)
    return rows[: max(1, min(limit, 200))]


@router.get("/overview")
def overview(user=Depends(require("official"))):
    flights = [f for f in runtime.all_("flights") if routing.visible_to(user, f)]
    return {
        "pending_requests": sum(f["status"] == "requested" for f in flights),
        "approved": sum(f["status"] == "approved" for f in flights),
        "watching": sum(f["status"] == "watching" for f in flights),
        "active_notices": sum(n["status"] == "active" for n in runtime.all_("notices") if n.get("origin") == "official"),
        "pilots": sum(u["role"] == "pilot" for u in runtime.all_("users")),
    }
