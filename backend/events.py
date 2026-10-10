"""Live events for the browsers.

With MongoDB, one change stream per collection watches notifications, breaches, notices and flights. Anything that changes a document,
from any server process or from a script, becomes an event, so an alert shows up on a pilot's screen the moment the document is written
(and only after its transaction commits). Without MongoDB (the JSON file store) the same events are published from runtime.py.
OWNER: Nikhil (stream 2A).
"""
import queue
import threading
import time

import config

WATCHED = ["notifications", "breaches", "notices", "flights"]
_subs = []
_lock = threading.Lock()
_started = False
status = {"mode": "in_process", "watching": [], "events": 0, "last_event": None, "restarts": 0}


def subscribe(push):
    """`push(event)` is called from any thread for every event. Returns it so it can be unsubscribed."""
    with _lock:
        _subs.append(push)
    return push


def subscribe_queue():
    q = queue.Queue(maxsize=1000)

    def push(ev):
        try:
            q.put_nowait(ev)
        except queue.Full:
            pass

    subscribe(push)
    return q, push


def unsubscribe(push):
    with _lock:
        if push in _subs:
            _subs.remove(push)


def publish(coll, op, doc):
    if coll not in WATCHED:
        return
    status["events"] += 1
    status["last_event"] = f"{coll} {op}"
    ev = {"coll": coll, "op": op, "doc": {k: v for k, v in doc.items() if k != "_id"}}
    with _lock:
        targets = list(_subs)
    for push in targets:
        try:
            push(ev)
        except Exception:
            pass


def _watch(coll):
    """Follow one collection's change stream forever. If the stream drops, reconnect and carry on."""
    from db import get_db
    while True:
        try:
            with get_db()[coll].watch(full_document="updateLookup", max_await_time_ms=500) as stream:
                with _lock:
                    if coll not in status["watching"]:
                        status["watching"].append(coll)
                while stream.alive:
                    change = stream.try_next()
                    if change is None:
                        continue
                    if change["operationType"] in ("insert", "update", "replace") and change.get("fullDocument"):
                        publish(coll, "insert" if change["operationType"] == "insert" else "update", change["fullDocument"])
        except Exception as e:
            status["restarts"] += 1
            print(f"[events] change stream on {coll} stopped ({type(e).__name__}), reconnecting")
            with _lock:
                if coll in status["watching"]:
                    status["watching"].remove(coll)
            time.sleep(2)


def start_watchers():
    """Start the change stream watchers (MongoDB only, once per process)."""
    global _started
    if not config.USE_MONGO or _started:
        return
    _started = True
    status["mode"] = "mongodb_change_streams"
    for coll in WATCHED:
        threading.Thread(target=_watch, args=(coll,), daemon=True, name=f"watch-{coll}").start()
