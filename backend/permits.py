"""Permits, preflight, revocation. Contract 10, docs/PERMITS_AND_VERIFICATION.md.

A permit is created when an officer approves a request. It is bound to the pilot, the drone serial, the area
and the time window, and signed by the server. Preflight re-checks everything at takeoff time.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import config
import runtime
from geo import circle, point_in_polygon
from pipeline import evaluate, get_drone, parse_when


def _canonical(p):
    return json.dumps({k: v for k, v in p.items() if k not in ("signature", "status", "revoked_by", "revoked_reason", "revoked_at")}, sort_keys=True, separators=(",", ":"))


def sign(p):
    return hmac.new(config.PERMIT_SECRET.encode(), _canonical(p).encode(), hashlib.sha256).hexdigest()


def valid_signature(p):
    return hmac.compare_digest(sign(p), p.get("signature", ""))


def issue(flight, drone, official, alt_max_m, conditions):
    permit = {"permit_id": runtime.new_id("P"), "flight_id": flight["flight_id"], "pilot_id": flight["pilot_id"],
              "pilot_name": flight["pilot_name"], "drone_id": drone["drone_id"], "serial": drone.get("serial"),
              "area": circle(flight["lat"], flight["lng"], config.PERMIT_RADIUS_KM), "alt_max_m": alt_max_m,
              "starts_at": flight["start"], "ends_at": flight["end"], "conditions": conditions,
              "authority_id": flight.get("authority_id"), "issued_by": official["name"], "issued_at": runtime.now_iso()}
    permit["signature"] = sign(permit)
    permit["status"] = "active"
    return runtime.insert("permits", permit)


def get_permit(permit_id):
    return next((p for p in runtime.all_("permits") if p["permit_id"] == permit_id), None)


def current_permit(flight_id):
    mine = [p for p in runtime.all_("permits") if p["flight_id"] == flight_id]
    return sorted(mine, key=lambda p: p["issued_at"])[-1] if mine else None


def view(p):
    """Permit as shown to clients, with expiry worked out."""
    if p is None:
        return None
    status = p["status"]
    if status == "active" and parse_when(p["ends_at"]) < datetime.now(timezone.utc):
        status = "expired"
    return {**p, "status": status, "signature_ok": valid_signature(p)}


def preflight(flight, pilot, now=None):
    """Re-check everything now. Returns {cleared, reasons, cleared_until, permit, verdict}."""
    now = now or datetime.now(timezone.utc)
    reasons = []
    start, end = parse_when(flight["start"]), parse_when(flight["end"])
    if now < start - timedelta(minutes=config.PREFLIGHT_EARLY_MIN):
        reasons.append("Too early: preflight opens " + str(config.PREFLIGHT_EARLY_MIN) + " minutes before the flight window")
    if now > end:
        reasons.append("The flight window has ended")
    if flight["status"] in ("cancelled", "rejected", "revoked"):
        reasons.append("This flight is " + flight["status"])
    drone = get_drone(flight["drone_id"])
    verdict, near, notices, used = evaluate(flight["lat"], flight["lng"], drone, now)
    permit = current_permit(flight["flight_id"])
    pv = view(permit)
    if verdict == "prohibited":
        why = [z["name"] for z in near if z["inside"]] + [n["title"] for n in notices]
        reasons.append("Flying here is prohibited now" + (": " + ", ".join(why) if why else ""))
    elif verdict == "cannot_determine":
        reasons.append("We cannot determine the rules for this spot. Ask the authority")
    elif verdict == "permission_needed":
        if pv is None:
            reasons.append("This spot needs permission and no permit has been issued")
        else:
            if pv["status"] == "revoked":
                reasons.append("Permit revoked: " + (pv.get("revoked_reason") or "no reason given"))
            elif pv["status"] == "expired":
                reasons.append("Permit expired")
            elif pv["status"] != "active":
                reasons.append("Permit is " + pv["status"])
            if not pv["signature_ok"]:
                reasons.append("Permit signature does not match, it may have been altered")
            if not (parse_when(pv["starts_at"]) - timedelta(minutes=config.PREFLIGHT_EARLY_MIN) <= now <= parse_when(pv["ends_at"])):
                reasons.append("Outside the permit time window")
            if pv.get("serial") != drone.get("serial") or pv["drone_id"] != drone["drone_id"]:
                reasons.append("The drone does not match the permit (serial mismatch)")
            if pv["pilot_id"] != pilot["user_id"]:
                reasons.append("The permit was issued to a different pilot")
            if not point_in_polygon(flight["lng"], flight["lat"], pv["area"]):
                reasons.append("The flight spot is outside the permitted area")
    if config.REQUIRE_VERIFICATION and verdict == "permission_needed":
        if (pilot.get("verification") or {}).get("status") != "verified":
            reasons.append("Pilot is not verified")
        if (drone.get("verification") or {}).get("status") != "verified":
            reasons.append("Drone is not verified")
    cleared = not reasons
    until = None
    if cleared:
        until = min(now + timedelta(minutes=config.PREFLIGHT_VALID_MIN), end).isoformat(timespec="seconds")
    return {"cleared": cleared, "reasons": reasons, "cleared_until": until, "verdict": verdict, "checked_at": now.isoformat(timespec="seconds"),
            "permit": pv, "conditions": pv["conditions"] if pv and cleared else []}


def conflicting_permits(notice):
    """Active permits whose area and time overlap a notice. Shown to the officer who publishes it."""
    ns, ne = parse_when(notice["starts_at"]), parse_when(notice["ends_at"])
    out = []
    for p in runtime.all_("permits"):
        v = view(p)
        if v["status"] != "active":
            continue
        if parse_when(p["starts_at"]) <= ne and ns <= parse_when(p["ends_at"]):
            ring = p["area"]["coordinates"][0]
            cx, cy = sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)
            if point_in_polygon(cx, cy, notice["area"]):
                out.append({"permit_id": p["permit_id"], "flight_id": p["flight_id"], "pilot_name": p["pilot_name"], "authority_id": p.get("authority_id")})
    return out
