"""GET /metrics in the Prometheus text format: request counts and latency per route, simulator tick time, live events.
No extra package: counters are kept in memory by a middleware. OWNER: Nikhil (stream 2A)."""
import threading
import time
from collections import defaultdict

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

import events

router = APIRouter()
_lock = threading.Lock()
_count = defaultdict(int)
_sum = defaultdict(float)
_buckets = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)
_hist = defaultdict(int)
_started = time.time()


def _route(request):
    r = request.scope.get("route")
    return getattr(r, "path", "other")


class Middleware:
    """A plain ASGI middleware (the decorator kind adds noticeable delay to every request)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        t = time.perf_counter()
        status = [500]

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)
        try:
            await self.app(scope, receive, send_wrap)
        finally:
            d = time.perf_counter() - t
            key = (scope["method"], getattr(scope.get("route"), "path", "other"), str(status[0]))
            with _lock:
                _count[key] += 1
                _sum[key[:2]] += d
                for b in _buckets:
                    if d <= b:
                        _hist[(key[:2], b)] += 1


@router.get("/metrics", response_class=PlainTextResponse)
def metrics():
    from simulator.fleet import get_fleet_simulator
    sim = get_fleet_simulator()
    out = ["# TYPE skyclear_http_requests_total counter"]
    with _lock:
        for (m, r, s), n in sorted(_count.items()):
            out.append(f'skyclear_http_requests_total{{method="{m}",route="{r}",status="{s}"}} {n}')
        out.append("# TYPE skyclear_http_request_seconds histogram")
        for (m, r), total in sorted(_sum.items()):
            n = sum(c for (mm, rr, _), c in _count.items() if (mm, rr) == (m, r))
            for b in _buckets:
                out.append(f'skyclear_http_request_seconds_bucket{{method="{m}",route="{r}",le="{b}"}} {_hist[((m, r), b)]}')
            out.append(f'skyclear_http_request_seconds_bucket{{method="{m}",route="{r}",le="+Inf"}} {n}')
            out.append(f'skyclear_http_request_seconds_sum{{method="{m}",route="{r}"}} {total:.4f}')
            out.append(f'skyclear_http_request_seconds_count{{method="{m}",route="{r}"}} {n}')
    out += ["# TYPE skyclear_uptime_seconds gauge", f"skyclear_uptime_seconds {time.time() - _started:.0f}",
            "# TYPE skyclear_simulated_drones gauge", f"skyclear_simulated_drones {len(sim.drones)}",
            "# TYPE skyclear_live_events_total counter", f"skyclear_live_events_total {events.status['events']}",
            "# TYPE skyclear_change_stream_restarts_total counter", f"skyclear_change_stream_restarts_total {events.status['restarts']}"]
    return "\n".join(out) + "\n"
