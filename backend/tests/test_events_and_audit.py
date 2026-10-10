"""Audit log, atomic transactions and live events (MongoDB change streams, or the in-process bus without MongoDB)."""
import os
import time

import pytest
from fastapi.testclient import TestClient

import events
import runtime
from main import app
from tests.support import ADMIN_EMAIL, PASSWORD, officer_email
from tests.test_bridge import GOV_SPOT, auth, official, officer, pilot, verified_pilot, window

client = TestClient(app)
MONGO = os.environ.get("USE_MONGO") == "1"


def request_flight(email, serial):
    p, drone_id = verified_pilot(email, serial)
    f = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **GOV_SPOT, **window(-1, 90)}).json()
    return p, f["flight_id"]


def audit_actions():
    return [a["action"] for a in client.get("/audit?limit=200", headers=auth(official())).json()]


def test_every_official_action_leaves_an_audit_entry():
    p, fid = request_flight("au1@example.com", "AU0001")
    desk = officer(officer_email("A-POL"))
    client.post(f"/flights/{fid}/decision", headers=auth(desk), json={"decision": "approved", "alt_max_m": 60})
    permit_id = next(f for f in client.get("/flights", headers=auth(official())).json() if f["flight_id"] == fid)["permit_id"]
    client.post(f"/permits/{permit_id}/revoke", headers=auth(desk), json={"reason": "Audit test"})
    w = window(-1, 60)
    n = client.post("/notices", headers=auth(official()), json={"title": "Audit test notice", "note": "", "lat": 17.36, "lng": 78.30, "radius_km": 1, "starts_at": w["start"], "ends_at": w["end"]}).json()
    client.post(f"/notices/{n['notice_id']}/cancel", headers=auth(official()))
    got = audit_actions()
    for action in ("permission_approved", "permit_revoked", "notice_published", "notice_cancelled", "verification_approved"):
        assert action in got, action
    top = client.get("/audit?limit=5", headers=auth(official())).json()[0]
    assert {"audit_id", "ts", "actor", "role", "action", "target"} <= set(top)


def test_the_audit_log_is_for_administrators_only():
    p = pilot("au2@example.com")
    assert client.get("/audit", headers=auth(p)).status_code == 403
    assert client.get("/audit", headers=auth(officer(officer_email("A-POL")))).status_code == 403  # an officer is not an admin
    assert client.get("/audit").status_code == 401
    assert client.get("/audit", headers=auth(official())).status_code == 200


def test_the_audit_log_cannot_be_edited_through_the_api():
    for method in ("put", "patch", "delete", "post"):
        assert getattr(client, method)("/audit", headers=auth(official())).status_code in (404, 405)


