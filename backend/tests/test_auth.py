from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from fastapi.testclient import TestClient

import auth
import config
from main import app

client = TestClient(app)
_n = [9100000000]


def new_pilot(email=None):
    _n[0] += 1
    email = email or f"auth{_n[0]}@example.com"
    r = client.post("/auth/register", json={"name": "Auth Pilot", "email": email, "phone": f"+91 {_n[0]}", "password": "longenough1"})
    assert r.status_code == 200, r.text
    return email, r.json()


def h(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_needs_otp_then_issues_tokens():
    email, reg = new_pilot()
    assert reg["needs_otp"] and reg["identifier"].startswith("+91") and len(reg["dev_code"]) == 6
    # password login is blocked until the phone is verified
    assert client.post("/auth/login", json={"identifier": email, "password": "longenough1"}).status_code == 403
    bad = client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": "000000" if reg["dev_code"] != "000000" else "111111"})
    assert bad.status_code == 400
    ok = client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": reg["dev_code"]}).json()
    assert {"access_token", "refresh_token", "token", "expires_in", "user"} <= set(ok)
    assert client.get("/me", headers=h(ok["access_token"])).json()["email"] == email
    assert "*" in ok["user"]["phone"]  # masked
    again = client.post("/auth/login", json={"identifier": email, "password": "longenough1"})
    assert again.status_code == 200


def test_login_by_phone_and_otp_login():
    email, reg = new_pilot()
    client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": reg["dev_code"]})
    assert client.post("/auth/login", json={"identifier": reg["identifier"], "password": "longenough1"}).status_code == 200
    auth._hits.clear()
    req = client.post("/auth/otp/request", json={"identifier": email}).json()
    assert req["sent"] and len(req["dev_code"]) == 6
    assert client.post("/auth/otp/verify", json={"identifier": email, "code": req["dev_code"]}).status_code == 200


def test_otp_request_does_not_reveal_unknown_accounts():
    r = client.post("/auth/otp/request", json={"identifier": "nobody@example.com"})
    assert r.status_code == 200 and r.json() == {"sent": True}


def test_phone_validation_and_duplicates():
    assert client.post("/auth/register", json={"name": "A B", "email": "p1@example.com", "phone": "12345", "password": "longenough1"}).status_code == 422
    email, reg = new_pilot()
    dup = client.post("/auth/register", json={"name": "A B", "email": "other@example.com", "phone": reg["identifier"], "password": "longenough1"})
    assert dup.status_code == 409


def test_lockout_after_repeated_wrong_passwords():
    email, reg = new_pilot()
    client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": reg["dev_code"]})
    for _ in range(config.MAX_FAILED_LOGINS):
        assert client.post("/auth/login", json={"identifier": email, "password": "wrong-password"}).status_code == 401
    locked = client.post("/auth/login", json={"identifier": email, "password": "longenough1"})
    assert locked.status_code == 423


def test_refresh_rotates_and_reuse_revokes_the_session():
    email, reg = new_pilot()
    t1 = client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": reg["dev_code"]}).json()
    t2 = client.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    assert t2["refresh_token"] != t1["refresh_token"] and client.get("/me", headers=h(t2["access_token"])).status_code == 200
    # the first refresh token is replayed, as a thief would: the whole session ends
    replay = client.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert replay.status_code == 401 and replay.json()["detail"] == "session_revoked"
    assert client.post("/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_logout_ends_the_session():
    email, reg = new_pilot()
    t = client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": reg["dev_code"]}).json()
    client.post("/auth/logout", json={"refresh_token": t["refresh_token"]})
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_expired_and_forged_access_tokens_are_rejected():
    email, reg = new_pilot()
    t = client.post("/auth/otp/verify", json={"identifier": reg["identifier"], "code": reg["dev_code"]}).json()
    claims = jwt.decode(t["access_token"], config.JWT_SECRET, algorithms=["HS256"])
    old = jwt.encode({**claims, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, config.JWT_SECRET, algorithm="HS256")
    r = client.get("/me", headers=h(old))
    assert r.status_code == 401 and r.json()["detail"] == "token_expired"
    forged = jwt.encode(claims, "not-the-secret", algorithm="HS256")
    assert client.get("/me", headers=h(forged)).status_code == 401
    admin_claim = jwt.encode({**claims, "role": "official"}, "not-the-secret", algorithm="HS256")
    assert client.get("/overview", headers=h(admin_claim)).status_code == 401


def test_official_mfa_flow_with_authenticator_code(monkeypatch):
    admin = client.post("/auth/login", json={"identifier": config.OFFICIAL_EMAIL, "password": config.OFFICIAL_PASSWORD}).json()["token"]
    client.post("/admin/officials", headers=h(admin), json={"name": "MFA Officer", "email": "mfa@skyclear.demo", "authority_id": "A-FOR", "password": "a-long-password-1"})
    monkeypatch.setattr(config, "REQUIRE_OFFICIAL_MFA", True)
    login = {"identifier": "mfa@skyclear.demo", "password": "a-long-password-1"}
    first = client.post("/auth/login", json=login).json()
    assert first.get("mfa_setup_required") and "access_token" not in first
    setup = client.post("/auth/totp/setup", json={"mfa_token": first["mfa_token"]}).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    assert client.post("/auth/totp/verify", json={"mfa_token": first["mfa_token"], "code": "000000"}).status_code == 400
    done = client.post("/auth/totp/verify", json={"mfa_token": first["mfa_token"], "code": pyotp.TOTP(setup["secret"]).now()})
    assert done.status_code == 200 and done.json()["user"]["mfa_enabled"]
    second = client.post("/auth/login", json=login).json()
    assert second.get("mfa_required")
    assert client.post("/auth/totp/verify", json={"mfa_token": second["mfa_token"], "code": pyotp.TOTP(setup["secret"]).now()}).status_code == 200


def test_officials_cannot_sign_in_with_otp_and_are_invite_only():
    assert client.post("/auth/register", json={"name": "Fake Official", "email": "f@gov.in", "phone": "9199999999", "password": "longenough1", "role": "official"}).json().get("needs_otp")
    me = client.post("/auth/login", json={"identifier": "f@gov.in", "password": "longenough1"})
    assert me.status_code == 403  # registered as a pilot, not verified; role field is ignored
    admin = client.post("/auth/login", json={"identifier": config.OFFICIAL_EMAIL, "password": config.OFFICIAL_PASSWORD}).json()["token"]
    desk = client.post("/auth/login", json={"identifier": "police@skyclear.demo", "password": config.OFFICIAL_PASSWORD}).json()["token"]
    body = {"name": "New Officer", "email": "newofficer@skyclear.demo", "authority_id": "A-POL", "password": "a-long-password-1"}
    assert client.post("/admin/officials", headers=h(desk), json=body).status_code == 403   # an officer is not an admin
    assert client.post("/admin/officials", headers=h(admin), json=body).status_code == 200
    assert client.post("/auth/login", json={"identifier": "newofficer@skyclear.demo", "password": "a-long-password-1"}).status_code == 200


def test_rate_limit_on_login(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMITS", True)
    auth._hits.clear()
    codes = [client.post("/auth/login", json={"identifier": "nobody@example.com", "password": "x"}).status_code for _ in range(22)]
    assert 429 in codes
    auth._hits.clear()


def test_passwords_are_argon2():
    from runtime import all_
    assert all(u["password"].startswith("$argon2") for u in all_("users"))
