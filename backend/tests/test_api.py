import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import config
from main import app

client = TestClient(app)
CASES = json.load(open(config.DATA_DIR / "eval_cases.json", encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_eval_case(case):
    r = client.post("/check", json=case["input"])
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == case["expected_verdict"]
    assert set(case["expected_rule_ids"]) <= {c["rule_id"] for c in body["citations"]}


def test_unknown_drone():
    assert client.post("/check", json={"lat": 12.9, "lng": 77.6, "drone_id": "nope"}).status_code == 404


def test_lists():
    assert len(client.get("/drones").json()) == 5
    assert client.get("/zones").json()["type"] == "FeatureCollection"


def test_route_through_airport_flags_issue():
    body = {"drone_id": "small-1800", "speed_mps": 15, "datetime": "2026-10-12T10:00:00+05:30",
            "waypoints": [{"lat": 17.15, "lng": 78.43}, {"lat": 17.32, "lng": 78.43}]}
    r = client.post("/simulate/route", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["summary"]["worst_verdict"] == "permission_needed"
    assert out["summary"]["first_issue"]["zones"] == ["Rajiv Gandhi International Airport"]
    assert out["samples"][0]["verdict"] == "can_fly"


def test_route_needs_two_points():
    body = {"drone_id": "small-1800", "waypoints": [{"lat": 12.9, "lng": 77.6}]}
    assert client.post("/simulate/route", json=body).status_code == 422


def test_zones_bbox_returns_only_zones_in_view():
    all_n = len(client.get("/zones").json()["features"])
    hyd = client.get("/zones?bbox=78.3,17.1,78.6,17.7").json()["features"]
    names = {f["properties"]["name"] for f in hyd}
    assert "Rajiv Gandhi International Airport" in names and 0 < len(hyd) < all_n
    assert client.get("/zones?bbox=bad").status_code == 422


def test_live_and_analytics_have_the_contract_shape():
    assert client.get("/live/drones").json()["drones"] == []
    assert client.get("/analytics/summary").status_code == 401


def test_zone_search_box():
    if config.USE_MONGO:
        pytest.skip("small Atlas tier cannot duplicate the production autocomplete index")
    hits = client.get("/zones/search?q=begum").json()
    assert hits and hits[0]["name"] == "Begumpet Airport" and {"lat", "lng"} <= set(hits[0]["center"])
    assert client.get("/zones/search?q=x").json() == []


def test_config_comes_from_the_server_not_the_page():
    c = client.get("/config").json()
    assert c["city"] and len(c["center"]) == 2 and c["droneClasses"][0]["name"] == "nano"
    js = client.get("/config.js")
    assert js.headers["content-type"].startswith("application/javascript") and js.text.startswith("window.SKYCLEAR = ")


def test_examples_are_built_from_real_zones():
    ex = client.get("/examples").json()
    kinds = {s["kind"] for s in ex["spots"]}
    assert {"airport", "military", "park", "government"} <= kinds and "clear" in kinds
    zones = {f["properties"]["name"] for f in client.get("/zones").json()["features"]}
    assert all(s["label"] in zones for s in ex["spots"] if s["kind"] != "clear")
    assert len(ex["route"]) == 2
