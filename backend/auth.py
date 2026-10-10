"""Authentication: registration with a one-time code, password and code login, password reset and change, TOTP for officials, JWT and rotating refresh tokens.

OWNER: Nikhil (stream 2A). Contract 2 in docs/CONTRACTS.md.
Codes are sent by otp_delivery.py (email or SMS). Nothing is shown on screen unless OTP_DEV_ECHO=1, which is for tests only.
"""
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import config
import otp_delivery
import runtime
from security import current_user, public_user, require_admin

router = APIRouter()
_hits = defaultdict(deque)


def rate_limit(key, limit, window_s):
    """Simple in-memory sliding window. With several API replicas this needs a shared store (MongoDB)."""
    if not config.RATE_LIMITS:
        return
    now = time.time()
    q = _hits[key]
    while q and q[0] < now - window_s:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    q.append(now)


def normalize_phone(raw):
    d = re.sub(r"[\s\-()]", "", raw or "")
    d = re.sub(r"^(\+91|91|0)", "", d) if len(re.sub(r"^\+", "", d)) > 10 else d
    if not re.fullmatch(r"[6-9]\d{9}", d):
        raise HTTPException(422, "Enter a valid 10-digit Indian mobile number")
    return "+91" + d


def find_user(identifier):
    ident = (identifier or "").strip()
    if "@" in ident:
        return next((u for u in runtime.all_("users") if u["email"] == ident.lower()), None)
    try:
        phone = normalize_phone(ident)
    except HTTPException:
        return None
    return next((u for u in runtime.all_("users") if u.get("phone") == phone), None)


# ---- tokens ----
def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def access_token(user):
    now = datetime.now(timezone.utc)
    claims = {"sub": user["user_id"], "role": user["role"], "aid": user.get("authority_id"), "typ": "access",
              "iat": now, "exp": now + timedelta(minutes=config.ACCESS_TTL_MIN), "jti": secrets.token_hex(6)}
    return jwt.encode(claims, config.JWT_SECRET, algorithm="HS256")


def short_token(user, purpose, minutes=10):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user["user_id"], "typ": purpose, "iat": now, "exp": now + timedelta(minutes=minutes)}, config.JWT_SECRET, algorithm="HS256")


def read_short(token, purpose):
    try:
        c = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(401, "That step expired. Sign in again.")
    if c.get("typ") != purpose:
        raise HTTPException(401, "That step expired. Sign in again.")
    user = next((u for u in runtime.all_("users") if u["user_id"] == c["sub"]), None)
    if user is None:
        raise HTTPException(401, "That step expired. Sign in again.")
    return user


def issue_tokens(user, family=None):
    family = family or secrets.token_hex(8)
    refresh = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=config.REFRESH_TTL_DAYS)
    doc = {"token_hash": _hash(refresh), "family": family, "user_id": user["user_id"], "used": False,
           "expires_at": expires.isoformat(timespec="seconds"), "created_at": runtime.now_iso()}
    if config.USE_MONGO:
        doc["expireAt"] = expires  # BSON date for the TTL index
    runtime.insert("refresh_tokens", doc)
    access = access_token(user)
    return {"access_token": access, "refresh_token": refresh, "token": access, "expires_in": config.ACCESS_TTL_MIN * 60, "user": public_user(user)}


def revoke_family(family):
    if config.USE_MONGO:
        from db import get_db
        get_db().refresh_tokens.delete_many({"family": family})
    else:
        data = runtime._load()
        data["refresh_tokens"] = [t for t in data["refresh_tokens"] if t["family"] != family]
        runtime._save(data)


# ---- OTP (codes belong to an account, not to a phone number) ----
def send_otp(user, purpose):
    uid = user["user_id"]
    last = [o for o in runtime.all_("otps") if o["identifier"] == uid]
    if last and (time.time() - datetime.fromisoformat(last[-1]["created_at"]).timestamp()) < 20:
        raise HTTPException(429, "Wait 20 seconds before asking for another code")
    code = f"{secrets.randbelow(10**6):06d}"
    _drop_otps(uid)
    runtime.insert("otps", {"identifier": uid, "purpose": purpose, "code_hash": _hash(code + config.JWT_SECRET), "attempts": 0,
                            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=config.OTP_TTL_MIN)).isoformat(timespec="seconds"),
                            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    try:
        sent_to = otp_delivery.deliver(user, code, purpose)
    except otp_delivery.DeliveryError as e:
        print(f"[otp] delivery failed: {e}")
        raise HTTPException(502, "We could not send the code right now. Try again in a moment.")
    return code, sent_to


