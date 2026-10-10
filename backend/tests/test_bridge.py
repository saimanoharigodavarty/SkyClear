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


def test_permission_request_approval_and_alert():
    p, o = pilot("req@example.com"), official()
    d = client.post("/me/drones", headers=auth(p), json={"name": "My Mavic", "weight_g": 900}).json()
    assert d["class"] == "micro"
    # Secretariat sample zone needs permission
    f = client.post("/flights", headers=auth(p), json={"drone_id": d["drone_id"], "lat": 17.407, "lng": 78.47,
                    "kind": "permission", "purpose": "survey", **WINDOW})
    assert f.status_code == 200 and f.json()["status"] == "requested"
    fid = f.json()["flight_id"]
    assert client.post(f"/flights/{fid}/decision", headers=auth(o), json={"decision": "rejected"}).status_code == 422
    done = client.post(f"/flights/{fid}/decision", headers=auth(o), json={"decision": "approved", "comment": "Keep below 60 m"})
    assert done.json()["status"] == "approved"
    alerts = client.get("/notifications", headers=auth(p)).json()
    assert alerts["unread"] == 1 and "approved" in alerts["items"][0]["title"].lower()


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
