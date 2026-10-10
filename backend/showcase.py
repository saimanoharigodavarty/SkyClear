"""Showcase data for demos: fictional pilots, drones and flights in every state, a verification queue, three notices, and history.

Everything goes through the real API in-process (permits are signed, alerts are written, flight logs come from the simulator),
then timestamps are spread over the last three days so the dashboard looks like a working week. All names are fictional,
all emails are @example.com. Run: python backend/manage.py seed-showcase
"""
import random
import secrets
from datetime import datetime, timedelta, timezone

import config
import runtime

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")
PILOTS = [  # name, email local part, drone name, weight in grams, how far along verification is
    ("Aarav Mehta", "aarav.mehta", "DJI Air 3", 720, "verified"),
    ("Diya Reddy", "diya.reddy", "Autel Evo II", 1191, "verified"),
    ("Kabir Singh", "kabir.singh", "Parrot Anafi", 320, "verified"),
    ("Meera Nair", "meera.nair", "AgriSprayer X10", 9000, "verified"),
    ("Rohan Das", "rohan.das", "DJI Mavic 3", 895, "verified"),
    ("Sana Qureshi", "sana.qureshi", "Skydio 2", 775, "verified"),
    ("Vikram Rao", "vikram.rao", "DJI Mini 3", 249, "verified"),
    ("Ishita Verma", "ishita.verma", "Inspire 3", 3995, "pending"),     # sent documents, waiting for an officer
    ("Naveen Kumar", "naveen.kumar", "Phantom 4", 1380, "drone_pending"),  # pilot verified, drone waiting
    ("Tara Joshi", "tara.joshi", "DJI Mini 2", 249, "none"),            # just signed up
]