def _drop_otps(identifier):
    if config.USE_MONGO:
        from db import get_db
        get_db().otps.delete_many({"identifier": identifier})
    else:
        data = runtime._load()
        data["otps"] = [o for o in data["otps"] if o["identifier"] != identifier]
        runtime._save(data)


def check_otp(user, code, purposes):
    uid = user["user_id"]
    rec = next((o for o in runtime.all_("otps") if o["identifier"] == uid), None)
    if rec is None or datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(400, "That code expired. Ask for a new one.")
    if rec["attempts"] >= config.OTP_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many wrong codes. Ask for a new one.")
    if rec["purpose"] not in purposes or not hmac.compare_digest(rec["code_hash"], _hash(code.strip() + config.JWT_SECRET)):
        runtime.update("otps", "identifier", uid, {"attempts": rec["attempts"] + 1})
        raise HTTPException(400, "That code is not right")
    _drop_otps(uid)
    return rec["purpose"]


# ---- endpoints ----
class Register(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    phone: str = Field(min_length=10, max_length=20)
    password: str = Field(min_length=8, max_length=100)
    pilot_cert: Optional[str] = Field(default=None, max_length=40)


@router.post("/auth/register")
def register(body: Register, request: Request):
    rate_limit("reg:" + (request.client.host if request.client else "x"), 10, 60)
    email, phone = body.email.strip().lower(), normalize_phone(body.phone)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Enter a valid email")
    for u in runtime.all_("users"):
        if u["email"] == email:
            raise HTTPException(409, "An account with this email already exists. Sign in instead.")
        if u.get("phone") == phone:
            raise HTTPException(409, "An account with this mobile number already exists. Sign in instead.")
    runtime.insert("users", {"user_id": runtime.new_id("U"), "role": "pilot", "name": body.name.strip(), "email": email, "phone": phone,
                             "phone_verified": False, "pilot_cert": body.pilot_cert, "password": runtime.hash_password(body.password),
                             "failed_attempts": 0, "created_at": runtime.now_iso()})
    user = next(u for u in runtime.all_("users") if u["email"] == email)
    code, sent_to = send_otp(user, "register")
    return {"needs_otp": True, "identifier": email, "sent_to": sent_to, **({"dev_code": code} if config.OTP_DEV_ECHO else {})}


class OtpRequest(BaseModel):
    identifier: str


@router.post("/auth/otp/request")
def otp_request(body: OtpRequest, request: Request):
    rate_limit("otp:" + body.identifier, 5, 60)
    user = find_user(body.identifier)
    # Same answer whether or not the account exists, so nobody can probe for accounts.
    result = {"sent": True}
    if user and user["role"] == "pilot":
        code, _ = send_otp(user, "login" if user.get("phone_verified") else "register")
        if config.OTP_DEV_ECHO:
            result["dev_code"] = code
    return result


class OtpVerify(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerify, request: Request):
    rate_limit("otpv:" + body.identifier, 10, 60)
    user = find_user(body.identifier)
    if user is None or user["role"] != "pilot":
        raise HTTPException(400, "That code is not right")
    check_otp(user, body.code, ("register", "login"))
    if not user.get("phone_verified"):
        user = runtime.update("users", "user_id", user["user_id"], {"phone_verified": True})
    return issue_tokens(user)


class Login(BaseModel):
    identifier: str
    password: str


@router.post("/auth/login")
def login(body: Login, request: Request):
    rate_limit("login:" + (request.client.host if request.client else "x"), 20, 60)
    user = find_user(body.identifier)
    now = datetime.now(timezone.utc)
    if user and user.get("locked_until") and datetime.fromisoformat(user["locked_until"]) > now:
        raise HTTPException(423, "This account is locked for a few minutes after too many wrong passwords. Try again later.")
    if user is None or not runtime.check_password(body.password, user["password"]):
        if user:
            fails = user.get("failed_attempts", 0) + 1
            lock = (now + timedelta(minutes=config.LOCK_MINUTES)).isoformat(timespec="seconds") if fails >= config.MAX_FAILED_LOGINS else None
            runtime.update("users", "user_id", user["user_id"], {"failed_attempts": 0 if lock else fails, "locked_until": lock})
        raise HTTPException(401, "Wrong email, mobile number or password")
    runtime.update("users", "user_id", user["user_id"], {"failed_attempts": 0, "locked_until": None})
    if user["role"] == "pilot" and not user.get("phone_verified"):
        raise HTTPException(403, "not_verified")  # the app then asks for a code with /auth/otp/request
    if user["role"] == "official" and (config.REQUIRE_OFFICIAL_MFA or user.get("totp_secret")):
        step = "mfa_required" if user.get("totp_secret") else "mfa_setup_required"
        return {step: True, "mfa_token": short_token(user, "mfa")}
    return issue_tokens(user)


class MfaSetup(BaseModel):
    mfa_token: str


@router.post("/auth/totp/setup")
def totp_setup(body: MfaSetup):
    user = read_short(body.mfa_token, "mfa")
    if user.get("totp_secret"):
        raise HTTPException(409, "Authenticator already set up")
    secret = user.get("totp_pending") or pyotp.random_base32()
    runtime.update("users", "user_id", user["user_id"], {"totp_pending": secret})
    return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name="SkyClear")}


