import json

from fastapi.testclient import TestClient

import ask
import config
from main import app

client = TestClient(app)


def post(**kw):
    return client.post("/ask", json=kw)


def test_answers_from_the_rules_and_cites_them():
    r = post(question="Do I need permission to fly near an airport?").json()
    ids = [c["rule_id"] for c in r["citations"]]
    assert "R-001" in ids and r["answered_by"] == "extracted" and "R-001" in r["answer"]
    assert r["disclaimer"] and r["retrieval"]


def test_says_so_when_the_rules_do_not_cover_the_question():
    r = post(question="What is the best pizza restaurant in town?").json()
    assert r["citations"] == [] and r["answered_by"] == "none" and "could not find" in r["answer"]


def test_a_picked_spot_adds_the_decided_verdict_and_its_rules():
    # inside the sample government zone: permission needed (R-005)
    r = post(question="Can I fly here with a small drone?", lat=17.407, lng=78.47, drone_id="small-1800").json()
    assert r["spot"]["verdict"] == "permission_needed" and "Secretariat" in r["spot"]["zones"][0]
    assert "R-005" in [c["rule_id"] for c in r["citations"]]
    assert "permission" in r["answer"].lower()  # the decided verdict is part of the answer
    assert r["answer"].startswith(next(c["text"] for c in r["citations"] if c["rule_id"] == "R-005"))  # the deciding rule leads


def test_llm_answer_is_used_only_when_valid(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    ask._down_until = 0
    good = json.dumps({"answer": "Flying inside an airport zone needs permission from the airport authority [R-001].", "citations": ["R-001", "R-999"]})
    monkeypatch.setattr(ask, "_chat", lambda prompt: good)
    r = post(question="Do I need permission near an airport?").json()
    assert r["answered_by"] == "llm" and "R-999" not in [c["rule_id"] for c in r["citations"]]


def test_llm_answer_that_contradicts_the_decided_verdict_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    ask._down_until = 0
    bad = json.dumps({"answer": "You can fly here, no restriction applies.", "citations": ["R-005"]})
    monkeypatch.setattr(ask, "_chat", lambda prompt: bad)
    r = post(question="Can I fly here?", lat=17.407, lng=78.47, drone_id="small-1800").json()
    assert r["answered_by"] == "extracted" and "can fly here, no restriction" not in r["answer"].lower()


def test_llm_down_falls_back_without_error(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    ask._down_until = 0

    def boom(prompt): raise ConnectionError("down")

    monkeypatch.setattr(ask, "_chat", boom)
    r = post(question="What are the rules for military areas?")
    assert r.status_code == 200 and r.json()["answered_by"] == "extracted"
    ask._down_until = 0


def test_validation():
    assert post(question="hi").status_code == 422


def test_off_topic_question_is_refused_even_with_a_spot_picked():
    r = post(question="What is the best pizza restaurant in town?", lat=17.407, lng=78.47, drone_id="small-1800").json()
    assert r["answered_by"] == "none" and r["spot"] is None and r["citations"] == []


def test_when_only_close_rules_exist_the_answer_says_so():
    r = post(question="Can I fly my drone in heavy rain with a payload?").json()
    if r["answered_by"] == "extracted":
        assert r["answer"].startswith("These are the closest rules we hold")


def test_a_general_answer_may_say_prohibited_but_never_safe(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    ask._down_until = 0
    monkeypatch.setattr(ask, "_chat", lambda p: json.dumps({"answer": "Flying over military areas is prohibited for all drones [R-002].", "citations": ["R-002"]}))
    assert post(question="Can I fly over a military area?").json()["answered_by"] == "llm"
    ask._cache.clear()  # the first answer was kept for repeat questions
    monkeypatch.setattr(ask, "_chat", lambda p: json.dumps({"answer": "Military areas are safe to fly over [R-002].", "citations": ["R-002"]}))
    assert post(question="Can I fly over a military area?").json()["answered_by"] == "extracted"


def test_a_quick_answer_does_not_wait_for_the_model(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    ask._down_until = 0
    monkeypatch.setattr(ask, "_chat", lambda p: (_ for _ in ()).throw(AssertionError("the model must not be called")))
    r = post(question="Can I fly over a military area?", explain=False).json()
    assert r["answered_by"] == "extracted" and r["citations"]


def test_metrics_are_exposed_in_prometheus_format():
    text = TestClient(app).get("/metrics").text
    assert "skyclear_http_requests_total" in text and "skyclear_simulated_drones" in text


def test_an_unreachable_model_laptop_fails_in_seconds_not_a_minute():
    t = config.ollama_timeout()
    assert t.connect <= 5 and t.read >= 20  # a switched-off laptop is given up on quickly, a slow model still gets its time
