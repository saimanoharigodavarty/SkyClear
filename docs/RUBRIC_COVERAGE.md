# Coverage against the judging components

Status is as of the last commit. "Gap" means not done, said plainly.

## Technology stack and system architecture

- FastAPI backend (67 API paths, OpenAPI at `/docs`), vanilla JS pages, Leaflet 2D and MapLibre plus three.js 3D, MongoDB, Ollama for the language model, Mailpit for mail in development. See `ARCHITECTURE.md`.
- `docker-compose.yml` runs MongoDB and the mail catcher; `run.sh` starts everything.
- Production-style stack: `Dockerfile`, `docker-compose.prod.yml` and `deploy/nginx.conf` (Nginx with gzip, request limits, security headers, no buffering for the live stream). The image builds; the full prod stack has not been load tested.

## MongoDB architecture and implementation

| Feature | Where |
|---|---|
| 2dsphere, `$geoIntersects`, `$geoNear` | zones check, nearest zones |
| Atlas Search (lucene.english), autocomplete | rule search, zone search box |
| Atlas Vector Search, 768 dimensions | rule retrieval |
| `$rankFusion` hybrid with keyword fallback | `search.py` |
| Schema validation, unique and partial indexes | `db.py` |
| TTL indexes | one-time codes, sessions |
| Time-series collection | drone telemetry |
| GridFS | uploaded documents |
| `$merge` materialised analytics | `analytics.py` |
| Change streams | `events.py`, `events_api.py`, pushed to browsers |
| Multi-document transactions | `runtime.atomic()`: decisions, revocations, recalls, notices, verification, invites |
| Append-only audit log | `runtime.audit()`, `GET /audit` (admin only) |
| Guard alerts (public siren stream from a change stream, Web Push with a server key) | `guard_api.py`, `push.py`, `frontend/guard.html`, `frontend/sw.js`, `docs/GUARD_ALERTS.md` |

Tests prove the transaction rollback and the change stream on a real MongoDB (`USE_MONGO=1 pytest`).
Gap: no Atlas Charts dashboard, no sharding or replica-set write concern discussion beyond `docs/SCALING.md`.

## Advanced technologies and engineering

- Flight lifecycle: requested, approved with a signed permit, preflight, cleared, launch, flying, completed or recalled.
- Simulator: kinematics with wind, battery and sensor noise, permit-aware geofence with look-ahead warnings, altitude limits, manual 10 Hz control from a phone, return home, recall by an officer.
- 3D live view: satellite chase camera, drone camera with a heads-up display and distance to the nearest zone, zone and permit volumes.
- MAVLink telemetry adapter (tested with a mocked message).
- Real tracker input: `POST /ingest/position` with a per-tracker key (`docs/TRACKERS.md`), so a Remote ID receiver or radar feeds the same geofence and alerts.
- Gap: no real drone hardware tested, no real video feed, no terrain or building heights in 3D.

## AI/ML implementation and integration

- Retrieval over rules: keyword, vector, hybrid, with measured recall in `docs/RESULTS.md`.
- Guards on the model: forbidden wording per verdict, label leak check, nearby-zone mention, citation validation, relevance gate, instant verdict then the explanation fills in.
- 32 evaluation cases for verdicts, 0 false "can fly" in the recorded run.
- Gap: the rule corpus is a 7-rule sample. Retrieval numbers say little until the real regulation is loaded.

## Backend, API and system integration

- REST with typed requests, role checks on every route, server-sent events at `/events`.
- Mail through SMTP, optional SMS through Twilio, Google sign-in, Mappls place search, OpenStreetMap and Digital Sky zone imports.
- 18 test files with about 190 tests, a 25 step browser test (`scripts/e2e.py`), a load test (`scripts/loadtest.py`).
- Gap: DigiLocker is future scope.

## Security, performance and scalability

- Security: argon2id, short access tokens with rotating refresh tokens and reuse detection, lockout and rate limits, one-time codes, optional authenticator app, invite-only officials, signed permits, scoped phone tokens, hardened Google sign-in, an audit trail.
- Performance, measured on one Mac (see `docs/RESULTS.md`): about 390 checks per second from 50 to 200 users (95th percentile 661 ms at 200); 1000 simulated drones tick in about 245 ms. `GET /metrics` exposes request counts and latency in Prometheus format.
- Scalability: the zone map and live list still queue at 200 users on one process (95th percentile about 5 s). Splitting the simulator into its own process and running several API workers behind Nginx is the next step, not done.
- Gaps: no dashboard on top of `/metrics`, no secrets manager, no penetration test.
