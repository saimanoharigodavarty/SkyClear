"""All settings in one place. Override with environment variables (see .env.example)."""
import json
import os
import secrets
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


def _secret(name):
    """Secrets are never written in code. Use the environment, or one generated for this install and kept in data/.secrets.json (git-ignored)."""
    if os.getenv(name):
        return os.environ[name]
    path = DATA_DIR / ".secrets.json"
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        store = {}
    if name not in store:
        store[name] = secrets.token_hex(32)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return store[name]
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"

USE_MONGO = os.getenv("USE_MONGO", "0") == "1"
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/?directConnection=true")
MONGO_DB = os.getenv("MONGO_DB", "skyclear")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
USE_LLM = os.getenv("USE_LLM", "0") == "1"
MAPPLS_API_KEY = os.getenv("MAPPLS_API_KEY", "")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "60"))   # a small model on a laptop CPU needs a few seconds, the first call also loads it
LLM_KEEP_ALIVE = os.getenv("LLM_KEEP_ALIVE", "30m")      # keep the model loaded on the Ollama laptop between questions

# Area our data covers: (min_lng, min_lat, max_lng, max_lat). Outside it the verdict is cannot_determine.
def _region():
    with open(DATA_DIR / "region.json", encoding="utf-8") as f:
        return json.load(f)


REGION = _region()
COVERAGE_BBOX = tuple(REGION["coverage_bbox"])  # outside it the verdict is cannot_determine
NEARBY_KM = 5.0
DATA_LAST_UPDATED = "2026-10-10"
DISCLAIMER = "Decision support only, not legal permission."

# Runtime data (accounts, flights, official notices, alerts). JSON file for the prototype.
RUNTIME_PATH = Path(os.getenv("RUNTIME_PATH", str(DATA_DIR / "runtime.json")))

# Permits and verification
PERMIT_SECRET = _secret("PERMIT_SECRET")
REQUIRE_VERIFICATION = os.getenv("REQUIRE_VERIFICATION", "1") == "1"   # verified pilot and drone before a permission request
PERMIT_RADIUS_KM = 0.3
PREFLIGHT_VALID_MIN = 15
PREFLIGHT_EARLY_MIN = 15      # preflight opens this long before the flight window
UPLOAD_MAX_BYTES = 5 * 1024 * 1024

# Authentication
JWT_SECRET = _secret("JWT_SECRET")
ACCESS_TTL_MIN = int(os.getenv("ACCESS_TTL_MIN", "15"))
REFRESH_TTL_DAYS = int(os.getenv("REFRESH_TTL_DAYS", "7"))
OTP_TTL_MIN = 5
OTP_MAX_ATTEMPTS = 5
OTP_DEV_ECHO = os.getenv("OTP_DEV_ECHO", "0") == "1"   # tests only: return the code in the API response. Never on a real deployment
OTP_CHANNEL = os.getenv("OTP_CHANNEL", "email")        # email or sms: where one-time codes are sent
OTP_PROVIDER = os.getenv("OTP_PROVIDER", "console")    # console (server log), smtp (email), twilio (sms)
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "SkyClear <no-reply@skyclear.local>")
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
REQUIRE_OFFICIAL_MFA = os.getenv("REQUIRE_OFFICIAL_MFA", "0") == "1"
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
RATE_LIMITS = os.getenv("RATE_LIMITS", "1") == "1"

# Drone weight classes come from data/region.json so the API and the UI use one source.
DRONE_CLASSES = REGION["drone_classes"]

# Ask SkyClear answers only when the question is about the rules: a keyword match, or a vector similarity at least this high.
# Calibrated on a few real questions (related 0.80 to 0.91, unrelated 0.71 to 0.76). The eval should refine it.
ASK_MIN_SCORE = float(os.getenv("ASK_MIN_SCORE", "0.78"))

# Google Authentication
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()