def run(client, ha_for, official_for, admin, create_user, save, quiet=False):
    import auth
    import manage
    import pipeline
    from simulator.fleet import get_fleet_simulator
    log = (lambda *a: None) if quiet else print
    sim = get_fleet_simulator()
    now = datetime.now(timezone.utc)
    iso = lambda d: d.isoformat(timespec="seconds")
    rng = random.Random(7)
    zones = client.get("/zones").json()["features"]
    center_of = lambda f: (sum(y for _, y in f["geometry"]["coordinates"][0]) / len(f["geometry"]["coordinates"][0]),
                           sum(x for x, _ in f["geometry"]["coordinates"][0]) / len(f["geometry"]["coordinates"][0]))
    by_id = {f["properties"]["zone_id"]: f for f in zones}
    first = lambda t: next(f for f in zones if f["properties"]["zone_type"] == t)
    gov, park = first("government"), first("park")
    rgia, beg = by_id.get("Z-VOHS") or first("airport"), by_id.get("Z-VOHY") or first("airport")
    free_lat, free_lng = manage._free_spot(zones)

    admin_h = {"Authorization": f"Bearer {auth.access_token(admin)}"}
    users = {}
    lines = []
    for i, (name, local, drone_name, grams, state) in enumerate(PILOTS):
        email = f"{local}@example.com"
        existing = next((u for u in runtime.all_("users") if u["email"] == email), None)
        if existing:
            users[local] = existing
            continue
        pw = secrets.token_urlsafe(10)
        u = create_user(email, name, "pilot", pw, verified=True, phone=f"+9199{rng.randrange(10**7, 10**8)}")
        users[local] = u
        lines.append(f"pilot  {email}  {pw}")
        hp = {"Authorization": f"Bearer {auth.access_token(u)}"}
        up = lambda: [client.post("/uploads", headers=hp, files={"file": ("doc.png", PNG, "image/png")}).json()["file_id"]]
        drone = client.post("/me/drones", headers=hp, json={"name": drone_name, "weight_g": grams, "uin": f"UIN-{rng.randrange(1000, 9999)}"}).json()
        if state != "none":
            pv = client.post("/me/verification/pilot", headers=hp, json={"cert_no": f"RPC-{rng.randrange(10000, 99999)}", "file_ids": up()}).json()
            dv = client.post(f"/me/drones/{drone['drone_id']}/verification", headers=hp, json={"serial": f"{local[:3].upper()}-{secrets.token_hex(3).upper()}", "file_ids": up()}).json()
            if state in ("verified", "drone_pending"):
                client.post(f"/verification/{pv['verification_id']}/decision", headers=admin_h, json={"decision": "approved", "comment": "Certificate checked (demo data)"})
            if state == "verified":
                client.post(f"/verification/{dv['verification_id']}/decision", headers=admin_h, json={"decision": "approved", "comment": "Serial plate photo matches (demo data)"})
        log(f"  pilot {name}: {state}")
    save(lines)

    def tok(local): return {"Authorization": f"Bearer {auth.access_token(users[local])}"}
    def drone_of(local): return client.get("/me/drones", headers=tok(local)).json()[0]

    def request(local, zone, start, hours=2, purpose="Survey", lat=None, lng=None, kind="permission"):
        la, ln = (lat, lng) if lat is not None else center_of(zone)
        r = client.post("/flights", headers=tok(local), json={"drone_id": drone_of(local)["drone_id"], "lat": la, "lng": ln, "kind": kind, "purpose": purpose,
                                                              "start": iso(start), "end": iso(start + timedelta(hours=hours))})
        if r.status_code != 200:
            log("   could not create:", local, r.json())
            return None
        return r.json()

    def decide(f, decision, comment="", conditions=None, alt=60):
        h = ha_for(f["authority_id"])
        return client.post(f"/flights/{f['flight_id']}/decision", headers=h, json={"decision": decision, "comment": comment, "alt_max_m": alt, "conditions": conditions or []})

    def backdate(f, hours_ago, decided_after_min=None):
        created = now - timedelta(hours=hours_ago)
        ch = {"created_at": iso(created)}
        cur = next(x for x in runtime.all_("flights") if x["flight_id"] == f["flight_id"])
        if cur.get("decision") and decided_after_min is not None:
            ch["decision"] = {**cur["decision"], "at": iso(created + timedelta(minutes=decided_after_min))}
        runtime.update("flights", "flight_id", f["flight_id"], ch)

    tomorrow = (now + timedelta(days=1)).replace(hour=4, minute=30, second=0, microsecond=0)  # 10:00 India time
    soon = now - timedelta(minutes=1)

    # 1. Requests waiting in each office's queue
    pend = [request("aarav.mehta", gov, tomorrow, purpose="Heritage building survey"),
            request("diya.reddy", beg, tomorrow + timedelta(hours=4), purpose="Aerial photography for a film location"),
            request("kabir.singh", rgia, tomorrow + timedelta(hours=1), purpose="Runway approach inspection training"),
            request("meera.nair", park, tomorrow + timedelta(hours=2), purpose="Crop and tree health survey")]
    for f, h in zip([p for p in pend if p], (0.5, 1.5, 3.0, 6.0)):
        backdate(f, h)
    # 2. Approved with a permit, waiting for their time window
    for local, zone, why in (("rohan.das", gov, "Roof inspection"), ("sana.qureshi", rgia, "Perimeter fence check")):
        f = request(local, zone, tomorrow + timedelta(hours=3), purpose=why)
        if f:
            decide(f, "approved", "Approved with conditions", ["Daylight only", "Stay inside the marked area", "Keep below 60 m"])
            backdate(f, rng.uniform(8, 20), rng.choice([9, 14, 23]))
    # 3. Rejected with a reason
    f = request("vikram.rao", gov, tomorrow + timedelta(hours=5), purpose="Event coverage")
    if f:
        decide(f, "rejected", "A security event is scheduled for that day. Apply again for next week.")
        backdate(f, 30, 41)
    # 4. History: flights that were flown and landed (the simulator flies them)
    sim.stop_all()
    sim.speed_x = 40
    history = [("aarav.mehta", gov, "Heritage survey, flown", 0, 52), ("rohan.das", gov, "Roof inspection, flown", 0, 61),
               ("diya.reddy", beg, "Photography flight, flown, drifted out of the permit area", 1, 96), ("kabir.singh", rgia, "Training flight, flown", 0, 3), ("sana.qureshi", rgia, "Fence check, flown", 2, 28)]
    def land_fast(fid):
        sim.speed_x = 40
        for _ in range(400):
            sim.tick(1.0)
            if sim.get_flight_drone(fid) is None:
                return

    for n, (local, zone, why, breaches, hours_ago) in enumerate(history):
        f = request(local, zone, soon, hours=3, purpose=why)
        if not f:
            continue
        decide(f, "approved", "Approved", ["Daylight only", "Keep below 60 m"])
        h = tok(local)
        client.post(f"/flights/{f['flight_id']}/preflight", headers=h)
        if client.post(f"/flights/{f['flight_id']}/launch", headers=h).status_code != 200:
            continue
        d = sim.get_flight_drone(f["flight_id"])
        if breaches and d is not None:
            sim.speed_x = 1.0
            for _ in range(3):
                sim.tick(1.0)
            d.lat += 0.004  # drifts out of the permitted area while hovering: a real breach, an alert and a log entry
            d.waypoints, d.waypoint_idx, d.speed_mps, d.target_speed_mps = [(d.lat + 0.5, d.lng, 50.0)], 0, 0.0, 0.0
            for _ in range(4):
                sim.tick(0.1)
            sim.return_home_flight(f["flight_id"])  # the pilot notices and presses Return home
        land_fast(f["flight_id"])
        backdate(f, hours_ago, rng.choice([7, 12, 18, 33]))
    # 5. One recalled by an officer
    f = request("kabir.singh", gov, soon, hours=3, purpose="Training flight, recalled")
    if f:
        decide(f, "approved", "Approved", ["Daylight only"])
        client.post(f"/flights/{f['flight_id']}/preflight", headers=tok("kabir.singh"))
        client.post(f"/flights/{f['flight_id']}/launch", headers=tok("kabir.singh"))
        sim.speed_x = 1.0
        for _ in range(4):
            sim.tick(1.0)
        client.post(f"/flights/{f['flight_id']}/recall", headers=ha_for(f["authority_id"]), json={"reason": "VIP convoy passing nearby, land now"})
        land_fast(f["flight_id"])
        backdate(f, 70, 25)
    # 6. A pilot watching a flight in open air
    request("meera.nair", None, soon, hours=4, purpose="Field mapping, open area", lat=free_lat, lng=free_lng, kind="watch")
    sim.stop_all()
    sim.speed_x = 1.0

    # 7. Three notices: one active now, one scheduled, one cancelled
    mk = lambda title, note, lat, lng, km, s, e: client.post("/notices", headers=admin_h, json={"title": title, "note": note, "lat": lat, "lng": lng, "radius_km": km, "starts_at": iso(s), "ends_at": iso(e)}).json()
    mk("VIP movement, Old City", "Airspace closed along the route. Route details are not published.", 17.3616, 78.4747, 1.5, now - timedelta(minutes=10), now + timedelta(hours=3))
    mk("Republic Day parade rehearsal", "Rehearsal with low-flying aircraft. No drones in the area.", 17.4239, 78.4738, 2.0, tomorrow, tomorrow + timedelta(hours=5))
    gone = mk("Cricket match security perimeter, Uppal", "Match postponed, restriction withdrawn.", 17.4054, 78.5578, 2.0, now + timedelta(hours=20), now + timedelta(hours=28))
    client.post(f"/notices/{gone['notice_id']}/cancel", headers=admin_h)
    log("  3 notices: 1 active now, 1 scheduled, 1 cancelled")
    return {"pilots": len(PILOTS), "requests_waiting": len([p for p in pend if p])}
