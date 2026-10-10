# Working together

The base runs end to end on local JSON files, so nobody is blocked on anyone else. Pick an area, work in your own files, merge small and often.

## Setup (once)

See "Running it" in README.md. Short version: copy .env.example to .env, `docker compose up -d`, `python backend/load_data.py`, then `uvicorn main:app --reload` from backend/. Ollama runs on the other laptop, set OLLAMA_URL in your .env.

## Workstreams (four people)

Read [ARCHITECTURE.md](ARCHITECTURE.md) first (10 minutes), then [docs/CONTRACTS.md](docs/CONTRACTS.md). The contracts are the only thing the streams share, so everyone works at the same time. Where a contract is not built yet, code against the stub or a mock. Write each name in the Owner row.

| | Stream 1: Experience | Stream 2: Identity and platform | Stream 3: Simulation and engine | Stream 4: MongoDB data and RAG |
|---|---|---|---|---|
| Owner | Nikhil | ____ | ____ | ____ |
| Files | frontend/*, docs/DEMO.md | backend/bridge.py, runtime.py, main.py, new backend/security.py, docker/, locust/ | backend/live.py, sim.py, verdict.py, geo.py, new simulator/ | backend/search.py, load_data.py, zones_api.py, analytics.py, embeddings.py, explain.py, eval.py, data/, new ingestion/ |
| Goal | A map and screens that look and feel like a real product | Real authentication, workflow and a deployment that scales out | A proper drone simulation with live geofencing | Real data, deep MongoDB geo search, and a strong RAG engine |

### Stream 1: Experience (Nikhil)

- P0: Rebuild the map on MapLibre GL JS with OpenFreeMap vector tiles. Load zones by viewport (`/zones?bbox=` on every moveend), style them by severity, smooth clustering of labels.
- P0: Live airspace view for the pilot and the authority: drones moving on the map from `/live/stream`, color by status, breach feed panel.
- P0: Simulation screen for officials: start and stop a fleet, scale slider, "inject VIP movement" button (contract 4).
- P0: Auth screens against contract 2 (refresh handling, TOTP step for officials, logout).
- P1: Authority dashboard with the analytics (heatmap layer, charts without effects, contract 6). Mobile layout and keyboard accessibility.
- P1: Demo lead: 3 minute script, backup recording, slides using real numbers from docs/RESULTS.md.
- Done when: a stranger completes the pilot and the authority flow on a phone and a laptop, and the live view stays smooth with 200 drones.

### Stream 2: Identity and platform

- P0: Authentication per contract 2: JWT access and rotating refresh tokens (PyJWT), argon2id (argon2-cffi), roles pilot, official, admin, invite-only officials with TOTP (pyotp), account lockout, rate limits (slowapi), refresh token TTL index and revocation.
- P0: Alerts by change stream: a listener on `notices` and `flights` writes `notifications`. Remove the notification calls from the HTTP handlers.
- P0: Permission decisions in a MongoDB transaction (flight update, audit entry, notification together). Audit log for every official action.
- P0: Scale-out deployment: `docker compose` with Nginx, 3 API replicas, MongoDB replica set. Prometheus and Grafana with a latency dashboard.
- P0: Locust load test script, run it, record numbers in docs/RESULTS.md (target in ARCHITECTURE.md).
- P1: Email alerts (aiosmtplib or ntfy). Security headers, CORS policy, input size caps. Flight and notice list endpoints with pagination.
- Done when: a notice published from a second terminal alerts a pilot in 2 seconds with no call from the handler, officials cannot self-register, a stolen refresh token is rejected after use, and the load test numbers are recorded.

### Stream 3: Simulation and engine

- P0: Fleet simulator in `simulator/` (asyncio): kinematics with speed, heading, altitude, battery drain, wind drift and GPS noise. Approved flights fly their own route, the rest fly random missions. 100 drones at 1 Hz, scalable to 1000.
- P0: Telemetry into a MongoDB time series collection with batched inserts, TTL and a 2dsphere index (contract 5).
- P0: Geofence engine: every tick, test positions against zones and notices with MongoDB geo queries, predict breaches ahead along the heading (lookahead and ETA), write `breaches`. Make `/live/drones` and `/live/stream` real (contract 3) from change streams.
- P0: Simulation control endpoints (contract 4), including the VIP scenario that makes running drones breach on demand.
- P0: Verdict engine fixes from PRODUCT.md: A3 (route against polygon intersection, not 100 m sampling), A4, A5, A6, with tests.
- P1: Altitude and day or night rules in the verdict. Corridor buffer around routes.
- P1 stretch: ArduPilot SITL in Docker with pymavlink writing the same telemetry shape (`source: "mavlink"`).
- Done when: 100 drones fly live on the map, a VIP scenario produces breaches and alerts within seconds, and a narrow corridor notice is always caught on a route.

### Stream 4: MongoDB data and RAG

- P0: Real zones: ingest OpenStreetMap for Telangana (Geofabrik extract, osmium or Overpass): aeroways, military land, prisons, government sites, power plants, stadiums. Keep source and ODbL attribution. Aim for 300 or more Hyderabad zones. Add JSON schema validation and the right indexes to `zones`.
- P0: Geo queries done properly: viewport `$geoIntersects`, `$geoNear` for nearest zones, flights stored as GeoJSON with a time range and a geo plus time overlap query. Prove index use with `explain()` and note it in docs/SCALING.md.
- P0: Real rules: replace placeholder text with the actual regulation (section and date for each). Decide the notices source (authority entry only).
- P0: RAG with the remote Ollama: run `load_data.py`, vector index, hybrid search, tune the prompt on all eval cases, adversarial notice tests for prompt injection.
- P0: Evaluation: grow to 30 cases including zone edges and overlaps, record real vector, text and hybrid numbers in docs/RESULTS.md.
- P0: Analytics aggregation pipelines (contract 6): heatmap cells, breaches per zone, median decision time.
- P1: Sharding plan in docs/SCALING.md (telemetry by drone_id and time, zones by geohash prefix), test with a larger synthetic dataset.
- Done when: the map shows 300 or more real zones fast, `explain()` shows index scans, docs/RESULTS.md has real numbers, and 0 false-safe on 30 cases.

## Order of work

1. Everyone (first 30 minutes): pull, run the setup above, run the app, read ARCHITECTURE.md and docs/CONTRACTS.md. Stream 4 starts the Ollama laptop.
2. Checkpoint 1 (about one third of the time): each stream demos its P0 contract working, even with mock data. Fix contract mismatches now.
3. Checkpoint 2 (about two thirds): live airspace on the map end to end, load test numbers, real zones loaded.
4. Final stretch: freeze features, run `python backend/eval.py` and both test modes, rehearse the demo twice.

## Who touches what

Only the owner edits a stream's files. Need a change in someone else's file, ask them. Shared files (README.md, API.md, PRODUCT.md, TEAM.md, docs/CONTRACTS.md) get small edits only, with `git pull --rebase` first. `backend/main.py` belongs to stream 2: to add a router, ask stream 2 or add one include line and tell them.

## Rules

- The API shape in API.md is the contract. Change it only after telling everyone, and update API.md in the same commit.
- Keep the store interface in search.py (zones_near, notices_at, rules_for). The pipeline in main.py depends on it.
- Code decides the verdict. The LLM only explains and cites.
- Work directly on main with small commits, and `git pull --rebase` before you push.
- Run `python -m pytest backend` (and `USE_MONGO=1 python -m pytest backend` if you touched search or storage) and `./scripts/check_design.sh` before every push.
- Never commit .env or real secrets.
