"""Setup commands. Accounts are never created by the app on its own and no password is written in code.

  python backend/manage.py create-admin --email you@example.com --name "Your Name"   asks for a password
  python backend/manage.py create-admin --email you@example.com --generate           makes one and prints it once
  python backend/manage.py seed-officers                                             one officer per authority, generated passwords
  python backend/manage.py seed-demo                                                 a verified demo pilot, a drone, flights and a notice
  python backend/manage.py logins                                                    show the saved logins
  python backend/manage.py set-password --email x@y.z                                set a known password for an account
  python backend/manage.py seed-showcase                                             fill the platform with believable demo data (pilots, flights in every state, notices)
  python backend/manage.py prepare-demo                                              get a presentation ready: a demo pilot with two approved flights (phone control demo)
  python backend/manage.py list-users
  python backend/manage.py has-admin                                                 exit code 0 when an admin exists

Generated passwords are printed once and saved in data/demo_credentials.txt (git-ignored). Delete that file when you are done.
"""
import argparse
import getpass
import secrets
import sys
from datetime import datetime, timedelta, timezone

import config
import routing
import runtime

CREDS = config.DATA_DIR / "demo_credentials.txt"


def _save(lines):
    """Keep data/demo_credentials.txt tidy: one line per account, the newest password wins."""
    kept = {}
    if CREDS.exists():
        for l in CREDS.read_text(encoding="utf-8").splitlines():
            parts = l.split()
            if len(parts) >= 3 and "@" in parts[1]:
                kept[parts[1]] = l
    for l in lines:
        kept[l.split()[1]] = l
    CREDS.write_text("\n".join(kept.values()) + "\n", encoding="utf-8")
    try:
        CREDS.chmod(0o600)
    except OSError:
        pass


def _exists(email):
    return any(u["email"] == email for u in runtime.all_("users"))


def create_user(email, name, role, password, authority_id=None, verified=True, phone=None):
    email = email.strip().lower()
    if _exists(email):
        raise SystemExit(f"{email} already exists")
    user = {"user_id": runtime.new_id("U"), "role": role, "name": name, "email": email, "password": runtime.hash_password(password),
            "authority_id": authority_id, "failed_attempts": 0, "created_at": runtime.now_iso()}
    if role == "pilot":
        user.update({"phone": phone, "phone_verified": verified})
    return runtime.insert("users", user)


def cmd_create_admin(a):
    password = a.password
    if a.generate:
        password = secrets.token_urlsafe(12)
    elif not password:
        password = getpass.getpass("Password (at least 10 characters): ")
        if password != getpass.getpass("Again: "):
            raise SystemExit("Passwords do not match")
    if len(password) < 10:
        raise SystemExit("Use at least 10 characters")
    create_user(a.email, a.name, "official", password)
    print(f"Admin created: {a.email}")
    if a.generate:
        print(f"Password (shown once): {password}")
        _save([f"admin  {a.email}  {password}"])
        print(f"Also saved in {CREDS}")


def cmd_seed_officers(a):
    lines = []
    for auth in routing.all_authorities():
        email = f"{auth['authority_id'].lower()}@{a.domain}"
        if _exists(email):
            print(f"skip {email} (exists)")
            continue
        pw = secrets.token_urlsafe(12)
        create_user(email, auth["name"], "official", pw, authority_id=auth["authority_id"])
        lines.append(f"officer  {email}  {pw}  ({auth['name']})")
    if lines:
        print("\n".join(lines))
        _save(lines)
        print(f"Saved in {CREDS}. Each officer can change the password after signing in.")


