from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from fastapi.testclient import TestClient

import auth
import config
from main import app
from tests.support import ADMIN_EMAIL, PASSWORD, officer_email

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
    assert reg["needs_otp"] and reg["identifier"] == email and "***@" in reg["sent_to"] and len(reg["dev_code"]) == 6
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
    assert client.post("/auth/login", json={"identifier": f"+91{_n[0]}", "password": "longenough1"}).status_code == 200  # by mobile number
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
    dup = client.post("/auth/register", json={"name": "A B", "email": "other@example.com", "phone": f"+91 {_n[0]}", "password": "longenough1"})
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
    admin = client.post("/auth/login", json={"identifier": ADMIN_EMAIL, "password": PASSWORD}).json()["token"]
    invited = client.post("/admin/officials", headers=h(admin), json={"name": "MFA Officer", "email": "mfa@officers.test.local", "authority_id": "A-FOR"}).json()
    monkeypatch.setattr(config, "REQUIRE_OFFICIAL_MFA", True)
    login = {"identifier": "mfa@officers.test.local", "password": invited["temporary_password"]}
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
    admin = client.post("/auth/login", json={"identifier": ADMIN_EMAIL, "password": PASSWORD}).json()["token"]
    desk = client.post("/auth/login", json={"identifier": officer_email("A-POL"), "password": PASSWORD}).json()["token"]
    body = {"name": "New Officer", "email": "newofficer@officers.test.local", "authority_id": "A-POL"}
    assert client.post("/admin/officials", headers=h(desk), json=body).status_code == 403   # an officer is not an admin
    made = client.post("/admin/officials", headers=h(admin), json=body)
    assert made.status_code == 200 and made.json()["must_change_password"] is True
    assert client.post("/auth/login", json={"identifier": body["email"], "password": made.json()["temporary_password"]}).status_code == 200


def test_rate_limit_on_login(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMITS", True)
    auth._hits.clear()
    codes = [client.post("/auth/login", json={"identifier": "nobody@example.com", "password": "x"}).status_code for _ in range(22)]
    assert 429 in codes
    auth._hits.clear()


def test_passwords_are_argon2():
    from runtime import all_
    assert all(u["password"].startswith("$argon2") for u in all_("users"))


def test_invited_official_must_change_the_temporary_password():
    admin = client.post("/auth/login", json={"identifier": ADMIN_EMAIL, "password": PASSWORD}).json()["token"]
    made = client.post("/admin/officials", headers=h(admin), json={"name": "Fresh Officer", "email": "fresh@officers.test.local", "authority_id": "A-DEF"}).json()
    first = client.post("/auth/login", json={"identifier": "fresh@officers.test.local", "password": made["temporary_password"]}).json()
    assert first["user"]["must_change_password"] is True
    wrong = client.post("/auth/password/change", headers=h(first["token"]), json={"current_password": "not-it", "new_password": "A-new-password-9"})
    assert wrong.status_code == 401
    ok = client.post("/auth/password/change", headers=h(first["token"]), json={"current_password": made["temporary_password"], "new_password": "A-new-password-9"})
    assert ok.status_code == 200 and ok.json()["user"]["must_change_password"] is False
    assert client.post("/auth/login", json={"identifier": "fresh@officers.test.local", "password": made["temporary_password"]}).status_code == 401
    assert client.post("/auth/login", json={"identifier": "fresh@officers.test.local", "password": "A-new-password-9"}).status_code == 200


def test_password_reset_with_a_code_signs_out_old_sessions():
    email, reg = new_pilot()
    t = client.post("/auth/otp/verify", json={"identifier": email, "code": reg["dev_code"]}).json()
    auth._hits.clear()
    sent = client.post("/auth/password/forgot", json={"identifier": email}).json()
    assert sent["sent"] and len(sent["dev_code"]) == 6
    assert client.post("/auth/password/reset", json={"identifier": email, "code": "000000" if sent["dev_code"] != "000000" else "111111", "new_password": "brand-new-pass-1"}).status_code == 400
    ok = client.post("/auth/password/reset", json={"identifier": email, "code": sent["dev_code"], "new_password": "brand-new-pass-1"})
    assert ok.status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401   # old session ended
    assert client.post("/auth/login", json={"identifier": email, "password": "longenough1"}).status_code == 401
    assert client.post("/auth/login", json={"identifier": email, "password": "brand-new-pass-1"}).status_code == 200


def test_a_register_code_cannot_reset_a_password():
    email, reg = new_pilot()
    r = client.post("/auth/password/reset", json={"identifier": email, "code": reg["dev_code"], "new_password": "brand-new-pass-1"})
    assert r.status_code == 400


def test_forgot_password_does_not_reveal_unknown_accounts():
    assert client.post("/auth/password/forgot", json={"identifier": "ghost@example.com"}).json() == {"sent": True}


def test_codes_are_sent_by_email_through_smtp(monkeypatch):
    import smtplib
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): sent.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def send_message(self, msg): sent.append(("mail", msg["To"], msg.get_content()))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(config, "OTP_PROVIDER", "smtp")
    monkeypatch.setattr(config, "OTP_DEV_ECHO", False)
    email, reg = new_pilot()
    mail = [s for s in sent if s[0] == "mail"][0]
    assert mail[1] == email and "Your SkyClear code is" in mail[2] and "dev_code" not in reg


