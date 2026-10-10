"""SkyClear backend package."""
from pathlib import Path
import sys

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
import db
import geo
import pipeline
import runtime
try:
    import guard_api
    sys.modules.setdefault("backend.guard_api", guard_api)
except Exception:
    pass

sys.modules.setdefault("backend.config", config)
sys.modules.setdefault("backend.db", db)
sys.modules.setdefault("backend.geo", geo)
sys.modules.setdefault("backend.pipeline", pipeline)
sys.modules.setdefault("backend.runtime", runtime)