def cmd_check_llm(a):
    """Check the Ollama connection step by step and say what to fix."""
    import llm
    import embeddings
    if not config.USE_LLM:
        raise SystemExit("USE_LLM is 0 in .env. Set USE_LLM=1 and OLLAMA_URL=http://<ollama-laptop-ip>:11434, then run this again.")
    print(f"Ollama at {config.OLLAMA_URL}")
    s = llm.status(force=True)
    if not s["reachable"]:
        raise SystemExit(f"  NOT REACHABLE ({s.get('error')}). On the Ollama laptop run:  OLLAMA_HOST=0.0.0.0 ollama serve\n  Same Wi-Fi? Check the IP with:  ipconfig getifaddr en0   and that its firewall allows port 11434.")
    print("  reachable, models there:", ", ".join(s.get("models", [])) or "none")
    for label, ready, name in (("language model", s["llm_model_ready"], config.LLM_MODEL), ("embedding model", s["embed_model_ready"], config.EMBED_MODEL)):
        print(f"  {label} {name}: {'ready' if ready else 'MISSING, run on that laptop: ollama pull ' + name}")
    if s["embed_model_ready"]:
        v = embeddings.embed(["can I fly near an airport"], "query")
        print(f"  embedding test: {'ok, ' + str(len(v[0])) + ' dimensions' if v else 'FAILED'}")
    if s["llm_model_ready"]:
        try:
            import json
            import ask
            out = ask._chat('QUESTION: Do I need permission near an airport?\nSPOT FACTS: none\nPASSAGES:\n[R-001] Flying inside an airport zone needs permission from the airport authority.')
            print("  answer test: ok," , json.loads(out).get("answer", "")[:120])
        except Exception as e:
            print(f"  answer test FAILED ({type(e).__name__}: {e})")
    print("\nNext: python backend/load_data.py   (embeds the rules and builds the vector index), then restart the app.")


def cmd_has_admin(a):
    sys.exit(0 if any(u["role"] == "official" and not u.get("authority_id") for u in runtime.all_("users")) else 1)


def cmd_logins(a):
    """Print the generated logins in a readable table, with what each one is for."""
    if not CREDS.exists():
        raise SystemExit("No saved logins yet. Run: python backend/manage.py create-admin --email you@example.com --generate")
    role_note = {"admin": "sees every office, invites officials, publishes notices", "officer": "reviews requests for one office", "pilot": "a verified pilot with a verified drone"}
    print(f"\nSkyClear logins (saved in {CREDS})\n")
    for l in CREDS.read_text(encoding="utf-8").splitlines():
        p = l.split(None, 3)
        if len(p) >= 3:
            print(f"  {p[0]:8} {p[1]:46} {p[2]:20} {role_note.get(p[0], '')}")
    print("\nSign in at http://localhost:8000/account.html . One-time codes arrive at http://localhost:8025 (the mail catcher).\n")


def cmd_set_password(a):
    """Set a known password for an existing account (for example if you lost it)."""
    user = next((u for u in runtime.all_("users") if u["email"] == a.email.strip().lower()), None)
    if user is None:
        raise SystemExit("No such user. See: python backend/manage.py list-users")
    pw = a.password or getpass.getpass("New password (at least 10 characters): ")
    if len(pw) < 10:
        raise SystemExit("Use at least 10 characters")
    runtime.update("users", "user_id", user["user_id"], {"password": runtime.hash_password(pw), "failed_attempts": 0, "locked_until": None})
    print(f"Password set for {user['email']}")


def _demo_drone(client, ha, hp, pilot_user):
    """The demo pilot's drone, created and verified if it does not exist yet."""
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")
    up = lambda: [client.post("/uploads", headers=hp, files={"file": ("doc.png", png, "image/png")}).json()["file_id"]]
    mine = [d for d in client.get("/me/drones", headers=hp).json() if (d.get("verification") or {}).get("status") == "verified"]
    if mine:
        return mine[0]
    drone = client.post("/me/drones", headers=hp, json={"name": "Demo Drone", "weight_g": 895}).json()
    v2 = client.post(f"/me/drones/{drone['drone_id']}/verification", headers=hp, json={"serial": "DEMO-" + secrets.token_hex(3).upper(), "file_ids": up()}).json()
    client.post(f"/verification/{v2['verification_id']}/decision", headers=ha, json={"decision": "approved", "comment": "Demo data"})
    if (pilot_user.get("verification") or {}).get("status") != "verified":
        v1 = client.post("/me/verification/pilot", headers=hp, json={"cert_no": "DEMO-CERT-" + secrets.token_hex(2).upper(), "file_ids": up()}).json()
        client.post(f"/verification/{v1['verification_id']}/decision", headers=ha, json={"decision": "approved", "comment": "Demo data"})
    return drone