def test_rejecting_is_audited_with_the_reason():
    p, fid = request_flight("au3@example.com", "AU0003")
    client.post(f"/flights/{fid}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "rejected", "comment": "Event that day"})
    row = next(a for a in client.get("/audit?limit=200", headers=auth(official())).json() if a["action"] == "permission_rejected" and a["target"] == fid)
    assert "Event that day" in row["detail"]


@pytest.mark.skipif(not MONGO, reason="needs MongoDB transactions")
def test_a_failed_step_rolls_the_whole_decision_back(monkeypatch):
    """Approving writes a permit, a flight status, an alert and an audit entry. If the alert fails, none of it may remain."""
    import bridge
    p, fid = request_flight("au4@example.com", "AU0004")
    before = len(runtime.all_("permits")), len(runtime.all_("audit_log"))

    def broken(*a, **k):
        raise RuntimeError("the alert could not be written")

    monkeypatch.setattr(bridge, "notify", broken)
    r = TestClient(app, raise_server_exceptions=False).post(f"/flights/{fid}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "approved"})
    assert r.status_code == 500
    assert (len(runtime.all_("permits")), len(runtime.all_("audit_log"))) == before   # no orphan permit, no audit entry
    flight = next(f for f in runtime.all_("flights") if f["flight_id"] == fid)
    assert flight["status"] == "requested" and not flight.get("permit_id")           # still waiting, and can be decided again
    monkeypatch.undo()
    assert client.post(f"/flights/{fid}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "approved"}).status_code == 200


def wait_for(q, coll, timeout=6.0, match=lambda d: True):
    end = time.time() + timeout
    while time.time() < end:
        try:
            ev = q.get(timeout=0.5)
        except Exception:
            continue
        if ev["coll"] == coll and match(ev["doc"]):
            return ev
    return None


def test_an_alert_reaches_subscribers_as_soon_as_it_is_written():
    events.start_watchers()  # with MongoDB this opens the change streams, without it it does nothing
    if MONGO:
        time.sleep(1.5)       # let the streams open
    q, push = events.subscribe_queue()
    try:
        p, fid = request_flight("au5@example.com", "AU0005")
        client.post(f"/flights/{fid}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "approved"})
        ev = wait_for(q, "notifications", match=lambda d: "approved" in d.get("title", "").lower())
        assert ev is not None, "no notification event arrived"
        assert ev["op"] == "insert" and ev["doc"]["kind"] in ("decision", "verification")
        assert wait_for(q, "flights", match=lambda d: d.get("flight_id") == fid and d.get("status") == "approved") is not None
    finally:
        events.unsubscribe(push)


@pytest.mark.skipif(not MONGO, reason="change streams need MongoDB")
def test_a_write_from_outside_the_api_is_also_seen_through_the_change_stream():
    """The point of change streams: any writer is noticed, not only this server's own code."""
    from db import get_db
    events.start_watchers()
    time.sleep(1.5)
    q, push = events.subscribe_queue()
    try:
        get_db().breaches.insert_one({"event_id": "BR-OUTSIDE", "drone_id": "X", "flight_id": "F-X", "kind": "zone", "name": "Written by a script", "ts": runtime.now_iso()})
        ev = wait_for(q, "breaches", match=lambda d: d.get("event_id") == "BR-OUTSIDE")
        assert ev is not None and ev["doc"]["name"] == "Written by a script"
        assert "_id" not in ev["doc"]
        assert events.status["mode"] == "mongodb_change_streams" and "breaches" in events.status["watching"]
    finally:
        events.unsubscribe(push)


def test_each_person_is_told_only_what_they_may_know():
    from events_api import shape
    pilot_a, pilot_b = {"role": "pilot", "user_id": "U-A"}, {"role": "pilot", "user_id": "U-B"}
    admin = {"role": "official", "user_id": "U-X"}
    alert = {"coll": "notifications", "op": "insert", "doc": {"user_id": "U-A", "title": "Hi", "kind": "decision"}}
    assert shape(alert, pilot_a)[0] == "alert" and shape(alert, pilot_b) is None and shape(alert, admin) is None
    breach = {"coll": "breaches", "op": "insert", "doc": {"flight_id": "F-1", "name": "Zone"}}
    assert shape(breach, admin)[0] == "breach" and shape(breach, pilot_a) is None
    flight = {"coll": "flights", "op": "update", "doc": {"flight_id": "F-1", "pilot_id": "U-A", "status": "flying", "secret": "x"}}
    assert shape(flight, pilot_a) == ("flight", {"flight_id": "F-1", "status": "flying"}) and shape(flight, pilot_b) is None
    notice = {"coll": "notices", "op": "insert", "doc": {"notice_id": "RN-1", "title": "T", "status": "active", "area": {}}}
    assert shape(notice, pilot_b)[0] == "notice" and "area" not in shape(notice, pilot_b)[1]


def test_the_live_channel_needs_a_sign_in():
    assert client.get("/events").status_code == 401
    assert client.get("/events?token=not-a-token").status_code == 401


def test_event_status_is_for_the_admin():
    p = pilot("au7@example.com")
    assert client.get("/events/status", headers=auth(p)).status_code == 403
    s = client.get("/events/status", headers=auth(official())).json()
    assert "mode" in s and "watching" in s
