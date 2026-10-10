"""Step 3: the rule engine. Code decides the verdict. The LLM never does.

OWNER: rules/verdict teammate. Keep this file free of I/O so it stays easy to test.
"""
import config

SEVERITY = {"allowed": 0, "permission_needed": 1, "prohibited": 2}
EFFECT_TO_VERDICT = {"allowed": "can_fly", "permission_needed": "permission_needed", "prohibited": "prohibited"}


def in_coverage(lat, lng):
    min_lng, min_lat, max_lng, max_lat = config.COVERAGE_BBOX
    return min_lng <= lng <= max_lng and min_lat <= lat <= max_lat


def decide(lat, lng, drone_class, zones, notices, rules_by_zone_type, alt_m=None, when=None, check_night=False):
    """Return (verdict, used_rules).

    zones: zone dicts from search with an `inside` flag. notices: notices active now at the point.
    rules_by_zone_type: {zone_type: [rule, ...]} already filtered to this drone class.
    used_rules: the rules that produced the verdict (these become citations).
    alt_m: flight altitude in metres AGL (P1).
    when: datetime for time-of-day checks (day/night) (P1).
    check_night: enable night flight permission check (P1).
    """
    if not in_coverage(lat, lng):
        return "cannot_determine", []

    hits = []  # (effect, rule)
    unknown_zone = False
    for z in zones:
        if not z["inside"]:
            continue
        matching = rules_by_zone_type.get(z["zone_type"], [])
        if matching:
            hits.extend((r["effect"], r) for r in matching)
        else:
            unknown_zone = True  # inside a zone we have no rule for
    if notices:
        notice_rules = rules_by_zone_type.get("notice", [])
        if not notice_rules:
            # An active official notice must never be ignored, even with no rule on file for it.
            notice_rules = [{"rule_id": n.get("notice_id", "NOTICE"), "effect": "prohibited", "zone_type": "notice",
                             "text": n.get("text") or n.get("title", "Active restriction notice."),
                             "source": n.get("source", "Official notice")} for n in notices]
        hits.extend((r["effect"], r) for r in notice_rules)

    # Altitude rules (P1)
    if alt_m is not None:
        if alt_m > 400:
            hits.append(("prohibited", {
                "rule_id": "R-ALT-CEIL", "effect": "prohibited", "zone_type": "altitude",
                "text": "Flights exceeding 400m AGL are prohibited in civil airspace.",
                "source": "Standard Drone Regulations (Altitude Limits)"
            }))
        elif alt_m > 120:
            hits.append(("permission_needed", {
                "rule_id": "R-ALT-120", "effect": "permission_needed", "zone_type": "altitude",
                "text": "Flights above 120m (400 ft) AGL require prior permission from the authority.",
                "source": "Standard Drone Regulations (Altitude Limits)"
            }))

    # Day or night rules (P1)
    if check_night and when is not None:
        # Check local hour (convert to local time if timezone aware, or assume local)
        local_hour = when.hour
        if local_hour < 6 or local_hour >= 18:
            hits.append(("permission_needed", {
                "rule_id": "R-NIGHT-01", "effect": "permission_needed", "zone_type": "time_of_day",
                "text": "Night drone operations require permission and anti-collision lighting.",
                "source": "Standard Operating Conditions"
            }))

    worst = max((SEVERITY[e] for e, _ in hits), default=-1)
    if worst == SEVERITY["prohibited"]:
        pass  # nothing can be stricter than prohibited
    elif unknown_zone:
        return "cannot_determine", []  # an unknown zone could be stricter than what we found
    if not hits:
        return "can_fly", []

    used = [r for e, r in hits if SEVERITY[e] == worst]
    return EFFECT_TO_VERDICT[[e for e, _ in hits if SEVERITY[e] == worst][0]], used
