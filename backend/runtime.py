"""Store for accounts, flights, official notices and alerts.

Two backends behind the same functions: MongoDB when config.USE_MONGO, otherwise a JSON file.
"""
import contextlib
import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone

import config
import events


def _mongo():
    from db import get_db
    return get_db()

_lock = threading.RLock()
_EMPTY = {"users": [], "sessions": {}, "drones": [], "flights": [], "notices": [], "notifications": [],
          "permits": [], "verifications": [], "files": [], "authorities": [], "refresh_tokens": [], "otps": [],
          "breaches": [], "audit_log": [], "trackers": []}
_tls = threading.local()  # the MongoDB session of the transaction this thread is inside, if any


def _kw():
    s = getattr(_tls, "session", None)
    return {"session": s} if s is not None else {}


@contextlib.contextmanager
def atomic():
    """Everything written inside this block succeeds together or not at all (a MongoDB multi-document transaction).
    With the JSON file store there is one writer, so it simply runs the block."""
    if not config.USE_MONGO:
        yield
        return
    with _mongo().client.start_session() as session:
        with session.start_transaction():  # commits when the block ends, aborts if it raises
            _tls.session = session
            try:
                yield
            finally:
                _tls.session = None


def audit(actor, action, target, detail=None):
    """An append-only record of what an official did, who did it and when. Written inside the same transaction as the action."""
    return insert("audit_log", {"audit_id": new_id("AU"), "ts": now_iso(), "actor_id": actor["user_id"], "actor": actor["name"],
                                "role": actor["role"], "authority_id": actor.get("authority_id"), "action": action, "target": target, "detail": detail or ""})


def _load():
    try:
        with open(config.RUNTIME_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {k: data.get(k, type(v)()) for k, v in _EMPTY.items()}


def _save(data):
    config.RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.RUNTIME_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    tmp.replace(config.RUNTIME_PATH)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(3).upper()}"


def all_(coll):
    if config.USE_MONGO:
        return list(_mongo()[coll].find({}, {"_id": 0}))
    with _lock:
        return _load()[coll]


def insert(coll, doc):
    if config.USE_MONGO:
        _mongo()[coll].insert_one(dict(doc), **_kw())  # the change stream publishes it, after any transaction commits
        return doc
    with _lock:
        data = _load()
        data[coll].append(doc)
        _save(data)
    events.publish(coll, "insert", doc)
    return doc


def update(coll, key, value, changes):
    """Merge `changes` into the first doc where doc[key] == value. Returns the doc or None."""
    if config.USE_MONGO:
        return _mongo()[coll].find_one_and_update({key: value}, {"$set": changes}, projection={"_id": 0}, return_document=True, **_kw())
    with _lock:
        data = _load()
        for d in data[coll]:
            if d.get(key) == value:
                d.update(changes)
                _save(data)
                events.publish(coll, "update", d)
                return d
    return None


def mark_read(user_id):
    if config.USE_MONGO:
        _mongo().notifications.update_many({"user_id": user_id}, {"$set": {"read": True}}, **_kw())
        return
    with _lock:
        data = _load()
        for n in data["notifications"]:
            if n["user_id"] == user_id:
                n["read"] = True
        _save(data)


def hash_password(password, salt=None):
    """argon2id. (`salt` is accepted only for the old scrypt format used by check_password.)"""
    if salt is not None:
        h = hashlib.scrypt(password.encode(), salt=salt.encode(), n=2**14, r=8, p=1).hex()
        return f"{salt}${h}"
    from argon2 import PasswordHasher
    return PasswordHasher().hash(password)


def check_password(password, stored):
    if not stored:  # an account made with Google has no password
        return False
    if stored.startswith("$argon2"):
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError, InvalidHashError
        try:
            return PasswordHasher().verify(stored, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    salt, _ = stored.split("$", 1)  # older accounts used scrypt
    return secrets.compare_digest(hash_password(password, salt), stored)


def create_session(user_id):
    token = secrets.token_urlsafe(24)
    if config.USE_MONGO:
        _mongo().sessions.insert_one({"token": token, "user_id": user_id})
        return token
    with _lock:
        data = _load()
        data["sessions"][token] = user_id
        _save(data)
    return token


def user_for_token(token):
    if config.USE_MONGO:
        sess = _mongo().sessions.find_one({"token": token})
        return _mongo().users.find_one({"user_id": sess["user_id"]}, {"_id": 0}) if sess else None
    with _lock:
        data = _load()
        uid = data["sessions"].get(token)
        return next((u for u in data["users"] if u["user_id"] == uid), None)
