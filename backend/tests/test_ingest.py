"""A real tracker's positions go through the same geofence, with its own key, and a breach reaches the guard alert."""
from fastapi.testclient import TestClient

import time

import events
from guard_api import alert_for
from main import app
from tests.test_bridge import auth, official, pilot
from tests.test_guard import POLY, window

client = TestClient(app)
INSIDE = {"lat": 17.34875, "lng": 78.3412}
OUTSIDE = {"lat": 17.40, "lng": 78.50}


def make_key():
    r = client.post("/admin/trackers", headers=auth(official()), json={"name": "Campus receiver"})
    assert r.status_code == 200
    return r.json()["key"], r.json()["tracker_id"]


def post(key, ref="RID-0001", **where):
    return client.post("/ingest/position", headers={"X-Tracker-Key": key} if key else {}, json={"drone_ref": ref, "alt_m": 40, "speed_mps": 8, **where})


def test_only_an_administrator_manages_trackers_and_the_key_is_not_stored():
    assert client.post("/admin/trackers", json={"name": "x" * 5}).status_code == 401
    assert client.post("/admin/trackers", headers=auth(pilot("tk1@example.com")), json={"name": "Receiver"}).status_code == 403
    key, tid = make_key()
    import runtime
    stored = next(t for t in runtime.all_("trackers") if t["tracker_id"] == tid)
    assert key not in str(stored) and stored["key_hash"] != key
    assert all("key" not in t and "key_hash" not in t for t in client.get("/admin/trackers", headers=auth(official())).json())


def test_a_position_needs_a_valid_active_key():
    key, tid = make_key()
    assert post(None, **OUTSIDE).status_code == 401
    assert post("trk_wrong", **OUTSIDE).status_code == 401
    assert post(key, **OUTSIDE).status_code == 200
    client.post(f"/admin/trackers/{tid}/revoke", headers=auth(official()))
    assert post(key, **OUTSIDE).status_code == 401  # a revoked key stops working at once


def test_bad_positions_are_refused():
    key, _ = make_key()
    for bad in ({"lat": 95, "lng": 78}, {"lat": 17, "lng": 200}, {"lat": 17, "lng": 78, "alt_m": -5}, {"lat": 17, "lng": 78, "speed_mps": 900}):
        assert post(key, **bad).status_code == 422
    assert client.post("/ingest/position", headers={"X-Tracker-Key": key}, json={"drone_ref": "a b;c", "lat": 17, "lng": 78}).status_code == 422


def test_a_drone_seen_inside_a_declared_area_raises_one_breach_and_a_guard_alert():
    key, _ = make_key()
    admin = official()
    n = client.post("/notices", headers=auth(admin), json={"title": "Tracker campus", "polygon": POLY, **window()}).json()
    events.start_watchers()  # with MongoDB the breach reaches the guard through the change stream
    time.sleep(1.5)
    q, push = events.subscribe_queue()
    try:
        assert post(key, ref="RID-AREA", **OUTSIDE).json()["breach_recorded"] is False
        r = post(key, ref="RID-AREA", **INSIDE).json()
        assert r["status"] == "breach" and r["breach_recorded"] is True
        assert post(key, ref="RID-AREA", **INSIDE).json()["breach_recorded"] is False  # same entry, not reported again
        alerts, end = [], time.time() + 5
        while time.time() < end and not alerts:
            try:
                a = alert_for(q.get(timeout=0.5))
            except Exception:
                continue
            if a:
                alerts.append(a)
        time.sleep(0.5)
        while not q.empty():
            a = alert_for(q.get())
            if a:
                alerts.append(a)
        assert any(a["area"] == "Tracker campus" and a["kind"] == "intrusion" for a in alerts)
        assert len([a for a in alerts if a["area"] == "Tracker campus"]) == 1
    finally:
        events.unsubscribe(push)
        client.post(f"/notices/{n['notice_id']}/cancel", headers=auth(admin))
