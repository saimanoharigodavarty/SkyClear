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


def test_the_drill_declares_the_area_and_flies_a_drone_at_it():
    from simulator.fleet import get_fleet_simulator
    admin = official()
    assert client.post("/sim/scenarios/intruder", json={"lat": 17.4, "lng": 78.4}).status_code == 401
    assert client.post("/sim/scenarios/intruder", headers=auth(pilot("gd2@example.com")), json={"lat": 17.4, "lng": 78.4}).status_code in (401, 403)
    r = client.post("/sim/scenarios/intruder", headers=auth(admin), json={"lat": 17.4, "lng": 78.4, "title": "Drill campus", "radius_m": 100})
    assert r.status_code == 200 and r.json()["drone_id"].startswith("DRILL-") and r.json()["arrives_in_s"] > 0
    assert any(n["title"] == "Drill campus" for n in client.get("/notices", headers=auth(admin)).json())
    sim = get_fleet_simulator()
    d = next(d for d in sim.drones if d.drone_id == r.json()["drone_id"])
    assert 0.004 < abs(d.lat - 17.4) + abs(d.lng - 78.4) < 0.02  # starts a few hundred metres away
    client.delete("/sim/fleet", headers=auth(admin))
    client.post(f"/notices/{r.json()['notice_id']}/cancel", headers=auth(admin))


POLY = [[78.3395, 17.3500], [78.3430, 17.3500], [78.3430, 17.3475], [78.3395, 17.3475]]


def window():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return {"starts_at": (now - timedelta(minutes=1)).isoformat(timespec="seconds"), "ends_at": (now + timedelta(hours=1)).isoformat(timespec="seconds")}


def test_a_drawn_boundary_becomes_the_restricted_area():
    from geo import point_in_polygon
    admin = official()
    r = client.post("/notices", headers=auth(admin), json={"title": "Drawn campus", "polygon": POLY, **window()})
    assert r.status_code == 200
    n = r.json()
    assert n["shape"] == "polygon" and n["area"]["coordinates"][0][0] == n["area"]["coordinates"][0][-1]
    assert point_in_polygon(78.3412, 17.3489, n["area"]) and not point_in_polygon(78.3500, 17.3489, n["area"])  # the shape is the drawn one, not a circle
    assert 0.1 < n["radius_km"] < 1 and abs(n["center"]["lat"] - 17.34875) < 0.001
    client.post(f"/notices/{n['notice_id']}/cancel", headers=auth(admin))


def test_a_bad_boundary_is_refused_with_a_reason():
    admin = official()
    bow = [[78.0, 17.0], [78.01, 17.01], [78.01, 17.0], [78.0, 17.01]]  # edges cross
    line = [[78.0, 17.0], [78.01, 17.0], [78.02, 17.0]]
    for pts, word in ((bow, "cross"), (line, "line"), ([[78.0, 17.0], [78.01, 17.0]], "corners"), ([[78.0, 17.0], [80.0, 17.0], [80.0, 19.0]], "larger")):
        r = client.post("/notices", headers=auth(admin), json={"title": "Bad boundary", "polygon": pts, **window()})
        assert r.status_code == 422 and word in r.json()["detail"], (word, r.json())
    assert client.post("/notices", headers=auth(admin), json={"title": "No shape", **window()}).status_code == 422


def test_the_drill_can_use_a_drawn_boundary():
    admin = official()
    r = client.post("/sim/scenarios/intruder", headers=auth(admin), json={"title": "Drill boundary", "polygon": POLY})
    assert r.status_code == 200
    client.delete("/sim/fleet", headers=auth(admin))
    client.post(f"/notices/{r.json()['notice_id']}/cancel", headers=auth(admin))


def test_the_drill_can_fly_at_an_area_that_is_already_declared_without_publishing_another():
    admin = official()
    n = client.post("/notices", headers=auth(admin), json={"title": "Existing campus", "polygon": POLY, **window()}).json()
    before = [x["notice_id"] for x in client.get("/notices", headers=auth(admin)).json()]
    r = client.post("/sim/scenarios/intruder", headers=auth(admin), json={"notice_id": n["notice_id"]})
    assert r.status_code == 200 and r.json()["created"] is False and r.json()["notice_id"] == n["notice_id"] and r.json()["title"] == "Existing campus"
    assert [x["notice_id"] for x in client.get("/notices", headers=auth(admin)).json()] == before  # nothing new was published
    assert client.post("/sim/scenarios/intruder", headers=auth(admin), json={"notice_id": "RN-NOPE00"}).status_code == 404
    client.post(f"/notices/{n['notice_id']}/cancel", headers=auth(admin))
    assert client.post("/sim/scenarios/intruder", headers=auth(admin), json={"notice_id": n["notice_id"]}).status_code == 404  # a cancelled area cannot be drilled
    client.delete("/sim/fleet", headers=auth(admin))
