# Real tracker input

The simulator is not the only source of drone positions. A Remote ID receiver, a radar feed or a ground station can post what it sees, and the platform treats it exactly like a simulated drone: geofence check, breach record in MongoDB, officer feed, guard alert.

## Set up a tracker

```
cd backend && ../.venv/bin/python manage.py create-tracker --name "Campus receiver"
```

The key is printed once and stored only as a hash. An administrator can also create, list and revoke trackers through `POST /admin/trackers`, `GET /admin/trackers` and `POST /admin/trackers/{id}/revoke`. Creation and revocation are written to the audit log.

## Send a position

```
curl -X POST http://localhost:8000/ingest/position \
  -H "X-Tracker-Key: trk_..." -H "Content-Type: application/json" \
  -d '{"drone_ref":"RID-0001","lat":17.3487,"lng":78.3412,"alt_m":40,"speed_mps":8,"heading_deg":90}'
```

Answer: `{"status":"breach","zone":"KLH Aziznagar campus","breach_recorded":true}`. One breach is recorded per entry (the same drone in the same area is not reported again for 60 seconds). Every position is also saved in the telemetry time-series collection with `source: tracker`.

## What protects it

- A valid, active key is required. A revoked key stops working at once. A missing or wrong key is a 401.
- Values are range checked (latitude, longitude, altitude, speed, heading) and the drone reference allows only letters, digits and `. _ : -`.
- Each tracker is limited to 600 positions a minute.

## What it does not do

- It trusts the tracker. A tracker that lies, or a key that leaks, can report false positions. Keys can be revoked, and every use is traceable to a tracker, but positions are not cross-checked against a second source.
- It does not decode the Remote ID radio broadcast itself. A receiver does that and calls this endpoint.
- Drones reported this way are not drawn on the live map yet. The breach, the officer feed and the guard alert work.
