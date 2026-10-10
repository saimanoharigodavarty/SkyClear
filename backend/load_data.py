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

RULES_SEARCH_INDEX = "rules_search"
ZONES_SEARCH_INDEX = "zones_autocomplete"
RULES_SEARCH_DEFINITION = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "text": {"type": "string"},
            "zone_type": {"type": "token"},
            "drone_classes": {"type": "token"},
        },
    }
}
ZONES_SEARCH_DEFINITION = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "name": {
                "type": "autocomplete",
                "tokenization": "edgeGram",
                "minGrams": 2,
                "maxGrams": 15,
                "foldDiacritics": True,
            }
        },
    }
}


ZONE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["zone_id", "name", "zone_type", "geometry", "rule_ids", "source"],
        "properties": {
            "zone_id": {"bsonType": "string", "minLength": 1},
            "name": {"bsonType": "string", "minLength": 1},
            "zone_type": {"bsonType": "string", "minLength": 1},
            "geometry": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "properties": {
                    "type": {"enum": ["Polygon", "MultiPolygon"]},
                    "coordinates": {"bsonType": "array", "minItems": 1},
                },
            },
            "rule_ids": {"bsonType": "array", "items": {"bsonType": "string"}},
            "source": {"bsonType": "string", "minLength": 1},
        },
    }
}


def ensure_zones_collection(db):
    """Create zones or enforce its GeoJSON and attribution contract on future writes."""
    options = {"validator": ZONE_VALIDATOR, "validationLevel": "strict", "validationAction": "error"}
    if "zones" in db.list_collection_names():
        info = db.command("listCollections", filter={"name": "zones"})["cursor"]["firstBatch"][0]
        current = info.get("options", {})
        if any(current.get(key) != value for key, value in options.items()):
            db.command("collMod", "zones", **options)
    else:
        db.create_collection("zones", **options)


def ensure_zone_indexes(db):
    """Create indexes used by point, viewport, type and identity queries."""
    db.zones.create_index([("geometry", "2dsphere")])
    db.zones.create_index("zone_id", unique=True)
    db.zones.create_index("zone_type")


def ensure_search_index(collection, name, definition, log):
    """Create or update one MongoDB Search index and wait briefly for it to become queryable."""
    current = next((i for i in collection.list_search_indexes() if i["name"] == name), None)
    if current:
        collection.update_search_index(name, definition)
    else:
        from pymongo.operations import SearchIndexModel
        collection.create_search_index(SearchIndexModel(name=name, definition=definition))
    for _ in range(30):
        index = next((i for i in collection.list_search_indexes() if i["name"] == name), None)
        if index and index.get("queryable") and index.get("status") == "READY":
            log(f"search index ready: {name}")
            return True
        time.sleep(2)
    log(f"search index still building: {name}")
    return False


def _read(name):
    with open(config.DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def load(verbose=True, search_indexes=("rules", "zones"), embeddings=True):
    """Load seed data; tests may limit external Search indexes to fit small Atlas tiers."""
    db = get_db()
    log = print if verbose else (lambda *a, **k: None)
    ensure_zones_collection(db)

    # drones: seed catalog has no owner_id (pilot drones do)
    db.drones.delete_many({"owner_id": {"$exists": False}})
    db.drones.insert_many([{**d, "origin": "seed"} for d in _read("drones.json")])
    db.drones.create_index("drone_id", unique=True)

    # zones
    db.zones.delete_many({})
    db.zones.insert_many([{**f["properties"], "geometry": f["geometry"]} for f in _read("zones.geojson")["features"]])
    ensure_zone_indexes(db)

    # notices: replace seed notices only
    db.notices.delete_many({"origin": "seed"})
    db.notices.insert_many([{**n, "origin": "seed", "status": "active"} for n in _read("notices.json")])
    db.notices.create_index([("area", "2dsphere")])

    # rules, with embeddings when Ollama is available
    rules = _read("rules.json")
    vectors = embed([r["text"] for r in rules], "document") if embeddings else None
    if vectors:
        for r, v in zip(rules, vectors):
            r["embedding"] = v
    db.rules.delete_many({})
    db.rules.insert_many(rules)
    db.rules.create_index([("text", "text")])
    db.rules.create_index([("zone_type", 1), ("drone_classes", 1)])

    if "rules" in search_indexes:
        ensure_search_index(db.rules, RULES_SEARCH_INDEX, RULES_SEARCH_DEFINITION, log)
    if "zones" in search_indexes:
        ensure_search_index(db.zones, ZONES_SEARCH_INDEX, ZONES_SEARCH_DEFINITION, log)

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
