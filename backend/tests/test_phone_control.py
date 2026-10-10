"""Flying by phone: sticks, hover on silence, a pairing token that fits one flight only, altitude limit, return home."""
import math
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import config
from main import app
from simulator.fleet import get_fleet_simulator
from tests.support import officer_email
from tests.test_bridge import GOV_SPOT, auth, official, officer, verified_pilot, window

client = TestClient(app)
sim = get_fleet_simulator()


@pytest.fixture(autouse=True)
def clean_sky():
    sim.stop_all()
    sim.speed_x = 1.0
    yield
    sim.stop_all()


def hand_flight(email, serial):
    """A verified pilot, an approved permit, a cleared preflight and a hand-flown take off. Returns (token, flight_id, drone)."""
    p, drone_id = verified_pilot(email, serial)
    f = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **GOV_SPOT, **window(-1, 90)}).json()
    client.post(f"/flights/{f['flight_id']}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "approved", "alt_max_m": 60})
    assert client.post(f"/flights/{f['flight_id']}/preflight", headers=auth(p)).json()["cleared"]
    r = client.post(f"/flights/{f['flight_id']}/launch", headers=auth(p), json={"mode": "manual"})
    assert r.status_code == 200, r.text
    return p, f["flight_id"], sim.get_flight_drone(f["flight_id"])


def pair(p, fid):
    r = client.post(f"/flights/{fid}/pair", headers=auth(p))
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def metres(a, b):
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])))


def test_hand_launch_hovers_until_the_sticks_move():
    p, fid, d = hand_flight("pc1@example.com", "PC0001")
    assert d.manual and d.alt_m == 10.0
    start = (d.lat, d.lng)
    for _ in range(10):
        sim.tick(0.1)
    assert metres(start, (d.lat, d.lng)) < 5  # nothing pressed: it hovers (only a little wind)
    h = pair(p, fid)
    assert client.post(f"/flights/{fid}/control", headers=h, json={"fwd": 1.0}).json() == {"ok": True}
    for _ in range(30):
        sim.tick(0.1)
        client.post(f"/flights/{fid}/control", headers=h, json={"fwd": 1.0})
    assert metres(start, (d.lat, d.lng)) > 20 and d.speed_mps > 8  # forward stick: it flies


def test_it_hovers_when_the_phone_goes_quiet():
    p, fid, d = hand_flight("pc2@example.com", "PC0002")
    h = pair(p, fid)
    for _ in range(20):
        client.post(f"/flights/{fid}/control", headers=h, json={"fwd": 1.0})
        sim.tick(0.1)
    assert d.speed_mps > 5
    d.cmd_at = time.monotonic() - 10  # the phone has not been heard from for ten seconds
    for _ in range(40):
        sim.tick(0.1)
    assert d.speed_mps < 0.5


def test_yaw_turns_and_climb_changes_height():
    p, fid, d = hand_flight("pc3@example.com", "PC0003")
    h = pair(p, fid)
    heading, alt = d.heading_deg, d.alt_m
    for _ in range(10):
        client.post(f"/flights/{fid}/control", headers=h, json={"yaw": 1.0, "climb": 1.0})
        sim.tick(0.1)
    assert (d.heading_deg - heading) % 360 > 50 and d.alt_m > alt + 3


