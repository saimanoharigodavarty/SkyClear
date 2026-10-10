"""Drone flight simulation helpers: turn waypoints into evenly spaced samples and summarise them.

OWNER: simulation teammate. No I/O here, so it is easy to test. A real autopilot (MAVLink on a
simulator) would later feed the same kind of samples.
"""
from geo import corridor_intersects_polygon, haversine_km, segment_polygon_intersections

STEP_M = 100.0
ORDER = {"can_fly": 0, "cannot_determine": 1, "permission_needed": 2, "prohibited": 3}


def sample_route(waypoints, speed_mps, step_m=STEP_M, geometries=None, corridor_m=0.0):
    """waypoints: [(lat, lng), ...].

    geometries: optional list of GeoJSON polygons to compute exact entry/exit intersections (A3 fix).
    Returns [{lat, lng, dist_m, t_s}] sampled by distance and exact geometry intersections.
    """
    samples, total = [], 0.0
    geometries = geometries or []

    for (la1, ln1), (la2, ln2) in zip(waypoints, waypoints[1:]):
        seg = haversine_km(la1, ln1, la2, ln2) * 1000
        n = max(1, int(seg // step_m))
        fractions = set(i / n for i in range(n))

        # A3 fix: insert exact intersection parameters with restricted geometries
        for geom in geometries:
            ts = segment_polygon_intersections(ln1, la1, ln2, la2, geom)
            for t in ts:
                fractions.add(t)
                # Sample slightly inside the boundary to ensure point lies within the polygon
                if t > 0.0001:
                    fractions.add(max(0.0, t - 0.0001))
                if t < 0.9999:
                    fractions.add(min(1.0, t + 0.0001))
            if len(ts) >= 2:
                for i in range(len(ts) - 1):
                    fractions.add((ts[i] + ts[i + 1]) / 2.0)

        sorted_f = sorted(fractions)
        for f in sorted_f:
            d_m = round(total + seg * f, 1)
            # Avoid duplicate samples within 0.5 metres
            if samples and abs(samples[-1]["dist_m"] - d_m) < 0.5:
                continue
            samples.append({
                "lat": la1 + (la2 - la1) * f,
                "lng": ln1 + (ln2 - ln1) * f,
                "dist_m": d_m,
                "t_s": round((total + seg * f) / speed_mps, 1)
            })
        total += seg

    la, ln = waypoints[-1]
    last_d = round(total, 1)
    if not samples or abs(samples[-1]["dist_m"] - last_d) >= 0.5:
        samples.append({"lat": la, "lng": ln, "dist_m": last_d, "t_s": round(total / speed_mps, 1)})
    return samples


def check_corridor(waypoints, corridor_m, geometries):
    """Check if any geometry intersects the corridor buffer around the route (P1)."""
    intersecting = []
    for geom in geometries:
        if corridor_intersects_polygon(waypoints, corridor_m, geom):
            intersecting.append(geom)
    return intersecting


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
