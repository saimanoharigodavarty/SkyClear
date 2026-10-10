"""Load data/*.json into MongoDB, embed the rules and create indexes.

Run (MongoDB must be running: docker compose up -d):  python backend/load_data.py
Safe to re-run. Seed data is replaced. Accounts, flights and officially published notices are kept.
Embeddings need Ollama with the embedding model pulled. Without it the vector index is skipped and
search falls back to keyword search.
"""
import json
import time

import config
from db import get_db
from embeddings import DIMENSIONS, embed


def _read(name):
    with open(config.DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def load(verbose=True):
    db = get_db()
    log = print if verbose else (lambda *a, **k: None)

    # drones: seed catalog has no owner_id (pilot drones do)
    db.drones.delete_many({"owner_id": {"$exists": False}})
    db.drones.insert_many([{**d, "origin": "seed"} for d in _read("drones.json")])
    db.drones.create_index("drone_id", unique=True)

    # zones
    db.zones.delete_many({})
    db.zones.insert_many([{**f["properties"], "geometry": f["geometry"]} for f in _read("zones.geojson")["features"]])
    db.zones.create_index([("geometry", "2dsphere")])
    db.zones.create_index("zone_id", unique=True)

    # notices: replace seed notices only
    db.notices.delete_many({"origin": "seed"})
    db.notices.insert_many([{**n, "origin": "seed", "status": "active"} for n in _read("notices.json")])
    db.notices.create_index([("area", "2dsphere")])

    # rules, with embeddings when Ollama is available
    rules = _read("rules.json")
    vectors = embed([r["text"] for r in rules], "document")
    if vectors:
        for r, v in zip(rules, vectors):
            r["embedding"] = v
    db.rules.delete_many({})
    db.rules.insert_many(rules)
    db.rules.create_index([("text", "text")])
    db.rules.create_index([("zone_type", 1), ("drone_classes", 1)])

    _search_index(db, log)
    if vectors:
        _vector_index(db, log)
    else:
        log("No embeddings: vector index skipped. Install Ollama and pull the embedding model, then re-run.")

    db.eval_cases.delete_many({})
    db.eval_cases.insert_many(_read("eval_cases.json"))
    log(f"loaded: {db.zones.count_documents({})} zones, {db.rules.count_documents({})} rules, "
        f"{db.drones.count_documents({'origin': 'seed'})} drones, {db.notices.count_documents({'origin': 'seed'})} sample notices, "
        f"{db.eval_cases.count_documents({})} eval cases")
    return db


def _search_index(db, log):
    """Atlas Search (Lucene) index on the rule text. The English analyzer drops filler words (is, in, the) and handles
    word forms, so an off-topic question matches nothing and Ask can say it has no answer."""
    from pymongo.operations import SearchIndexModel
    definition = {"mappings": {"dynamic": False, "fields": {"text": {"type": "string", "analyzer": "lucene.english"}, "zone_type": {"type": "string"}}}}
    if any(i["name"] == "rules_search" for i in db.rules.list_search_indexes()):
        db.rules.update_search_index("rules_search", definition)
        time.sleep(2)
    else:
        db.rules.create_search_index(SearchIndexModel(name="rules_search", definition=definition))
    for _ in range(40):
        idx = next((i for i in db.rules.list_search_indexes() if i["name"] == "rules_search"), None)
        if idx and idx.get("queryable") and idx.get("status") == "READY":
            log("search index ready")
            return
        time.sleep(1)
    log("search index still building, it will be ready shortly")


def _vector_index(db, log):
    from pymongo.operations import SearchIndexModel
    if any(i["name"] == "rules_vector" for i in db.rules.list_search_indexes()):
        db.rules.drop_search_index("rules_vector")
        time.sleep(2)
    db.rules.create_search_index(SearchIndexModel(name="rules_vector", type="vectorSearch", definition={"fields": [
        {"type": "vector", "path": "embedding", "numDimensions": DIMENSIONS, "similarity": "cosine"},
        {"type": "filter", "path": "zone_type"}, {"type": "filter", "path": "drone_classes"}]}))
    for _ in range(30):  # index builds in the background
        idx = next((i for i in db.rules.list_search_indexes() if i["name"] == "rules_vector"), None)
        if idx and idx.get("queryable"):
            log("vector index ready")
            return
        time.sleep(2)
    log("vector index still building, it will be ready shortly")


if __name__ == "__main__":
    load()
