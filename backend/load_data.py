"""Load data/*.json into MongoDB, create embeddings and indexes.

OWNER: data/search teammate. Run: python load_data.py   (needs USE_MONGO=1 and a running MongoDB)

TODO:
 1. insert drones, zones (from zones.geojson features), notices, rules, eval_cases
 2. embed rules[].text with Ollama EMBED_MODEL (768 dims) and store in rules.embedding
 3. create indexes: 2dsphere on zones.geometry and notices.area, vector index on rules.embedding,
    text index on rules.text
"""
if __name__ == "__main__":
    raise SystemExit("load_data.py is not implemented yet. See the TODO in this file.")
