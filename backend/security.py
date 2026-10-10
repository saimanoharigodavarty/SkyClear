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