def _free_spot(zones):
    """An open spot about 1.5 km outside the nearest military zone and outside every other zone, so flying toward the military zone is a short, dramatic trip."""
    import math
    from geo import haversine_km
    import pipeline
    mil = [f for f in zones if f["properties"]["zone_type"] == "military"]
    centre = config.REGION["center"]
    for f in sorted(mil, key=lambda f: haversine_km(centre[0], centre[1], *[sum(c) / len(c) for c in zip(*[(y, x) for x, y in f["geometry"]["coordinates"][0]])])):
        ring = f["geometry"]["coordinates"][0]
        clat, clng = (sum(y for _, y in ring) / len(ring), sum(x for x, _ in ring) / len(ring))
        radius = max(haversine_km(clat, clng, y, x) for x, y in ring)
        for bearing in range(180, 180 + 360, 30):
            d = radius + 1.5
            lat = clat + (d * math.cos(math.radians(bearing))) / 111.32
            lng = clng + (d * math.sin(math.radians(bearing))) / (111.32 * math.cos(math.radians(clat)))
            if not any(z["inside"] for z in pipeline.store.zones_near(lat, lng)):
                return round(lat, 5), round(lng, 5)
    return centre[0] + 0.1, centre[1] + 0.1


def cmd_prepare_demo(a):
    """Get ready for a presentation: a verified demo pilot with two flights ready to fly, valid for six hours.
    1) a permit flight inside a yellow zone (fly out of the dashed area, or climb over the limit, and it breaches)
    2) a free flight in open air just outside a military zone (fly toward it and the screen warns, then breaches)
    The demo pilot's password is reset and printed, so you can sign in on the presentation computer."""
    from fastapi.testclient import TestClient
    from main import app
    import auth
    client = TestClient(app)
    admin = next((u for u in runtime.all_("users") if u["role"] == "official" and not u.get("authority_id")), None)
    if admin is None:
        raise SystemExit("Create an admin first: python backend/manage.py create-admin --email you@example.com --generate")
    ha = {"Authorization": f"Bearer {auth.access_token(admin)}"}
    pilot = next((u for u in runtime.all_("users") if u["email"] == a.pilot_email), None)
    pw = secrets.token_urlsafe(12)
    if pilot is None:
        pilot = create_user(a.pilot_email, "Demo Pilot", "pilot", pw, verified=True, phone="+919" + str(secrets.randbelow(10**9)).zfill(9))
    else:
        runtime.update("users", "user_id", pilot["user_id"], {"password": runtime.hash_password(pw), "failed_attempts": 0, "locked_until": None, "phone_verified": True})
        pilot = next(u for u in runtime.all_("users") if u["user_id"] == pilot["user_id"])
    hp = {"Authorization": f"Bearer {auth.access_token(pilot)}"}
    drone = _demo_drone(client, ha, hp, pilot)
    for old in runtime.all_("flights"):  # clear last time's demo flights so the screen shows only fresh ones
        if old["pilot_id"] == pilot["user_id"] and old.get("purpose", "").startswith("Presentation demo") and old["status"] in ("approved", "watching", "cleared"):
            runtime.update("flights", "flight_id", old["flight_id"], {"status": "cancelled"})
    now = datetime.now(timezone.utc)
    iso = lambda d: d.isoformat(timespec="seconds")
    zones = client.get("/zones").json()["features"]
    gov = next((f for f in zones if f["properties"]["zone_type"] == "government"), None)
    window = {"start": iso(now - timedelta(minutes=1)), "end": iso(now + timedelta(hours=6))}
    ready = []
    if gov:
        ring = gov["geometry"]["coordinates"][0]
        lat, lng = sum(y for _, y in ring) / len(ring), sum(x for x, _ in ring) / len(ring)
        f = client.post("/flights", headers=hp, json={"drone_id": drone["drone_id"], "lat": lat, "lng": lng, "kind": "permission", "purpose": "Presentation demo", **window}).json()
        client.post(f"/flights/{f['flight_id']}/decision", headers=ha, json={"decision": "approved", "alt_max_m": 60, "conditions": ["Stay inside the dashed area", "Keep below 60 m"], "comment": "Demo permit"})
        ready.append(f"{f['flight_id']}  permit flight in {gov['properties']['name']}")
    lat, lng = _free_spot(zones)
    w = client.post("/flights", headers=hp, json={"drone_id": drone["drone_id"], "lat": lat, "lng": lng, "kind": "watch", "purpose": "Presentation demo, free flight", **window}).json()
    ready.append(f"{w['flight_id']}  free flight in open air near a military zone")
    _save([f"pilot  {a.pilot_email}  {pw}"])
    print("Demo ready. Flights approved for the next 6 hours:")
    print("\n".join("  " + r for r in ready))
    print(f"\nSign in on the presentation computer as the demo pilot:\n  {a.pilot_email}   {pw}\nThen open http://localhost:8000/display.html")


