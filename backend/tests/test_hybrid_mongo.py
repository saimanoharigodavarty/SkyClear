"""Vector, keyword and hybrid ($rankFusion) search on MongoDB. Run with: USE_MONGO=1 python -m pytest backend

Stand-in embeddings are used (words hashed into 768 numbers), so this checks the MongoDB pipeline without needing Ollama.
"""
import hashlib
import math
import os
import re

import pytest
from pymongo.errors import OperationFailure

pytestmark = pytest.mark.skipif(os.environ.get("USE_MONGO") != "1", reason="needs MongoDB")


def fake_embed(texts, kind="document"):
    out = []
    for t in texts:
        v = [0.0] * 768
        for w in re.findall(r"[a-z]+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 768] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


@pytest.fixture(scope="module")
def store():
    import embeddings
    import load_data
    import search
    mp = pytest.MonkeyPatch()
    for mod in (embeddings, load_data, search):
        mp.setattr(mod, "embed", fake_embed)
    try:
        # The shared small tier cannot duplicate production Search indexes. Build only the
        # vector index here; keyword retrieval uses the built-in text-index fallback.
        load_data.load(verbose=False, search_indexes=())
    except OperationFailure as error:
        if "maximum number of FTS indexes" in str(error):
            pytest.skip("Atlas tier cannot create duplicate Search/vector indexes in skyclear_test")
        raise
    yield search.MongoStore()
    mp.undo()


QUESTION = "do I need permission to fly near an airport"


@pytest.mark.parametrize("mode", ["text", "vector", "hybrid"])
def test_each_mode_finds_the_airport_rule(store, mode):
    found = store.search_rules(QUESTION, k=3, mode=mode)
    assert found and "R-001" in [r["rule_id"] for r in found], mode
    assert all("embedding" not in r and "_id" not in r for r in found)


def test_hybrid_is_ranked_by_mongodb(store):
    found = store.search_rules(QUESTION, k=3, mode="hybrid")
    assert 0 < len(found) <= 3 and "R-001" in [r["rule_id"] for r in found]  # the real ranking quality comes from the Ollama embeddings


def test_hybrid_falls_back_to_keyword_when_there_are_no_embeddings(store, monkeypatch):
    import search
    monkeypatch.setattr(search, "embed", lambda texts, kind="document": None)  # Ollama unreachable
    found = store.search_rules(QUESTION, k=3, mode="hybrid")
    assert "R-001" in [r["rule_id"] for r in found]


def test_ask_uses_the_search(store):
    from fastapi.testclient import TestClient
    from main import app
    r = TestClient(app).post("/ask", json={"question": QUESTION}).json()
    assert "R-001" in [c["rule_id"] for c in r["citations"]]
