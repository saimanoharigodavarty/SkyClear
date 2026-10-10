"""Run data/eval_cases.json through the pipeline and print the metrics promised in the README.

Run from backend/:  python eval.py          (set USE_MONGO=1 to include the retrieval comparison)
  - verdict accuracy, false-safe rate (said can_fly when it should not), rule recall in citations
  - retrieval recall@k for text, vector and hybrid search over rule passages (MongoDB only)
Numbers in the presentation must come from this output.
"""
import json
import sys

import config
from fastapi.testclient import TestClient
from main import app, store


def run_pipeline(cases):
    client = TestClient(app)
    correct = false_safe = recall_hits = recall_total = 0
    rows = []
    for c in cases:
        r = client.post("/check", json=c["input"]).json()
        got = r["verdict"]
        ok = got == c["expected_verdict"]
        correct += ok
        false_safe += got == "can_fly" and c["expected_verdict"] != "can_fly"
        expected = set(c["expected_rule_ids"])
        if expected:
            recall_total += 1
            recall_hits += expected <= {x["rule_id"] for x in r["citations"]}
        rows.append((c["case_id"], c["expected_verdict"], got, ok))
    for cid, exp, got, ok in rows:
        print(f"  {cid}: expected {exp:<18} got {got:<18} {'ok' if ok else 'WRONG'}")
    n = len(cases)
    print(f"\nverdict accuracy : {correct}/{n} = {correct / n:.0%}")
    print(f"false-safe rate  : {false_safe}/{n}")
    print(f"citation recall  : {recall_hits}/{recall_total}")
    return correct == n and false_safe == 0


def run_retrieval(cases, ks=(1, 3)):
    if not hasattr(store, "search_rules"):
        print("\nretrieval comparison needs MongoDB (USE_MONGO=1)")
        return
    queried = [c for c in cases if c.get("query") and c["expected_rule_ids"]]
    print(f"\nretrieval recall over {len(queried)} questions (did an expected rule appear in the top k?)")
    vector_ok = bool(store.search_rules(queried[0]["query"], k=1, mode="vector"))
    for mode in ("text", "vector", "hybrid"):
        results = {}
        for c in queried:
            ids = [r["rule_id"] for r in store.search_rules(c["query"], k=max(ks), mode=mode)]
            for k in ks:
                results[k] = results.get(k, 0) + bool(set(c["expected_rule_ids"]) & set(ids[:k]))
        if mode == "vector" and not vector_ok:
            print(f"  {mode:<7}: not available (Ollama unreachable or vector index not built)")
            continue
        note = "  (keyword only, vector unavailable)" if mode == "hybrid" and not vector_ok else ""
        print(f"  {mode:<7}: " + "  ".join(f"recall@{k} {results[k]}/{len(queried)}" for k in ks) + note)


if __name__ == "__main__":
    cases = json.load(open(config.DATA_DIR / "eval_cases.json", encoding="utf-8"))
    print(f"store: {'MongoDB' if config.USE_MONGO else 'local JSON'}, {len(cases)} cases")
    passed = run_pipeline(cases)
    run_retrieval(cases)
    sys.exit(0 if passed else 1)