def cmd_create_tracker(a):
    from ingest_api import create_tracker
    rec, key = create_tracker(a.name)
    print(f"Tracker {rec['tracker_id']} ({rec['name']}) created.\nKey, shown once, copy it now:\n  {key}\nSend positions with:  POST /ingest/position  header X-Tracker-Key: <key>")


def cmd_seed_showcase(a):
    """Fill the platform with believable demo data: fictional pilots and flights in every state, a verification queue, three notices, history.
    Safe to run once on a fresh database. Run prepare-demo afterwards for the flights you fly live."""
    from fastapi.testclient import TestClient
    from main import app
    import auth
    import showcase
    client = TestClient(app)
    admin = next((u for u in runtime.all_("users") if u["role"] == "official" and not u.get("authority_id")), None)
    if admin is None:
        raise SystemExit("Create an admin first: python backend/manage.py create-admin --email you@example.com --generate")
    if any(u["email"] == "aarav.mehta@example.com" for u in runtime.all_("users")):
        raise SystemExit("Showcase data is already there. (Start from a fresh database to seed it again.)")
    if not any(u.get("authority_id") for u in runtime.all_("users")):
        cmd_seed_officers(argparse.Namespace(domain="officers.skyclear.local"))
    def officer_for(authority_id):
        u = next((x for x in runtime.all_("users") if x.get("authority_id") == authority_id), None) or admin
        return {"Authorization": f"Bearer {auth.access_token(u)}"}
    out = showcase.run(client, officer_for, None, admin, create_user, _save)
    print(f"Showcase data created: {out['pilots']} pilots, {out['requests_waiting']} requests waiting for officers. Pilot logins are in {CREDS}.")


def cmd_list_users(a):
    for u in runtime.all_("users"):
        print(f"{u['role']:9} {u['email']:45} {u.get('authority_id') or '-'}")


