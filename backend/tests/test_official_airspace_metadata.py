import json

import config


def test_official_airspace_metadata_is_well_formed_and_geometry_is_not_claimed():
    path = config.DATA_DIR / "official_airspace" / "hyderabad_digital_sky_metadata.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["geometry_status"] == "pending_official_coordinates"
    ids = [zone["digital_sky_zone_id"] for zone in data["zones"]]
    assert len(ids) == len(set(ids))
    assert {"DSAR5ZONE00094", "DSAY8ZONE000138", "DSAY12ZONE000138"} <= set(ids)
    assert all("geometry" not in zone for zone in data["zones"])
