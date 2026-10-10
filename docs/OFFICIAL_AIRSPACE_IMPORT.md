# Official Digital Sky airspace import

`data/official_airspace/hyderabad_digital_sky_metadata.json` records the zone identifiers and restrictions observed on the official Digital Sky map for Hyderabad. It intentionally contains no geometry.

The official map is the legal source for red, yellow and green classification. A screenshot is not an authoritative geometry source: it cannot support an exact point-in-polygon decision.

## Required next input

Add one official coordinate source to `data/official_airspace/`:

- `hyderabad_airspace.geojson` (preferred)
- `hyderabad_airspace.kml`
- an official JSON/API response with polygon coordinates

The imported feature must retain the Digital Sky zone ID (for example, `DSRZONE0003145`), the airspace class, validity dates, altitude limits, source URL and retrieval date. Do not use browser cookies, bearer tokens or credentials in the repository.

Until geometry arrives, the metadata may be cited in the UI but must not be used to decide whether a point is inside an official restriction.
