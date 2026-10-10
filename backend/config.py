"""All settings in one place. Override with environment variables (see .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"

USE_MONGO = os.getenv("USE_MONGO", "0") == "1"
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "skyclear")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
USE_LLM = os.getenv("USE_LLM", "0") == "1"

# Area our data covers: (min_lng, min_lat, max_lng, max_lat). Outside it the verdict is cannot_determine.
COVERAGE_BBOX = (77.40, 12.80, 77.80, 13.20)
NEARBY_KM = 5.0
DATA_LAST_UPDATED = "2026-10-10"
DISCLAIMER = "Decision support only, not legal permission."
