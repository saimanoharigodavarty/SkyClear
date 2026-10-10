# Working together

The base runs end to end on local JSON files, so nobody is blocked on anyone else. Pick an area, work in your own files, merge small and often.

## Setup (once)

See "Running it" in README.md. Short version: copy .env.example to .env, `docker compose up -d`, `python backend/load_data.py`, then `uvicorn main:app --reload` from backend/. Ollama runs on the other laptop, set OLLAMA_URL in your .env.

## Workstreams (four people)

Read [ARCHITECTURE.md](ARCHITECTURE.md) first (10 minutes), then [docs/CONTRACTS.md](docs/CONTRACTS.md). The contracts are the only thing the streams share, so everyone works at the same time. Where a contract is not built yet, code against the stub or a mock.

| Person | Streams | Why this split |
|---|---|---|
| Manohari | Stream 4: MongoDB data and RAG | The core of the hackathon track. Geo, vector and hybrid search, real data, evaluation numbers |
| Thanvi | Stream 3: Simulation and engine | The most visible technical piece. Live drones, geofencing, route checks |
| Nikhil | Stream 1: Experience, and Stream 2A: Identity and workflow | Everything the user sees, plus authentication and alerts, which touch every screen |
| Suhas | Stream 2B: Atlas, charts, load testing and demo material | Self-contained, clear steps. Puts the demo on MongoDB Atlas with live Atlas Charts, and makes the scale claims provable |

### Stream 4: MongoDB data and RAG (Manohari)

Files: backend/search.py, load_data.py, zones_api.py, analytics.py, embeddings.py, explain.py, eval.py, data/, new ingestion/.

The MongoDB showpiece stream. Verified on our local MongoDB 8.3: Atlas Search (`$search`) and `$rankFusion` work. See the feature map in ARCHITECTURE.md.

- P0: Real zones: ingest OpenStreetMap for Telangana (Geofabrik extract, osmium or Overpass): aeroways, military land, prisons, government sites, power plants, stadiums. Keep source and ODbL attribution. Aim for 300 or more Hyderabad zones. Add JSON schema validation and the right indexes to `zones`.
- P0: Hybrid search done the MongoDB way: create an Atlas Search index on `rules.text` and use `$rankFusion` over `$vectorSearch` and `$search` instead of the hand-written merge in `search_rules`. Keep the metadata filters. Fall back to `$search` alone when embeddings are missing.
- P0: Atlas Search autocomplete with fuzzy matching on `zones.name` for the search box (contract 8). The endpoint already exists with a plain name match, keep the response shape.
- P0: Geo queries done properly: viewport `$geoIntersects`, `$geoNear` for nearest zones, flights stored as GeoJSON with a time range and a geo plus time overlap query. Prove index use with `explain()` and note it in docs/SCALING.md.
- P0: Real rules: replace placeholder text with the actual regulation (section and date for each). Decide the notices source (authority entry only).
- P0: RAG with the remote Ollama: run `load_data.py`, vector index, tune the prompt on all eval cases, adversarial notice tests for prompt injection.
- P0: Evaluation: grow to 30 cases including zone edges and overlaps, record real numbers for keyword (`$search`), vector and `$rankFusion` hybrid in docs/RESULTS.md.
- P0: Analytics aggregation pipelines (contract 6): `$facet`, `$bucket`, `$group`, heatmap cells, breaches per zone, median decision time. Write results into summary collections with `$merge` so the dashboard and Atlas Charts read fast.
- P0: Authorities data (contract 12): `authorities` collection with jurisdiction polygons and office points for Hyderabad (sample data, labelled), 2dsphere indexes, `authority_id` on zones.
- P0: Zone authority data side (contract 11): `class`, `official`, `version` fields, `zone_versions` collection, maker and checker rule enforced in the publish endpoint, KML and GeoJSON import for official zone files, schema validation.
- P1: Sharding plan in docs/SCALING.md (telemetry by drone_id and time, zones by geohash prefix), test with a larger synthetic dataset.
- P2 stretch: MongoDB MCP server (open source) so officials can ask the airspace questions in plain language.
- Done when: the map shows 300 or more real zones fast, `explain()` shows index scans, hybrid search runs inside MongoDB with `$rankFusion`, docs/RESULTS.md has real numbers, and 0 false-safe on 30 cases.

