"""Tests for Stream 3 (Thanvi): fleet simulator, kinematics, geofence, and live API contracts.

Contracts covered:
- Contract 3: GET /live/drones and GET /live/stream
- Contract 4: POST /sim/fleet, DELETE /sim/fleet, GET /sim/status, POST /sim/scenarios/vip
- Contract 5: Telemetry time series shape
- P1 stretch: MAVLink telemetry adapter
"""
from fastapi.testclient import TestClient
import pytest

from main import app
from simulator.fleet import FleetSimulator
from simulator.geofence import GeofenceEngine
from simulator.kinematics import DroneKinematics
from simulator.mavlink import MavlinkAdapter, parse_global_position_int

client = TestClient(app)


def test_drone_kinematics_physics_and_sensor_noise():
    # Test kinematics stepping, wind drift, battery drain, and GPS sensor noise
    drone = DroneKinematics(
        drone_id="SIM-TEST",
        flight_id="F-TEST",
        initial_lat=17.40,
        initial_lng=78.40,
        initial_alt_m=50.0,
        speed_mps=12.0,
        battery_pct=90.0,
        waypoints=[(17.45, 78.45, 70.0)],
    )
    initial_battery = drone.battery_pct

    # Step physics with wind towards east
    drone.step(dt=2.0, wind_mps=4.0, wind_heading_deg=90.0)

    # Drone moved towards target and east
    assert drone.lat > 17.40
    assert drone.lng > 78.40
    assert drone.alt_m > 50.0
    assert drone.battery_pct < initial_battery

    # GPS sensor noise check
    r_lat, r_lng = drone.get_reported_position()
    assert abs(r_lat - drone.lat) < 0.001
    assert abs(r_lng - drone.lng) < 0.001

    # Contract 5 record structure
    telemetry = drone.telemetry_record()
    assert telemetry["drone_id"] == "SIM-TEST"
    assert telemetry["source"] == "sim"
    assert telemetry["position"]["type"] == "Point"
    assert len(telemetry["position"]["coordinates"]) == 2
    assert "alt_m" in telemetry
    assert "speed_mps" in telemetry
    assert "heading_deg" in telemetry
    assert "battery_pct" in telemetry


def test_geofence_engine_breach_and_warning_prediction():
    engine = GeofenceEngine()
    engine.lookahead_s = 30.0

    # Drone flying east at 10 m/s towards a restricted zone
    drone = DroneKinematics(
        drone_id="SIM-GEOFENCE",
        flight_id="F-GEOFENCE",
        initial_lat=17.40,
        initial_lng=78.40,
        speed_mps=10.0,
        waypoints=[(17.40, 78.50)],
    )
    drone.heading_deg = 90.0  # East

    # Restricted zone 100 metres east: from lng 78.401 to 78.405
    zone = {
        "zone_id": "Z-RESTRICTED",
        "name": "Secunderabad Military Base",
        "zone_type": "military",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[78.401, 17.395], [78.405, 17.395], [78.405, 17.405], [78.401, 17.405], [78.401, 17.395]]]
        }
    }

    # Ahead prediction should trigger warning with ETA
    status, zone_name, breach = engine.evaluate_drone(drone, [zone], [])
    assert status == "warning"
    assert "Secunderabad Military Base" in zone_name
    assert "ETA" in zone_name
    assert breach is None

    # Place drone inside the zone -> should trigger breach event
    drone.lat = 17.402
    drone.lng = 78.403
    status, zone_name, breach = engine.evaluate_drone(drone, [zone], [])
    assert status == "breach"
    assert breach is not None
    assert breach["kind"] == "zone"
    assert breach["severity"] == "prohibited"
    assert breach["drone_id"] == "SIM-GEOFENCE"


def test_fleet_simulator_100_drones_and_scalable():
    sim = FleetSimulator()
    sim.start(count=100, seed=42)
    assert len(sim.drones) == 100
    assert sim.is_running is True

    # Scale to 200 drones
    sim.start(count=200, seed=42)
    assert len(sim.drones) == 200

    status = sim.get_status()
    assert status["running"] is True
    assert status["drones"] == 200

    # Get drones with bbox
    res = sim.get_drones(bbox=[78.2, 17.2, 78.7, 17.7])
    assert "as_of" in res
    assert len(res["drones"]) > 0

    sim.stop()
    assert sim.is_running is False
    assert len(sim.drones) == 0


