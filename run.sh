#!/usr/bin/env bash
# One command to run SkyClear: sets up Python, starts MongoDB if Docker is running, loads data, starts the server, opens the browser.
# Usage: ./run.sh            run the app
#        ./run.sh --seed     also fill it with demo accounts and flights (first run)
#        ./run.sh --local    skip MongoDB, use the JSON files in data/
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r backend/requirements.txt
[ -f .env ] || cp .env.example .env

SEED=0; LOCAL=0
for a in "$@"; do [ "$a" = "--seed" ] && SEED=1; [ "$a" = "--local" ] && LOCAL=1; done

if [ "$LOCAL" = "0" ] && docker info >/dev/null 2>&1; then
  docker compose up -d
  export USE_MONGO=1
  echo "Waiting for MongoDB..."
  for i in $(seq 1 30); do .venv/bin/python -c "from pymongo import MongoClient; MongoClient('mongodb://localhost:27017/?directConnection=true', serverSelectionTimeoutMS=1000).admin.command('ping')" 2>/dev/null && break; sleep 2; done
  (cd backend && ../.venv/bin/python load_data.py)
else
  export USE_MONGO=0
  echo "Running without MongoDB (local JSON files). Start Docker and re-run to use MongoDB."
fi

(cd backend && ../.venv/bin/uvicorn main:app --port 8000 --reload) &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for i in $(seq 1 30); do curl -s localhost:8000/health >/dev/null && break; sleep 1; done
[ "$SEED" = "1" ] && .venv/bin/python scripts/seed_demo.py
echo "SkyClear is running at http://localhost:8000"
command -v open >/dev/null && open http://localhost:8000
wait $SERVER
