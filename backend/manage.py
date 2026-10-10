"""Setup commands. Accounts are never created by the app on its own and no password is written in code.

  python backend/manage.py create-admin --email you@example.com --name "Your Name"   asks for a password
  python backend/manage.py create-admin --email you@example.com --generate           makes one and prints it once
  python backend/manage.py seed-officers                                             one officer per authority, generated passwords
  python backend/manage.py seed-demo                                                 a verified demo pilot, a drone, flights and a notice
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
    existing = CREDS.read_text(encoding="utf-8") if CREDS.exists() else ""
    CREDS.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
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


def cmd_has_admin(a):
    sys.exit(0 if any(u["role"] == "official" and not u.get("authority_id") for u in runtime.all_("users")) else 1)


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
    pilot_pw, admin_pw = secrets.token_urlsafe(12), secrets.token_urlsafe(16)
    # The admin signs in through the real API with a one-off password so nothing needs to be known in advance.
    runtime.update("users", "user_id", admin["user_id"], {"password": runtime.hash_password(admin_pw)})
    create_user(a.pilot_email, "Demo Pilot", "pilot", pilot_pw, verified=True, phone="+919" + str(secrets.randbelow(10**9)).zfill(9))
    a_tok = client.post("/auth/login", json={"identifier": admin["email"], "password": admin_pw}).json()["token"]
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
    # leave the admin with a password nobody knows: set a fresh one to print
    admin_final = secrets.token_urlsafe(12)
    runtime.update("users", "user_id", admin["user_id"], {"password": runtime.hash_password(admin_final)})
    lines = [f"pilot  {a.pilot_email}  {pilot_pw}", f"admin  {admin['email']}  {admin_final}  (reset by seed-demo)"]
    print("\n".join(lines))
    _save(lines)
    print(f"Demo data created. Saved in {CREDS}.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("create-admin"); s.add_argument("--email", required=True); s.add_argument("--name", default="Administrator")
    s.add_argument("--password"); s.add_argument("--generate", action="store_true"); s.set_defaults(fn=cmd_create_admin)
    s = sub.add_parser("seed-officers"); s.add_argument("--domain", default="officers.skyclear.local"); s.set_defaults(fn=cmd_seed_officers)
    s = sub.add_parser("seed-demo"); s.add_argument("--pilot-email", default="demo.pilot@example.com"); s.set_defaults(fn=cmd_seed_demo)
    s = sub.add_parser("list-users"); s.set_defaults(fn=cmd_list_users)
    s = sub.add_parser("has-admin"); s.set_defaults(fn=cmd_has_admin)
    a = p.parse_args(argv)
    routing.setup()
    a.fn(a)


if __name__ == "__main__":
    main()
