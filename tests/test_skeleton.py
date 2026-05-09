"""Smoke tests on the skeleton — verify the catalog/manifest contract holds.

When you replace the example endpoint with real ones, keep these tests
working: they verify the discovery layer is wired correctly.
"""


async def test_health(main_module):
    resp = await main_module.health()
    assert resp["status"] == "ok"


async def test_api_status_shape(main_module):
    resp = await main_module.api_status()
    assert resp["status"] == "ok"
    assert isinstance(resp["uptime_seconds"], int)


async def test_services_manifest_uses_catalog(main_module):
    resp = await main_module.services_manifest()
    paths_in_manifest = [e["path"] for e in resp["endpoints"]]
    paths_in_catalog = [e["path"] for e in main_module.ENDPOINT_CATALOG]
    assert paths_in_manifest == paths_in_catalog


async def test_x402_manifest_payTo_matches_env(main_module):
    import os
    resp = await main_module.x402_manifest()
    assert resp["x402Version"] == 2
    assert resp["payment"]["payTo"] == os.environ["EVM_ADDRESS"]


async def test_x402_manifest_paid_amounts_match_catalog(main_module):
    resp = await main_module.x402_manifest()
    catalog_paid = {
        e["path"]: e["amount_atomic"]
        for e in main_module.ENDPOINT_CATALOG
        if e["amount_atomic"] is not None
    }
    manifest_paid = {
        e["path"]: e["accepts"][0]["amount"]
        for e in resp["endpoints"]
        if e["accepts"]
    }
    assert manifest_paid == catalog_paid


async def test_paid_route_atomic_amounts_match_price_usd(main_module):
    """USDC has 6 decimals — atomic = USD * 1_000_000."""
    for e in main_module.ENDPOINT_CATALOG:
        if e["price_usd"] is None:
            continue
        usd = float(e["price_usd"].replace("$", ""))
        expected = str(int(round(usd * 10**6)))
        assert e["amount_atomic"] == expected, (
            f"{e['path']}: ${usd} should be amount_atomic={expected}, got {e['amount_atomic']}"
        )


async def test_routes_built_from_paid_entries(main_module):
    paid = [e for e in main_module.ENDPOINT_CATALOG if e["route_pattern"] is not None]
    assert set(main_module.routes.keys()) == {e["route_pattern"] for e in paid}


async def test_llms_txt_lists_all_catalog_entries(main_module):
    resp = await main_module.llms_txt()
    body = resp.body.decode()
    for e in main_module.ENDPOINT_CATALOG:
        assert e["path"] in body, f"missing {e['path']} in /llms.txt"
