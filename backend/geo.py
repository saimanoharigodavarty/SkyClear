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
    """geometry is a GeoJSON Polygon (holes are ignored in this base version)."""
    return point_in_ring(lng, lat, geometry["coordinates"][0])


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_to_polygon_km(lat, lng, geometry):
    """Approximate: distance to the nearest vertex. 0 if inside. Good enough for 'nearby' lists."""
    if point_in_polygon(lng, lat, geometry):
        return 0.0
    return min(haversine_km(lat, lng, y, x) for x, y in geometry["coordinates"][0])


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