### Stream 3: Simulation and engine (Thanvi)

Files: backend/live.py, sim.py, verdict.py, geo.py, backend/tests/test_verdict.py, new simulator/.

- P0: Fleet simulator in `simulator/` (asyncio): kinematics with speed, heading, altitude, battery drain, wind drift and GPS noise. Approved flights fly their own route, the rest fly random missions. 100 drones at 1 Hz, scalable to 1000.
- P0: Telemetry into a MongoDB time series collection with batched inserts, TTL and a 2dsphere index (contract 5). Use `$setWindowFields` for smoothed speed and track.
- P0: Geofence engine: every tick, test positions against zones and notices with MongoDB geo queries, predict breaches ahead along the heading (lookahead and ETA), write `breaches`. Make `/live/drones` and `/live/stream` real (contract 3) from MongoDB change streams.
- P0: Simulation control endpoints (contract 4), including the VIP scenario that makes running drones breach on demand.
- P0: Verdict engine fixes from PRODUCT.md: A3 (route against polygon intersection, not 100 m sampling), A4, A5, A6, with tests.
- P0: Follow docs/SIMULATION.md: level 1 fleet first, scenarios A, B and E for the core story.
- P0: Permit-aware simulation (contract 10): a drone arms only if its flight passes preflight. Yellow-zone flights without a valid permit, or with a serial that does not match, become breaches. Telemetry carries the drone serial.
- P1: Altitude and day or night rules in the verdict. Corridor buffer around routes.
- P1 stretch: ArduPilot SITL in Docker with pymavlink writing the same telemetry shape (`source: "mavlink"`).
- Done when: 100 drones fly live on the map, a VIP scenario produces breaches and alerts within seconds, and a narrow corridor notice is always caught on a route.

### Stream 1: Experience (Nikhil)

