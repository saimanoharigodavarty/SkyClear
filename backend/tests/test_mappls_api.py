import mappls_api


def test_mappls_search_is_empty_when_no_key(monkeypatch):
    monkeypatch.setattr(mappls_api.config, "MAPPLS_API_KEY", "")
    assert mappls_api.place_search("Hyderabad") == []


def test_mappls_search_never_claims_airspace_status(monkeypatch):
    monkeypatch.setattr(mappls_api.config, "MAPPLS_API_KEY", "private-key")
    monkeypatch.setattr(mappls_api, "_get_json", lambda _: {"suggestedLocations": [{"placeName": "Charminar", "placeAddress": "Hyderabad", "eLoc": "ABC123"}]})
    result = mappls_api.place_search("Charminar")
    assert result == [{"name": "Charminar", "address": "Hyderabad", "eloc": "ABC123", "provider": "Mappls place search, not airspace data"}]


def test_mappls_place_detail_returns_only_location_context(monkeypatch):
    monkeypatch.setattr(mappls_api.config, "MAPPLS_API_KEY", "private-key")
    monkeypatch.setattr(mappls_api, "_get_json", lambda _: {"name": "Charminar", "address": "Hyderabad", "latitude": "17.3616", "longitude": "78.4747"})
    assert mappls_api.place_detail("ABC123")["lat"] == 17.3616