def cmd_seed_demo(a):
    """Creates a verified pilot with a drone, a permission request, a watched flight and a VIP notice, using the real API in-process."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    admin = next((u for u in runtime.all_("users") if u["role"] == "official" and not u.get("authority_id")), None)
    if admin is None:
        raise SystemExit("Create an admin first: python backend/manage.py create-admin --generate ...")
    if _exists(a.pilot_email):
        raise SystemExit(f"{a.pilot_email} already exists, demo data is already there")
    pilot_pw = secrets.token_urlsafe(12)
    import auth
    create_user(a.pilot_email, "Demo Pilot", "pilot", pilot_pw, verified=True, phone="+919" + str(secrets.randbelow(10**9)).zfill(9))
    a_tok = auth.access_token(admin)  # a short-lived token minted here, so the admin password is never touched
    p_tok = client.post("/auth/login", json={"identifier": a.pilot_email, "password": pilot_pw}).json()["token"]
    ha, hp = {"Authorization": f"Bearer {a_tok}"}, {"Authorization": f"Bearer {p_tok}"}
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")
    up = lambda: [client.post("/uploads", headers=hp, files={"file": ("doc.png", png, "image/png")}).json()["file_id"]]
    drone = client.post("/me/drones", headers=hp, json={"name": "Demo Drone", "weight_g": 895}).json()
    v1 = client.post("/me/verification/pilot", headers=hp, json={"cert_no": "DEMO-CERT-1", "file_ids": up()}).json()
    v2 = client.post(f"/me/drones/{drone['drone_id']}/verification", headers=hp, json={"serial": "DEMO-SERIAL-1", "file_ids": up()}).json()
    for v in (v1, v2):
        client.post(f"/verification/{v['verification_id']}/decision", headers=ha, json={"decision": "approved", "comment": "Demo data"})
    now = datetime.now(timezone.utc)
    iso = lambda d: d.isoformat(timespec="seconds")
    zones = client.get("/zones").json()["features"]
    pick = lambda t: next((f for f in zones if f["properties"]["zone_type"] == t), None)
    gov, airport = pick("government"), pick("airport")
    center = lambda f: (sum(y for _, y in f["geometry"]["coordinates"][0]) / len(f["geometry"]["coordinates"][0]), sum(x for x, _ in f["geometry"]["coordinates"][0]) / len(f["geometry"]["coordinates"][0]))
    if gov:
        lat, lng = center(gov)
        client.post("/flights", headers=hp, json={"drone_id": drone["drone_id"], "lat": lat, "lng": lng, "kind": "permission", "purpose": "Demo survey", "start": iso(now), "end": iso(now + timedelta(hours=2))})
    if airport:
        lat, lng = center(airport)
        client.post("/flights", headers=hp, json={"drone_id": drone["drone_id"], "lat": lat, "lng": lng, "kind": "watch", "start": iso(now + timedelta(minutes=30)), "end": iso(now + timedelta(minutes=90))})
        client.post("/notices", headers=ha, json={"title": "Demo VIP movement", "note": "Demo notice.", "lat": lat, "lng": lng, "radius_km": 3, "starts_at": iso(now), "ends_at": iso(now + timedelta(hours=3))})
    lines = [f"pilot  {a.pilot_email}  {pilot_pw}"]
    print("\n".join(lines))
    _save(lines)
    print(f"Demo data created. Saved in {CREDS}.")


def cmd_test_email(a):
    import otp_delivery
    dest = a.to.strip()
    code = secrets.token_hex(3).upper()
    print(f"Testing SMTP delivery to: {dest}")
    print(f"Host: {config.SMTP_HOST}:{config.SMTP_PORT}")
    print(f"From: {config.SMTP_FROM}")
    print(f"User: {config.SMTP_USER or '(none)'}")
    print(f"SSL:  {getattr(config, 'SMTP_USE_SSL', False)}")
    try:
        otp_delivery.smtp({"name": "Test User"}, dest, code, "register")
        print(f"Success! Verification code sent to {dest}: {code}")
    except Exception as e:
        print(f"Delivery failed: {e}")
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("create-admin"); s.add_argument("--email", required=True); s.add_argument("--name", default="Administrator")
    s.add_argument("--password"); s.add_argument("--generate", action="store_true"); s.set_defaults(fn=cmd_create_admin)
    s = sub.add_parser("seed-officers"); s.add_argument("--domain", default="officers.skyclear.local"); s.set_defaults(fn=cmd_seed_officers)
    s = sub.add_parser("seed-demo"); s.add_argument("--pilot-email", default="demo.pilot@example.com"); s.set_defaults(fn=cmd_seed_demo)
    s = sub.add_parser("create-tracker"); s.add_argument("--name", required=True); s.set_defaults(fn=cmd_create_tracker)
    s = sub.add_parser("seed-showcase"); s.set_defaults(fn=cmd_seed_showcase)
    s = sub.add_parser("prepare-demo"); s.add_argument("--pilot-email", default="demo.pilot@example.com"); s.set_defaults(fn=cmd_prepare_demo)
    s = sub.add_parser("list-users"); s.set_defaults(fn=cmd_list_users)
    s = sub.add_parser("logins"); s.set_defaults(fn=cmd_logins)
    s = sub.add_parser("set-password"); s.add_argument("--email", required=True); s.add_argument("--password"); s.set_defaults(fn=cmd_set_password)
    s = sub.add_parser("test-email"); s.add_argument("--to", required=True); s.set_defaults(fn=cmd_test_email)
    s = sub.add_parser("check-llm"); s.set_defaults(fn=cmd_check_llm)
    s = sub.add_parser("has-admin"); s.set_defaults(fn=cmd_has_admin)
    a = p.parse_args(argv)
    routing.setup()
    a.fn(a)


if __name__ == "__main__":
    main()
