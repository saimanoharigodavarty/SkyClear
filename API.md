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
  "next_steps": ["Apply for permission on the official portal."],
  "data_last_updated": "2026-10-10",
  "disclaimer": "Decision support only, not legal permission."
}
```

`verdict` is one of: `can_fly`, `permission_needed`, `prohibited`, `cannot_determine`.

`can_fly` is shown in the UI as "No restriction found in our data". Never show "safe".

## GET /zones

Returns all zones as a GeoJSON FeatureCollection for drawing on the map. Each feature has `properties: { zone_id, name, zone_type, rule_ids }`.

## GET /drones

Returns a list of `{ drone_id, name, weight_g, class }` for the dropdown.
