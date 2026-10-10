"""Unit tests for the rule engine. These cover the two false-safe bugs found in the product review (A1, A2)."""
from verdict import decide

AIRPORT_RULE = {"rule_id": "R-001", "zone_type": "airport", "effect": "permission_needed", "text": "t", "source": "s"}
MIL_RULE = {"rule_id": "R-002", "zone_type": "military", "effect": "prohibited", "text": "t", "source": "s"}
PT = (17.4, 78.4)  # inside coverage


def zone(zone_type, inside=True):
    return {"zone_type": zone_type, "inside": inside, "name": zone_type}


def test_a1_active_notice_without_a_rule_is_not_ignored():
    notice = {"notice_id": "RN-1", "title": "VIP movement", "text": "No flying.", "source": "Authority"}
    verdict, used = decide(*PT, "small", [], [notice], {})
    assert verdict == "prohibited"
    assert used[0]["rule_id"] == "RN-1"  # the notice itself is cited


def test_a2_unknown_zone_does_not_hide_prohibited():
    zones = [zone("mystery"), zone("military")]
    verdict, used = decide(*PT, "small", zones, [], {"military": [MIL_RULE]})
    assert verdict == "prohibited" and used == [MIL_RULE]


def test_unknown_zone_beats_a_milder_rule():
    zones = [zone("mystery"), zone("airport")]
    assert decide(*PT, "small", zones, [], {"airport": [AIRPORT_RULE]}) == ("cannot_determine", [])


def test_unknown_zone_alone_is_cannot_determine():
    assert decide(*PT, "small", [zone("mystery")], [], {}) == ("cannot_determine", [])


def test_nothing_found_inside_coverage_is_can_fly():
    assert decide(*PT, "small", [zone("airport", inside=False)], [], {}) == ("can_fly", [])


def test_outside_coverage_is_cannot_determine():
    assert decide(51.5, -0.12, "small", [], [], {}) == ("cannot_determine", [])


# ---- Fix A3: Route sampling geometry intersection ----
def test_a3_narrow_corridor_is_caught_on_route():
    from sim import sample_route
    from geo import point_in_polygon

    # Route: 2 km east-west leg from lng 78.40 to 78.42 at lat 17.40
    waypoints = [(17.40, 78.40), (17.40, 78.42)]
    # Narrow VIP corridor: 20 metres wide at lng 78.4100 to 78.4102
    corridor = {
        "type": "Polygon",
        "coordinates": [[[78.4100, 17.39], [78.4102, 17.39], [78.4102, 17.41], [78.4100, 17.41], [78.4100, 17.39]]]
    }
    # With geometry intersection sampling, corridor is guaranteed to have samples inside
    samples = sample_route(waypoints, speed_mps=10.0, step_m=100.0, geometries=[corridor])
    caught = [s for s in samples if point_in_polygon(s["lng"], s["lat"], corridor)]
    assert len(caught) > 0, "A3 fix: narrow corridor must be sampled along route"


# ---- Fix A4: True point-to-segment distance ----
def test_a4_true_point_to_segment_distance():
    from geo import distance_to_polygon_km

    # Long rectangular polygon from lng 78.0 to 78.1 (about 10.6 km long)
    poly = {
        "type": "Polygon",
        "coordinates": [[[78.0, 17.0], [78.1, 17.0], [78.1, 17.05], [78.0, 17.05], [78.0, 17.0]]]
    }
    # Point at midpoint of bottom edge, 110 metres south: lat 16.999, lng 78.05
    # Nearest vertex is > 5 km away, but nearest segment is ~0.11 km away
    d = distance_to_polygon_km(16.999, 78.05, poly)
    assert 0.09 < d < 0.15, f"Expected ~0.11 km true segment distance, got {d} km"


# ---- Fix A5: Polygon holes (inner rings) ----
def test_a5_polygon_holes_respected():
    from geo import point_in_polygon

    # Polygon with outer boundary [78.0, 17.0] to [78.1, 17.1] and hole at center [78.04, 17.04] to [78.06, 17.06]
    poly_with_hole = {
        "type": "Polygon",
        "coordinates": [
            [[78.0, 17.0], [78.1, 17.0], [78.1, 17.1], [78.0, 17.1], [78.0, 17.0]],  # outer
            [[78.04, 17.04], [78.06, 17.04], [78.06, 17.06], [78.04, 17.06], [78.04, 17.04]]  # hole
        ]
    }
    # Point inside the hole should NOT be inside the polygon
    assert not point_in_polygon(78.05, 17.05, poly_with_hole)
    # Point in the solid body should be inside
    assert point_in_polygon(78.02, 17.02, poly_with_hole)


# ---- Fix A6: Timezone offset handling ----
def test_a6_timezone_offset_handling():
    from datetime import timedelta, timezone
    from pipeline import parse_when

    # Naive ISO string should default to local IST (UTC+05:30), not UTC
    dt = parse_when("2026-10-12T17:00:00")
    assert dt.tzinfo is not None
    assert dt.tzinfo.utcoffset(dt) == timedelta(hours=5, minutes=30)

    # Explicit UTC offset should be preserved
    dt_utc = parse_when("2026-10-12T17:00:00Z")
    assert dt_utc.tzinfo.utcoffset(dt_utc) == timedelta(0)


# ---- P1: Altitude and day/night rules ----
def test_p1_altitude_rules():
    # Flying at 150m exceeds 120m limit -> permission_needed
    v1, used1 = decide(*PT, "small", [], [], {}, alt_m=150.0)
    assert v1 == "permission_needed"
    assert any(r["rule_id"] == "R-ALT-120" for r in used1)

    # Flying at 450m exceeds 400m ceiling -> prohibited
    v2, used2 = decide(*PT, "small", [], [], {}, alt_m=450.0)
    assert v2 == "prohibited"
    assert any(r["rule_id"] == "R-ALT-CEIL" for r in used2)


def test_p1_night_flying_rules():
    from datetime import datetime
    from pipeline import LOCAL_TZ

    night_time = datetime(2026, 10, 12, 21, 0, tzinfo=LOCAL_TZ)
    v, used = decide(*PT, "small", [], [], {}, when=night_time, check_night=True)
    assert v == "permission_needed"
    assert any(r["rule_id"] == "R-NIGHT-01" for r in used)

    day_time = datetime(2026, 10, 12, 11, 0, tzinfo=LOCAL_TZ)
    v_day, _ = decide(*PT, "small", [], [], {}, when=day_time, check_night=True)
    assert v_day == "can_fly"


def test_p1_route_corridor_buffering():
    from sim import check_corridor

    waypoints = [(17.40, 78.40), (17.40, 78.42)]
    # Zone 30 metres north of the line: lat 17.4003 (approx 33m north)
    nearby_zone = {
        "type": "Polygon",
        "coordinates": [[[78.405, 17.4003], [78.415, 17.4003], [78.415, 17.405], [78.405, 17.405], [78.405, 17.4003]]]
    }
    # With a 50m corridor buffer, it should be detected
    hits = check_corridor(waypoints, corridor_m=50.0, geometries=[nearby_zone])
    assert len(hits) == 1
    # With a 10m corridor buffer, it should not hit
    hits_narrow = check_corridor(waypoints, corridor_m=10.0, geometries=[nearby_zone])
    assert len(hits_narrow) == 0
