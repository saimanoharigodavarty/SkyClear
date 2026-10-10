# MongoDB query and scaling evidence

Measured results only are recorded here. Times from a single `explain("executionStats")` call demonstrate the query plan, not production latency guarantees.

## Environment

- Date: 2026-10-10
- MongoDB: Atlas 8.0.34
- Database: `skyclear`
- Zones: 454 total; 304 intersect the Hyderabad ingestion bounding box
- Zone geometry index: `geometry_2dsphere`

## Nearest zones with `$geoNear`

`MongoStore.zones_near` starts its aggregation with `$geoNear`, uses the GeoJSON `geometry` field, limits results to 5 km, and asks MongoDB to calculate spherical distance in metres. Results are already ordered nearest-first. A polygon containing the query point has a distance of zero and is returned with `inside: true`.

Explain input:

```javascript
db.zones.explain("executionStats").aggregate([
  {
    $geoNear: {
      near: { type: "Point", coordinates: [78.43, 17.245] },
      key: "geometry",
      distanceField: "distance_m",
      maxDistance: 5000,
      spherical: true
    }
  },
  { $limit: 5 }
])
```

Observed plan and execution:

| Field | Result |
|---|---:|
| Winning stage | `GEO_NEAR_2DSPHERE` |
| Input stage | `IXSCAN` |
| Index | `geometry_2dsphere` |
| Returned | 2 |
| Keys examined | 55 |
| Documents examined | 42 |
| Execution time | 1 ms |

At the airport test point, Rajiv Gandhi International Airport was first with `distance_km: 0.0` and `inside: true`. At `[78.43, 17.30]`, it was first with a MongoDB-computed distance of 2.65 km.

## Viewport zones with `$geoIntersects`

`MongoStore.zones_in_bbox` queries only polygons intersecting the requested map viewport.

Explain input:

```javascript
db.zones.find({
  geometry: {
    $geoIntersects: {
      $geometry: {
        type: "Polygon",
        coordinates: [[
          [78.3, 17.3], [78.6, 17.3], [78.6, 17.6],
          [78.3, 17.6], [78.3, 17.3]
        ]]
      }
    }
  }
}).explain("executionStats")
```

Observed plan and execution:

| Field | Result |
|---|---:|
| Winning stage | `FETCH` over `IXSCAN` |
| Index | `geometry_2dsphere` |
| Returned | 245 |
| Keys examined | 1,585 |
| Documents examined | 256 |
| Execution time | 7 ms |

The query used the geospatial index and did not perform a collection scan.

## Pending evidence

- GeoJSON flight route/area plus time-window overlap query
- Analytics aggregation query plans
- Larger synthetic dataset measurements
- Telemetry and zone sharding plan

## Planned scale path

The implementation should not claim a scale number until it is measured. When the
simulation owner stores a flight route as GeoJSON plus `starts_at` and `ends_at`, add
a compound time index for the time-window predicate and retain a `2dsphere` index on
the route geometry. Query candidates by overlap in time, then use `$geoIntersects` for
the zone/route overlap. This avoids sampling a route every fixed distance.

For a scale check, generate a disposable test database with at least 100,000 telemetry
documents and 10,000 route records, run `explain("executionStats")` for the geo-plus-
time and analytics pipelines, and record the exact hardware, index definitions,
returned count, keys examined, documents examined and elapsed time here. Do not run a
synthetic load against the shared `skyclear` database.

If live telemetry later requires sharding, shard it by a hashed drone identity with a
time component in the query/index strategy, so an individual drone's recent track is
targeted while write load is distributed. Keep slowly changing airspace zones separate;
if they grow beyond a single shard's practical capacity, use a stable geospatial prefix
as their shard key. Validate both choices against the real access patterns before
enabling sharding.
