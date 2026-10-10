"""Small pure-Python geometry helpers used by the local (no MongoDB) store."""
import math


def point_in_ring(lng, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygon(lng, lat, geometry):
    """geometry is a GeoJSON Polygon or MultiPolygon with hole support (A5)."""
    geom_type = geometry.get("type", "Polygon")
    if geom_type == "Polygon":
        rings = geometry.get("coordinates", [])
        if not rings:
            return False
        if not point_in_ring(lng, lat, rings[0]):
            return False
        # Check holes (inner rings)
        for hole in rings[1:]:
            if point_in_ring(lng, lat, hole):
                return False
        return True
    elif geom_type == "MultiPolygon":
        for poly_coords in geometry.get("coordinates", []):
            if not poly_coords:
                continue
            if point_in_ring(lng, lat, poly_coords[0]):
                in_hole = any(point_in_ring(lng, lat, hole) for hole in poly_coords[1:])
                if not in_hole:
                    return True
        return False
    return False


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_to_segment_dist_km(lat, lng, lat1, lng1, lat2, lng2):
    """True point-to-segment distance in km (A4 fix)."""
    lat_mid = (lat1 + lat2) / 2.0
    scale_x = 111.32 * math.cos(math.radians(lat_mid))
    scale_y = 110.57
    x = (lng - lng1) * scale_x
    y = (lat - lat1) * scale_y
    dx = (lng2 - lng1) * scale_x
    dy = (lat2 - lat1) * scale_y
    denom = dx * dx + dy * dy
    if denom < 1e-12:
        return haversine_km(lat, lng, lat1, lng1)
    t = max(0.0, min(1.0, (x * dx + y * dy) / denom))
    closest_lat = lat1 + t * (lat2 - lat1)
    closest_lng = lng1 + t * (lng2 - lng1)
    return haversine_km(lat, lng, closest_lat, closest_lng)


def _iter_polygon_segments(geometry):
    """Yield all segment coordinate pairs ((lng1, lat1), (lng2, lat2)) in the geometry."""
    geom_type = geometry.get("type", "Polygon")
    if geom_type == "Polygon":
        polygons = [geometry.get("coordinates", [])]
    elif geom_type == "MultiPolygon":
        polygons = geometry.get("coordinates", [])
    else:
        polygons = []
    for rings in polygons:
        for ring in rings:
            for i in range(len(ring) - 1):
                yield ring[i], ring[i + 1]


def distance_to_polygon_km(lat, lng, geometry):
    """True minimum distance to polygon in km. 0 if inside (A4 fix)."""
    if point_in_polygon(lng, lat, geometry):
        return 0.0
    min_dist = float("inf")
    for (x1, y1), (x2, y2) in _iter_polygon_segments(geometry):
        d = point_to_segment_dist_km(lat, lng, y1, x1, y2, x2)
        if d < min_dist:
            min_dist = d
    return 0.0 if min_dist == float("inf") else min_dist


def segment_intersection_param(p1, p2, p3, p4):
    """Return t in [0, 1] for segment p1->p2 intersecting p3->p4, or None."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    d1x, d1y = x2 - x1, y2 - y1
    d2x, d2y = x4 - x3, y4 - y3
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-14:
        return None
    dx, dy = x3 - x1, y3 - y1
    t = (dx * d2y - dy * d2x) / denom
    u = (dx * d1y - dy * d1x) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


def segment_polygon_intersections(lng1, lat1, lng2, lat2, geometry):
    """Return sorted list of t values in [0, 1] where the segment crosses polygon boundaries (A3 fix)."""
    p1 = (lng1, lat1)
    p2 = (lng2, lat2)
    ts = []
    for q1, q2 in _iter_polygon_segments(geometry):
        t = segment_intersection_param(p1, p2, q1, q2)
        if t is not None:
            ts.append(t)
    return sorted(set(ts))


def segment_intersects_polygon(lng1, lat1, lng2, lat2, geometry):
    """Test whether segment intersects or enters polygon geometry."""
    if point_in_polygon(lng1, lat1, geometry) or point_in_polygon(lng2, lat2, geometry):
        return True
    return bool(segment_polygon_intersections(lng1, lat1, lng2, lat2, geometry))


def corridor_intersects_polygon(waypoints, corridor_m, geometry):
    """Test whether a route buffered by corridor_m touches or enters a polygon (P1)."""
    corridor_km = corridor_m / 1000.0
    for i in range(len(waypoints) - 1):
        la1, ln1 = waypoints[i]
        la2, ln2 = waypoints[i + 1]
        if segment_intersects_polygon(ln1, la1, ln2, la2, geometry):
            return True
        # Check endpoints and segments distance
        if distance_to_polygon_km(la1, ln1, geometry) <= corridor_km:
            return True
        if distance_to_polygon_km(la2, ln2, geometry) <= corridor_km:
            return True
        # Check polygon vertices distance to route segment
        for (vx, vy), _ in _iter_polygon_segments(geometry):
            if point_to_segment_dist_km(vy, vx, la1, ln1, la2, ln2) <= corridor_km:
                return True
    return False


def circle(lat, lng, radius_km, n=32):
    """GeoJSON Polygon approximating a circle."""
    coords = []
    for i in range(n):
        a = 2 * math.pi * i / n
        dlat = (radius_km / 111.32) * math.cos(a)
        dlng = (radius_km / (111.32 * math.cos(math.radians(lat)))) * math.sin(a)
        coords.append([round(lng + dlng, 5), round(lat + dlat, 5)])
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def ring_from_points(points):
    """A closed GeoJSON ring from [lng, lat] corners drawn by an official, or raise ValueError. Needs 3 to 60 corners, a real area, no crossing edges."""
    pts = [[round(float(p[0]), 6), round(float(p[1]), 6)] for p in points]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not 3 <= len(pts) <= 60:
        raise ValueError("draw between 3 and 60 corners")
    if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in pts):
        raise ValueError("a corner is outside the world")
    if max(p[0] for p in pts) - min(p[0] for p in pts) > 0.5 or max(p[1] for p in pts) - min(p[1] for p in pts) > 0.5:
        raise ValueError("the area is larger than about 50 km across")

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # neighbouring edges share a corner
            a, b, c, d = pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]
            if ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d):
                raise ValueError("the edges cross each other, redraw the corners in order")
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    if abs(area2) < 1e-10:
        raise ValueError("the corners are in a line, the area is empty")
    return pts + [pts[0]]


def ring_center_radius_km(ring):
    """Centre (mean of the corners) and the distance in km from it to the farthest corner."""
    pts = ring[:-1]
    lat = sum(p[1] for p in pts) / len(pts)
    lng = sum(p[0] for p in pts) / len(pts)
    far = max(math.hypot((p[1] - lat) * 111.32, (p[0] - lng) * 111.32 * math.cos(math.radians(lat))) for p in pts)
    return lat, lng, round(far, 3)
