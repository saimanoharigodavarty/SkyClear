"""Auth dependencies shared by every router: who is calling, and what role they need.

OWNER: Nikhil (stream 2A). Prototype: bearer token from /auth/login. Contract 2 replaces this with JWT access and refresh tokens.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException

import runtime


def current_user(authorization: Optional[str] = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = runtime.user_for_token(token) if token else None
    if user is None:
        raise HTTPException(401, "sign in required")
    return user


def require(role):
    def dep(user=Depends(current_user)):
        if user["role"] != role:
            raise HTTPException(403, f"{role} access only")
        return user
    return dep


def public_user(u):
    out = {k: u[k] for k in ("user_id", "role", "name", "email", "authority_id") if k in u}
    return out | {"pilot_cert": u.get("pilot_cert"), "verification": u.get("verification") or {"status": "unverified"}}
