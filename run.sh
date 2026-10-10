#!/usr/bin/env bash
# One command to run SkyClear: sets up Python, starts MongoDB and the mail catcher if Docker is running,
# loads the data, creates the first admin, starts the server, shows your logins and opens the browser.
#   ./run.sh --demo     first time: also create one officer per office and a verified demo pilot with flights
#   ./run.sh            run the app (asks for an admin email the first time)
#   ./run.sh --local    skip Docker, use the JSON files in data/ (one-time codes are printed in this terminal)
# (--seed is the same as --demo.)
set -e
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements.txt
[ -f .env ] || cp .env.example .env

SEED=0; LOCAL=0
for a in "$@"; do [ "$a" = "--seed" ] || [ "$a" = "--demo" ] && SEED=1; [ "$a" = "--local" ] && LOCAL=1; done

# Already running? Just show how to use it.
if curl -s -m 2 localhost:8000/health >/dev/null 2>&1; then
  echo "SkyClear is already running at http://localhost:8000"
  (cd backend && ../.venv/bin/python manage.py logins 2>/dev/null) || true
  command -v open >/dev/null && open http://localhost:8000/guide.html
  exit 0
fi

if [ "$LOCAL" = "0" ] && docker info >/dev/null 2>&1; then
  docker compose up -d
  export USE_MONGO=1 OTP_PROVIDER=smtp
  echo "Waiting for MongoDB..."
  for i in $(seq 1 30); do .venv/bin/python -c "from pymongo import MongoClient; MongoClient('mongodb://localhost:27017/?directConnection=true', serverSelectionTimeoutMS=1000).admin.command('ping')" 2>/dev/null && break; sleep 2; done
  (cd backend && ../.venv/bin/python load_data.py)
else
  export USE_MONGO=0 OTP_PROVIDER=console
  echo "Running without Docker (local JSON files). One-time codes are printed in this terminal."
fi

if ! (cd backend && ../.venv/bin/python manage.py has-admin); then
  echo
  echo "No administrator yet. Create one."
  read -r -p "Admin email: " ADMIN_EMAIL
  (cd backend && ../.venv/bin/python manage.py create-admin --email "$ADMIN_EMAIL" --name "Administrator" --generate)
  echo
fi

(cd backend && ../.venv/bin/uvicorn main:app --port 8000 --reload) &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for i in $(seq 1 30); do curl -s localhost:8000/health >/dev/null && break; sleep 1; done
if [ "$SEED" = "1" ]; then
  (cd backend && ../.venv/bin/python manage.py seed-officers && ../.venv/bin/python manage.py seed-demo) || true
fi
echo
(cd backend && ../.venv/bin/python manage.py logins) || true
echo "SkyClear is running at http://localhost:8000   (guided tour: http://localhost:8000/guide.html)"
[ "$LOCAL" = "0" ] && echo "Mail catcher for one-time codes: http://localhost:8025"
command -v open >/dev/null && open http://localhost:8000/guide.html
wait $SERVER
