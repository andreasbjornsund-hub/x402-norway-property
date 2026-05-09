"""Kartverket / Geonorge upstream client.

APIs (all free, no auth, JSON):

  - Addresses:    https://ws.geonorge.no/adresser/v1/
                  /sok?sok=<query>&treffPerSide=N&utkoordsys=4326
                  /punkt?lat=<lat>&lon=<lon>&radius=<m>&utkoordsys=4326
  - Place names:  https://ws.geonorge.no/stedsnavn/v1/
                  /navn?sok=<query>&utkoordsys=4326&treffPerSide=N
  - Elevation:    https://ws.geonorge.no/hoydedata/v1/
                  /punkt?nord=<lat>&ost=<lon>&koordsys=4258
  - Property:     https://ws.geonorge.no/eiendomsinfo/v1/eiendom
                  ?kommunenr=<knr>&gaardsnr=<gnr>&bruksnr=<bnr>

`utkoordsys=4326` and `koordsys=4258` both yield WGS84 / ETRS89 lat/lon
coordinates suitable for downstream display.

Rate limit: Kartverket asks for "fair use" (no published number). We cap
ourselves at 10 concurrent requests as a courtesy.
"""
import asyncio

import httpx

import cache


USER_AGENT = "x402agent-norway-property/1.0 github.com/andreasbjornsund-hub"

ADDR_BASE = "https://ws.geonorge.no/adresser/v1"
PLACE_BASE = "https://ws.geonorge.no/stedsnavn/v1"
ELEVATION_BASE = "https://ws.geonorge.no/hoydedata/v1"
PROPERTY_BASE = "https://ws.geonorge.no/eiendomsinfo/v1"

_SEM = asyncio.Semaphore(10)


class KartverketError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Kartverket {status_code}: {message}")


async def _get(client: httpx.AsyncClient, url: str, params: dict, ttl: float, key_extra: str = "") -> tuple[dict, bool]:
    """GET an endpoint with caching. Returns (json, cache_hit)."""
    import json as _json
    cache_key = f"kv:{url}:{key_extra}:{_json.dumps(params, sort_keys=True)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, True
    async with _SEM:
        resp = await client.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise KartverketError(resp.status_code, resp.text[:300])
    data = resp.json()
    cache.put(cache_key, data, ttl)
    return data, False


async def address_search(client: httpx.AsyncClient, query: str, limit: int = 10, ttl: float = 7 * 86400.0):
    """Free-text address search."""
    return await _get(
        client,
        f"{ADDR_BASE}/sok",
        {"sok": query, "treffPerSide": min(max(1, limit), 50), "utkoordsys": 4326},
        ttl,
        key_extra="addr_search",
    )


async def address_reverse(client: httpx.AsyncClient, lat: float, lon: float, radius_m: int = 200, ttl: float = 7 * 86400.0):
    """Reverse geocode — nearest addresses to a coordinate, in meters."""
    return await _get(
        client,
        f"{ADDR_BASE}/punkt",
        {"lat": lat, "lon": lon, "radius": radius_m, "utkoordsys": 4326, "treffPerSide": 1},
        ttl,
        key_extra="addr_reverse",
    )


async def place_search(client: httpx.AsyncClient, query: str, limit: int = 10, ttl: float = 7 * 86400.0):
    """Place name search (cities, mountains, lakes, etc.)."""
    return await _get(
        client,
        f"{PLACE_BASE}/navn",
        {"sok": query, "treffPerSide": min(max(1, limit), 50), "utkoordsys": 4326},
        ttl,
        key_extra="place_search",
    )


async def elevation(client: httpx.AsyncClient, lat: float, lon: float, ttl: float = 30 * 86400.0):
    """Elevation at a point in metres above sea level (WGS84/ETRS89 lat/lon)."""
    return await _get(
        client,
        f"{ELEVATION_BASE}/punkt",
        {"nord": lat, "ost": lon, "koordsys": 4258},
        ttl,
        key_extra="elev",
    )


async def property_lookup(client: httpx.AsyncClient, knr: str, gnr: int, bnr: int, ttl: float = 7 * 86400.0):
    """Cadastral lookup by (kommunenummer, gårdsnummer, bruksnummer)."""
    return await _get(
        client,
        f"{PROPERTY_BASE}/eiendom",
        {"kommunenr": knr, "gaardsnr": gnr, "bruksnr": bnr},
        ttl,
        key_extra="property",
    )
