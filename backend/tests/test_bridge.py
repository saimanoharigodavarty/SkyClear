from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import config
from main import app

client = TestClient(app)
WINDOW = {"start": "2026-10-20T10:00:00+05:30", "end": "2026-10-20T11:00:00+05:30"}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def pilot(email):
    r = client.post("/auth/register", json={"name": "Test Pilot", "email": email, "password": "longenough1"})
    assert r.status_code == 200
    return r.json()["token"]


def official():
    r = client.post("/auth/login", json={"email": config.OFFICIAL_EMAIL, "password": config.OFFICIAL_PASSWORD})
    assert r.status_code == 200
    return r.json()["token"]


def test_roles_are_enforced():
    p = pilot("roles@example.com")
    assert client.get("/me").status_code == 401
    assert client.post("/notices", headers=auth(p), json={}).status_code in (403, 422)
    assert client.get("/overview", headers=auth(p)).status_code == 403
    assert client.post("/auth/login", json={"email": "roles@example.com", "password": "wrong-pass"}).status_code == 401


def test_cannot_request_permission_when_prohibited():
    p = pilot("proh@example.com")
    r = client.post("/flights", headers=auth(p), json={"drone_id": "nano-200", "lat": 17.55, "lng": 78.525,
                    "kind": "permission", **WINDOW})
    assert r.status_code == 400


def test_official_notice_alerts_watching_pilot_and_blocks_checks():
    p, o = pilot("watch@example.com"), official()
    spot = {"lat": 17.36, "lng": 78.30}
    f = client.post("/flights", headers=auth(p), json={"drone_id": "small-1800", "kind": "watch", **spot, **WINDOW}).json()
    assert f["status"] == "watching"
    n = client.post("/notices", headers=auth(o), json={"title": "VIP movement test", "note": "", "radius_km": 2,
                    "starts_at": "2026-10-20T09:30:00+05:30", "ends_at": "2026-10-20T12:00:00+05:30", **spot})
    assert n.status_code == 200 and n.json()["affected_flights"] == 1
    assert client.get("/notifications", headers=auth(p)).json()["unread"] >= 1
    chk = client.post("/check", json={"drone_id": "small-1800", "datetime": "2026-10-20T10:30:00+05:30", **spot}).json()
    assert chk["verdict"] == "prohibited"
    client.post(f"/notices/{n.json()['notice_id']}/cancel", headers=auth(o))
    after = client.post("/check", json={"drone_id": "small-1800", "datetime": "2026-10-20T10:30:00+05:30", **spot}).json()
    assert after["verdict"] == "can_fly"


# ---- permits, verification and routing ----
def iso(dt):
    return dt.isoformat(timespec="seconds")


