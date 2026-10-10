"""Asyncio fleet simulator managing 100 to 1000 concurrent drones.

Coordinates kinematics, geofencing, batched telemetry persistence,
and real-time event streaming for Contract 3 and Contract 4.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import random
import secrets
import sys
import time

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import backend.config as config
from backend.db import get_db
import backend.runtime as runtime
from backend.pipeline import store

from simulator.geofence import GeofenceEngine
from simulator.kinematics import DroneKinematics


class FleetSimulator:
    """Asyncio fleet simulation engine."""

    def __init__(self):
        self.drones = []
        self.is_running = False
        self.speed_x = 1.0
        self.bbox = (78.20, 17.20, 78.65, 17.60)  # Default Hyderabad coverage bbox
        self.geofence = GeofenceEngine()
        self._task = None
        self._subscribers = set()
        self.actual_tps = 0.0
        self._tick_times = []
        self._recent_telemetry = []

    def _get_db(self):
        if config.USE_MONGO:
            try:
                return get_db()
            except Exception:
                return None
        return None

    def start(self, count: int = 100, bbox: list = None, seed: int = 1, speed_x: float = 1.0):
        """Start or reconfigure simulated fleet."""
        if seed is not None:
            random.seed(seed)
        self.speed_x = max(0.1, min(50.0, speed_x))
        if bbox and len(bbox) == 4:
            self.bbox = tuple(bbox)

        # Cancel any existing running loop task
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

        # Clear existing drones
        self.drones = []

        # Load approved flights from runtime/mongo
        approved_flights = []
        try:
            all_flights = runtime.all_("flights")
            approved_flights = [f for f in all_flights if f.get("status") == "approved"]
        except Exception:
            pass

        idx = 1
        # 1. Spawn approved flights on their own routes
        for flight in approved_flights:
            lat = flight.get("lat", 17.42)
            lng = flight.get("lng", 78.45)
            # Build waypoints around the flight point
            wpts = [
                (lat - 0.015, lng - 0.015, 60.0),
                (lat + 0.015, lng + 0.015, 75.0),
                (lat + 0.02, lng - 0.01, 55.0),
            ]
            drone = DroneKinematics(
                drone_id=f"SIM-{idx:03d}",
                flight_id=flight.get("flight_id", f"F-{secrets.token_hex(3).upper()}"),
                initial_lat=lat,
                initial_lng=lng,
                initial_alt_m=60.0,
                speed_mps=11.0,
                battery_pct=random.uniform(70.0, 95.0),
                waypoints=wpts,
                bbox=self.bbox,
                owner_id=flight.get("user_id"),
                is_approved=True,
            )
            self.drones.append(drone)
            idx += 1
            if len(self.drones) >= count:
                break

        # 2. Spawn remaining drones for random missions
        min_lng, min_lat, max_lng, max_lat = self.bbox
        while len(self.drones) < count:
            r_lat = random.uniform(min_lat + 0.05, max_lat - 0.05)
            r_lng = random.uniform(min_lng + 0.05, max_lng - 0.05)
            r_alt = random.uniform(40.0, 90.0)
            r_spd = random.uniform(8.0, 16.0)
            drone = DroneKinematics(
                drone_id=f"SIM-{idx:03d}",
                flight_id=f"F-{secrets.token_hex(3).upper()}",
                initial_lat=r_lat,
                initial_lng=r_lng,
                initial_alt_m=r_alt,
                speed_mps=r_spd,
                battery_pct=random.uniform(60.0, 98.0),
                bbox=self.bbox,
                owner_id=None,
                is_approved=False,
            )
            self.drones.append(drone)
            idx += 1

        self.is_running = True
        self._tick_times = []

        # Start asyncio background task if event loop is running
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run_loop())
        except RuntimeError:
            pass

    def stop(self):
        """Stop simulator and remove simulated drones."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.drones = []
        self.actual_tps = 0.0

    def tick(self, dt: float = 1.0):
        """Advance simulation by dt seconds across all drones."""
        db = self._get_db()
        self.geofence.db = db
        now = datetime.now(timezone.utc)

        # 1. Fetch active zones and notices
        active_zones = []
        active_notices = []
        try:
            active_zones = store.all_zones_geojson().get("features", [])
            active_notices = store.active_notices()
        except Exception:
            pass

        # 2. Step kinematics and geofence for all drones
        telemetry_batch = []
        breaches_generated = []

        for drone in self.drones:
            drone.step(dt * self.speed_x)
            status, zone_name, breach = self.geofence.evaluate_drone(
                drone, active_zones, active_notices, now_dt=now
            )
            if breach:
                breaches_generated.append(breach)
                self.geofence.log_breach(breach)

            # Batch telemetry record (Contract 5)
            rec = drone.telemetry_record(now_dt=now)
            telemetry_batch.append(rec)

        # 3. Batched insert into MongoDB time series collection (Contract 5)
        if config.USE_MONGO and db is not None and telemetry_batch:
            try:
                db.telemetry.insert_many(telemetry_batch, ordered=False)
            except Exception:
                pass
        self._recent_telemetry = telemetry_batch[-100:]

        return {
            "telemetry": telemetry_batch,
            "breaches": breaches_generated,
            "now": now,
        }

    async def _run_loop(self):
        """1 Hz asyncio loop stepping kinematics, geofencing, and telemetry batched write."""
        while self.is_running:
            t0 = time.monotonic()
            step_res = self.tick(dt=1.0)
            telemetry_batch = step_res["telemetry"]
            breaches_generated = step_res["breaches"]
            now_iso = step_res["now"].isoformat(timespec="seconds")

            # Broadcast events to SSE subscribers (Contract 3)
            if self._subscribers:
                # Broadcast position snapshot
                positions_sample = [d.snapshot(as_of_iso=now_iso) for d in self.drones[:200]]
                for pos in positions_sample:
                    self._dispatch_event("position", pos)

                for b in breaches_generated:
                    self._dispatch_event("breach", b)

            # Measure actual ticks per second
            t1 = time.monotonic()
            self._tick_times.append(t1)
            if len(self._tick_times) > 10:
                self._tick_times.pop(0)
            if len(self._tick_times) >= 2:
                elapsed = self._tick_times[-1] - self._tick_times[0]
                self.actual_tps = (len(self._tick_times) - 1) / max(0.001, elapsed)
            else:
                self.actual_tps = 1.0

            # Sleep remainder of interval
            duration = t1 - t0
            sleep_time = max(0.01, (1.0 / self.speed_x) - duration)
            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

    def _dispatch_event(self, event_type: str, data: dict):
        """Deliver event to all connected SSE subscriber queues."""
        dead = set()
        for q in self._subscribers:
            try:
                q.put_nowait({"event": event_type, "data": data})
            except Exception:
                dead.add(q)
        self._subscribers.difference_update(dead)

    def subscribe_events(self):
        """Create an asyncio queue to receive live SSE events."""
        q = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe_events(self, q):
        """Remove subscriber queue."""
        self._subscribers.discard(q)

    def get_status(self):
        """Return Contract 4 simulation status."""
        return {
            "running": self.is_running,
            "drones": len(self.drones),
            "ticks_per_second": round(self.actual_tps, 1) if self.is_running else 0.0,
        }

    def get_drones(self, bbox: list = None, user: dict = None):
        """Return Contract 3 drone list."""
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        drones_out = []

        is_pilot = bool(user and user.get("role") == "pilot")
        pilot_id = user.get("user_id") if is_pilot else None

        for d in self.drones:
            # Contract 3: Pilots only receive their own drones. Officials and guests receive all.
            if is_pilot and d.owner_id != pilot_id:
                continue

            snap = d.snapshot(as_of_iso=now_iso)

            # Optional bbox filter [w, s, e, n]
            if bbox and len(bbox) == 4:
                w, s, e, n = bbox
                if not (w <= snap["lng"] <= e and s <= snap["lat"] <= n):
                    continue

            drones_out.append(snap)

        return {"as_of": now_iso, "drones": drones_out}

    def inject_vip_scenario(self):
        """Publish a notice that crosses paths of running drones to demo live breaches (Contract 4)."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")
        later_iso = (now.replace(hour=(now.hour + 4) % 24)).isoformat(timespec="seconds")

        # Pick location near active drones or Hyderabad center
        if self.drones:
            sample_drones = self.drones[:5]
            avg_lat = sum(d.lat for d in sample_drones) / len(sample_drones)
            avg_lng = sum(d.lng for d in sample_drones) / len(sample_drones)
        else:
            avg_lat, avg_lng = 17.43, 78.44

        # Create a restricted corridor polygon across active drone paths
        corridor_notice = {
            "notice_id": f"RN-VIP-{secrets.token_hex(2).upper()}",
            "title": "VIP Motorcade Restricted Airspace",
            "text": "Temporary flight restriction for official dignitary movement.",
            "starts_at": now_iso,
            "ends_at": later_iso,
            "status": "active",
            "source": "State Police Airspace Notice",
            "area": {
                "type": "Polygon",
                "coordinates": [[
                    [round(avg_lng - 0.02, 5), round(avg_lat - 0.01, 5)],
                    [round(avg_lng + 0.02, 5), round(avg_lat - 0.01, 5)],
                    [round(avg_lng + 0.02, 5), round(avg_lat + 0.01, 5)],
                    [round(avg_lng - 0.02, 5), round(avg_lat + 0.01, 5)],
                    [round(avg_lng - 0.02, 5), round(avg_lat - 0.01, 5)],
                ]]
            }
        }

        # Store notice in runtime and Mongo
        runtime.insert("notices", corridor_notice)
        db = self._get_db()
        if db is not None:
            try:
                db.notices.insert_one(dict(corridor_notice))
            except Exception:
                pass

        # Trigger immediate geofence evaluation on running drones
        affected = 0
        for d in self.drones:
            st, name, breach = self.geofence.evaluate_drone(d, [], [corridor_notice], now_dt=now)
            if breach or st == "warning":
                affected += 1
                if breach:
                    self.geofence.log_breach(breach)
                    self._dispatch_event("breach", breach)

                # Generate alert notification for pilot if drone has an owner
                if d.owner_id:
                    alert_doc = {
                        "notification_id": f"NT-{secrets.token_hex(3).upper()}",
                        "user_id": d.owner_id,
                        "kind": "notice",
                        "title": f"Airspace Alert: {corridor_notice['title']}",
                        "body": f"Your flight {d.flight_id} is affected by an active restriction notice.",
                        "severity": "high",
                        "flight_id": d.flight_id,
                        "read": False,
                        "created_at": now_iso,
                    }
                    runtime.insert("notifications", alert_doc)
                    self._dispatch_event("alert", alert_doc)

        return {
            "ok": True,
            "notice_id": corridor_notice["notice_id"],
            "title": corridor_notice["title"],
            "affected_drones": affected,
        }


_simulator_instance = None


def get_fleet_simulator() -> FleetSimulator:
    """Return shared FleetSimulator singleton."""
    global _simulator_instance
    if _simulator_instance is None:
        _simulator_instance = FleetSimulator()
    return _simulator_instance
