# Contracts between workstreams

Build against these, not against each other's code. Anything marked "done" already works. Change a contract only after telling the team, and update this file in the same commit. Existing endpoints are in [API.md](../API.md).

## 1. Zones by viewport (done, stream 4 owns)

`GET /zones?bbox=west,south,east,north` returns a GeoJSON FeatureCollection of zones touching the box. Each feature has `properties: { zone_id, name, zone_type, rule_ids, source }`. `GET /zones` without bbox returns all.

## 2. Authentication (Nikhil builds in stream 2A and consumes in stream 1)

| Endpoint | Body | Response |
|---|---|---|
| POST /auth/register | name, email, password, optional pilot_cert | tokens and user |
| POST /auth/login | email, password | tokens and user, or `{ "mfa_required": true, "mfa_token": "..." }` for officials |
| POST /auth/totp/verify | mfa_token, code | tokens and user |
| POST /auth/refresh | refresh_token | new tokens (the old refresh token stops working) |
| POST /auth/logout | refresh_token | `{ "ok": true }` and the token family is revoked |

Tokens object: `{ "access_token": "...", "refresh_token": "...", "expires_in": 900, "token": "<same as access_token, kept until the frontend moves>" }`. Send `Authorization: Bearer <access_token>`. An expired access token returns 401 with `{ "detail": "token_expired" }`, and the client calls /auth/refresh once and retries. Admin only: `POST /admin/officials` invites an official.

## 3. Live airspace (Thanvi, stream 3, builds; Nikhil, stream 1, consumes)

`GET /live/drones?bbox=w,s,e,n` returns:

```json
{ "as_of": "2026-10-12T10:00:01Z",
  "drones": [ { "drone_id": "SIM-014", "flight_id": "F-A1B2C3", "lat": 17.41, "lng": 78.47, "alt_m": 62.0,
                "speed_mps": 11.2, "heading_deg": 84, "battery_pct": 71, "status": "ok", "zone": null, "ts": "2026-10-12T10:00:01Z" } ] }
```

`status` is `ok`, `warning` (will enter a restricted area within the lookahead time) or `breach` (inside one). Pilots only receive their own drones. Officials receive all.

`GET /live/stream` is server-sent events with these event types, each `data:` a JSON object: `position` (one drone as above), `breach` (`{ event_id, drone_id, flight_id, kind: "zone" or "notice", name, lat, lng, severity, ts }`), `alert` (a notification for the signed-in user), `ping` every 15 seconds.

## 4. Simulation control (Thanvi builds, Nikhil consumes, official or admin only)

| Endpoint | Purpose |
|---|---|
| POST /sim/fleet | Start a fleet: `{ "count": 100, "bbox": [w,s,e,n], "seed": 1, "speed_x": 10 }`. Approved flights fly their own route, the rest fly random missions |
| DELETE /sim/fleet | Stop and remove simulated drones |
| GET /sim/status | `{ "running": true, "drones": 100, "ticks_per_second": 99.8 }` |
| POST /sim/scenarios/vip | Publish a notice that crosses the paths of running drones, so a demo shows breaches and alerts live |

## 5. Telemetry record (Thanvi writes, anyone reads)

Time series collection `telemetry`: `{ ts, drone_id, flight_id, position: {type:"Point", coordinates:[lng,lat]}, alt_m, speed_mps, heading_deg, battery_pct, source: "sim" or "mavlink" }`. A real autopilot adapter writes the same shape.

## 6. Analytics (Manohari builds, Nikhil consumes, officials only)

`GET /analytics/summary` returns `{ "heatmap": [ { "cell": [lng, lat], "count": 12 } ], "breaches_by_zone": [ { "zone_id": "Z-VOHY", "name": "Begumpet Airport", "count": 4 } ], "median_decision_minutes": 18.5, "flights_by_status": { "requested": 3, "approved": 8 } }`.

## 7. Alerts (stream 2A builds)

When a notice is published or cancelled, or a decision is made, stream 2A writes documents to `notifications` (shape in API.md) from a change stream listener, not from the HTTP handler. Thanvi's `/live/stream` pushes new notifications of the requesting user as `alert` events.

## 8. Zone search box (Manohari builds, Nikhil consumes)

`GET /zones/search?q=begum` returns up to 8 matches: `[ { "zone_id": "Z-VOHY", "name": "Begumpet Airport", "zone_type": "airport", "source": "...", "center": { "lat": 17.4531, "lng": 78.4676 } } ]`. Works today with a simple name match. Manohari upgrades it to an Atlas Search autocomplete index with fuzzy matching, the response shape stays the same.

## 9. Verification (Nikhil builds, Nikhil consumes in the UI)

`POST /uploads` (multipart, signed in) stores a file in MongoDB GridFS and returns `{ "file_id": "..." }`. Only the owner and officials can read it.
`POST /me/verification/pilot` with `{ cert_no, file_ids: [...] }` and `POST /me/drones/{drone_id}/verification` with `{ serial, uin, file_ids: [...] }` create a pending request.
`GET /verification/queue` (official) lists pending requests. `POST /verification/{id}/decision` with `{ "decision": "approved" or "rejected", "comment": "..." }` decides it.
Pilot and drone objects gain `verification: { status: "unverified" | "pending" | "verified" | "rejected", by, at }`. A serial can belong to only one active owner. Permission requests are accepted only from a verified pilot with a verified drone.

## 10. Permits and preflight (Nikhil builds, Thanvi and the UI consume)

Approving a request (existing endpoint) now also creates a permit:
`{ "permit_id": "P-9F3A21", "flight_id": "F-...", "pilot_id": "U-...", "drone_id": "D-...", "serial": "...", "area": GeoJSON, "alt_max_m": 60, "starts_at": "...", "ends_at": "...", "conditions": ["Daylight only"], "issued_by": "...", "issued_at": "...", "status": "active", "signature": "..." }` with status `active`, `used`, `expired` or `revoked`.
`GET /permits/{permit_id}` returns it. `POST /permits/{permit_id}/revoke` (official, reason required) revokes it and alerts the pilot.
`POST /flights/{flight_id}/preflight` returns `{ "cleared": true, "reasons": [], "cleared_until": "...", "permit": {...} }` or `{ "cleared": false, "reasons": ["permit revoked", "serial mismatch"] }`. The simulator calls the same check before a drone arms.
When a notice is published, the response also lists `conflicting_permits` so the officer can revoke.

## 11. Zone management (Manohari builds the data side, Nikhil builds the editor UI, officials only)

Zones gain `class: "red" | "yellow"`, `official: true | false`, `version`, `effective_from`, `effective_to`, `alt_band_m`.
`POST /admin/zones/drafts` creates a draft from GeoJSON plus those fields. `POST /admin/zones/{zone_id}/publish` publishes it and must be called by a different officer than the author. `GET /admin/zones/{zone_id}/versions` lists versions. `POST /admin/zones/import` accepts a KML or GeoJSON file of official zones.
`GET /zones` returns published zones only, with the fields above.