def test_a_pair_token_fits_one_flight_and_expires():
    p, fid, d = hand_flight("pc4@example.com", "PC0004")
    p2, fid2, d2 = hand_flight("pc4b@example.com", "PC0004B")
    h = pair(p, fid)
    assert client.post(f"/flights/{fid2}/control", headers=h, json={"fwd": 1}).status_code == 403   # another flight
    assert client.get(f"/flights/{fid2}/live", headers=h).status_code == 403
    assert client.get("/me", headers=h).status_code == 401  # it is not a login: no account access
    assert client.get("/notifications", headers=h).status_code == 401
    old = jwt.encode({"sub": "U-X", "fid": fid, "typ": "pair", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, config.JWT_SECRET, algorithm="HS256")
    assert client.post(f"/flights/{fid}/control", headers={"Authorization": "Bearer " + old}, json={"fwd": 1}).status_code == 401
    assert client.post(f"/flights/{fid}/control", json={"fwd": 1}).status_code == 401
    other = hand_flight("pc4c@example.com", "PC0004C")[0]
    assert client.post(f"/flights/{fid}/control", headers=auth(other), json={"fwd": 1}).status_code == 403  # a different pilot's login


def test_altitude_over_the_permit_is_a_warning_then_a_breach():
    p, fid, d = hand_flight("pc5@example.com", "PC0005")
    d.alt_m = 57.0  # permit cap is 60 m, 90 percent is 54 m
    d.set_command(0, 0, 0, 0)
    sim.tick(0.1)
    assert d.status == "warning" and "altitude" in d.zone.lower()
    d.alt_m = 63.0
    out = sim.tick(0.1)
    assert d.status == "breach" and [b["kind"] for b in out["breaches"]] == ["altitude"]
    assert sim.tick(0.1)["breaches"] == []  # still too high: the same breach is not reported again
    alerts = [n for n in client.get("/notifications", headers=auth(p)).json()["items"] if n["kind"] == "breach"]
    assert len(alerts) == 1
    assert any(e["kind"] == "breach" and "Altitude" in e["text"] for e in sim.flight_events(fid))


def test_flying_out_of_the_permitted_area_is_a_breach_you_can_see_in_the_event_log():
    p, fid, d = hand_flight("pc6@example.com", "PC0006")
    d.lat += 0.004  # about 440 m north: out of the 300 m permit circle, still over the yellow zone
    d.set_command(0, 0, 0, 0)
    sim.tick(0.1)
    events = client.get(f"/flights/{fid}/live", headers=pair(p, fid)).json()
    assert events["airborne"] and events["drone"]["status"] == "breach" and events["drone"]["mode"] == "manual"
    assert [e["kind"] for e in events["events"]][0] == "takeoff" and "breach" in [e["kind"] for e in events["events"]]


def test_return_home_lands_as_a_normal_flight_not_a_recall():
    p, fid, d = hand_flight("pc7@example.com", "PC0007")
    h = pair(p, fid)
    d.lat += 0.001
    assert client.post(f"/flights/{fid}/home", headers=h).json() == {"ok": True}
    assert client.post(f"/flights/{fid}/control", headers=h, json={"fwd": 1}).status_code == 409  # the drone is flying itself home
    sim.speed_x = 20
    for _ in range(200):
        sim.tick(0.5)
        if sim.get_flight_drone(fid) is None:
            break
    f = next(f for f in client.get("/flights", headers=auth(p)).json() if f["flight_id"] == fid)
    assert f["status"] == "completed" and f["flight_log"]["reason"] == "completed"


def test_pilot_can_land_from_the_paired_phone_and_the_screen_sees_it_end():
    p, fid, d = hand_flight("pc8@example.com", "PC0008")
    h = pair(p, fid)
    assert client.post(f"/flights/{fid}/land", headers=h).json()["status"] == "completed"
    live = client.get(f"/flights/{fid}/live", headers=h).json()
    assert live["airborne"] is False and live["events"][-1]["kind"] == "landed"
    info = client.get(f"/flights/{fid}/info", headers=h).json()
    assert info["status"] == "completed" and info["permit"]["area"]["type"] == "Polygon"


def test_an_officer_recall_takes_the_sticks_away():
    p, fid, d = hand_flight("pc9@example.com", "PC0009")
    h = pair(p, fid)
    assert client.post(f"/flights/{fid}/recall", headers=auth(officer(officer_email("A-POL"))), json={"reason": "Pilot test"}).status_code == 200
    assert client.post(f"/flights/{fid}/control", headers=h, json={"fwd": 1}).status_code == 409
    assert d.recalled and not d.manual


def test_the_big_screen_can_find_a_link_a_phone_can_open():
    r = client.get("/lan").json()
    assert "urls" in r and r["port"]
    assert all(not u.startswith("http://127.") for u in r["urls"])


def test_an_automatic_flight_cannot_be_flown_by_hand():
    p, drone_id = verified_pilot("pc10@example.com", "PC0010")
    f = client.post("/flights", headers=auth(p), json={"drone_id": drone_id, "kind": "permission", **GOV_SPOT, **window(-1, 90)}).json()
    client.post(f"/flights/{f['flight_id']}/decision", headers=auth(officer(officer_email("A-POL"))), json={"decision": "approved"})
    client.post(f"/flights/{f['flight_id']}/preflight", headers=auth(p))
    client.post(f"/flights/{f['flight_id']}/launch", headers=auth(p))  # default mode: auto
    assert client.post(f"/flights/{f['flight_id']}/control", headers=auth(p), json={"fwd": 1}).status_code == 409
