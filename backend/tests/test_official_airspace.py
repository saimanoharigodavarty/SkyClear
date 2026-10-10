import json

import pytest

from official_airspace import official_zone_records


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _metadata():
    return {
        "geometry_status": "pending_official_coordinates",
        "source": {"map_url": "https://digitalsky.aai.aero/", "captured_on": "2026-10-10"},
        "zones": [{
            "digital_sky_zone_id": "DSRZONE0003145", "airspace_class": "red",
            "zone_detail": "Airspace - Red Zone", "starts_at": None, "ends_at": None,
            "altitude_agl_ft": {"min": 0, "max": 50000},
        }],
    }


def _feature(zone_id="DSRZONE0003145"):
    return {"type": "Feature", "properties": {"digital_sky_zone_id": zone_id}, "geometry": {
        "type": "Polygon", "coordinates": [[[78.4, 17.3], [78.5, 17.3], [78.5, 17.4], [78.4, 17.3]]],
    }}


def test_official_geojson_is_matched_to_recorded_digital_sky_metadata(tmp_path):
    metadata, geojson = tmp_path / "metadata.json", tmp_path / "zones.geojson"
    _write(metadata, _metadata())
    _write(geojson, {"type": "FeatureCollection", "features": [_feature()]})

    zones = official_zone_records(geojson, metadata)

    assert zones[0]["zone_id"] == "digital-sky:DSRZONE0003145"
    assert zones[0]["zone_type"] == "digital_sky_red"
    assert zones[0]["rule_ids"] == ["R-DS-RED"]


def test_official_geojson_rejects_an_unknown_or_non_polygon_zone(tmp_path):
    metadata, geojson = tmp_path / "metadata.json", tmp_path / "zones.geojson"
    _write(metadata, _metadata())
    _write(geojson, {"type": "FeatureCollection", "features": [_feature("NOT-RECORDED")]})
    with pytest.raises(ValueError, match="unknown"):
        official_zone_records(geojson, metadata)

    bad = _feature()
    bad["geometry"] = {"type": "Point", "coordinates": [78.4, 17.3]}
    _write(geojson, {"type": "FeatureCollection", "features": [bad]})
    with pytest.raises(ValueError, match="Polygon"):
        official_zone_records(geojson, metadata)
