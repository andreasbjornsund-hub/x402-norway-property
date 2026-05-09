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
    payload = {"eiendommer": [{
        "kommunenavn": "Oslo",
        "areal": 1250,
        "eiendomstype": "Bolig",
        "adressetekst": "Exampleveien 1",
        "representasjonspunkt": {"lat": 59.92, "lon": 10.75},
    }]}
    out = parsers_module.parse_property(payload, knr="0301", gnr=208, bnr=350)
    assert out["municipality_code"] == "0301"
    assert out["municipality"] == "Oslo"
    assert out["gnr"] == 208 and out["bnr"] == 350
    assert out["area_sqm"] == 1250
    assert out["property_type"] == "Bolig"


def test_property_empty_response(parsers_module):
    out = parsers_module.parse_property({}, knr="0301", gnr=1, bnr=1)
    # Defensive: should still return a sensible shape
    assert out["municipality_code"] == "0301"
    assert out["gnr"] == 1
    assert out["bnr"] == 1


def test_in_norway_bounds(parsers_module):
    assert parsers_module.in_norway(59.91, 10.75)   # Oslo
    assert parsers_module.in_norway(78.22, 15.62)   # Svalbard
    assert not parsers_module.in_norway(48.85, 2.35)  # Paris
    assert not parsers_module.in_norway(0, 0)