Files: frontend/*.

- P0: Rebuild the map on MapLibre GL JS with OpenFreeMap vector tiles. Load zones by viewport (`/zones?bbox=` on every moveend), style them by severity, tidy the labels.
- P0: Search box on the map using `/zones/search` (contract 8), jump to the zone on select.
- P0: Satellite basemap toggle (Sentinel-2 cloudless by EOX) and the red, yellow, green legend.
- P0: Pilot screens for verification and permits (upload, status badges, permit with QR, Preflight button). Officer screens for the verification queue, permission review with approve, reject, ask for information, revoke.
- P1: Zone editor for officers: draw a polygon over the satellite layer, set class and dates, save draft, publish (contract 11).
- P0: Live airspace view for the pilot and the authority: drones moving on the map from `/live/stream`, color by status, breach feed panel.
- P0: Simulation screen for officials: start and stop a fleet, scale slider, "inject VIP movement" button (contract 4).
- P0: Auth screens against contract 2 (refresh handling, TOTP step for officials, logout).
- P1: Authority dashboard with the analytics (heatmap layer, plain charts, contract 6). Mobile layout and keyboard accessibility.
- Done when: a stranger completes the pilot and the authority flow on a phone and a laptop, and the live view stays smooth with 200 drones.

### Stream 2A: Identity and workflow (Nikhil)

Files: backend/bridge.py, runtime.py, main.py, new backend/security.py.

- P0: Authentication per contract 2: JWT access and rotating refresh tokens (PyJWT), argon2id (argon2-cffi), roles pilot, official, admin, invite-only officials with TOTP (pyotp), account lockout, rate limits (slowapi), refresh token TTL index and revocation.
- P0: Alerts by change stream: a listener on `notices` and `flights` writes `notifications`. Remove the notification calls from the HTTP handlers.
- P0: Permission decisions in a MongoDB transaction (flight update, audit entry, notification together). Audit log for every official action.
- P1: Pagination on flight and notice lists. Security headers, CORS policy, input size caps.
- P0: Permits and preflight (contract 10): approval creates a signed permit with conditions, `/flights/{id}/preflight`, revoke, conflicting permits listed when a notice is published. See docs/PERMITS_AND_VERIFICATION.md.
- P0: Routing (contract 12): send each permission request to the right authority (zone owner, then jurisdiction polygon, then nearest office), officers see only their queue, escalate after the response time, pilot sees who will review it.
- P0: Verification (contract 9): uploads in GridFS, pilot and drone verification queue for officers, unique serial index, permission requests only from verified pilots with verified drones.
- Done when: a notice published from a second terminal alerts a pilot in 2 seconds with no call from the handler, officials cannot self-register, a stolen refresh token is rejected after use, and a pilot cannot get cleared for takeoff without an active permit that matches their drone.

### Stream 2B: Atlas, charts, load testing and demo material (Suhas)

Files: docs/ATLAS.md, docs/RESULTS.md (load section), docs/DEMO.md, docs/SLIDES.md, locust/, docker/, docker-compose.prod.yml, monitoring/, backend/notify_email.py (new).

Do these in order, each is a clear step with a visible result. MongoDB comes first because this is a MongoDB hackathon.

1. P0, Atlas as the demo database: create a free MongoDB Atlas cluster, allow your IP, set `MONGO_URI` in `.env` to the Atlas connection string, run `python backend/load_data.py`, start the app and run `USE_MONGO=1 python -m pytest backend`. Write docs/ATLAS.md: the exact steps, and which features worked on the free tier and which did not (vector search, Atlas Search, time series collections, change streams, transactions, geo). The team needs this answer early, so do it first and tell everyone the result.
2. P0, Atlas Charts on live data: with the app running on Atlas, build 4 charts in Atlas Charts (flights by area, breaches per zone, decision times, drones by status), a dashboard, and an embed or link on the authority page. Agree the embed approach with Nikhil. Take screenshots as a backup for the demo.
3. P0, demo material: docs/DEMO.md with a 3 minute script (what to click, what to say, which numbers to quote) and docs/SLIDES.md with the slide outline for the Track 2 pitch, built around the MongoDB feature map in ARCHITECTURE.md. Use PRODUCT.md for the honest limits and judge questions. Record a backup screen video once the app is ready.
4. P1, load test in `locust/`: a user that checks random Hyderabad spots (`POST /check`), loads zones by viewport and logs in. Run it with 50, 200 and 500 users. Put the real numbers (requests per second, p95, errors) in docs/RESULTS.md with the date and the machine.
5. P1, production-style compose file `docker-compose.prod.yml`: Nginx in front, 3 copies of the API (a Dockerfile in docker/), MongoDB replica set. Nginx gzips and caches `GET /zones` for 30 seconds.
6. P1, monitoring and email: `prometheus-fastapi-instrumentator` (one small change in backend/main.py, tell Nikhil first), Prometheus and Grafana with a latency dashboard in monitoring/. `backend/notify_email.py` with `send_alert(to, subject, body)` tested against Mailpit, Nikhil wires it into the alert listener.
- Done when: docs/ATLAS.md exists with real findings, the app runs on Atlas with Charts showing live data, the demo script has been rehearsed once end to end, and RESULTS.md has real load numbers.

## Order of work

1. Everyone (first 30 minutes): pull, run the setup above, run the app, read ARCHITECTURE.md and docs/CONTRACTS.md. Stream 4 starts the Ollama laptop.
2. Checkpoint 1 (about one third of the time): each stream demos its P0 contract working, even with mock data. Fix contract mismatches now.
3. Checkpoint 2 (about two thirds): live airspace on the map end to end, load test numbers, real zones loaded.
4. Final stretch: freeze features, run `python backend/eval.py` and both test modes, rehearse the demo twice.

## Who touches what

Only the owner edits a stream's files. Need a change in someone else's file, ask them. Shared files (README.md, API.md, PRODUCT.md, TEAM.md, docs/CONTRACTS.md) get small edits only, with `git pull --rebase` first. `backend/main.py` belongs to Nikhil: to add a router or middleware, add one line and tell him.

## Rules

- The API shape in API.md is the contract. Change it only after telling everyone, and update API.md in the same commit.
- Keep the store interface in search.py (zones_near, notices_at, rules_for). The pipeline in main.py depends on it.
- Code decides the verdict. The LLM only explains and cites.
- Work directly on main with small commits, and `git pull --rebase` before you push.
- Run `python -m pytest backend` (and `USE_MONGO=1 python -m pytest backend` if you touched search or storage) and `./scripts/check_design.sh` before every push.
- Never commit .env or real secrets.
