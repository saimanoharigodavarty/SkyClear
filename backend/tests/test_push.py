"""Web Push for the guard page: keys, subscriptions, and what is sent when an alert happens. The push service itself is replaced by a recorder."""
from fastapi.testclient import TestClient

import push
import runtime
from main import app
from tests.test_bridge import auth, official

client = TestClient(app)
SUB = {"endpoint": "https://push.example.test/abc123", "keys": {"p256dh": "BPubKeyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "auth": "authsecretxxxx"}}


def clean():
    for r in runtime.all_("push_subscriptions"):
        push.remove_subscription(r["endpoint"])
    push._sent.clear()


def test_the_server_key_is_stable_public_and_not_in_the_repo_files():
    a = client.get("/guard/push-key").json()["key"]
    assert a == client.get("/guard/push-key").json()["key"] and len(a) > 80
    import config
    pem = (config.DATA_DIR / ".secrets.json").read_text()
    assert "VAPID_PRIVATE_PEM" in pem and a not in pem  # the private key stays in the git-ignored secrets file, only the public half is served


def test_a_subscription_is_checked_stored_once_and_removable():
    clean()
    assert client.post("/guard/push-subscribe", json={"endpoint": "http://insecure.test/x", "keys": SUB["keys"]}).status_code == 422
    assert client.post("/guard/push-subscribe", json={"endpoint": SUB["endpoint"], "keys": {}}).status_code == 422
    assert client.post("/guard/push-subscribe", json={**SUB, "area": "Campus"}).status_code == 200
    assert client.post("/guard/push-subscribe", json={**SUB, "area": "Campus"}).status_code == 200
    assert len(runtime.all_("push_subscriptions")) == 1
    assert client.post("/guard/push-unsubscribe", json={**SUB}).status_code == 200
    assert runtime.all_("push_subscriptions") == []


def test_an_alert_is_pushed_to_matching_subscriptions_with_no_identities(monkeypatch):
    clean()
    sent = []
    monkeypatch.setattr(push, "_send", lambda sub, payload: sent.append((sub["endpoint"], payload)) or 201)
    push.save_subscription(SUB, "Campus")
    push.save_subscription({**SUB, "endpoint": "https://push.example.test/other"}, "Another area")
    push.save_subscription({**SUB, "endpoint": "https://push.example.test/all"}, "")
    n = push.deliver({"area": "Campus", "kind": "intrusion", "ts": "t"})
    assert n == 2 and {e for e, _ in sent} == {SUB["endpoint"], "https://push.example.test/all"}
    body = sent[0][1]
    assert body["title"] == "Drone in Campus" and set(body) == {"title", "body", "kind"}
    assert push.deliver({"area": "Campus", "kind": "intrusion", "ts": "t"}) == 0  # not again within 20 seconds
    clean()


def test_a_dead_subscription_is_removed(monkeypatch):
    clean()
    monkeypatch.setattr(push, "_send", lambda sub, payload: 410)
    push.save_subscription(SUB, "")
    push.deliver({"area": "Campus", "kind": "test", "ts": "t"})
    assert runtime.all_("push_subscriptions") == []


def test_the_official_test_siren_also_sends_a_push(monkeypatch):
    import time
    clean()
    sent = []
    monkeypatch.setattr(push, "_send", lambda sub, payload: sent.append(payload) or 201)
    push.start()
    push.save_subscription(SUB, "")
    assert client.post("/guard/test?area=Campus", headers=auth(official())).status_code == 200
    end = time.time() + 3
    while not sent and time.time() < end:
        time.sleep(0.1)
    assert sent and sent[0]["kind"] == "test" and "Campus" in sent[0]["title"]
    clean()


def test_the_real_sender_signs_and_encrypts_a_push(monkeypatch):
    """Runs the real pywebpush code against a throwaway local server that plays the push service, with a real subscriber key."""
    import base64
    import http.server
    import os
    import threading
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got["auth"] = self.headers.get("Authorization", "")
            got["enc"] = self.headers.get("Content-Encoding")
            got["len"] = len(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            self.send_response(201); self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    sub = {"endpoint": f"http://127.0.0.1:{srv.server_port}/push", "keys": {"p256dh": b64(pub), "auth": b64(os.urandom(16))}}
    try:
        status = push._send(sub, {"title": "t", "body": "b", "kind": "test"})
    finally:
        srv.shutdown()
    assert status == 201 and got["auth"].startswith("vapid ") and got["enc"] == "aes128gcm" and got["len"] > 20
