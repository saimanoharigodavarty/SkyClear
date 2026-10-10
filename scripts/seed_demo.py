"""Fill a running SkyClear server with demo data: a verified pilot with a drone, a permission request, a watched flight, a VIP notice.

Run: python scripts/seed_demo.py [http://localhost:8000]
Pilot login after seeding: asha@example.com / longenough1.
Officers (password skyclear-demo): official@skyclear.demo (sees everything), police@, rgia@, begumpet@, defence@, forest@, hq@ skyclear.demo
"""
import sys
from datetime import datetime, timedelta, timezone

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")


def call(method, path, token=None, **kw):
    r = requests.request(method, BASE + path, headers={"Authorization": f"Bearer {token}"} if token else {}, **kw)
    if not r.ok:
        raise SystemExit(f"{method} {path} failed: {r.status_code} {r.text}")
    return r.json()


def iso(dt):
    return dt.isoformat(timespec="seconds")


now = datetime.now(timezone.utc)
pilot = call("POST", "/auth/register", json={"name": "Asha Rao", "email": "asha@example.com", "password": "longenough1"})["token"]
admin = call("POST", "/auth/login", json={"email": "official@skyclear.demo", "password": "skyclear-demo"})["token"]
drone = call("POST", "/me/drones", pilot, json={"name": "DJI Mavic 3", "weight_g": 895, "uin": "UIN-0042"})
files = lambda: [call("POST", "/uploads", pilot, files={"file": ("doc.png", PNG, "image/png")})["file_id"]]
v1 = call("POST", "/me/verification/pilot", pilot, json={"cert_no": "RPC-48213", "file_ids": files()})
v2 = call("POST", f"/me/drones/{drone['drone_id']}/verification", pilot, json={"serial": "MV3-8841-7720", "uin": "UIN-0042", "file_ids": files()})
for v in (v1, v2):
    call("POST", f"/verification/{v['verification_id']}/decision", admin, json={"decision": "approved", "comment": "Documents match records (demo)"})
# permission request in the sample Secretariat zone, window opens now so Preflight works in the demo
call("POST", "/flights", pilot, json={"drone_id": drone["drone_id"], "lat": 17.407, "lng": 78.47, "kind": "permission", "purpose": "Heritage building survey",
                                      "start": iso(now), "end": iso(now + timedelta(hours=2))})
# a watched flight near Begumpet, later today, then a VIP notice over it
call("POST", "/flights", pilot, json={"drone_id": drone["drone_id"], "lat": 17.4531, "lng": 78.4776, "kind": "watch",
                                      "start": iso(now + timedelta(minutes=30)), "end": iso(now + timedelta(minutes=90))})
n = call("POST", "/notices", admin, json={"title": "VIP movement, Begumpet", "note": "Airspace closed for the motorcade. Route details are not published.",
                                          "lat": 17.4531, "lng": 78.4776, "radius_km": 3, "starts_at": iso(now), "ends_at": iso(now + timedelta(hours=3))})
print(f"seeded. notice {n['notice_id']} alerted {n['affected_flights']} flight(s), {len(n['conflicting_permits'])} permit conflict(s).")
