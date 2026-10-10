"""Validate and translate an official Digital Sky GeoJSON export into zone records.

This deliberately accepts only geometries which can be matched to a zone ID already
recorded in ``data/official_airspace/hyderabad_digital_sky_metadata.json``.  It is
not a screen-scraper: operators must provide an official, coordinate-bearing export.
"""
import json
from pathlib import Path

import config


OFFICIAL_DIR = config.DATA_DIR / "official_airspace"
METADATA_PATH = OFFICIAL_DIR / "hyderabad_digital_sky_metadata.json"
GEOJSON_PATH = OFFICIAL_DIR / "hyderabad_airspace.geojson"
ID_FIELDS = ("digital_sky_zone_id", "digitalSkyZoneId", "zone_id", "zoneId", "id")


def _read_json(path: Path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _zone_id(properties):
    for key in ID_FIELDS:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError("official airspace feature is missing a Digital Sky zone ID")


def official_zone_records(geojson_path=GEOJSON_PATH, metadata_path=METADATA_PATH):
    """Return validated MongoDB zone documents from an official GeoJSON FeatureCollection.

    The file may contain a subset of the metadata list, but it may not invent IDs or
    omit a Polygon/MultiPolygon geometry.  The generated zone IDs are namespaced so
    they cannot collide with OSM-derived zones.
    """
    metadata = _read_json(Path(metadata_path))
    if metadata.get("geometry_status") != "pending_official_coordinates":
        raise ValueError("official airspace metadata has an unexpected geometry status")
    known = {z["digital_sky_zone_id"]: z for z in metadata["zones"]}
    geojson = _read_json(Path(geojson_path))
    if geojson.get("type") != "FeatureCollection" or not isinstance(geojson.get("features"), list):
        raise ValueError("official airspace must be a GeoJSON FeatureCollection")

    records, seen = [], set()
    for feature in geojson["features"]:
        if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise ValueError("official airspace contains an invalid GeoJSON feature")
        zone_id = _zone_id(feature["properties"])
        if zone_id not in known:
            raise ValueError(f"official airspace contains unknown Digital Sky zone ID: {zone_id}")
        if zone_id in seen:
            raise ValueError(f"official airspace contains duplicate Digital Sky zone ID: {zone_id}")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"} or not geometry.get("coordinates"):
            raise ValueError(f"official airspace zone {zone_id} has no Polygon or MultiPolygon geometry")
        seen.add(zone_id)
        meta = known[zone_id]
        airspace_class = meta["airspace_class"]
        records.append({
            "zone_id": f"digital-sky:{zone_id}",
            "digital_sky_zone_id": zone_id,
            "name": f"Digital Sky {meta['zone_detail']} ({zone_id})",
            "zone_type": f"digital_sky_{airspace_class}",
            "rule_ids": [f"R-DS-{airspace_class.upper()}"],
            "geometry": geometry,
            "source": metadata["source"]["map_url"],
            "source_retrieved_on": metadata["source"].get("captured_on"),
            "starts_at": meta["starts_at"],
            "ends_at": meta["ends_at"],
            "altitude_agl_ft": meta["altitude_agl_ft"],
        })
    return records


def available_official_zone_records():
    """Return no records until an official GeoJSON export has intentionally been added."""
    return official_zone_records() if GEOJSON_PATH.exists() else []
