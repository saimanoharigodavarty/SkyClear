"""The pilot and official sides of SkyClear: accounts, drones, flight requests, official notices, alerts.

OWNER: platform teammate. Prototype auth: bearer token from /auth/login, roles "pilot" and "official".
"""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import config
import permits
import routing
import runtime
from geo import circle, point_in_polygon
from pipeline import evaluate, get_drone, parse_when
from security import current_user, public_user, require

router = APIRouter()
ACTIVE_FLIGHT = ("watching", "requested", "approved")


# ---- auth ----
class Register(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=8, max_length=100)
    pilot_cert: Optional[str] = Field(default=None, max_length=40)


class Login(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
def register(body: Register):
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "enter a valid email")
    if any(u["email"] == email for u in runtime.all_("users")):
        raise HTTPException(409, "an account with this email already exists")
    user = runtime.insert("users", {"user_id": runtime.new_id("U"), "role": "pilot", "name": body.name.strip(),
                                    "email": email, "pilot_cert": body.pilot_cert,
                                    "password": runtime.hash_password(body.password), "created_at": runtime.now_iso()})
    return {"token": runtime.create_session(user["user_id"]), "user": public_user(user)}


@router.post("/auth/login")
def login(body: Login):
    email = body.email.strip().lower()
    user = next((u for u in runtime.all_("users") if u["email"] == email), None)
    if user is None or not runtime.check_password(body.password, user["password"]):
        raise HTTPException(401, "wrong email or password")
    return {"token": runtime.create_session(user["user_id"]), "user": public_user(user)}


@router.get("/me")
def me(user=Depends(current_user)):
    return public_user(user)


# ---- pilot drones ----
def drone_class(weight_g):
    if weight_g <= 250:
        return "nano"
    if weight_g <= 2000:
        return "micro"
    if weight_g <= 25000:
        return "small"
    return "medium"


class DroneIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    weight_g: int = Field(gt=0, le=150000)
    uin: Optional[str] = Field(default=None, max_length=40)


@router.get("/me/drones")
def my_drones(user=Depends(require("pilot"))):
    return [d for d in runtime.all_("drones") if d["owner_id"] == user["user_id"]]


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
    return {**f, "permit": permits.view(permit)}


@router.post("/flights/{flight_id}/preflight")
def preflight(flight_id: str, user=Depends(require("pilot"))):
    f = _get_flight(flight_id)
    if f["pilot_id"] != user["user_id"]:
        raise HTTPException(403, "not your flight")
    result = permits.preflight(f, user)
    runtime.update("flights", "flight_id", flight_id, {"last_preflight": {k: result[k] for k in ("cleared", "reasons", "checked_at")}})
    return result


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
    p = runtime.update("permits", "permit_id", permit_id, {"status": "revoked", "revoked_by": user["name"], "revoked_reason": body.reason.strip(), "revoked_at": runtime.now_iso()})
    runtime.update("flights", "flight_id", f["flight_id"], {"status": "revoked"})
    notify(f["pilot_id"], "permit", f"Permit {permit_id} revoked", f"{user['name']} revoked your permit: {body.reason.strip()}. You are not cleared to fly.",
           severity="high", flight_id=f["flight_id"])
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
    lat: float
    lng: float
    radius_km: float = Field(gt=0, le=25)
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


@router.post("/notices")
def publish_notice(body: NoticeIn, user=Depends(require("official"))):
    if parse_when(body.ends_at) <= parse_when(body.starts_at):
        raise HTTPException(422, "end must be after start")
    notice = runtime.insert("notices", {
        "notice_id": runtime.new_id("RN"), "title": body.title.strip(), "text": body.note.strip(),
        "status": "active", "origin": "official", "starts_at": body.starts_at, "ends_at": body.ends_at,
        "center": {"lat": body.lat, "lng": body.lng}, "radius_km": body.radius_km,
        "area": circle(body.lat, body.lng, body.radius_km),
        "source": f"Published by {user['name']}", "published_by": user["name"], "published_at": runtime.now_iso()})
    hit = _affected(notice)
    for f in hit:
        notify(f["pilot_id"], "notice", f"Restriction: {notice['title']}",
               f"A restriction overlaps your flight {f['flight_id']} ({_window(notice)}). Do not fly in this area during this time unless the authority says otherwise.",
               severity="high", flight_id=f["flight_id"])
    return {**notice, "affected_flights": len(hit), "conflicting_permits": permits.conflicting_permits(notice)}


@router.post("/notices/{notice_id}/cancel")
def cancel_notice(notice_id: str, user=Depends(require("official"))):
    n = next((n for n in runtime.all_("notices") if n["notice_id"] == notice_id), None)
    if n is None:
        raise HTTPException(404, "notice not found")
    if n["status"] != "active":
        raise HTTPException(409, "notice is not active")
    hit = _affected(n)
    n = runtime.update("notices", "notice_id", notice_id, {"status": "cancelled"})
    for f in hit:
        notify(f["pilot_id"], "notice", f"Cancelled: {n['title']}",
               f"The restriction that overlapped your flight {f['flight_id']} was cancelled. Re-check before you fly.",
               severity="info", flight_id=f["flight_id"])
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
