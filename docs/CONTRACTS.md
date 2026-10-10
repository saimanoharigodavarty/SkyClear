# Contracts between workstreams

Build against these, not against each other's code. Anything marked "done" already works. Change a contract only after telling the team, and update this file in the same commit. Existing endpoints are in [API.md](../API.md).

## 1. Zones by viewport (done, stream 4 owns)

`GET /zones?bbox=west,south,east,north` returns a GeoJSON FeatureCollection of zones touching the box. Each feature has `properties: { zone_id, name, zone_type, rule_ids, source }`. `GET /zones` without bbox returns all.

## 2. Authentication (stream 2 builds, stream 1 consumes)

| Endpoint | Body | Response |
|---|---|---|
| POST /auth/register | name, email, password, optional pilot_cert | tokens and user |
| POST /auth/login | email, password | tokens and user, or `{ "mfa_required": true, "mfa_token": "..." }` for officials |
| POST /auth/totp/verify | mfa_token, code | tokens and user |
| POST /auth/refresh | refresh_token | new tokens (the old refresh token stops working) |
| POST /auth/logout | refresh_token | `{ "ok": true }` and the token family is revoked |

Tokens object: `{ "access_token": "...", "refresh_token": "...", "expires_in": 900, "token": "<same as access_token, kept until the frontend moves>" }`. Send `Authorization: Bearer <access_token>`. An expired access token returns 401 with `{ "detail": "token_expired" }`, and the client calls /auth/refresh once and retries. Admin only: `POST /admin/officials` invites an official.

## 3. Live airspace (stream 3 builds, stream 1 consumes)

`GET /live/drones?bbox=w,s,e,n` returns:

```json
{ "as_of": "2026-10-12T10:00:01Z",
  "drones": [ { "drone_id": "SIM-014", "flight_id": "F-A1B2C3", "lat": 17.41, "lng": 78.47, "alt_m": 62.0,
                "speed_mps": 11.2, "heading_deg": 84, "battery_pct": 71, "status": "ok", "zone": null, "ts": "2026-10-12T10:00:01Z" } ] }
```

`status` is `ok`, `warning` (will enter a restricted area within the lookahead time) or `breach` (inside one). Pilots only receive their own drones. Officials receive all.

`GET /live/stream` is server-sent events with these event types, each `data:` a JSON object: `position` (one drone as above), `breach` (`{ event_id, drone_id, flight_id, kind: "zone" or "notice", name, lat, lng, severity, ts }`), `alert` (a notification for the signed-in user), `ping` every 15 seconds.

## 4. Simulation control (stream 3 builds, stream 1 consumes, official or admin only)

| Endpoint | Purpose |
|---|---|
| POST /sim/fleet | Start a fleet: `{ "count": 100, "bbox": [w,s,e,n], "seed": 1, "speed_x": 10 }`. Approved flights fly their own route, the rest fly random missions |
| DELETE /sim/fleet | Stop and remove simulated drones |
| GET /sim/status | `{ "running": true, "drones": 100, "ticks_per_second": 99.8 }` |
| POST /sim/scenarios/vip | Publish a notice that crosses the paths of running drones, so a demo shows breaches and alerts live |

## 5. Telemetry record (stream 3 writes, anyone reads)

Time series collection `telemetry`: `{ ts, drone_id, flight_id, position: {type:"Point", coordinates:[lng,lat]}, alt_m, speed_mps, heading_deg, battery_pct, source: "sim" or "mavlink" }`. A real autopilot adapter writes the same shape.

## 6. Analytics (stream 4 builds, stream 1 consumes, officials only)

`GET /analytics/summary` returns `{ "heatmap": [ { "cell": [lng, lat], "count": 12 } ], "breaches_by_zone": [ { "zone_id": "Z-VOHY", "name": "Begumpet Airport", "count": 4 } ], "median_decision_minutes": 18.5, "flights_by_status": { "requested": 3, "approved": 8 } }`.

## 7. Alerts (stream 2 builds)

When a notice is published or cancelled, or a decision is made, stream 2 writes documents to `notifications` (shape in API.md) from a change stream listener, not from the HTTP handler. Stream 3's `/live/stream` pushes new notifications of the requesting user as `alert` events.
