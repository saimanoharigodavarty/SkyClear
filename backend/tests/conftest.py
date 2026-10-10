import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("USE_MONGO", "0")  # tests default to local JSON; run USE_MONGO=1 pytest backend for MongoDB
os.environ["RUNTIME_PATH"] = str(Path(tempfile.mkdtemp()) / "runtime.json")

if os.environ.get("USE_MONGO") == "1":
    # Mongo run: use a dedicated database so tests never touch application data. Recreate its
    # collections without dropping the database; the least-privilege Atlas user has no dropDatabase
    # or collMod, but can drop collections in this test-only database.
    os.environ["MONGO_DB"] = "skyclear_test"
    import config
    from db import get_db
    test_db = get_db()
    for collection_name in test_db.list_collection_names():
        test_db.drop_collection(collection_name)
    import load_data
    # The small Atlas tier cannot duplicate production Search indexes. Search pipelines have
    # focused unit tests and direct production checks; this database covers CRUD and geo queries.
    load_data.load(verbose=False, search_indexes=(), embeddings=False)
