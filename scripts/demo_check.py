"""Run this 10 minutes before the demo. It checks every part the demo uses and says what to fix.

  .venv/bin/python scripts/demo_check.py            # server on http://localhost:8000
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

B = os.environ.get("BASE", "http://localhost:8000")
ROOT = os.path.join(os.path.dirname(__file__), "..")
results = []


def call(path, method="GET", body=None, token=None, timeout=20):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def check(name, fn, fix=""):
    try:
        out = fn()
        ok, note = (out if isinstance(out, tuple) else (bool(out), ""))
    except Exception as e:  # noqa: BLE001
        ok, note = False, f"{type(e).__name__}: {e}"
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({note})" if note else "") + (f"\n        fix: {fix}" if not ok and fix else ""))
    return ok


def creds():
    rows = {}
    try:
        for line in open(os.path.join(ROOT, "data", "demo_credentials.txt"), encoding="utf-8"):
            f = line.split()
            if len(f) >= 3:
                rows[f[1]] = f[2]
    except FileNotFoundError:
        pass
    return rows


def login(email):
    pw = creds().get(email)
    if not pw:
        raise RuntimeError("no password for " + email + " in data/demo_credentials.txt")
    return call("/auth/login", "POST", {"identifier": email, "password": pw})["access_token"]


def _bad_key():
    try:
        call("/ingest/position", "POST", {"drone_ref": "x", "lat": 17, "lng": 78})
    except urllib.error.HTTPError as e:
        return e.code == 401
    return False


def _guard_stream():
    with urllib.request.urlopen(B + "/guard/stream", timeout=10) as r:
        return r.readline().decode().startswith("event: ready")


health = {}
check("server answers", lambda: health.update(call("/health")) or True, "start it with ./run.sh")
check("MongoDB is connected", lambda: health.get("mongo") is True, "start Docker, then ./run.sh")
check("language model reachable (optional)", lambda: (health.get("llm") is True, "the app still works, answers use plain wording"))
check("zones are loaded", lambda: (len(call("/zones")["features"]) > 50, ""), "cd backend && python load_data.py")
check("Ask finds rules", lambda: (len(call("/ask", "POST", {"question": "Do I need permission near an airport?", "explain": False}, timeout=30)["citations"]) > 0, ""))
lan = {}
check("phones can reach the laptop", lambda: (lan.update(call("/lan")) or bool(lan.get("urls")), (lan.get("urls") or ["no network address"])[0]), "connect the laptop to Wi-Fi or a phone hotspot")
adm = {}
check("admin can sign in", lambda: adm.update(t=login("owner@example.org")) or True, "cd backend && python manage.py set-password --email owner@example.org --password '...' and put it in data/demo_credentials.txt")
if adm.get("t"):
    t = adm["t"]
    check("officer queue has requests to decide", lambda: (len([f for f in call("/flights", token=t) if f["status"] == "requested"]) >= 1, ""), "cd backend && python manage.py seed-showcase (once)")
    check("insights and audit log load", lambda: (call("/analytics/summary", token=t) is not None and isinstance(call("/audit?limit=3", token=t), list), ""))
    check("live event channel is on", lambda: (call("/events/status", token=t).get("watching") is not None, call("/events/status", token=t).get("mode", "")))
    check("tracker endpoint rejects a bad key", lambda: _bad_key())
check("guard stream is open", lambda: _guard_stream())
check("metrics endpoint answers", lambda: "skyclear_http_requests_total" in urllib.request.urlopen(B + "/metrics", timeout=10).read().decode())
pilot = {}
check("demo pilot can sign in", lambda: pilot.update(t=login("demo.pilot@example.com")) or True, "cd backend && python manage.py prepare-demo")
if pilot.get("t"):
    def flights():
        fl = [f for f in call("/flights", token=pilot["t"]) if f["status"] in ("approved", "watching", "cleared", "flying") and f["end"] > time.strftime("%Y-%m-%dT%H:%M", time.gmtime())]
        return (len(fl) >= 1, f"{len(fl)} flight(s) ready")
    check("demo flights are ready to fly", flights, "cd backend && python manage.py prepare-demo (the flights last 6 hours)")


print(f"\n{sum(results)} of {len(results)} checks passed.")
if lan.get("urls"):
    print(f"\nOpen on the presentation computer:  {B}/display.html\nGuard link for phones:               {lan['urls'][0]}/guard.html")
sys.exit(0 if all(results) else 1)
