import json

import config
import explain

DRONE = {"class": "small", "weight_g": 1800}
ZONES = [{"name": "Sample Airport", "zone_type": "airport", "inside": True, "distance_km": 0}]
USED = [{"rule_id": "R-001", "text": "Permission needed.", "source": "s"}]
EXTRA = [{"rule_id": "R-009", "text": "Other rule.", "source": "s"}]


def run(reply, verdict="permission_needed", monkeypatch=None):
    config.USE_LLM = True
    explain._down_until = 0
    explain._chat = lambda prompt: reply if isinstance(reply, str) else (_ for _ in ()).throw(reply)
    try:
        return explain.explain(verdict, ZONES, [], USED, drone=DRONE, extra_rules=EXTRA)
    finally:
        config.USE_LLM = False


def test_unknown_citations_are_dropped_and_deciding_rules_always_cited():
    reply = json.dumps({"summary": "You are inside Sample Airport, so you need permission.", "citations": ["R-009", "R-999"]})
    summary, ids, source = run(reply)
    assert source == "llm" and ids == ["R-001", "R-009"]


def test_contradicting_summary_falls_back_to_template():
    reply = json.dumps({"summary": "You can fly here, no restriction.", "citations": []})
    assert run(reply)[2] == "template"


def test_safe_claim_is_rejected():
    reply = json.dumps({"summary": "This area is safe to fly in.", "citations": []})
    assert run(reply, verdict="can_fly")[2] == "template"


def test_unreachable_llm_uses_template_and_cools_down():
    summary, ids, source = run(ConnectionError("no route"))
    assert source == "template" and ids == ["R-001"] and explain._down_until > 0


def test_bad_json_falls_back():
    assert run("not json")[2] == "template"


def test_llm_off_by_default():
    config.USE_LLM = False
    assert explain.explain("prohibited", ZONES, [], USED, drone=DRONE)[2] == "template"