class MfaVerify(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=6)


@router.post("/auth/totp/verify")
def totp_verify(body: MfaVerify, request: Request):
    rate_limit("totp:" + body.mfa_token[-12:], 8, 60)
    user = read_short(body.mfa_token, "mfa")
    secret = user.get("totp_secret") or user.get("totp_pending")
    if not secret or not pyotp.TOTP(secret).verify(body.code, valid_window=1):
        raise HTTPException(400, "That code is not right")
    if not user.get("totp_secret"):
        user = runtime.update("users", "user_id", user["user_id"], {"totp_secret": secret, "totp_pending": None})
    return issue_tokens(user)


class Refresh(BaseModel):
    refresh_token: str


@router.post("/auth/refresh")
def refresh(body: Refresh):
    rec = next((t for t in runtime.all_("refresh_tokens") if t["token_hash"] == _hash(body.refresh_token)), None)
    if rec is None:
        raise HTTPException(401, "sign in required")
    if rec["used"]:
        revoke_family(rec["family"])  # a used token came back: assume it was stolen, end the whole session
        raise HTTPException(401, "session_revoked")
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(401, "sign in required")
    user = next((u for u in runtime.all_("users") if u["user_id"] == rec["user_id"]), None)
    if user is None:
        raise HTTPException(401, "sign in required")
    runtime.update("refresh_tokens", "token_hash", rec["token_hash"], {"used": True})
    return issue_tokens(user, family=rec["family"])


@router.post("/auth/logout")
def logout(body: Refresh):
    rec = next((t for t in runtime.all_("refresh_tokens") if t["token_hash"] == _hash(body.refresh_token)), None)
    if rec:
        revoke_family(rec["family"])
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return public_user(user)


class Forgot(BaseModel):
    identifier: str


@router.post("/auth/password/forgot")
def password_forgot(body: Forgot, request: Request):
    rate_limit("forgot:" + body.identifier, 3, 60)
    user = find_user(body.identifier)
    result = {"sent": True}  # same answer for unknown accounts
    if user:
        code, _ = send_otp(user, "reset")
        if config.OTP_DEV_ECHO:
            result["dev_code"] = code
    return result


def _strong(password):
    if len(password) < 8:
        raise HTTPException(422, "Use at least 8 characters")
    return password


class Reset(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=100)


