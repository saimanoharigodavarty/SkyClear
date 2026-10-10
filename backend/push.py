"""Web Push for the guard page: a notification that reaches a phone or laptop even when the page is closed.

The browser needs HTTPS for this (localhost counts as secure, a plain http://192.168... address does not). The server signs each push with its own
VAPID key, generated once and kept in data/.secrets.json (never in code). Only the area name and kind go in the message, never a pilot or flight.
OWNER: Nikhil (stream 2A).
"""
import base64
import json
import os
import threading
import time

import config
import events
import runtime

MAX_SUBSCRIPTIONS = 500
RESEND_S = {"intrusion": 20, "approaching": 20, "test": 0}
_sent = {}
_started = False


def _keys():
    """(private key PEM, public key as the browser wants it). From the environment, else generated once for this install."""
    pem = os.getenv("VAPID_PRIVATE_PEM")
    path = config.DATA_DIR / ".secrets.json"
    if not pem:
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            store = {}
        pem = store.get("VAPID_PRIVATE_PEM")
        if not pem:
            from py_vapid import Vapid
            v = Vapid(); v.generate_keys()
            pem = store["VAPID_PRIVATE_PEM"] = v.private_pem().decode()
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(store), encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    v = Vapid.from_pem(pem.encode())
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return pem, base64.urlsafe_b64encode(pub).decode().rstrip("=")


def public_key():
    return _keys()[1]


def save_subscription(sub, area=None):
    """Store one browser subscription (replacing the same endpoint). Raises ValueError for a bad one."""
    endpoint = (sub or {}).get("endpoint", "")
    keys = (sub or {}).get("keys") or {}
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 600):
        raise ValueError("the push endpoint must be an https address")
    if not (isinstance(keys.get("p256dh"), str) and isinstance(keys.get("auth"), str) and len(keys["p256dh"]) < 200 and len(keys["auth"]) < 100):
        raise ValueError("the subscription keys are missing")
    rows = runtime.all_("push_subscriptions")
    if len(rows) >= MAX_SUBSCRIPTIONS and not any(r["endpoint"] == endpoint for r in rows):
        raise ValueError("too many subscriptions")
    rec = {"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}, "area": (area or "").strip()[:120], "created_at": runtime.now_iso()}
    if any(r["endpoint"] == endpoint for r in rows):
        runtime.update("push_subscriptions", "endpoint", endpoint, rec)
    else:
        runtime.insert("push_subscriptions", rec)
    return rec


def remove_subscription(endpoint):
    if config.USE_MONGO:
        runtime._mongo().push_subscriptions.delete_many({"endpoint": endpoint})
        return
    with runtime._lock:
        data = runtime._load()
        data["push_subscriptions"] = [r for r in data["push_subscriptions"] if r["endpoint"] != endpoint]
        runtime._save(data)


def _send(sub, payload):
    """One push. Returns the HTTP status the push service gave (or 0). Kept apart so tests can replace it."""
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
    pem, _ = _keys()
    try:
        r = webpush(subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]}, data=json.dumps(payload), vapid_private_key=Vapid.from_pem(pem.encode()),
                    vapid_claims={"sub": config.VAPID_SUBJECT}, ttl=120, timeout=10)
        return getattr(r, "status_code", 201)
    except WebPushException as e:
        return getattr(getattr(e, "response", None), "status_code", 0) or 0
    except Exception:
        return 0


def message_for(alert):
    """What the notification says, from the public alert."""
    area = alert.get("area") or "the area"
    if alert["kind"] == "intrusion":
        return {"title": "Drone in " + area, "body": "A drone has entered the protected area.", "kind": "intrusion"}
    if alert["kind"] == "approaching":
        return {"title": "Drone approaching " + area, "body": "A drone is about to enter the protected area.", "kind": "approaching"}
    return {"title": "Test alert: " + area, "body": "This is a test of the guard alerts.", "kind": "test"}


def deliver(alert):
    """Send a push to every subscription that watches this area. Dead subscriptions (404, 410) are removed."""
    k = (alert["kind"], alert.get("area"))
    if time.monotonic() - _sent.get(k, 0) < RESEND_S.get(alert["kind"], 20):
        return 0
    _sent[k] = time.monotonic()
    if len(_sent) > 500:
        _sent.clear()
    msg, n = message_for(alert), 0
    for sub in runtime.all_("push_subscriptions"):
        if sub.get("area") and alert.get("area") and sub["area"].lower() != alert["area"].lower() and alert["kind"] != "test":
            continue
        status = _send(sub, msg)
        if status in (404, 410):
            remove_subscription(sub["endpoint"])
        elif 200 <= status < 300:
            n += 1
    return n


def _on_event(ev):
    from guard_api import alert_for
    alert = alert_for(ev)
    if alert:
        threading.Thread(target=deliver, args=(alert,), daemon=True).start()  # never slow the thread that recorded the breach


def start():
    """Listen to the same events as the guard stream, once."""
    global _started
    if not _started:
        _started = True
        events.subscribe(_on_event)
