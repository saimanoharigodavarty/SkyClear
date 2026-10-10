"""All settings in one place. Override with environment variables (see .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Read KEY=VALUE lines from <repo>/.env into the environment (real env vars win)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"

USE_MONGO = os.getenv("USE_MONGO", "0") == "1"
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/?directConnection=true")
MONGO_DB = os.getenv("MONGO_DB", "skyclear")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
USE_LLM = os.getenv("USE_LLM", "0") == "1"

# Area our data covers: (min_lng, min_lat, max_lng, max_lat). Outside it the verdict is cannot_determine.
COVERAGE_BBOX = (68.0, 6.5, 97.5, 37.0)  # India; airport zones come from OurAirports
NEARBY_KM = 5.0
DATA_LAST_UPDATED = "2026-10-10"
DISCLAIMER = "Decision support only, not legal permission."

# Runtime data (accounts, flights, official notices, alerts). JSON file for the prototype.
RUNTIME_PATH = Path(os.getenv("RUNTIME_PATH", str(DATA_DIR / "runtime.json")))
# Demo official account, seeded on startup. Change for any shared deployment.
OFFICIAL_EMAIL = os.getenv("OFFICIAL_EMAIL", "official@skyclear.demo")
OFFICIAL_PASSWORD = os.getenv("OFFICIAL_PASSWORD", "skyclear-demo")
OFFICIAL_NAME = os.getenv("OFFICIAL_NAME", "Hyderabad Airspace Desk")