def test_simulation_control_endpoints_contract_4():
    from tests.support import ADMIN_EMAIL, PASSWORD
    admin = {"Authorization": "Bearer " + client.post("/auth/login", json={"identifier": ADMIN_EMAIL, "password": PASSWORD}).json()["token"]}
    # The controls are for officials: a visitor is refused
    assert client.post("/sim/fleet", json={"count": 5}).status_code == 401
    assert client.delete("/sim/fleet").status_code == 401
    assert client.post("/sim/scenarios/vip").status_code == 401

    # Start fleet via POST /sim/fleet
    r = client.post("/sim/fleet", json={"count": 50, "speed_x": 2.0, "seed": 7}, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 50
    assert body["running"] is True

    # Check GET /sim/status
    r_stat = client.get("/sim/status")
    assert r_stat.status_code == 200
    stat_body = r_stat.json()
    assert stat_body["running"] is True
    assert stat_body["drones"] == 50

    # Check GET /live/drones (Contract 3): an official sees every drone
    r_drones = client.get("/live/drones", headers=admin)
    assert r_drones.status_code == 200
    d_body = r_drones.json()
    assert "as_of" in d_body
    assert len(d_body["drones"]) == 50
    d0 = d_body["drones"][0]
    for key in ("drone_id", "flight_id", "lat", "lng", "alt_m", "speed_mps", "heading_deg", "battery_pct", "status"):
        assert key in d0
    # a visitor sees the background traffic too, with no pilot's flight in it
    assert len(client.get("/live/drones").json()["drones"]) == 50

    # Trigger VIP scenario: POST /sim/scenarios/vip. It goes through the normal notice path.
    r_vip = client.post("/sim/scenarios/vip", headers=admin)
    assert r_vip.status_code == 200
    vip_body = r_vip.json()
    assert vip_body["ok"] is True
    assert "notice_id" in vip_body
    notice = next(n for n in client.get("/notices", headers=admin).json() if n["notice_id"] == vip_body["notice_id"])
    assert notice["status"] == "active" and notice["origin"] == "official" and notice["ends_at"] > notice["starts_at"]
    client.post(f"/notices/{vip_body['notice_id']}/cancel", headers=admin)

    # Stop fleet via DELETE /sim/fleet
    r_del = client.delete("/sim/fleet", headers=admin)
    assert r_del.status_code == 200
    del_body = r_del.json()
    assert del_body["ok"] is True
    assert del_body["running"] is False


def test_geofence_feature_properties_and_notice_time_window():
    from datetime import datetime, timezone
    engine = GeofenceEngine()

    drone = DroneKinematics(
        drone_id="SIM-GEO-TEST",
        flight_id="F-GEO-TEST",
        initial_lat=17.44,
        initial_lng=78.38,
        speed_mps=10.0,
    )

    # GeoJSON Feature with properties dictionary
    feature_zone = {
        "type": "Feature",
        "properties": {
            "zone_id": "Z-MIL-HYD",
            "name": "Hyderabad Military Base",
            "zone_type": "military",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[78.37, 17.43], [78.39, 17.43], [78.39, 17.45], [78.37, 17.45], [78.37, 17.43]]],
        },
    }

    status, name, breach = engine.evaluate_drone(drone, [feature_zone], [])
    assert status == "breach"
    assert name == "Hyderabad Military Base"
    assert breach["kind"] == "zone"
    assert breach["severity"] == "prohibited"

    # Expired notice should NOT trigger breach
    expired_notice = {
        "notice_id": "RN-OLD",
        "title": "Old Rally",
        "starts_at": "2026-01-01T08:00:00Z",
        "ends_at": "2026-01-01T12:00:00Z",
        "area": feature_zone["geometry"],
    }
    now_recent = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    st_exp, _, br_exp = engine.evaluate_drone(drone, [], [expired_notice], now_dt=now_recent)
    assert st_exp == "ok"
    assert br_exp is None


def test_contract_3_pilot_drone_isolation():
    sim = FleetSimulator()
    sim.start(count=10, seed=1)

    # Assign one drone to pilot U-PILOT-1
    sim.drones[0].owner_id = "U-PILOT-1"

    # Pilot request should only see their drone
    pilot_user = {"user_id": "U-PILOT-1", "role": "pilot"}
    res_pilot = sim.get_drones(user=pilot_user)
    assert len(res_pilot["drones"]) == 1
    assert res_pilot["drones"][0]["drone_id"] == sim.drones[0].drone_id

    # Another pilot with no drones sees 0 drones
    other_pilot = {"user_id": "U-PILOT-2", "role": "pilot"}
    res_other = sim.get_drones(user=other_pilot)
    assert len(res_other["drones"]) == 0

    # Official sees all drones
    official_user = {"user_id": "U-OFFICIAL", "role": "official"}
    res_off = sim.get_drones(user=official_user)
    assert len(res_off["drones"]) == 10

    sim.stop()


def test_mavlink_telemetry_adapter_p1_stretch():
    # Mock MAVLink GLOBAL_POSITION_INT message
    class MockGlobalPositionInt:
        lat = 174200000       # 17.42 deg
        lon = 784500000       # 78.45 deg
        relative_alt = 62000  # 62.0 m
        vx = 800              # 8.0 m/s north
        vy = 600              # 6.0 m/s east -> 10.0 m/s total
        hdg = 3687            # 36.87 deg

    adapter = MavlinkAdapter(drone_id="MAV-SITL-01")
    adapter.battery_pct = 88.0

    rec = adapter.handle_global_position(MockGlobalPositionInt())
    assert rec["source"] == "mavlink"
    assert rec["drone_id"] == "MAV-SITL-01"
    assert rec["position"]["coordinates"] == [78.45, 17.42]
    assert rec["alt_m"] == 62.0
    assert rec["speed_mps"] == 10.0
    assert rec["heading_deg"] == 36.9
    assert rec["battery_pct"] == 88.0
