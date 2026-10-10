"""The whole flight pipeline: request, approve, preflight (cleared), launch, fly, breach, recall, land. In-process, the simulator is ticked by hand."""
import pytest
from fastapi.testclient import TestClient

from main import app
from simulator.fleet import get_fleet_simulator
from tests.support import ADMIN_EMAIL, PASSWORD, officer_email
from tests.test_bridge import GOV_SPOT, auth, official, officer, pilot, verified_pilot, window

client = TestClient(app)
sim = get_fleet_simulator()


@pytest.fixture(autouse=True)
def clean_sky():
    sim.stop_all()
    sim.speed_x = 1.0
    yield
    sim.stop_all()


def cleared_flight(email, serial, spot=GOV_SPOT, permit=True):
    """A verified pilot with an approved, cleared flight, ready to launch. Returns (pilot_token, flight_id)."""
    p, drone_id = verified_pilot(email, serial)
    f = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission" if permit else "watch", **spot, **window(-1, 90)}).json()
    if permit:
        assert client.post(f"/flights/{f['flight_id']}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "approved", "alt_max_m": 60}).status_code == 200
    pre = client.post(f"/flights/{f['flight_id']}/preflight", headers=auth(p)).json()
    assert pre["cleared"], pre["reasons"]
    return p, f["flight_id"]


def status(p, fid):
    return next(f for f in client.get("/flights", headers=auth(p)).json() if f["flight_id"] == fid)["status"]


def test_preflight_clears_the_flight_and_launch_puts_a_drone_in_the_air():
    p, fid = cleared_flight("pl1@example.com", "PL0001")
    assert status(p, fid) == "cleared"
    r = client.post(f"/flights/{fid}/launch", headers=auth(p))
    assert r.status_code == 200 and r.json()["status"] == "flying"
    d = sim.get_flight_drone(fid)
    assert d is not None and d.kind == "flight" and d.permit_area is not None and d.one_shot
    assert status(p, fid) == "flying"


def test_launch_needs_a_cleared_flight():
    p, drone_id = verified_pilot("pl2@example.com", "PL0002")
    f = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **GOV_SPOT, **window(-1, 90)}).json()
    assert client.post(f"/flights/{f['flight_id']}/launch", headers=auth(p)).status_code == 409  # still waiting for the officer
    assert sim.get_flight_drone(f["flight_id"]) is None


def test_a_restriction_published_after_preflight_stops_the_launch():
    p, fid = cleared_flight("pl3@example.com", "PL0003")
    w = window(-1, 120)
    n = client.post("/notices", headers=auth(official()), json={"title": "Pipeline test closure", "note": "", "radius_km": 1, "starts_at": w["start"], "ends_at": w["end"], **GOV_SPOT}).json()
    r = client.post(f"/flights/{fid}/launch", headers=auth(p))
    assert r.status_code == 409 and "prohibited" in r.json()["detail"].lower()
    assert status(p, fid) == "approved" and sim.get_flight_drone(fid) is None  # clearance is lost, nothing took off
    client.post(f"/notices/{n['notice_id']}/cancel", headers=auth(official()))


def test_who_can_see_the_drone():
    p, fid = cleared_flight("pl4@example.com", "PL0004")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    other = pilot("pl4b@example.com")
    assert [d["flight_id"] for d in client.get("/live/drones", headers=auth(p)).json()["drones"]] == [fid]   # the owner
    assert client.get("/live/drones", headers=auth(other)).json()["drones"] == []                            # another pilot
    assert client.get("/live/drones").json()["drones"] == []                                                  # a visitor
    assert fid in [d["flight_id"] for d in client.get("/live/drones", headers=auth(official())).json()["drones"]]  # an officer


def test_permit_holder_is_clear_inside_its_area_and_a_breach_is_reported_once_outside_it():
    p, fid = cleared_flight("pl5@example.com", "PL0005")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    d = sim.get_flight_drone(fid)
    sim.tick(1.0)
    assert d.status != "breach"  # circling inside the permitted area of a yellow zone
    # now it drifts out of the permit area but is still over the yellow zone
    d.lat += 0.004  # about 440 m north: outside the 300 m permit circle around the spot, still inside the government zone
    breaches = 0
    d.waypoints, d.waypoint_idx = [(d.lat + 0.5, d.lng, 50.0)], 0  # a far target, and hover: it stays where it drifted to
    d.speed_mps = d.target_speed_mps = 0.0
    for _ in range(5):
        breaches += len(sim.tick(0.1)["breaches"])
    assert d.status == "breach" and breaches == 1  # one entry is one event, not one per second
    alerts = [n for n in client.get("/notifications", headers=auth(p)).json()["items"] if n["kind"] == "breach"]
    assert len(alerts) == 1 and "restricted airspace" in alerts[0]["title"]
    assert next(f for f in client.get("/flights", headers=auth(p)).json() if f["flight_id"] == fid)["breaches"] == 1


