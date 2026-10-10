# Zone ingestion

`osm_zones.py` makes one Overpass request for mapped physical sites in the Hyderabad bounding box and writes `data/zones_osm_hyderabad.geojson`.

Run from the repository root:

```powershell
python ingestion\osm_zones.py
python backend\build_zones.py
python backend\load_data.py
```

For a reproducible offline conversion from a previously saved response:

```powershell
python ingestion\osm_zones.py --input data\osm_hyderabad_raw.json
```

The raw response is cached locally but gitignored. The normalized GeoJSON is versioned and retains the OSM element ID, element URL, fetch date, and the attribution `OpenStreetMap contributors, ODbL 1.0` on every feature.

OpenStreetMap tags describe mapped physical features, not legal drone restrictions. Airport and military features use the project's existing rule mappings. Government, prison, power, and stadium features are stored as `unverified_context` with no rule IDs, so the engine returns `cannot_determine` rather than inventing a legal restriction. Point-only features receive small, explicitly labelled derived buffers; mapped polygons retain their OSM boundary.

The public Overpass API is for small, occasional jobs. Do not call it from the application or run ingestion requests in parallel. For frequent or larger rebuilds, use a regional extract and `osmium` instead.

Sources:

- OpenStreetMap copyright and licence: https://www.openstreetmap.org/copyright
- Overpass API and usage guidance: https://wiki.openstreetmap.org/wiki/Overpass_API
