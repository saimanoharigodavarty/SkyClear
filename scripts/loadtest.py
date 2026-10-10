"""Load test for the running server, and a timing of the simulator tick.

  .venv/bin/python scripts/loadtest.py            # server on http://localhost:8000
  .venv/bin/python scripts/loadtest.py --seconds 10 --levels 10,50,200

Prints a table to paste into docs/RESULTS.md. The numbers depend on the machine, so the table also prints it.
"""
import argparse
import asyncio
import os
import platform
import random
import statistics
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def worker(client, make, until, lat, errs):
    while time.perf_counter() < until:
        t = time.perf_counter()
        try:
            r = await make(client)
            (lat if r.status_code == 200 else errs).append(time.perf_counter() - t if r.status_code == 200 else r.status_code)
        except Exception as e:  # noqa: BLE001
            errs.append(type(e).__name__)


async def run(base, name, make, level, seconds):
    lat, errs = [], []
    limits = httpx.Limits(max_connections=level + 10, max_keepalive_connections=level + 10)
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as c:
        until = time.perf_counter() + seconds
        await asyncio.gather(*[worker(c, make, until, lat, errs) for _ in range(level)])
    lat.sort()
    pct = lambda p: round(lat[min(len(lat) - 1, int(len(lat) * p))] * 1000) if lat else None  # noqa: E731
    print(f"| {name} | {level} | {round(len(lat) / seconds)} | {pct(0.50)} | {pct(0.95)} | {pct(0.99)} | {len(errs)} |", flush=True)


def point():
    return round(random.uniform(17.25, 17.60), 5), round(random.uniform(78.25, 78.65), 5)


async def check(c):
    lat, lng = point()
    return await c.post("/check", json={"lat": lat, "lng": lng, "drone_id": "small-1800", "explain": False})


async def zones(c):
    lat, lng = point()
    return await c.get(f"/zones?bbox={lng - 0.03},{lat - 0.03},{lng + 0.03},{lat + 0.03}")


async def live(c):
    return await c.get("/live/drones")


def tick_timing():
    from simulator.fleet import FleetSimulator
    print("\n| Simulator drones | Tick time (ms), median of 20 | Worst of 20 (ms) |\n|---|---|---|")
    for n in (100, 500, 1000):
        sim = FleetSimulator(); sim.start(count=n, seed=1); sim.stop_all() if False else None
        ts = []
        for _ in range(20):
            t = time.perf_counter(); sim.tick(1.0); ts.append((time.perf_counter() - t) * 1000)
        print(f"| {n} | {round(statistics.median(ts), 1)} | {round(max(ts), 1)} |")
        sim.stop()


async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="http://localhost:8000"); ap.add_argument("--seconds", type=int, default=8)
    ap.add_argument("--levels", default="10,50,200"); ap.add_argument("--no-sim", action="store_true"); a = ap.parse_args()
    print(f"Machine: {platform.platform()}, {os.cpu_count()} CPUs, Python {platform.python_version()}, server {a.base}, {a.seconds} s per row\n")
    print("| Endpoint | Concurrent users | Requests per second | p50 (ms) | p95 (ms) | p99 (ms) | Errors |\n|---|---|---|---|---|---|---|")
    for name, fn in (("POST /check (zone + rules, no AI)", check), ("GET /zones?bbox (2dsphere)", zones), ("GET /live/drones", live)):
        for lv in map(int, a.levels.split(",")):
            await run(a.base, name, fn, lv, a.seconds)
    if not a.no_sim:
        os.environ.setdefault("USE_MONGO", "0")
        tick_timing()


asyncio.run(main())
