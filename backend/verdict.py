"""Step 3: the rule engine. Code decides the verdict. The LLM never does.

OWNER: rules/verdict teammate. Keep this file free of I/O so it stays easy to test.
"""
import config

SEVERITY = {"allowed": 0, "permission_needed": 1, "prohibited": 2}
EFFECT_TO_VERDICT = {"allowed": "can_fly", "permission_needed": "permission_needed", "prohibited": "prohibited"}


def in_coverage(lat, lng):
    min_lng, min_lat, max_lng, max_lat = config.COVERAGE_BBOX
    return min_lng <= lng <= max_lng and min_lat <= lat <= max_lat


def decide(lat, lng, drone_class, zones, notices, rules_by_zone_type):
    """Return (verdict, used_rules).

    zones: zone dicts from search with an `inside` flag. notices: notices active now at the point.
    rules_by_zone_type: {zone_type: [rule, ...]} already filtered to this drone class.
    used_rules: the rules that produced the verdict (these become citations).
    """
    if not in_coverage(lat, lng):
        return "cannot_determine", []

    hits = []  # (effect, rule)
    for z in zones:
        if not z["inside"]:
            continue
        matching = rules_by_zone_type.get(z["zone_type"], [])
        if not matching:
            return "cannot_determine", []  # inside a zone we have no rule for
        hits.extend((r["effect"], r) for r in matching)
    if notices:
        hits.extend((r["effect"], r) for r in rules_by_zone_type.get("notice", []))

    if not hits:
        return "can_fly", []

    worst = max(SEVERITY[e] for e, _ in hits)
    used = [r for e, r in hits if SEVERITY[e] == worst]
    return EFFECT_TO_VERDICT[[e for e, _ in hits if SEVERITY[e] == worst][0]], used
