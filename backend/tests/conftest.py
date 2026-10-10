import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("USE_MONGO", "0")  # tests default to local JSON; run USE_MONGO=1 pytest backend for MongoDB
os.environ.setdefault("RATE_LIMITS", "0")
os.environ["RUNTIME_PATH"] = str(Path(tempfile.mkdtemp()) / "runtime.json")

if os.environ.get("USE_MONGO") == "1":
    # Mongo run: use a throwaway database so tests never touch real data.
    os.environ["MONGO_DB"] = "skyclear_test"
    import config
    from db import get_db
    get_db().client.drop_database("skyclear_test")
    import load_data
    load_data.load(verbose=False)
