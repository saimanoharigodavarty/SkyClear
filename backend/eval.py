"""Run data/eval_cases.json through the pipeline and print the metrics from README.

OWNER: eval teammate. Metrics: verdict accuracy, recall@k, false-safe rate, vector vs hybrid.
Works today against the local store: python eval.py
"""
import json

import config
from fastapi.testclient import TestClient
from main import app


def run():
    cases = json.load(open(config.DATA_DIR / "eval_cases.json", encoding="utf-8"))
    client = TestClient(app)
    correct = false_safe = recall_hits = recall_total = 0
    for c in cases:
        r = client.post("/check", json=c["input"]).json()
        got = r["verdict"]
        correct += got == c["expected_verdict"]
        false_safe += got == "can_fly" and c["expected_verdict"] != "can_fly"
        expected = set(c["expected_rule_ids"])
        if expected:
            recall_total += 1
            recall_hits += expected <= {x["rule_id"] for x in r["citations"]}
        print(f"{c['case_id']}: expected {c['expected_verdict']}, got {got}")
    n = len(cases)
    print(f"verdict accuracy: {correct}/{n}")
    print(f"false-safe: {false_safe}/{n}")
    print(f"rule recall: {recall_hits}/{recall_total}")


if __name__ == "__main__":
    run()
