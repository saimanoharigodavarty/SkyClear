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
