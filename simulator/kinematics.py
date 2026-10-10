"""Drone kinematics and physics simulation.

Kinematics model with speed, heading, altitude, battery drain, wind drift,
and GPS sensor noise. Approved flights follow their planned waypoints,
while other drones execute randomized area patrol missions.
"""
from datetime import datetime, timezone
import math
import random


def bearing_deg(lat1, lng1, lat2, lng2):
    """Compute initial compass bearing from (lat1, lng1) to (lat2, lng2) in degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
    initial = math.degrees(math.atan2(y, x))
    return (initial + 360.0) % 360.0


def haversine_m(lat1, lng1, lat2, lng2):
    """Distance in metres between two coordinates."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class DroneKinematics:
    """State and physics engine for a single simulated drone."""

    def __init__(
        self,
        drone_id: str,
        flight_id: str,
        initial_lat: float,
        initial_lng: float,
        initial_alt_m: float = 50.0,
        speed_mps: float = 10.0,
        battery_pct: float = 95.0,
        waypoints: list = None,
        bbox: tuple = None,
        owner_id: str = None,
        is_approved: bool = False,
        kind: str = "traffic",
        permit_id: str = None,
        permit_area: dict = None,
        permit_start: datetime = None,
        permit_end: datetime = None,
        one_shot: bool = False,
    ):
        # kind "flight" is a pilot's real (simulated) flight tied to a permit, "traffic" is background fleet traffic.
        self.kind = kind
        self.permit_id = permit_id
        self.permit_area = permit_area      # GeoJSON polygon the permit covers
        self.permit_start = permit_start
        self.permit_end = permit_end
        self.one_shot = one_shot            # fly the route once, return and land (a pilot's flight)
        self.launch_pos = (initial_lat, initial_lng)
        self.recalled = False
        self.landed = False
        self.landed_reason = None
        self.last_breach = None             # (kind, name) of the breach already reported, so one entry is one event
        self.breach_count = 0
        self.max_alt_m = initial_alt_m
        self.launched_at = datetime.now(timezone.utc)
        self.drone_id = drone_id
        self.flight_id = flight_id
        self.owner_id = owner_id
        self.is_approved = is_approved

        self.lat = initial_lat
        self.lng = initial_lng
        self.alt_m = initial_alt_m
        self.target_alt_m = initial_alt_m

        self.speed_mps = speed_mps
        self.target_speed_mps = speed_mps
        self.heading_deg = 0.0

        self.battery_pct = max(5.0, min(100.0, battery_pct))
        self.drain_rate_per_sec = 0.025  # ~1.5% per minute

        self.bbox = bbox or (78.20, 17.20, 78.65, 17.60)
        self.waypoints = list(waypoints or [])
        self.waypoint_idx = 0
        if not self.waypoints:
            self._generate_random_waypoints(3)

        if self.waypoints:
            w_lat, w_lng = self.waypoints[0][:2]
            self.heading_deg = bearing_deg(self.lat, self.lng, w_lat, w_lng)

        self.status = "ok"  # "ok", "warning", "breach"
        self.zone = None
        self.source = "sim"

        # Sensor noise state
        self.gps_noise_m = 1.5  # standard deviation in metres
        self.reported_lat = self.lat
        self.reported_lng = self.lng

    def _generate_random_waypoints(self, count: int = 3):
        min_lng, min_lat, max_lng, max_lat = self.bbox
        pts = []
        for _ in range(count):
            r_lat = random.uniform(min_lat + 0.02, max_lat - 0.02)
            r_lng = random.uniform(min_lng + 0.02, max_lng - 0.02)
            r_alt = random.uniform(35.0, 95.0)
            pts.append((r_lat, r_lng, r_alt))
        self.waypoints = pts
        self.waypoint_idx = 0

    def step(self, dt: float, wind_mps: float = 2.0, wind_heading_deg: float = 90.0):
        """Advance dt seconds. A long step (fast playback) is split into steps of at most one second, otherwise a drone
        moves further than the waypoint arrival radius in one step, flies past it and never lands."""
        n = max(1, math.ceil(dt))
        for _ in range(n):
            if self.landed:
                break
            self._step(dt / n, wind_mps, wind_heading_deg)

    def _step(self, dt: float, wind_mps: float = 2.0, wind_heading_deg: float = 90.0):
        """Update kinematics over dt seconds with wind drift, turn limits, and battery drain."""
        if self.landed:
            return
        if not self.waypoints:
            self._generate_random_waypoints(3)

        target = self.waypoints[self.waypoint_idx]
        t_lat, t_lng = target[0], target[1]
        t_alt = target[2] if len(target) > 2 else 50.0

        # Distance to next waypoint
        dist_m = haversine_m(self.lat, self.lng, t_lat, t_lng)
        if dist_m < 25.0:
            self.waypoint_idx += 1
            if self.waypoint_idx >= len(self.waypoints):
                if self.one_shot:
                    # The route is done (or the drone is back after a recall): land here.
                    self.landed = True
                    self.landed_reason = "recalled" if self.recalled else "completed"
                    self.speed_mps = 0.0
                    self.alt_m = 0.0
                    return
                if self.is_approved:
                    # Patrol back and forth or loop
                    self.waypoints.reverse()
                    self.waypoint_idx = 0
                else:
                    self._generate_random_waypoints(3)
            target = self.waypoints[self.waypoint_idx]
            t_lat, t_lng = target[0], target[1]
            t_alt = target[2] if len(target) > 2 else 50.0

        # Steer heading towards target
        desired_heading = bearing_deg(self.lat, self.lng, t_lat, t_lng)
        heading_diff = (desired_heading - self.heading_deg + 180.0) % 360.0 - 180.0
        max_turn = 45.0 * dt  # max 45 degrees per second
        if abs(heading_diff) <= max_turn:
            self.heading_deg = desired_heading
        else:
            self.heading_deg = (self.heading_deg + math.copysign(max_turn, heading_diff)) % 360.0

        # Speed adjustment
        speed_diff = self.target_speed_mps - self.speed_mps
        max_accel = 3.0 * dt
        if abs(speed_diff) <= max_accel:
            self.speed_mps = self.target_speed_mps
        else:
            self.speed_mps += math.copysign(max_accel, speed_diff)

        # Altitude adjustment
        alt_diff = t_alt - self.alt_m
        max_climb = 2.5 * dt
        if abs(alt_diff) <= max_climb:
            self.alt_m = t_alt
        else:
            self.alt_m += math.copysign(max_climb, alt_diff)

        # Velocity components from drone engine
        h_rad = math.radians(self.heading_deg)
        v_drone_north = self.speed_mps * math.cos(h_rad)
        v_drone_east = self.speed_mps * math.sin(h_rad)

        # Wind drift component
        w_rad = math.radians(wind_heading_deg)
        v_wind_north = wind_mps * math.cos(w_rad)
        v_wind_east = wind_mps * math.sin(w_rad)

        total_north = v_drone_north + v_wind_north
        total_east = v_drone_east + v_wind_east

        # Integrate displacement
        dlat = (total_north * dt) / 111320.0
        cos_lat = math.cos(math.radians(self.lat))
        dlng = (total_east * dt) / (111320.0 * max(0.1, cos_lat))

        self.lat += dlat
        self.lng += dlng

        # Keep within bounding box
        min_lng, min_lat, max_lng, max_lat = self.bbox
        if self.lat < min_lat or self.lat > max_lat or self.lng < min_lng or self.lng > max_lng:
            self.lat = max(min_lat + 0.01, min(max_lat - 0.01, self.lat))
            self.lng = max(min_lng + 0.01, min(max_lng - 0.01, self.lng))
            if not self.is_approved:
                self._generate_random_waypoints(3)

        # Battery drain proportional to speed and time
        drain = (self.drain_rate_per_sec * (1.0 + (self.speed_mps / 15.0))) * dt
        self.battery_pct = max(0.0, self.battery_pct - drain)
        self.max_alt_m = max(self.max_alt_m, self.alt_m)

        # Update reported position with sensor noise once per step
        self.reported_lat, self.reported_lng = self.get_reported_position()

    def recall(self):
        """Order the drone home: fly straight back to where it launched, then land."""
        self.recalled = True
        self.one_shot = True
        self.waypoints = [(self.launch_pos[0], self.launch_pos[1], 40.0)]
        self.waypoint_idx = 0
        self.target_speed_mps = max(self.target_speed_mps, 14.0)

    def get_reported_position(self):
        """Return (lat, lng) with realistic GPS sensor noise added."""
        deg_per_m_lat = 1.0 / 111320.0
        deg_per_m_lng = 1.0 / (111320.0 * math.cos(math.radians(self.lat)))
        noise_lat = random.gauss(0.0, self.gps_noise_m * deg_per_m_lat)
        noise_lng = random.gauss(0.0, self.gps_noise_m * deg_per_m_lng)
        return self.lat + noise_lat, self.lng + noise_lng

    def snapshot(self, as_of_iso: str = None):
        """Return Contract 3 drone state dict."""
        ts = as_of_iso or datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {
            "drone_id": self.drone_id,
            "flight_id": self.flight_id,
            "lat": round(self.reported_lat, 5),
            "lng": round(self.reported_lng, 5),
            "alt_m": round(self.alt_m, 1),
            "speed_mps": round(self.speed_mps, 1),
            "heading_deg": round(self.heading_deg, 1),
            "battery_pct": round(self.battery_pct, 1),
            "status": self.status,
            "zone": self.zone,
            "phase": "returning" if self.recalled else "flying",
            "kind": self.kind,
            "ts": ts,
        }

    def telemetry_record(self, now_dt: datetime = None):
        """Return Contract 5 time series telemetry record."""
        ts = now_dt or datetime.now(timezone.utc)
        return {
            "ts": ts,
            "drone_id": self.drone_id,
            "flight_id": self.flight_id,
            "position": {"type": "Point", "coordinates": [round(self.reported_lng, 5), round(self.reported_lat, 5)]},
            "alt_m": round(self.alt_m, 1),
            "speed_mps": round(self.speed_mps, 1),
            "heading_deg": round(self.heading_deg, 1),
            "battery_pct": round(self.battery_pct, 1),
            "source": self.source,
        }
