# SkyClear: explainable drone flight check

Track 2: RAG Engine (MongoDB hackathon)

Product spec, accounts, notifications and the loophole list: [PRODUCT.md](PRODUCT.md). Target architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Permits, verification and the official map: [docs/PERMITS_AND_VERIFICATION.md](docs/PERMITS_AND_VERIFICATION.md). Simulation: [docs/SIMULATION.md](docs/SIMULATION.md). Who builds what: [TEAM.md](TEAM.md). Interfaces between streams: [docs/CONTRACTS.md](docs/CONTRACTS.md).

## Problem statement

Before every flight, a drone pilot must answer one question: "Can I fly here, today, with this drone?"

The answer depends on several things at once:
- the drone's weight class
- nearby airports and sensitive areas
- the date and time of the flight
- temporary restrictions such as VIP movements, rallies and events
- the current drone regulations

This information is spread across regulation PDFs, zone maps and local notices. Existing tools mostly show a zone color without explaining which rule applies to the pilot's drone, and they do not combine rules with time-based notices. A wrong decision can mean fines, a confiscated drone or a safety incident.

## Idea

A web app where a pilot:
1. clicks a location on a map,
2. chooses a drone model, date and time,
3. gets one of four verdicts:
   - Can fly (no restriction found in our data)
   - Permission needed
   - Prohibited
   - Can't determine (with who to ask)

The app shows the relevant zones on the map and the exact rule passages behind the verdict, so the pilot can check the source. It never says "safe". It says "no restriction found in our data".

SkyClear is a pre-flight planning tool. It does not control or connect to a drone in this version.

## How it works

```
Map click + drone + date/time
   -> 1. Geo search: zones and active notices near the point (MongoDB geospatial)
   -> 2. Rule search: relevant rule passages (MongoDB vector + keyword search, metadata filters)
   -> 3. Rule engine: Python code decides the verdict
   -> 4. LLM (Ollama): explains the verdict and picks citations from the retrieved passages
   -> Response: verdict, zones for the map, citations, "data last updated"
```

Key design choice: code decides the verdict, the LLM only explains and cites. Citation IDs returned by the LLM are checked against the retrieved passages, and unknown IDs are dropped.

## Data (MongoDB collections)

| Collection | Contents |
|---|---|
| rules | rule_id, text, embedding, zone_type, drone_classes, effective_from, source |
| zones | zone_id, name, zone_type, geometry (GeoJSON), rule_ids, source |
| drones | drone_id, name, weight_g, class |
| notices | notice_id, text, area (GeoJSON), starts_at, ends_at, source |
| eval_cases | input, expected_verdict, expected_rule_ids |

Indexes: 2dsphere on zones.geometry and notices.area, a vector index on rules.embedding (768 dimensions for nomic-embed-text), a text index on rules.text.

Data caveats:
- Rule text is placeholder paraphrase and must be verified against the official regulation before the demo.
- Zones are built from open data (OurAirports, OpenStreetMap) and labeled as derived.
- Notices are sample data and are labeled as such.

## Two sides of one platform

Pilots and the authority use the same rules and the same map. Pilot app (`/`): check a spot, simulate a flight, register drones, watch a flight or request permission, receive alerts. Authority console (`/official.html`): review and decide permission requests, publish and cancel restrictions such as VIP movements, and see how many flights each one affects. Accounts and flights are stored in `data/runtime.json` (gitignored) in this prototype. Endpoints are in [API.md](API.md). Run `python scripts/seed_demo.py` for demo data.

## Prototype scope

Two parts: real airport zones for India (demo city: Hyderabad) on the map (built by `backend/build_zones.py` from OurAirports), and a simulated drone. In the "Simulate flight" tab the pilot clicks waypoints, the backend checks the route every 100 m with the same engine as a single check (`POST /simulate/route`), and the drone flies the route on the map with a live verdict and a summary of the first issue.

## Tech stack (all free / open source)

- MongoDB (Docker, or free Atlas) for storage, geo search, vector search and hybrid search
- Ollama with qwen2.5 (LLM) and nomic-embed-text (embeddings)
- FastAPI backend
- Leaflet + OpenStreetMap frontend

## Evaluation

About 20 test scenarios with known correct answers, stored in eval_cases. Metrics:
- verdict accuracy
- retrieval recall@k (did the expected rule appear?)
- false-safe rate (how often we said "can fly" when we should not have)
- vector-only vs hybrid search comparison

Numbers in the presentation must come from real runs of this evaluation.

## Out of scope for the hackathon

A real drone connection (a simulated drone is in scope), multi-agent loops, user accounts, flight-plan upload. The roadmap is route upload, change-stream alerts for new notices, and live telemetry from open-source autopilots (MAVLink, tested on a simulator first).

## Design rules

See [DESIGN_RULES.md](DESIGN_RULES.md). Run `./scripts/check_design.sh` before every commit.

## Disclaimer

Decision support only, not legal permission. Always confirm with the official portal and local authorities.

## Running it

One command (it sets up Python, starts MongoDB and a mail catcher if Docker is running, loads the data, asks you for the first admin, starts the server and opens your browser):

