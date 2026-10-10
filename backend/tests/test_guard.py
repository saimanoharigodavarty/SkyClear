"""Guard alerts: the public stream carries only the area name, kind and time, and only for notice breaches."""
from fastapi.testclient import TestClient

from guard_api import alert_for
from main import app
from tests.test_bridge import auth, official, pilot

client = TestClient(app)


def breach(kind="notice", name="Campus", op="insert"):
    return {"coll": "breaches", "op": op, "doc": {"kind": kind, "name": name, "ts": "2026-10-11T10:00:00+00:00", "flight_id": "F-1", "drone_id": "D-1", "lat": 17.0, "lng": 78.0}}


def test_a_notice_breach_becomes_a_public_alert_without_identities():
    a = alert_for(breach())
    assert a == {"area": "Campus", "kind": "intrusion", "ts": "2026-10-11T10:00:00+00:00"}  # no flight, drone or position


def test_only_the_chosen_area_and_only_notices_are_announced():
    assert alert_for(breach(), area="campus") is not None
    assert alert_for(breach(), area="Another area") is None
    assert alert_for(breach(kind="zone")) is None
    assert alert_for(breach(op="update")) is None
    assert alert_for({"coll": "flights", "op": "insert", "doc": {}}) is None


def test_the_test_siren_is_for_officials_and_is_audited():
    assert client.post("/guard/test").status_code == 401
    assert client.post("/guard/test", headers=auth(pilot("gd1@example.com"))).status_code == 403
    r = client.post("/guard/test?area=Campus", headers=auth(official()))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert any(a["action"] == "guard_test" for a in client.get("/audit?limit=20", headers=auth(official())).json())


def test_a_test_signal_reaches_every_listener():
    import events
    q, push = events.subscribe_queue()
    try:
        client.post("/guard/test?area=Campus", headers=auth(official()))
        ev = q.get(timeout=2)
        assert ev["coll"] == "guard_test" and alert_for(ev)["kind"] == "test"
    finally:
        events.unsubscribe(push)


def test_status_is_public():
    assert client.get("/guard/status").json() == {"listeners": 0}
