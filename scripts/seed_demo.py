"""Fill a running SkyClear server with demo data: one pilot, two flights, one official notice.

Run: python scripts/seed_demo.py [http://localhost:8000]
Pilot login after seeding: asha@example.com / longenough1. Authority: see .env.example.
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def call(path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
    return json.load(urllib.request.urlopen(req))


pilot = call("/auth/register", {"name": "Asha Rao", "email": "asha@example.com", "password": "longenough1", "pilot_cert": "RPC-48213"})
official = call("/auth/login", {"email": "official@skyclear.demo", "password": "skyclear-demo"})
drone = call("/me/drones", {"name": "DJI Mavic 3", "weight_g": 895, "uin": "UIN-0042"}, pilot["token"])
call("/flights", {"drone_id": drone["drone_id"], "lat": 17.407, "lng": 78.47, "kind": "permission", "purpose": "Heritage building survey",
                  "start": "2026-10-12T10:00:00+05:30", "end": "2026-10-12T11:30:00+05:30"}, pilot["token"])
call("/flights", {"drone_id": drone["drone_id"], "lat": 17.4531, "lng": 78.4776, "kind": "watch",
                  "start": "2026-10-12T16:30:00+05:30", "end": "2026-10-12T17:30:00+05:30"}, pilot["token"])
n = call("/notices", {"title": "VIP movement, Begumpet", "note": "Airspace closed for the motorcade. Route details are not published.",
                      "lat": 17.4531, "lng": 78.4776, "radius_km": 3,
                      "starts_at": "2026-10-12T16:00:00+05:30", "ends_at": "2026-10-12T19:00:00+05:30"}, official["token"])
print(f"seeded. notice {n['notice_id']} alerted {n['affected_flights']} flight(s).")
