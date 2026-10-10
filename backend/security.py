"""Who is calling and what role they need. Access tokens are short-lived JWTs (auth.py issues them).

OWNER: Nikhil (stream 2A). Contract 2 in docs/CONTRACTS.md.
"""
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException

import config
import runtime


def decode_access(token):
    try:
        claims = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "sign in required")
    if claims.get("typ") != "access":
        raise HTTPException(401, "sign in required")
    return claims


def current_user(authorization: Optional[str] = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "sign in required")
    claims = decode_access(token)
    user = next((u for u in runtime.all_("users") if u["user_id"] == claims["sub"]), None)
    if user is None:
        raise HTTPException(401, "sign in required")
    return user


def require(role):
    def dep(user=Depends(current_user)):
        if user["role"] != role:
            raise HTTPException(403, f"{role} access only")
        return user
    return dep


def require_admin(user=Depends(require("official"))):
    if user.get("authority_id"):
        raise HTTPException(403, "admin access only")
    return user


def mask_phone(phone):
    return phone[:3] + "*" * 6 + phone[-4:] if phone else None


def public_user(u):
    out = {k: u[k] for k in ("user_id", "role", "name", "email", "authority_id") if k in u}
    return out | {"pilot_cert": u.get("pilot_cert"), "phone": mask_phone(u.get("phone")), "mfa_enabled": bool(u.get("totp_secret")), "must_change_password": bool(u.get("must_change_password")),
                  "verification": u.get("verification") or {"status": "unverified"}}


# ---- pairing: a phone that scanned a QR code may fly one flight, and nothing else ----
def make_pair_token(user_id, flight_id, minutes=45):
    """A short-lived token for one flight. It can send stick commands, return home, land and read that flight's live view.
    It cannot read an account, change anything else, or touch another flight."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": user_id, "fid": flight_id, "typ": "pair", "iat": now, "exp": now + dt.timedelta(minutes=minutes)}, config.JWT_SECRET, algorithm="HS256")


def flight_claims(flight_id, authorization):
    """Who is acting on this flight, from the token alone (no database read, so it is cheap enough for 10 calls a second).
    Accepts a pilot's or an official's access token, or a pair token made for exactly this flight."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "sign in required")
    try:
        c = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "sign in required")
    if c.get("typ") == "pair":
        if c.get("fid") != flight_id:
            raise HTTPException(403, "this controller is paired with a different flight")
        return {"user_id": c["sub"], "role": "pilot", "via": "pair"}
    if c.get("typ") == "access":
        return {"user_id": c["sub"], "role": c.get("role"), "via": "login"}
    raise HTTPException(401, "sign in required")
