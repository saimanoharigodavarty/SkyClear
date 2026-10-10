"""Asyncio fleet simulator managing 100 to 1000 concurrent drones.

Coordinates kinematics, geofencing, batched telemetry persistence,
and real-time event streaming for Contract 3 and Contract 4.
"""
import asyncio
import math
import threading
from datetime import datetime, timedelta, timezone
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
        self._lock = threading.RLock()
        self._loop = None            # the server's event loop, set at startup, so any thread can start the simulation
        self.on_landed = None        # callback(flight_id, reason, stats): a pilot's flight ended
        self.on_breach = None        # callback(breach, drone): a pilot's drone entered restricted airspace
        self.events = {}             # flight_id -> the last events for that flight (took off, warning, breach, landed), for the big screen
        self._zones_cache = (0.0, [])
        self._notices_cache = (0.0, [])
        self._tick_n = 0

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

        # A restart replaces the background traffic only. Pilots' flights keep flying.
        with self._lock:
            self.drones = [d for d in self.drones if d.kind == "flight"]
        idx = 1

        # Background traffic: random missions, so the airspace is busy and the scale is real.
        traffic_target = count + len(self.drones)
        min_lng, min_lat, max_lng, max_lat = self.bbox
        while len(self.drones) < traffic_target:
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
        self._ensure_task()

    def attach_loop(self, loop):
        """Called once at server startup. Lets flights launched from any thread start the simulation loop."""
        self._loop = loop

    def _ensure_task(self):
        """Make sure the 1 Hz loop is running, from the event loop thread or from any other thread."""
        def go():
            if self._task is None or self._task.done():
                self._task = asyncio.get_running_loop().create_task(self._run_loop())
        try:
            asyncio.get_running_loop()
            go()
        except RuntimeError:
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(go)

    def stop(self):
        """Remove the background traffic. Pilots' flights keep flying, the loop stops only when nothing is left in the air."""
        with self._lock:
            self.drones = [d for d in self.drones if d.kind == "flight"]
            if not self.drones:
                self._halt()

    def stop_all(self):
        """Remove every simulated drone, including pilots' flights."""
        with self._lock:
            self.drones = []
            self._halt()

    def _halt(self):
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.actual_tps = 0.0

    # ---- a pilot's flight: launch, recall, land ----
    def launch_flight(self, flight, permit=None, alt_max_m=60.0, laps=2, manual=False):
        """Start a simulated drone for one flight. Needs a cleared preflight, which the API checks before calling this.

        The route is a loop of `laps` circles around the flight spot (inside the permit area when there is a permit),
        then back to the launch point and landing.
        """
        lat, lng = flight["lat"], flight["lng"]
        radius_m = 150.0
        pts = []
        for lap in range(laps):
            for a in range(0, 360, 45):
                r = math.radians(a)
                pts.append((lat + (radius_m * math.cos(r)) / 111320.0, lng + (radius_m * math.sin(r)) / (111320.0 * max(0.1, math.cos(math.radians(lat)))),
                            min(alt_max_m, 55.0)))
        pts.append((lat, lng, 30.0))
        area = permit.get("area") if permit else None
        start = datetime.fromisoformat(permit["starts_at"].replace("Z", "+00:00")) if permit else None
        end = datetime.fromisoformat(permit["ends_at"].replace("Z", "+00:00")) if permit else None
        d = DroneKinematics(
            drone_id=flight.get("drone_id", f"FL-{flight['flight_id']}"), flight_id=flight["flight_id"],
            initial_lat=lat, initial_lng=lng, initial_alt_m=10.0 if manual else 2.0, speed_mps=0.0 if manual else 10.0, battery_pct=random.uniform(88.0, 100.0),
            waypoints=pts, bbox=self.bbox, owner_id=flight.get("pilot_id"), kind="flight", one_shot=not manual, manual=manual,
            alt_limit_m=float(alt_max_m) if permit else 120.0,
            permit_id=permit["permit_id"] if permit else None, permit_area=area,
            permit_start=start.replace(tzinfo=start.tzinfo or timezone.utc) if start else None,
            permit_end=end.replace(tzinfo=end.tzinfo or timezone.utc) if end else None)
        with self._lock:
            self.drones = [x for x in self.drones if x.flight_id != flight["flight_id"]]  # one drone per flight
            self.drones.append(d)
            self.events[flight["flight_id"]] = []
            self.is_running = True
            self._ensure_task()
        self.log_event(flight["flight_id"], "takeoff", "Took off, flying by phone" if manual else "Took off, flying its route")
        return d.drone_id

    def command_flight(self, flight_id, fwd=0.0, right=0.0, yaw=0.0, climb=0.0):
        """Stick positions from the pilot's phone. Returns False if the drone is not in the air or not flown by hand."""
        d = self.get_flight_drone(flight_id)
        if d is None or d.landed or not d.manual:
            return False
        d.set_command(fwd, right, yaw, climb)
        return True

    def return_home_flight(self, flight_id):
        """The pilot presses Return home: the drone flies back to where it launched and lands."""
        d = self.get_flight_drone(flight_id)
        if d is None or d.landed or d.returning or d.recalled:
            return False
        d.return_home()
        self.log_event(flight_id, "home", "Return home pressed")
        return True

    def log_event(self, flight_id, kind, text):
        """A line for the big screen's event log."""
        ev = self.events.setdefault(flight_id, [])
        ev.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "text": text})
        del ev[:-30]

    def flight_events(self, flight_id):
        return list(self.events.get(flight_id, []))

    def get_flight_drone(self, flight_id):
        return next((d for d in self.drones if d.flight_id == flight_id), None)

    def recall_flight(self, flight_id):
        """Order a flight's drone home. Returns True if it was in the air."""
        d = self.get_flight_drone(flight_id)
        if d is None or d.landed:
            return False
        d.recall()
        self.log_event(flight_id, "recall", "Recalled by an officer, flying home")
        return True

    def land_flight(self, flight_id):
        """Land a flight's drone now, where it is, and remove it. Returns its flight stats, or None if it was not in the air."""
        d = self.get_flight_drone(flight_id)
        if d is None or d.landed:
            return None
        d.landed, d.landed_reason, d.speed_mps, d.alt_m = True, "completed", 0.0, 0.0
        now = datetime.now(timezone.utc)
        stats = {"reason": "completed", "breaches": d.breach_count, "max_alt_m": round(d.max_alt_m, 1), "battery_pct": round(d.battery_pct, 1),
                 "launched_at": d.launched_at.isoformat(timespec="seconds"), "landed_at": now.isoformat(timespec="seconds")}
        with self._lock:
            self.drones = [x for x in self.drones if x is not d]
            if not self.drones:
                self._halt()
        self._dispatch_event("landed", {"flight_id": d.flight_id, "drone_id": d.drone_id, **stats})
        self.log_event(d.flight_id, "landed", "Landed")
        return stats

    def tick(self, dt: float = 1.0):
        """Advance simulation by dt seconds across all drones."""
        db = self._get_db()
        self.geofence.db = db
        now = datetime.now(timezone.utc)

        # 1. Fetch active zones and notices
        active_zones = []
        active_notices = []
        fast = dt < 0.5  # smooth manual flying runs at 10 Hz: keep database reads off every tick
        self._tick_n += 1
        t_m = time.monotonic()
        try:
            if self._zones_cache[1] and t_m - self._zones_cache[0] < 5.0:  # zones change rarely: read them every 5 s, not every tick
                active_zones = self._zones_cache[1]
            else:
                active_zones = store.all_zones_geojson().get("features", [])
                self._zones_cache = (t_m, active_zones)
            if fast and t_m - self._notices_cache[0] < 1.0:
                active_notices = self._notices_cache[1]
            else:
                active_notices = store.active_notices()
                self._notices_cache = (t_m, active_notices)
        except Exception:
            pass

        # 2. Step kinematics and geofence for all drones
        telemetry_batch = []
        breaches_generated = []

        landed = []
        with self._lock:
            airborne = list(self.drones)
        for drone in airborne:
            drone.step(dt * self.speed_x)
            if drone.landed:
                landed.append(drone)
                continue
            status, zone_name, breach = self.geofence.evaluate_drone(
                drone, active_zones, active_notices, now_dt=now
            )
            if status == "warning":
                try:  # a drone about to enter a declared area: the guard devices get a first, softer signal
                    import backend.guard_api as guard_api
                    guard_api.announce_warning(drone.drone_id, zone_name, active_notices)
                except Exception:
                    pass
            if drone.kind == "flight":  # tell the big screen about changes of state
                before = getattr(drone, "last_status", "ok")
                if status != before:
                    if status == "warning":
                        self.log_event(drone.flight_id, "warning", f"Warning: {zone_name}")
                    elif status == "ok":
                        self.log_event(drone.flight_id, "clear", "Back in clear airspace")
                    drone.last_status = status
            if breach:
                key = (breach["kind"], breach["name"])
                if drone.last_breach != key:  # one entry into restricted airspace is one event, not one per second
                    drone.last_breach = key
                    drone.breach_count += 1
                    breaches_generated.append(breach)
                    self.geofence.log_breach(breach)
                    if drone.kind == "flight":
                        self.log_event(drone.flight_id, "breach", f"BREACH: {breach['name']}")
                    if drone.kind == "flight" and self.on_breach:
                        try:
                            self.on_breach(breach, drone)
                        except Exception as e:
                            print(f"[sim] breach callback failed: {e}")
            else:
                drone.last_breach = None

            # Batch telemetry record (Contract 5)
            if not fast or self._tick_n % 10 == 0:  # telemetry is recorded once a second
                telemetry_batch.append(drone.telemetry_record(now_dt=now))

        # 3. Batched insert into MongoDB time series collection (Contract 5)
        if config.USE_MONGO and db is not None and telemetry_batch:
            try:
                db.telemetry.insert_many(telemetry_batch, ordered=False)
            except Exception:
                pass
        self._recent_telemetry = telemetry_batch[-100:]

        # 4. Drones that finished their route or came home after a recall have landed
        if landed:
            with self._lock:
                self.drones = [d for d in self.drones if d not in landed]
            for d in landed:
                stats = {"reason": d.landed_reason or "completed", "breaches": d.breach_count, "max_alt_m": round(d.max_alt_m, 1),
                         "battery_pct": round(d.battery_pct, 1), "launched_at": d.launched_at.isoformat(timespec="seconds"),
                         "landed_at": now.isoformat(timespec="seconds")}
                self._dispatch_event("landed", {"flight_id": d.flight_id, "drone_id": d.drone_id, **stats})
                if d.kind == "flight":
                    self.log_event(d.flight_id, "landed", "Landed" if stats["reason"] == "completed" else "Landed after a recall")
                if d.kind == "flight" and self.on_landed:
                    try:
                        self.on_landed(d.flight_id, stats["reason"], stats)
                    except Exception as e:
                        print(f"[sim] landed callback failed: {e}")

        return {
            "telemetry": telemetry_batch,
            "breaches": breaches_generated,
            "now": now,
        }

    async def _run_loop(self):
        """1 Hz asyncio loop stepping kinematics, geofencing, and telemetry batched write."""
        while self.is_running:
            if not self.drones:  # nothing in the air: stop ticking until something launches
                self._halt()
                break
            t0 = time.monotonic()
            hz = 10 if any(d.manual for d in self.drones) else 1  # smooth movement while a pilot flies by hand
            step_res = self.tick(dt=1.0 / hz)
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
            sleep_time = max(0.01, (1.0 / (hz * self.speed_x)) - duration)
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
        is_official = bool(user and user.get("role") == "official")
        pilot_id = user.get("user_id") if is_pilot else None

        for d in list(self.drones):
            # Contract 3: a pilot sees their own drones, an official sees every drone, a visitor sees background traffic only
            # (a pilot's position is private).
            if is_pilot and d.owner_id != pilot_id:
                continue
            if not is_pilot and not is_official and d.kind == "flight":
                continue

            snap = d.snapshot(as_of_iso=now_iso)

            # Optional bbox filter [w, s, e, n]
            if bbox and len(bbox) == 4:
                w, s, e, n = bbox
                if not (w <= snap["lng"] <= e and s <= snap["lat"] <= n):
                    continue

            drones_out.append(snap)

        return {"as_of": now_iso, "drones": drones_out}

    def vip_center(self):
        """Where a VIP restriction would cross drones that are flying right now, preferring pilots' flights. Returns (lat, lng)."""
        flights = [d for d in self.drones if d.kind == "flight"]
        sample = flights[:3] or self.drones[:5]
        if sample:
            return (sum(d.lat for d in sample) / len(sample), sum(d.lng for d in sample) / len(sample))
        return (17.43, 78.44)


_simulator_instance = None


def get_fleet_simulator() -> FleetSimulator:
    """Return shared FleetSimulator singleton."""
    global _simulator_instance
    if _simulator_instance is None:
        _simulator_instance = FleetSimulator()
    return _simulator_instance