def test_failed_delivery_gives_a_clean_error(monkeypatch):
    import smtplib

    def boom(*a, **k): raise OSError("mail server down")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    monkeypatch.setattr(config, "OTP_PROVIDER", "smtp")
    _n[0] += 1
    r = client.post("/auth/register", json={"name": "No Mail", "email": f"nomail{_n[0]}@example.com", "phone": str(_n[0]), "password": "longenough1"})
    assert r.status_code == 502 and "could not send" in r.json()["detail"]


def test_secrets_are_generated_not_written_in_code():
    assert len(config.JWT_SECRET) >= 32 and len(config.PERMIT_SECRET) >= 32 and config.JWT_SECRET != config.PERMIT_SECRET
    assert "dev-only" not in config.JWT_SECRET and "dev-only" not in config.PERMIT_SECRET


def test_google_auth_endpoint(monkeypatch):
    import requests

    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")

    # 1. Invalid token from Google returns 401
    class FakeBadResponse:
        status_code = 400
        headers = {"content-type": "application/json"}
        def json(self): return {"error_description": "Bad token"}

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeBadResponse())
    r_bad = client.post("/auth/google", json={"credential": "invalid_token_sample"})
    assert r_bad.status_code == 401

    # 2. Valid token returns tokens and creates/logs in pilot
    class FakeGoodResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self):
            return {
                "aud": "test-google-client-id.apps.googleusercontent.com",
                "email": "googlepilot@example.com",
                "email_verified": "true",
                "iss": "https://accounts.google.com",
                "name": "Google Test Pilot",
                "sub": "google-user-12345"
            }

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeGoodResponse())
    r_ok = client.post("/auth/google", json={"credential": "valid_token_sample"})
    assert r_ok.status_code == 200
    data = r_ok.json()
    assert {"access_token", "refresh_token", "user"} <= set(data)
    assert data["user"]["email"] == "googlepilot@example.com"
    assert data["user"]["role"] == "pilot"



# ---- Google sign-in: what it must never allow ----
def _google(monkeypatch, email, verified="true", sub="g-1", aud="test-google-client-id.apps.googleusercontent.com"):
    import requests

    class Fake:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self): return {"aud": aud, "iss": "https://accounts.google.com", "email": email, "email_verified": verified, "name": "G User", "sub": sub}

    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(requests, "get", lambda *a, **k: Fake())
    return client.post("/auth/google", json={"credential": "x" * 20})


def test_google_cannot_be_used_to_get_into_an_official_account(monkeypatch):
    r = _google(monkeypatch, officer_email("A-POL"))
    assert r.status_code == 403 and "access_token" not in r.json()
    assert _google(monkeypatch, ADMIN_EMAIL).status_code == 403


def test_google_email_must_be_verified_by_google(monkeypatch):
    r = _google(monkeypatch, "unverified@example.com", verified="false")
    assert r.status_code == 401
    assert all(u["email"] != "unverified@example.com" for u in __import__("runtime").all_("users"))  # no account was made


def test_google_token_for_another_app_is_refused(monkeypatch):
    assert _google(monkeypatch, "other@example.com", aud="someone-elses-app.apps.googleusercontent.com").status_code == 401


def test_a_google_only_account_gives_a_clean_login_error_not_a_crash(monkeypatch):
    assert _google(monkeypatch, "goog.only@example.com").status_code == 200
    r = client.post("/auth/login", json={"identifier": "goog.only@example.com", "password": "anything-at-all-1"})
    assert r.status_code == 401 and "Google" in r.json()["detail"]


def test_google_does_not_inherit_a_password_someone_set_before_the_owner_confirmed(monkeypatch):
    """An attacker starts an account with a victim's email and a password they know. When the real owner proves the email
    with Google, the attacker's password must be gone."""
    email, reg = new_pilot("victim.pilot@example.com")  # registered, never confirmed
    assert client.post("/auth/login", json={"identifier": email, "password": "longenough1"}).status_code == 403  # not confirmed yet
    assert _google(monkeypatch, email, sub="real-owner").status_code == 200
    assert client.post("/auth/login", json={"identifier": email, "password": "longenough1"}).status_code == 401  # attacker's password no longer works


def test_an_email_linked_to_one_google_account_rejects_another(monkeypatch):
    assert _google(monkeypatch, "linked@example.com", sub="first").status_code == 200
    assert _google(monkeypatch, "linked@example.com", sub="second").status_code == 401
    assert _google(monkeypatch, "linked@example.com", sub="first").status_code == 200


def test_a_google_account_can_still_reset_a_password_by_email_code():
    import requests  # noqa: F401
    import runtime
    u = next(u for u in runtime.all_("users") if u["email"] == "goog.only@example.com")
    auth._hits.clear()
    sent = client.post("/auth/password/forgot", json={"identifier": u["email"]}).json()
    assert sent["sent"] and len(sent["dev_code"]) == 6
    ok = client.post("/auth/password/reset", json={"identifier": u["email"], "code": sent["dev_code"], "new_password": "now-i-have-one-1"})
    assert ok.status_code == 200
    assert client.post("/auth/login", json={"identifier": u["email"], "password": "now-i-have-one-1"}).status_code == 200
