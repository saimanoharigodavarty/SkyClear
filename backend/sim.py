"""Drone flight simulation helpers: turn waypoints into evenly spaced samples and summarise them.

OWNER: simulation teammate. No I/O here, so it is easy to test. A real autopilot (MAVLink on a
simulator) would later feed the same kind of samples.
"""
from geo import haversine_km

STEP_M = 100.0
ORDER = {"can_fly": 0, "cannot_determine": 1, "permission_needed": 2, "prohibited": 3}


def sample_route(waypoints, speed_mps, step_m=STEP_M):
    """waypoints: [(lat, lng), ...]. Returns [{lat, lng, dist_m, t_s}] about every step_m metres."""
    samples, total = [], 0.0
    for (la1, ln1), (la2, ln2) in zip(waypoints, waypoints[1:]):
        seg = haversine_km(la1, ln1, la2, ln2) * 1000
        n = max(1, int(seg // step_m))
        for i in range(n):
            f = i / n
            samples.append({"lat": la1 + (la2 - la1) * f, "lng": ln1 + (ln2 - ln1) * f,
                            "dist_m": round(total + seg * f, 1), "t_s": round((total + seg * f) / speed_mps, 1)})
        total += seg
    la, ln = waypoints[-1]
    samples.append({"lat": la, "lng": ln, "dist_m": round(total, 1), "t_s": round(total / speed_mps, 1)})
    return samples


def summarize_route(samples):
    """Worst verdict, where it first happens, and total length/duration."""
    worst = max(samples, key=lambda s: ORDER[s["verdict"]])
    first_bad = next((s for s in samples if s["verdict"] in ("permission_needed", "prohibited")), None)
    return {
        "worst_verdict": worst["verdict"],
        "first_issue": None if first_bad is None else {
            "verdict": first_bad["verdict"], "dist_m": first_bad["dist_m"], "t_s": first_bad["t_s"],
            "zones": first_bad["zones"], "rule_ids": first_bad["rule_ids"]},
        "length_m": samples[-1]["dist_m"], "duration_s": samples[-1]["t_s"],
    }
