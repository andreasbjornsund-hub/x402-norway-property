"""Tests for the Kartverket response parsers."""


def _addr_search_payload():
    return {
        "metadata": {"totaltAntallTreff": 2},
        "adresser": [
            {
                "adressetekst": "Karl Johans gate 1",
                "postnummer": "0154",
                "poststed": "OSLO",
                "kommunenavn": "Oslo",
                "kommunenummer": "0301",
                "representasjonspunkt": {"lat": 59.9114, "lon": 10.7349},
            },
            {
                "adressetekst": "Karl Johans gate 2",
                "postnummer": "0154",
                "poststed": "OSLO",
                "kommunenavn": "Oslo",
                "kommunenummer": "0301",
                "representasjonspunkt": {"lat": 59.9118, "lon": 10.7355},
            },
        ],
    }


def test_address_search_basic(parsers_module):
    out = parsers_module.parse_address_search(_addr_search_payload(), limit=10)
    assert out["total"] == 2
    assert len(out["results"]) == 2
    assert out["results"][0]["address"] == "Karl Johans gate 1"
    assert out["results"][0]["postal_code"] == "0154"
    assert out["results"][0]["city"] == "OSLO"
    assert out["results"][0]["lat"] == 59.9114
    assert out["results"][0]["municipality_code"] == "0301"


def test_address_search_respects_limit(parsers_module):
    out = parsers_module.parse_address_search(_addr_search_payload(), limit=1)
    assert len(out["results"]) == 1


def test_address_search_empty(parsers_module):
    out = parsers_module.parse_address_search({}, limit=10)
    assert out == {"results": [], "total": 0}


def test_address_reverse_with_distance(parsers_module):
    payload = {"adresser": [{
        "adressetekst": "Karl Johans gate 1",
        "postnummer": "0154", "poststed": "OSLO",
        "kommunenavn": "Oslo", "kommunenummer": "0301",
        "representasjonspunkt": {"lat": 59.9115, "lon": 10.7350},
    }]}
    out = parsers_module.parse_address_reverse(payload, query_lat=59.9114, query_lon=10.7349)
    assert out["address"] == "Karl Johans gate 1"
    assert out["distance_m"] is not None
    assert 0 <= out["distance_m"] < 25  # very close


def test_address_reverse_no_match(parsers_module):
    out = parsers_module.parse_address_reverse({"adresser": []}, query_lat=59.0, query_lon=10.0)
    assert out["address"] is None


def test_place_search_norwegian(parsers_module):
    payload = {
        "metadata": {"totaltAntallTreff": 1},
        "navn": [{
            "skrivemåte": "Galdhøpiggen",
            "navneobjekttype": "Fjelltopp",
            "kommuner": [{"kommunenavn": "Lom", "kommunenummer": "3434", "fylkesnavn": "Innlandet"}],
            "representasjonspunkt": {"lat": 61.6363, "lon": 8.3124},
        }],
    }
    out = parsers_module.parse_place_search(payload)
    assert out["total"] == 1
    p = out["results"][0]
    assert p["name"] == "Galdhøpiggen"
    assert p["type"] == "Fjelltopp"
    assert p["municipality"] == "Lom"
    assert p["county"] == "Innlandet"
    assert p["lat"] == 61.6363


def test_place_search_dict_kommune(parsers_module):
    """Some Stedsnavn responses give a single kommune dict instead of a list."""
    payload = {"navn": [{
        "skrivemåte": "Mjøsa",
        "navneobjekttype": "Innsjø",
        "kommune": {"kommunenavn": "Hamar", "kommunenummer": "3403", "fylkesnavn": "Innlandet"},
        "representasjonspunkt": {"lat": 60.81, "lon": 11.07},
    }]}
    out = parsers_module.parse_place_search(payload)
    assert out["results"][0]["municipality"] == "Hamar"


def test_elevation_simple(parsers_module):
    payload = {"punkter": [{"z": 2469, "datakilde": "DTM1"}]}
    out = parsers_module.parse_elevation(payload, lat=61.6363, lon=8.3124)
    assert out["elevation_m"] == 2469
    assert out["source"] == "DTM1"
    assert out["lat"] == 61.6363


def test_elevation_no_data(parsers_module):
    out = parsers_module.parse_elevation({"punkter": []}, lat=0, lon=0)
    assert out["elevation_m"] is None


def test_property_basic(parsers_module):
    payload = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.36802, 63.35266]},
        "properties": {
            "kommunenummer": "5001", "gardsnummer": 315, "bruksnummer": 53,
            "festenummer": 0, "seksjonsnummer": 0,
            "matrikkelnummertekst": "315/53", "lokalid": 278936478,
            "objekttype": "Teig", "oppdateringsdato": "2020-06-16T07:12:12",
            "hovedområde": True,
        },
    }]}
    out = parsers_module.parse_property(payload, knr="5001", gnr=315, bnr=53)
    assert out["municipality_code"] == "5001"
    assert out["gnr"] == 315 and out["bnr"] == 53
    assert out["matrikkelnummer"] == "315/53"
    assert out["lokalid"] == 278936478
    assert out["object_type"] == "Teig"
    assert out["lat"] == 63.35266 and out["lon"] == 10.36802
    assert out["is_primary_parcel"] is True


def test_property_picks_hovedomrade_when_multiple(parsers_module):
    """If multiple Teig features exist, prefer the hovedområde one."""
    payload = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 60.0]},
         "properties": {"kommunenummer": "0301", "gardsnummer": 1, "bruksnummer": 1,
                        "matrikkelnummertekst": "1/1", "objekttype": "Teig",
                        "hovedområde": False}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.0, 61.0]},
         "properties": {"kommunenummer": "0301", "gardsnummer": 1, "bruksnummer": 1,
                        "matrikkelnummertekst": "1/1", "objekttype": "Teig",
                        "hovedområde": True}},
    ]}
    out = parsers_module.parse_property(payload, knr="0301", gnr=1, bnr=1)
    assert out["lat"] == 61.0 and out["lon"] == 11.0
    assert out["is_primary_parcel"] is True


def test_property_empty_features_returns_none(parsers_module):
    """Empty features → None so caller can map to 404."""
    assert parsers_module.parse_property({"type": "FeatureCollection", "features": []},
                                         knr="0301", gnr=1, bnr=1) is None
    assert parsers_module.parse_property({}, knr="0301", gnr=1, bnr=1) is None


def test_in_norway_bounds(parsers_module):
    assert parsers_module.in_norway(59.91, 10.75)   # Oslo
    assert parsers_module.in_norway(78.22, 15.62)   # Svalbard
    assert not parsers_module.in_norway(48.85, 2.35)  # Paris
    assert not parsers_module.in_norway(0, 0)
