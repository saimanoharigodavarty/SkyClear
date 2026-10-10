"""ArduPilot SITL / MAVLink telemetry adapter (P1 stretch).

Parses MAVLink telemetry packets (GLOBAL_POSITION_INT, SYS_STATUS, VFR_HUD)
and maps them into the Contract 5 telemetry format with source: "mavlink".
"""
from datetime import datetime, timezone
import math


def parse_global_position_int(msg, drone_id: str, flight_id: str = None, battery_pct: float = 100.0) -> dict:
    """Convert a MAVLink GLOBAL_POSITION_INT message to a Contract 5 telemetry record.

    MAVLink coordinates are integers scaled by 1e7.
    Altitude is in millimetres (relative_alt above ground).
    Velocities vx, vy are in cm/s. Heading hdg is in centidegrees (cdeg).
    """
    lat = msg.lat / 1e7 if hasattr(msg, "lat") else msg["lat"] / 1e7
    lng = msg.lon / 1e7 if hasattr(msg, "lon") else msg["lon"] / 1e7

    # Relative altitude above home/ground in metres
    rel_alt_mm = getattr(msg, "relative_alt", None) or (msg.get("relative_alt") if isinstance(msg, dict) else 0)
    alt_m = round(rel_alt_mm / 1000.0, 1)

    # Compute ground speed from vx and vy (cm/s -> m/s)
    vx = getattr(msg, "vx", 0) or (msg.get("vx", 0) if isinstance(msg, dict) else 0)
    vy = getattr(msg, "vy", 0) or (msg.get("vy", 0) if isinstance(msg, dict) else 0)
    speed_mps = round(math.hypot(vx, vy) / 100.0, 1)

    # Heading in degrees from centidegrees
    hdg_cdeg = getattr(msg, "hdg", 0) or (msg.get("hdg", 0) if isinstance(msg, dict) else 0)
    heading_deg = round(hdg_cdeg / 100.0, 1)

    return {
        "ts": datetime.now(timezone.utc),
        "drone_id": drone_id,
        "flight_id": flight_id or f"F-MAV-{drone_id}",
        "position": {"type": "Point", "coordinates": [round(lng, 5), round(lat, 5)]},
        "alt_m": alt_m,
        "speed_mps": speed_mps,
        "heading_deg": heading_deg,
        "battery_pct": round(battery_pct, 1),
        "source": "mavlink",
    }


class MavlinkAdapter:
    """Adapter bridging real or SITL MAVLink streams into the telemetry engine."""

    def __init__(self, drone_id: str = "MAV-001", flight_id: str = None):
        self.drone_id = drone_id
        self.flight_id = flight_id
        self.battery_pct = 100.0

    def handle_sys_status(self, msg):
        """Update battery percentage from SYS_STATUS message."""
        battery_remaining = getattr(msg, "battery_remaining", None)
        if battery_remaining is not None and battery_remaining >= 0:
            self.battery_pct = float(battery_remaining)

    def handle_global_position(self, msg) -> dict:
        """Process GLOBAL_POSITION_INT message into Contract 5 record."""
        return parse_global_position_int(
            msg, drone_id=self.drone_id, flight_id=self.flight_id, battery_pct=self.battery_pct
        )