```
./run.sh            # run the app
./run.sh --seed     # also create one officer per office and a verified demo pilot with flights
./run.sh --local    # no Docker: JSON files in data/, one-time codes printed in the terminal
```

Open http://localhost:8000. Do not open frontend/index.html straight from the folder (it can still talk to http://localhost:8000, but the server must be running). If the server is down the page shows a red bar saying how to start it.

**Nothing is hardcoded.** There are no built-in accounts or passwords:
- The first administrator is created on first run (`./run.sh` asks for an email and generates a password, shown once). Or by hand: `python backend/manage.py create-admin --email you@example.com --generate`.
- Officials are invited by the admin (Authority page, Team tab). They get a temporary password and must choose their own at first sign-in. `python backend/manage.py seed-officers` makes one officer per office for development, with generated passwords.
- `python backend/manage.py seed-demo` adds a verified demo pilot, a drone, flights and a notice. Generated passwords are printed once and saved in `data/demo_credentials.txt` (git-ignored, delete it when done).
- Secrets (`JWT_SECRET`, `PERMIT_SECRET`) are generated on first start in `data/.secrets.json` (git-ignored), or set them in `.env`.
- One-time codes go out by real email (SMTP) or SMS (Twilio). In development with Docker they land in the mail catcher at http://localhost:8025. Nothing is shown on screen.
- The city, map centre, drone classes and the example buttons come from `data/region.json` and the zones in the database through the server (`/config.js`, `/examples`).

By hand, if you prefer:

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env                 # edit as needed
docker compose up -d                 # MongoDB (geo, text, vector search) and the mail catcher
python backend/load_data.py          # zones, rules, drones, notices, embeddings, indexes
python backend/manage.py create-admin --email you@example.com --generate
cd backend && uvicorn main:app --reload
```

Ollama runs on another laptop, never required on yours. On the Ollama laptop:

```
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull qwen2.5:7b        # qwen2.5:3b if RAM is 8 GB
ollama pull nomic-embed-text
ipconfig getifaddr en0         # its IP address
```

On your laptop set `OLLAMA_URL=http://<that-ip>:11434` and `USE_LLM=1` in `.env`, then re-run `python backend/load_data.py` once to embed the rules and build the vector index. If Ollama cannot be reached the app keeps working: summaries use a plain template and rule search falls back to keyword search. `/health` shows the current mode. If the venue Wi-Fi blocks laptop-to-laptop traffic, use a phone hotspot.

Tests: `python -m pytest backend` (local JSON) and `USE_MONGO=1 python -m pytest backend` (MongoDB, uses a throwaway database). Evaluation: `cd backend && python eval.py`.

## Folder layout

```
data/       authorities.json, rules.json, zones.geojson, drones.json, notices.json, eval_cases.json
backend/    routing.py, permits.py, verification.py, security.py, zones_api.py, live.py, analytics.py, config.py, db.py, embeddings.py, geo.py, build_zones.py, sim.py, runtime.py, bridge.py, pipeline.py, search.py, verdict.py, explain.py, main.py, load_data.py, eval.py, tests/
frontend/   index.html + pilot.js, official.html + official.js, account.html, common.js, app.css, terms.html, privacy.html
scripts/    check_design.sh, seed_demo.py
docker-compose.yml   MongoDB (Atlas Local)
```

## Status

- [x] Folder structure, drones.json, requirements.txt
- [x] Design rules (CLAUDE.md, DESIGN_RULES.md, scripts/check_design.sh), skeleton loader, Terms and Privacy pages
- [x] Base: sample data, local search, rule engine, template explanation, API, map page, tests (runs without MongoDB or Ollama)
- [x] Airport zones for India (derived, 5 km / 3 km circles), simulated drone route check and playback
- [x] Hyderabad demo data, accounts, permission requests, official notices, pilot alerts, redesigned UI
- [x] MongoDB: loader, 2dsphere geo queries, text, vector and hybrid rule search, accounts and flights in MongoDB
- [x] Ollama explanation with citation validation, consistency checks and fallback
- [x] False-safe bugs A1 and A2 fixed
- [x] 20 eval cases and metrics (verdict accuracy, false-safe rate, citation recall, text vs vector vs hybrid)
- [x] Authentication: one-time codes by email or SMS, password reset and change, argon2id, JWT with rotating refresh tokens, lockout, authenticator codes for officials, invite-only officials. No built-in accounts or secrets
- [ ] Future scope: DigiLocker and regulator record checks for identity verification
- [x] Ask SkyClear: plain questions answered only from the rule passages with citations, refuses when the rules do not cover it
- [x] Friendlier UI: welcome and examples, step guide, map search, checklist, light and dark theme, run.sh
- [x] Authority routing, signed permits with preflight and revoke, document verification with officer queue, satellite toggle
- [ ] Real rule text verified against the official regulation, real notices source
- [ ] Run eval against the remote Ollama and record the vector vs hybrid numbers
- [ ] Demo rehearsal

Who does what: see [TEAM.md](TEAM.md).
