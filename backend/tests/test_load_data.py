import load_data


class FakeZones:
    def __init__(self):
        self.indexes = []

    def create_index(self, keys, **options):
        self.indexes.append((keys, options))


class FakeDb:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.commands = []
        self.created = []
        self.zones = FakeZones()

    def list_collection_names(self):
        return self.existing

    def command(self, *args, **options):
        self.commands.append((args, options))

    def create_collection(self, name, **options):
        self.created.append((name, options))


def test_zone_validator_requires_identity_geometry_rules_and_source():
    schema = load_data.ZONE_VALIDATOR["$jsonSchema"]
    assert schema["required"] == ["zone_id", "name", "zone_type", "geometry", "rule_ids", "source"]


def test_zone_validator_accepts_polygon_and_multipolygon_geojson():
    geometry = load_data.ZONE_VALIDATOR["$jsonSchema"]["properties"]["geometry"]
    assert geometry["required"] == ["type", "coordinates"]
    assert geometry["properties"]["type"]["enum"] == ["Polygon", "MultiPolygon"]


def test_existing_zones_collection_is_updated_with_strict_validation():
    db = FakeDb(existing=["zones"])
    load_data.ensure_zones_collection(db)
    args, options = db.commands[0]
    assert args == ("collMod", "zones")
    assert options == {"validator": load_data.ZONE_VALIDATOR, "validationLevel": "strict", "validationAction": "error"}


def test_missing_zones_collection_is_created_with_strict_validation():
    db = FakeDb()
    load_data.ensure_zones_collection(db)
    name, options = db.created[0]
    assert name == "zones"
    assert options["validator"] == load_data.ZONE_VALIDATOR
    assert options["validationLevel"] == "strict"
    assert options["validationAction"] == "error"


def test_zone_indexes_cover_geo_identity_and_type_queries():
    db = FakeDb()
    load_data.ensure_zone_indexes(db)
    assert db.zones.indexes == [
        ([("geometry", "2dsphere")], {}),
        ("zone_id", {"unique": True}),
        ("zone_type", {}),
    ]