@router.post("/auth/password/reset")
def password_reset(body: Reset, request: Request):
    rate_limit("reset:" + body.identifier, 10, 60)
    user = find_user(body.identifier)
    if user is None:
        raise HTTPException(400, "That code is not right")
    check_otp(user, body.code, ("reset",))
    runtime.update("users", "user_id", user["user_id"], {"password": runtime.hash_password(_strong(body.new_password)), "failed_attempts": 0,
                                                         "locked_until": None, "must_change_password": False})
    for t in [t for t in runtime.all_("refresh_tokens") if t["user_id"] == user["user_id"]]:
        revoke_family(t["family"])  # everyone signed in with the old password is signed out
    return {"ok": True}


class Change(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=100)


@router.post("/auth/password/change")
def password_change(body: Change, user=Depends(current_user)):
    if not runtime.check_password(body.current_password, user["password"]):
        raise HTTPException(401, "Your current password is not right")
    if body.current_password == body.new_password:
        raise HTTPException(422, "Choose a different password")
    user = runtime.update("users", "user_id", user["user_id"], {"password": runtime.hash_password(_strong(body.new_password)), "must_change_password": False})
    return issue_tokens(user)


class NewOfficial(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    authority_id: Optional[str] = None


@router.get("/admin/officials")
def list_officials(admin=Depends(require_admin)):
    return [public_user(u) for u in runtime.all_("users") if u["role"] == "official"]


@router.post("/admin/officials")
def invite_official(body: NewOfficial, admin=Depends(require_admin)):
    """Officials are created by an admin, never self-registered. The admin gets a one-time password to hand over, and the official must change it at first sign-in."""
    import routing
    if body.authority_id and routing.get(body.authority_id) is None:
        raise HTTPException(422, "unknown authority_id")
    email = body.email.strip().lower()
    if any(u["email"] == email for u in runtime.all_("users")):
        raise HTTPException(409, "email already in use")
    temp = secrets.token_urlsafe(9)
    u = runtime.insert("users", {"user_id": runtime.new_id("U"), "role": "official", "authority_id": body.authority_id or None, "name": body.name.strip(),
                                 "email": email, "password": runtime.hash_password(temp), "must_change_password": True, "failed_attempts": 0, "created_at": runtime.now_iso()})
    return {**public_user(u), "temporary_password": temp}


class GoogleAuthRequest(BaseModel):
    credential: str = Field(min_length=10)


@router.post("/auth/google")
def google_auth(body: GoogleAuthRequest, request: Request):
    rate_limit("gauth:" + (request.client.host if request.client else "x"), 20, 60)
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google Authentication is not configured on the server. Set GOOGLE_CLIENT_ID in .env")

    try:
        import requests
        resp = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": body.credential},
            timeout=10,
        )
        if resp.status_code != 200:
            err_msg = resp.json().get("error_description", "verification failed") if resp.headers.get("content-type", "").startswith("application/json") else "verification failed"
            raise HTTPException(401, f"Invalid Google credential: {err_msg}")
        idinfo = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Could not contact Google verification: {e}")

    if idinfo.get("aud") != config.GOOGLE_CLIENT_ID:
        raise HTTPException(401, "Google token audience mismatch")

    email = idinfo.get("email", "").strip().lower()
    name = idinfo.get("name", "Pilot").strip()
    google_id = idinfo.get("sub")

    if not email:
        raise HTTPException(400, "Google account did not provide an email address")

    user = next((u for u in runtime.all_("users") if u.get("email") == email), None)
    if user is None:
        user_doc = {
            "user_id": runtime.new_id("U"),
            "role": "pilot",
            "name": name,
            "email": email,
            "google_id": google_id,
            "phone": None,
            "phone_verified": True,
            "pilot_cert": None,
            "password": None,
            "failed_attempts": 0,
            "created_at": runtime.now_iso()
        }
        runtime.insert("users", user_doc)
        user = user_doc
    else:
        if not user.get("google_id"):
            runtime.update("users", "user_id", user["user_id"], {"google_id": google_id})

    return issue_tokens(user)


def setup_indexes():
    if config.USE_MONGO:
        from db import get_db
        db = get_db()
        db.refresh_tokens.create_index("token_hash", unique=True)
        db.refresh_tokens.create_index("expireAt", expireAfterSeconds=0)
        db.refresh_tokens.create_index("family")
        db.users.create_index("phone", unique=True, partialFilterExpression={"phone": {"$type": "string"}})
        db.otps.create_index("identifier")
