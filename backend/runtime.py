"""Store for accounts, flights, official notices and alerts.

Two backends behind the same functions: MongoDB when config.USE_MONGO, otherwise a JSON file.
"""
import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone

import config


def _mongo():
    from db import get_db
    return get_db()

_lock = threading.RLock()
_EMPTY = {"users": [], "sessions": {}, "drones": [], "flights": [], "notices": [], "notifications": []}


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
        _mongo()[coll].insert_one(dict(doc))
        return doc
    with _lock:
        data = _load()
        data[coll].append(doc)
        _save(data)
    return doc


def update(coll, key, value, changes):
    """Merge `changes` into the first doc where doc[key] == value. Returns the doc or None."""
    if config.USE_MONGO:
        return _mongo()[coll].find_one_and_update({key: value}, {"$set": changes}, projection={"_id": 0}, return_document=True)
    with _lock:
        data = _load()
        for d in data[coll]:
            if d.get(key) == value:
                d.update(changes)
                _save(data)
                return d
    return None


def mark_read(user_id):
    if config.USE_MONGO:
        _mongo().notifications.update_many({"user_id": user_id}, {"$set": {"read": True}})
        return
    with _lock:
        data = _load()
        for n in data["notifications"]:
            if n["user_id"] == user_id:
                n["read"] = True
        _save(data)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.scrypt(password.encode(), salt=salt.encode(), n=2**14, r=8, p=1).hex()
    return f"{salt}${h}"


def check_password(password, stored):
    salt, _ = stored.split("$", 1)
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


def seed_official():
    if config.USE_MONGO:
        _mongo().users.create_index("email", unique=True)
        _mongo().sessions.create_index("token", unique=True)
    with _lock:
        if any(u["email"] == config.OFFICIAL_EMAIL for u in all_("users")):
            return
        insert("users", {"user_id": new_id("U"), "role": "official", "name": config.OFFICIAL_NAME,
                         "email": config.OFFICIAL_EMAIL, "password": hash_password(config.OFFICIAL_PASSWORD),
                         "created_at": now_iso()})
