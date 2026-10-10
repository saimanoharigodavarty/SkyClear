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
