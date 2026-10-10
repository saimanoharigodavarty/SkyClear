"""Geofence engine: real-time position checking and forward breach prediction.

Every tick, tests drone positions against restricted zones and active notices,
predicts impending breaches ahead along the current heading vector (with ETA),
and logs breach records into the breaches collection.
"""
from datetime import datetime, timezone
import math
from pathlib import Path
import secrets
import sys

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from backend.geo import point_in_polygon, segment_polygon_intersections
import backend.config as config
import backend.runtime as runtime


_BBOX = {}  # geometry id -> (min_lng, min_lat, max_lng, max_lat), so most zones are ruled out by four comparisons


def _bbox(geom):
    key = id(geom)
    if len(_BBOX) > 4000:
        _BBOX.clear()
    b = _BBOX.get(key)
    if b is None or b[0] is not geom:
        pts = []
        def walk(c):
            if c and isinstance(c[0], (int, float)):
                pts.append(c)
            else:
                for x in c:
                    walk(x)
        walk(geom.get("coordinates", []))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        b = (geom, (min(xs), min(ys), max(xs), max(ys))) if pts else (geom, (0, 0, 0, 0))
        _BBOX[key] = b
    return b[1]


def _near(geom, x0, y0, x1=None, y1=None):
    """False when the point (or the segment x0,y0 to x1,y1) is certainly outside the geometry's bounding box."""
    a, b, c, d = _bbox(geom)
    if x1 is None:
        return a <= x0 <= c and b <= y0 <= d
    return not (max(x0, x1) < a or min(x0, x1) > c or max(y0, y1) < b or min(y0, y1) > d)


def _is_notice_active_at(notice: dict, now: datetime) -> bool:
    """Return True if notice starts_at <= now <= ends_at."""
    starts = notice.get("starts_at")
    ends = notice.get("ends_at")
    if not starts or not ends:
        return True
    try:
        s_dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
        e_dt = datetime.fromisoformat(ends.replace("Z", "+00:00"))
        now_cmp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=now_cmp.tzinfo)
        if e_dt.tzinfo is None:
            e_dt = e_dt.replace(tzinfo=now_cmp.tzinfo)
        return s_dt <= now_cmp <= e_dt
    except Exception:
        return True


def _covered_by_permit(drone, now):
    """A drone may be inside a yellow zone only while its own permit covers where it is and the permit window is open."""
    if drone.permit_area is not None:
        in_window = (drone.permit_start is None or drone.permit_start <= now) and (drone.permit_end is None or now <= drone.permit_end)
        return in_window and point_in_polygon(drone.lng, drone.lat, drone.permit_area)
    return drone.is_approved  # background traffic that was marked as approved


