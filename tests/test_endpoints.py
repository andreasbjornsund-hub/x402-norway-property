"""End-to-end tests for HTTP handlers (Kartverket stubbed)."""
import pytest
from fastapi import HTTPException, Response


# ── Free endpoints ──────────────────────────────────────────────────


async def test_health(main_module):
    r = await main_module.health()
    assert r["status"] == "ok"
    assert r["service"] == "norway-property"


async def test_municipalities(main_module):
    r = await main_module.list_municipalities()
    assert r["count"] >= 30
    assert any(m["code"] == "0301" for m in r["municipalities"])


async def test_api_status(main_module):
    r = await main_module.api_status()
    assert r["upstream"] == "ws.geonorge.no"
    for k in ("entries", "fresh", "max"):
        assert k in r["cache"]


# ── Manifest contract ───────────────────────────────────────────────


async def test_x402_manifest(main_module):
    r = await main_module.x402_manifest()
    paid = [e for e in r["endpoints"] if e["accepts"]]
    free = [e for e in r["endpoints"] if not e["accepts"]]
    assert len(paid) == 6  # /address, /address/reverse, /place, /elevation, /distance, /property
    assert len(free) == 3  # /municipalities, /health, /api-status


async def test_atomic_amounts_match_price(main_module):
    for e in main_module.ENDPOINT_CATALOG:
        if e["price_usd"] is None:
            continue
        usd = float(e["price_usd"].replace("$", ""))
        expected = str(int(round(usd * 10**6)))
        assert e["amount_atomic"] == expected, f"{e['path']}: {expected} vs {e['amount_atomic']}"


# ── Paid handlers ───────────────────────────────────────────────────


async def test_address_search_happy_path(main_module, fake_kv):
    fake_kv.stub("/adresser/v1/sok", 200, {
        "metadata": {"totaltAntallTreff": 1},
        "adresser": [{
            "adressetekst": "Karl Johans gate 1",
            "postnummer": "0154", "poststed": "OSLO",
            "kommunenavn": "Oslo", "kommunenummer": "0301",
            "representasjonspunkt": {"lat": 59.9114, "lon": 10.7349},
        }],
    })
    out = await main_module.address_search(response=Response(), q="karl johans", limit=10)
    assert out["total"] == 1
    assert out["results"][0]["address"] == "Karl Johans gate 1"


async def test_address_search_503_on_upstream(main_module, fake_kv):
    fake_kv.stub("/adresser/v1/sok", 502)
    with pytest.raises(HTTPException) as exc:
        await main_module.address_search(response=Response(), q="x", limit=10)
    assert exc.value.status_code == 503


async def test_address_reverse_rejects_out_of_norway(main_module):
    with pytest.raises(HTTPException) as exc:
        await main_module.address_reverse(response=Response(), lat=48.85, lon=2.35, radius_m=200)
    assert exc.value.status_code == 400


async def test_address_reverse_404_when_no_hit(main_module, fake_kv):
    fake_kv.stub("/adresser/v1/punkt", 200, {"adresser": []})
    with pytest.raises(HTTPException) as exc:
        await main_module.address_reverse(response=Response(), lat=59.9, lon=10.7, radius_m=10)
    assert exc.value.status_code == 404


async def test_place_search_happy_path(main_module, fake_kv):
    fake_kv.stub("/stedsnavn/v1/navn", 200, {
        "metadata": {"totaltAntallTreff": 1},
        "navn": [{
            "skrivemåte": "Galdhøpiggen",
            "navneobjekttype": "Fjelltopp",
            "kommuner": [{"kommunenavn": "Lom", "kommunenummer": "3434", "fylkesnavn": "Innlandet"}],
            "representasjonspunkt": {"lat": 61.6363, "lon": 8.3124},
        }],
    })
    out = await main_module.place_search(response=Response(), name="galdh", limit=10)
    assert out["results"][0]["name"] == "Galdhøpiggen"
    assert out["results"][0]["type"] == "Fjelltopp"


async def test_elevation_happy_path(main_module, fake_kv):
    fake_kv.stub("/hoydedata/v1/punkt", 200, {"punkter": [{"z": 2469, "datakilde": "DTM1"}]})
    out = await main_module.elevation(response=Response(), lat=61.6363, lon=8.3124)
    assert out["elevation_m"] == 2469


async def test_elevation_404_when_no_data(main_module, fake_kv):
    fake_kv.stub("/hoydedata/v1/punkt", 200, {"punkter": []})
    with pytest.raises(HTTPException) as exc:
        await main_module.elevation(response=Response(), lat=78.5, lon=20.0)
    assert exc.value.status_code == 404


async def test_distance_endpoint_no_upstream_call(main_module, fake_kv):
    """Distance is pure math — no upstream call regardless of stubs."""
    out = await main_module.distance_endpoint(
        response=Response(), from_lat=59.91, from_lon=10.75, to_lat=60.39, to_lon=5.32,
    )
    assert 300 < out["distance_km"] < 320
    assert 0 <= out["bearing_deg"] < 360
    assert len(fake_kv.calls) == 0


async def test_property_happy_path(main_module, fake_kv):
    fake_kv.stub("/eiendomsinfo/v1/eiendom", 200, {"eiendommer": [{
        "kommunenavn": "Oslo", "areal": 1250, "eiendomstype": "Bolig",
        "adressetekst": "Exampleveien 1",
        "representasjonspunkt": {"lat": 59.92, "lon": 10.75},
    }]})
    out = await main_module.property_endpoint(response=Response(), knr="0301", gnr=208, bnr=350)
    assert out["municipality"] == "Oslo"
    assert out["area_sqm"] == 1250


async def test_property_zero_pads_short_knr(main_module, fake_kv):
    fake_kv.stub("/eiendomsinfo/v1/eiendom", 200, {"eiendommer": [{}]})
    await main_module.property_endpoint(response=Response(), knr="301", gnr=1, bnr=1)
    # Verify the call used 4-digit kommunenr
    sent_params = fake_kv.calls[-1][1]
    assert sent_params.get("kommunenr") == "0301"


async def test_property_404_when_upstream_404(main_module, fake_kv):
    fake_kv.stub("/eiendomsinfo/v1/eiendom", 404)
    with pytest.raises(HTTPException) as exc:
        await main_module.property_endpoint(response=Response(), knr="0301", gnr=999, bnr=999)
    assert exc.value.status_code == 404