def test_revoking_the_permit_recalls_the_drone_and_it_lands_at_home():
    p, fid = cleared_flight("pl6@example.com", "PL0006")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    d = sim.get_flight_drone(fid)
    sim.speed_x = 30
    sim.tick(1.0)
    permit_id = next(f for f in client.get("/flights", headers=auth(official())).json() if f["flight_id"] == fid)["permit_id"]
    r = client.post(f"/permits/{permit_id}/revoke", headers=auth(officer(officer_email("A-POL"))), json={"reason": "Pipeline test recall"})
    assert r.status_code == 200 and status(p, fid) == "recalled" and d.recalled
    assert any("ordered home" in n["body"] for n in client.get("/notifications", headers=auth(p)).json()["items"])
    for _ in range(200):
        sim.tick(1.0)
        if sim.get_flight_drone(fid) is None:
            break
    assert sim.get_flight_drone(fid) is None  # it came home and landed
    f = next(f for f in client.get("/flights", headers=auth(p)).json() if f["flight_id"] == fid)
    assert f["status"] == "recalled" and f["flight_log"]["reason"] == "recalled"


def test_officer_can_recall_without_revoking_the_permit():
    p, fid = cleared_flight("pl7@example.com", "PL0007")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    assert client.post(f"/flights/{fid}/recall", headers=auth(p), json={"reason": "x"}).status_code == 403  # pilots cannot
    r = client.post(f"/flights/{fid}/recall", headers=auth(officer(officer_email("A-POL"))), json={"reason": "Emergency vehicle landing nearby"})
    assert r.status_code == 200 and r.json()["status"] == "recalled"
    f = next(f for f in client.get("/flights", headers=auth(official())).json() if f["flight_id"] == fid)
    assert f["permit"]["status"] == "active"  # the permit stands, only this flight was called home


def test_pilot_lands_and_the_flight_log_is_kept():
    p, fid = cleared_flight("pl8@example.com", "PL0008")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    sim.tick(1.0)
    r = client.post(f"/flights/{fid}/land", headers=auth(p))
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert r.json()["flight_log"]["breaches"] == 0 and sim.get_flight_drone(fid) is None
    assert client.post(f"/flights/{fid}/land", headers=auth(p)).status_code == 409  # already down
    assert any(n["kind"] == "landed" for n in client.get("/notifications", headers=auth(p)).json()["items"])


def test_a_flight_that_finishes_its_route_lands_by_itself():
    p, fid = cleared_flight("pl9@example.com", "PL0009")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    sim.speed_x = 40
    for _ in range(400):
        sim.tick(1.0)
        if sim.get_flight_drone(fid) is None:
            break
    assert sim.get_flight_drone(fid) is None and status(p, fid) == "completed"


def test_vip_scenario_alerts_a_pilot_who_is_flying():
    p, fid = cleared_flight("pl10@example.com", "PL0010")
    client.post(f"/flights/{fid}/launch", headers=auth(p))
    r = client.post("/sim/scenarios/vip", headers=auth(official()))
    assert r.status_code == 200 and r.json()["affected_flights"] >= 1
    sim.tick(1.0)
    kinds = {n["kind"] for n in client.get("/notifications", headers=auth(p)).json()["items"]}
    assert "notice" in kinds and "breach" in kinds  # told about the restriction, then told the drone is inside it
    client.post(f"/notices/{r.json()['notice_id']}/cancel", headers=auth(official()))


def test_a_flight_in_a_green_area_can_launch_without_a_permit():
    p, fid = cleared_flight("pl11@example.com", "PL0011", spot={"lat": 17.30, "lng": 78.30}, permit=False)
    assert client.post(f"/flights/{fid}/launch", headers=auth(p)).status_code == 200
    d = sim.get_flight_drone(fid)
    assert d.permit_area is None and d.kind == "flight"


def test_flights_left_flying_by_a_restart_are_closed():
    import main
    import runtime
    runtime.insert("flights", {"flight_id": "F-STALE1", "status": "flying", "pilot_id": "U-X"})
    main._close_interrupted_flights()
    f = next(x for x in runtime.all_("flights") if x["flight_id"] == "F-STALE1")
    assert f["status"] == "completed" and f["flight_log"]["interrupted"] is True
