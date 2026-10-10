import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("USE_MONGO", "0")  # tests default to local JSON; run USE_MONGO=1 pytest backend for MongoDB
os.environ.setdefault("RATE_LIMITS", "0")
os.environ["USE_LLM"] = "0"          # tests never call a real model, even when .env turns it on
os.environ["OTP_DEV_ECHO"] = "1"      # tests read the code from the response
os.environ["OTP_PROVIDER"] = "console"
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
        if not collection_name.startswith("system."):  # MongoDB's own bookkeeping (system.views holds the time-series telemetry view)
            test_db.drop_collection(collection_name)
    import load_data
    # The small Atlas tier cannot duplicate production Search indexes. Search pipelines have
    # focused unit tests and direct production checks; this database covers CRUD and geo queries.
    load_data.load(verbose=False, search_indexes=(), embeddings=False)

# Test accounts: one admin and one officer per authority, created the same way an operator would.
import manage  # noqa: E402
import routing  # noqa: E402
from tests.support import ADMIN_EMAIL, PASSWORD, officer_email  # noqa: E402

routing.setup()
manage.create_user(ADMIN_EMAIL, "Test Admin", "official", PASSWORD)
for _a in routing.all_authorities():
    manage.create_user(officer_email(_a["authority_id"]), _a["name"], "official", PASSWORD, authority_id=_a["authority_id"])

