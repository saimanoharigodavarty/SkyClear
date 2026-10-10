"""One shared MongoDB handle."""
from pymongo import MongoClient

import config

_client = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=4000)
    return _client[config.MONGO_DB]