class GeofenceEngine:
    """Evaluates spatial constraints and predicts boundary breaches."""

    def __init__(self, db=None, store=None):
        self.db = db
        self.store = store
        self.lookahead_s = 30.0  # 30-second lookahead along heading

    def evaluate_drone(self, drone, active_zones: list, active_notices: list, now_dt: datetime = None):
        """Test drone against zones and notices. Returns (status, zone_name, breach_event)."""
        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")

        # 0. Altitude: a permit caps the height (and the law does too). Going over it is a breach, close to it is a warning.
        limit = getattr(drone, "alt_limit_m", None)
        if limit and drone.alt_m > limit:
            name = f"Altitude limit ({limit:g} m)"
            drone.status, drone.zone = "breach", name
            return "breach", name, {"event_id": f"BR-{secrets.token_hex(3).upper()}", "drone_id": drone.drone_id, "flight_id": drone.flight_id, "kind": "altitude",
                                    "name": name, "lat": round(drone.lat, 5), "lng": round(drone.lng, 5), "severity": "prohibited", "ts": now_iso}

        # 1. Check current position against active notices
        for n in active_notices:
            geom = n.get("area") or n.get("geometry")
            if not geom:
                continue
            if not _is_notice_active_at(n, now):
                continue

            if point_in_polygon(drone.lng, drone.lat, geom):
                breach = {
                    "event_id": f"BR-{secrets.token_hex(3).upper()}",
                    "drone_id": drone.drone_id,
                    "flight_id": drone.flight_id,
                    "kind": "notice",
                    "name": n.get("title", "Active notice"),
                    "lat": round(drone.lat, 5),
                    "lng": round(drone.lng, 5),
                    "severity": "prohibited",
                    "ts": now_iso,
                }
                drone.status = "breach"
                drone.zone = breach["name"]
                return "breach", breach["name"], breach

        # 2. Check current position against zones
        for z in active_zones:
            geom = z.get("geometry")
            if not geom:
                continue
            props = z.get("properties") if isinstance(z.get("properties"), dict) else z
            zone_type = props.get("zone_type", "")
            # Only restricted airspace triggers a breach
            if zone_type not in ("military", "airport", "government", "prohibited", "restricted"):
                continue

            if _near(geom, drone.lng, drone.lat) and point_in_polygon(drone.lng, drone.lat, geom):
                # If flight is approved, it has clearance to fly unless prohibited
                if zone_type not in ("military", "prohibited") and _covered_by_permit(drone, now):
                    continue

                name = props.get("name") or props.get("zone_id", "Restricted Area")
                breach = {
                    "event_id": f"BR-{secrets.token_hex(3).upper()}",
                    "drone_id": drone.drone_id,
                    "flight_id": drone.flight_id,
                    "kind": "zone",
                    "name": name,
                    "lat": round(drone.lat, 5),
                    "lng": round(drone.lng, 5),
                    "severity": "prohibited" if zone_type in ("military", "prohibited") else "permission_needed",
                    "ts": now_iso,
                }
                drone.status = "breach"
                drone.zone = name
                return "breach", name, breach

        # 3. Lookahead projection along current heading
        lookahead_dist_m = drone.speed_mps * self.lookahead_s
        h_rad = math.radians(drone.heading_deg)
        dlat = (lookahead_dist_m * math.cos(h_rad)) / 111320.0
        cos_lat = math.cos(math.radians(drone.lat))
        dlng = (lookahead_dist_m * math.sin(h_rad)) / (111320.0 * max(0.1, cos_lat))

        ahead_lat = drone.lat + dlat
        ahead_lng = drone.lng + dlng

        # Test line segment against active notices
        earliest_t = None
        warning_name = None
        for n in active_notices:
            geom = n.get("area") or n.get("geometry")
            if not geom:
                continue
            if not _is_notice_active_at(n, now):
                continue
            ts = segment_polygon_intersections(drone.lng, drone.lat, ahead_lng, ahead_lat, geom)
            if ts:
                t = min(ts)
                if earliest_t is None or t < earliest_t:
                    earliest_t = t
                    warning_name = n.get("title", "Active restriction")

        # Test line segment against restricted zones
        for z in active_zones:
            geom = z.get("geometry")
            if not geom:
                continue
            props = z.get("properties") if isinstance(z.get("properties"), dict) else z
            zone_type = props.get("zone_type", "")
            if zone_type not in ("military", "airport", "government", "prohibited", "restricted"):
                continue
            if zone_type not in ("military", "prohibited") and _covered_by_permit(drone, now):
                continue

            if not _near(geom, drone.lng, drone.lat, ahead_lng, ahead_lat):
                continue
            ts = segment_polygon_intersections(drone.lng, drone.lat, ahead_lng, ahead_lat, geom)
            if ts:
                t = min(ts)
                if earliest_t is None or t < earliest_t:
                    earliest_t = t
                    warning_name = props.get("name") or props.get("zone_id", "Restricted zone")

        if earliest_t is not None and earliest_t >= 0.0:
            eta_s = round(earliest_t * self.lookahead_s, 1)
            drone.status = "warning"
            drone.zone = f"{warning_name} (ETA {eta_s}s)"
            return "warning", drone.zone, None

        if limit and drone.alt_m > 0.9 * limit:
            drone.status, drone.zone = "warning", f"Near the altitude limit ({limit:g} m)"
            return "warning", drone.zone, None

        # 4. Airspace clear
        drone.status = "ok"
        drone.zone = None
        return "ok", None, None

    def log_breach(self, breach: dict):
        """Save breach event to database or runtime storage."""
        if config.USE_MONGO and self.db is not None:
            try:
                self.db.breaches.insert_one(dict(breach))
            except Exception:
                pass
        else:
            try:
                runtime.insert("breaches", dict(breach))
            except Exception:
                pass