def officer(email):
    r = client.post("/auth/login", json={"email": email, "password": config.OFFICIAL_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def upload(token):
    r = client.post("/uploads", headers=auth(token), files={"file": ("doc.png", b"fake-image-bytes", "image/png")})
    assert r.status_code == 200
    return r.json()["file_id"]


def verified_pilot(email, serial):
    """A pilot with a verified certificate and one verified drone. Returns (token, drone_id)."""
    p, admin = pilot(email), official()
    drone = client.post("/me/drones", headers=auth(p), json={"name": "Mavic", "weight_g": 900}).json()
    v1 = client.post("/me/verification/pilot", headers=auth(p), json={"cert_no": "RPC-" + serial, "file_ids": [upload(p)]}).json()
    v2 = client.post(f"/me/drones/{drone['drone_id']}/verification", headers=auth(p), json={"serial": serial, "uin": "UIN-" + serial, "file_ids": [upload(p)]}).json()
    for v in (v1, v2):
        assert client.post(f"/verification/{v['verification_id']}/decision", headers=auth(admin), json={"decision": "approved"}).status_code == 200
    return p, drone["drone_id"]


def window(start_offset_min=-1, minutes=60):
    now = datetime.now(timezone.utc)
    return {"start": iso(now + timedelta(minutes=start_offset_min)), "end": iso(now + timedelta(minutes=start_offset_min + minutes))}


GOV_SPOT = {"lat": 17.407, "lng": 78.47}      # sample Secretariat zone: government, owned by the police desk
AIRPORT_SPOT = {"lat": 17.245, "lng": 78.43}  # Rajiv Gandhi airport zone


def test_unverified_pilot_cannot_request_permission():
    p = pilot("unver@example.com")
    d = client.post("/me/drones", headers=auth(p), json={"name": "Test Drone", "weight_g": 900}).json()
    r = client.post("/flights", headers=auth(p), json={"drone_id": d["drone_id"], "kind": "permission", **GOV_SPOT, **window()})
    assert r.status_code == 403 and "not_verified" in r.json()["detail"]


def test_verification_rules_uniqueness_and_ownership():
    p, _ = verified_pilot("ver1@example.com", "SER0001")
    other = pilot("ver2@example.com")
    d = client.post("/me/drones", headers=auth(other), json={"name": "Copy", "weight_g": 500}).json()
    dup = client.post(f"/me/drones/{d['drone_id']}/verification", headers=auth(other), json={"serial": "ser 0001", "file_ids": [upload(other)]})
    assert dup.status_code == 409  # same serial, spaces and case ignored
    fid = upload(p)
    assert client.get(f"/uploads/{fid}", headers=auth(other)).status_code == 403
    assert client.get(f"/uploads/{fid}", headers=auth(official())).status_code == 200
    assert client.post("/uploads", headers=auth(p), files={"file": ("x.exe", b"x", "application/octet-stream")}).status_code == 415


def test_permission_routed_approved_permit_preflight_and_revoke():
    p, drone_id = verified_pilot("flow@example.com", "SER0002")
    w = window()
    f = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", "purpose": "survey", **GOV_SPOT, **w})
    assert f.status_code == 200, f.text
    flight = f.json()
    assert flight["routed_to"]["authority"]["authority_id"] == "A-POL" and flight["routed_to"]["reason"] == "zone_owner"
    # preflight before approval: not cleared
    assert client.post(f"/flights/{flight['flight_id']}/preflight", headers=auth(p)).json()["cleared"] is False
    # the airport officer cannot decide a police request, the police officer can
    wrong = client.post(f"/flights/{flight['flight_id']}/decision", headers=auth(officer("rgia@skyclear.demo")), json={"decision": "approved"})
    assert wrong.status_code == 403
    done = client.post(f"/flights/{flight['flight_id']}/decision", headers=auth(officer("police@skyclear.demo")),
                       json={"decision": "approved", "alt_max_m": 50, "conditions": ["Daylight only"]})
    assert done.status_code == 200
    permit = done.json()["permit"]
    assert permit["status"] == "active" and permit["signature_ok"] and permit["alt_max_m"] == 50
    pre = client.post(f"/flights/{flight['flight_id']}/preflight", headers=auth(p)).json()
    assert pre["cleared"] is True and pre["conditions"] == ["Daylight only"] and pre["cleared_until"]
    # revoke, then preflight fails and the pilot is alerted
    rev = client.post(f"/permits/{permit['permit_id']}/revoke", headers=auth(officer("police@skyclear.demo")), json={"reason": "VIP movement"})
    assert rev.json()["status"] == "revoked"
    after = client.post(f"/flights/{flight['flight_id']}/preflight", headers=auth(p)).json()
    assert after["cleared"] is False and any("revoked" in r.lower() for r in after["reasons"])
    assert any("revoked" in a["title"].lower() for a in client.get("/notifications", headers=auth(p)).json()["items"])


def test_wrong_drone_fails_preflight():
    p, drone_id = verified_pilot("swap@example.com", "SER0003")
    flight = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **GOV_SPOT, **window()}).json()
    client.post(f"/flights/{flight['flight_id']}/decision", headers=auth(official()), json={"decision": "approved"})
    # the pilot tampers with the drone serial after approval
    from runtime import update
    update("drones", "drone_id", drone_id, {"serial": "SOMETHING-ELSE"})
    pre = client.post(f"/flights/{flight['flight_id']}/preflight", headers=auth(p)).json()
    assert pre["cleared"] is False and any("serial mismatch" in r for r in pre["reasons"])


def test_airport_request_goes_to_airport_desk_and_preview_matches():
    p, drone_id = verified_pilot("air@example.com", "SER0004")
    prev = client.get("/route-preview", headers=auth(p), params=AIRPORT_SPOT).json()
    assert prev["authority"]["authority_id"] == "A-RGIA"
    flight = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **AIRPORT_SPOT, **window()}).json()
    assert flight["authority_id"] == "A-RGIA"
    mine = client.get("/flights?status=requested", headers=auth(officer("rgia@skyclear.demo"))).json()
    assert flight["flight_id"] in {f["flight_id"] for f in mine}
    other = client.get("/flights?status=requested", headers=auth(officer("forest@skyclear.demo"))).json()
    assert flight["flight_id"] not in {f["flight_id"] for f in other}


def test_notice_lists_conflicting_permits():
    p, drone_id = verified_pilot("conf@example.com", "SER0005")
    flight = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **GOV_SPOT, **window()}).json()
    client.post(f"/flights/{flight['flight_id']}/decision", headers=auth(official()), json={"decision": "approved"})
    w = window()
    n = client.post("/notices", headers=auth(official()), json={"title": "VIP movement conflict", "note": "", "radius_km": 1, "starts_at": w["start"], "ends_at": w["end"], **GOV_SPOT}).json()
    assert flight["flight_id"] in {c["flight_id"] for c in n["conflicting_permits"]}
    client.post(f"/notices/{n['notice_id']}/cancel", headers=auth(official()))


def test_my_drones_lists_only_own_drones_not_the_sample_catalog():
    p = pilot("mine@example.com")
    assert client.get("/me/drones", headers=auth(p)).json() == []
    d = client.post("/me/drones", headers=auth(p), json={"name": "My Drone", "weight_g": 400}).json()
    mine = client.get("/me/drones", headers=auth(p)).json()
    assert [x["drone_id"] for x in mine] == [d["drone_id"]] and mine[0]["verification"]["status"] == "unverified"
