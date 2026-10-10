# Official Digital Sky airspace import

`data/official_airspace/hyderabad_digital_sky_metadata.json` records the zone identifiers and restrictions observed on the official Digital Sky map for Hyderabad. It intentionally contains no geometry.

The official map is the legal source for red, yellow and green classification. A screenshot is not an authoritative geometry source: it cannot support an exact point-in-polygon decision.

## Required next input

Add an official **GeoJSON FeatureCollection** as `data/official_airspace/hyderabad_airspace.geojson` (preferred). Its feature properties must include one of `digital_sky_zone_id`, `digitalSkyZoneId`, `zone_id`, `zoneId`, or `id`, containing an ID already recorded in the metadata file.

On the next `python backend/load_data.py`, the loader validates every feature before inserting it. It rejects unknown or duplicated zone IDs and non-polygon geometries. Imported records are namespaced as `digital-sky:<Digital Sky ID>` and use the attributable red/yellow rule passages in `data/rules.json`.

Other source formats first need a conversion to that GeoJSON shape; do not place arbitrary data under this filename.

The source export should retain:

- the Digital Sky zone ID (for example, `DSRZONE0003145`),
- airspace class, validity dates and altitude limits,
- source URL and retrieval date.

Do not use browser cookies, bearer tokens or credentials in the repository.

Until geometry arrives, the metadata may be cited in the UI but must not be used to decide whether a point is inside an official restriction.
