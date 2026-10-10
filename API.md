# SkyClear API contract

Frontend and backend both follow this. Frontend can build against the mock response below before the real backend exists.

## POST /check

Request:

```json
{
  "lat": 12.9500,
  "lng": 77.6680,
  "drone_id": "small-1800",
  "datetime": "2026-10-12T17:00:00+05:30"
}
```

Response:

```json
{
  "verdict": "permission_needed",
  "summary": "Short plain-language explanation, 2 to 3 sentences.",
  "zones": [
    {
      "zone_id": "Z-001",
      "name": "Sample Airport",
      "zone_type": "airport",
      "distance_km": 3.2,
      "geometry": { "type": "Polygon", "coordinates": [[[77.60, 12.95], [77.62, 12.95], [77.62, 12.97], [77.60, 12.97], [77.60, 12.95]]] }
    }
  ],
  "notices": [
    {
      "notice_id": "N-001",
      "title": "Sample VIP movement",
      "starts_at": "2026-10-12T16:00:00+05:30",
      "ends_at": "2026-10-12T20:00:00+05:30",
      "geometry": { "type": "Polygon", "coordinates": [[[77.58, 12.97], [77.60, 12.97], [77.60, 12.99], [77.58, 12.99], [77.58, 12.97]]] }
    }
  ],
  "citations": [
    {
      "rule_id": "R-012",
      "text": "Full text of the rule passage that was used.",
      "source": "Sample source (verify against official regulation)"
    }
  ],
  "explained_by": "template",
  "next_steps": ["Apply for permission on the official portal."],
  "data_last_updated": "2026-10-10",
  "disclaimer": "Decision support only, not legal permission."
}
```

`explained_by` is `llm` when the summary came from the language model and passed the checks, otherwise `template`. The rules that decided the verdict are always in `citations`.

`verdict` is one of: `can_fly`, `permission_needed`, `prohibited`, `cannot_determine`.

`can_fly` is shown in the UI as "No restriction found in our data". Never show "safe".

## GET /zones

Returns all zones as a GeoJSON FeatureCollection for drawing on the map. Each feature has `properties: { zone_id, name, zone_type, rule_ids }`.

## GET /drones

Returns a list of `{ drone_id, name, weight_g, class }` for the dropdown.

## POST /simulate/route

Simulated flight. The backend samples the route about every 100 m and runs the same checks as `/check` at each sample, with time moving forward at the drone speed.

Request: `{ "drone_id": "small-1800", "speed_mps": 10, "datetime": "2026-10-12T10:00:00+05:30", "waypoints": [{ "lat": 12.90, "lng": 77.668 }, { "lat": 13.00, "lng": 77.668 }] }`

Response: `{ "drone": {...}, "samples": [{ "lat", "lng", "dist_m", "t_s", "verdict", "zones": ["name"], "rule_ids": ["R-001"] }], "summary": { "worst_verdict", "first_issue": { "verdict", "dist_m", "t_s", "zones", "rule_ids" } or null, "length_m", "duration_s" }, "data_last_updated", "disclaimer" }`

## Accounts and roles (prototype)

Bearer token from `/auth/login` or `/auth/register`, sent as `Authorization: Bearer <token>`. Roles: `pilot`, `official`. Checking (`/check`, `/simulate/route`, `/zones`, `/drones`, `/notices/active`) needs no sign-in.

| Endpoint | Role | Purpose |
|---|---|---|
| POST /auth/register | none | Create a pilot account: name, email, password, optional pilot_cert (self-declared) |
| POST /auth/login | none | Returns token and user |
| GET /me | any | Current user |
| GET, POST /me/drones | pilot | List or add a drone (name, weight_g, optional uin). Class is derived from weight |
| POST /flights | pilot | Save a flight: drone_id, lat, lng, start, end, purpose, kind `watch` or `permission`. Permission is refused when the verdict is prohibited or can_fly |
| GET /flights?status= | any | Pilot sees own flights, official sees all |
| POST /flights/{id}/decision | official | `approved` or `rejected` with a comment (required to reject). Alerts the pilot |
| POST /flights/{id}/cancel | pilot | Cancel own flight |
| POST /notices | official | Publish a restriction: title, note, lat, lng, radius_km, starts_at, ends_at. Alerts every pilot whose active flight overlaps and returns `affected_flights` |
| POST /notices/{id}/cancel | official | Cancel it and alert the same pilots |
| GET /notices | any | Official sees all, pilot sees active |
| GET /notices/active | none | Active restrictions for the map |
| GET /notifications, POST /notifications/read | pilot | Alerts inbox |
| GET /overview | official | Counts for the console |
