"""
x402-norway-property — Norwegian Property & Address

x402 micropayment API wrapping Kartverket's free Geonorge web services.

Endpoints (free):
  GET /                       — landing page (HTML or JSON)
  GET /health                 — health check
  GET /api-status             — uptime + cache shape
  GET /municipalities         — list ~50 Norwegian municipalities + codes
  GET /services.json          — agent-readable services manifest
  GET /llms.txt               — LLMs.txt for AI crawlers
  GET /robots.txt             — robots policy
  GET /.well-known/x402.json  — x402 agent-discovery manifest

Endpoints (paid, USDC on Base):
  GET /address                $0.005   free-text address search (Kartverket)
  GET /address/reverse        $0.005   reverse geocode coords → nearest address
  GET /place                  $0.005   place-name search (cities/lakes/mountains)
  GET /elevation              $0.005   elevation at coords (Kartverket DTM)
  GET /distance               $0.005   haversine distance + bearing (no upstream)
  GET /property               $0.01    cadastral lookup by knr/gnr/bnr

Data: Kartverket / Geonorge (https://ws.geonorge.no). All free, no API
key needed. We respect their fair-use policy (10 concurrent max). Address
and place results cached 7d, elevation 30d, property 7d.
"""
import os
import time
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import cache
import distance as dist
import kartverket_client as kv
from kartverket_client import KartverketError
import municipalities
import parsers

from cdp_auth import create_cdp_auth_provider

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────

SERVICE_ID = "norway-property"
SERVICE_NAME = "Norwegian Property & Address"
SERVICE_DESCRIPTION = (
    "Address search, reverse geocoding, place-name lookup, elevation, distance, "
    "and cadastral data for Norway. Powered by Kartverket. Pay per query with USDC via x402."
)
SERVICE_CATEGORY = "data"

EVM_ADDRESS = os.getenv("EVM_ADDRESS")
EVM_NETWORK: Network = "eip155:8453"
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")
SITE_URL = os.getenv("SITE_URL", "https://x402-norway-property.fly.dev")
USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

TTL_ADDR = int(os.getenv("TTL_ADDR", str(7 * 86400)))      # 7 d
TTL_PLACE = int(os.getenv("TTL_PLACE", str(7 * 86400)))    # 7 d
TTL_ELEV = int(os.getenv("TTL_ELEV", str(30 * 86400)))     # 30 d
TTL_PROP = int(os.getenv("TTL_PROP", str(7 * 86400)))      # 7 d

if not EVM_ADDRESS:
    raise ValueError("Set EVM_ADDRESS in .env")

# ── FastAPI app ─────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await _http.aclose()


app = FastAPI(
    title=SERVICE_NAME,
    description=SERVICE_DESCRIPTION,
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

import json as _json

cdp_auth = None
if "cdp.coinbase.com" in FACILITATOR_URL:
    cdp_auth = create_cdp_auth_provider()
facilitator_config = FacilitatorConfig(url=FACILITATOR_URL, auth_provider=cdp_auth)
facilitator = HTTPFacilitatorClient(facilitator_config)

_CAIP2_TO_V1 = {"eip155:8453": "base", "eip155:84532": "base-sepolia"}


def _v2_payload_to_v1(payload_dict: dict) -> dict:
    v1 = {"x402Version": 1}
    v1["scheme"] = payload_dict.get("scheme", "exact")
    raw_net = payload_dict.get("network", EVM_NETWORK)
    v1["network"] = _CAIP2_TO_V1.get(raw_net, raw_net)
    v1["payload"] = payload_dict.get("payload", payload_dict)
    return v1


def _v2_requirements_to_v1(req_dict: dict) -> dict:
    raw_net = req_dict.get("network", EVM_NETWORK)
    extra = req_dict.get("extra", {})
    if isinstance(extra, str):
        try:
            extra = _json.loads(extra)
        except Exception:
            extra = {}
    v1 = {
        "scheme": req_dict.get("scheme", "exact"),
        "network": _CAIP2_TO_V1.get(raw_net, raw_net),
        "maxAmountRequired": req_dict.get("amount", req_dict.get("maxAmountRequired", "0")),
        "resource": req_dict.get("resource", ""),
        "description": req_dict.get("description", ""),
        "mimeType": req_dict.get("mimeType", req_dict.get("mime_type", "application/json")),
        "asset": req_dict.get("asset", ""),
        "payTo": req_dict.get("payTo", req_dict.get("pay_to", "")),
        "maxTimeoutSeconds": req_dict.get("maxTimeoutSeconds", req_dict.get("max_timeout_seconds", 300)),
        "extra": extra,
    }
    extensions = req_dict.get("extensions", {})
    bazaar = extensions.get("bazaar", {})
    if bazaar.get("info"):
        v1["outputSchema"] = bazaar["info"]
    return v1


_orig_verify = facilitator._verify_http
_orig_settle = facilitator._settle_http


async def _v1_verify(version, payload_dict, requirements_dict):
    return await _orig_verify(1, _v2_payload_to_v1(payload_dict), _v2_requirements_to_v1(requirements_dict))


async def _v1_settle(version, payload_dict, requirements_dict):
    return await _orig_settle(1, _v2_payload_to_v1(payload_dict), _v2_requirements_to_v1(requirements_dict))


facilitator._verify_http = _v1_verify
facilitator._settle_http = _v1_settle

server = x402ResourceServer(facilitator)
server.register(EVM_NETWORK, ExactEvmServerScheme())

# ── Endpoint catalog ────────────────────────────────────────────────

ENDPOINT_CATALOG: list[dict] = [
    # /address/reverse must come BEFORE /address so the longer x402 route
    # pattern matches first.
    {
        "method": "GET",
        "path": "/address/reverse",
        "route_pattern": "GET /address/reverse",
        "description": "Reverse geocode WGS84 coordinates to the nearest Norwegian address.",
        "price_usd": "$0.005",
        "amount_atomic": "5000",
        "query_params": {"lat": 59.9114, "lon": 10.7349},
        "path_params": {},
        "output_example": {
            "address": "Karl Johans gate 1", "postal_code": "0154", "city": "OSLO",
            "municipality": "Oslo", "lat": 59.9114, "lon": 10.7349, "distance_m": 12,
        },
    },
    {
        "method": "GET",
        "path": "/address",
        "route_pattern": "GET /address",
        "description": "Free-text Norwegian address search via Kartverket. Returns up to 10 results with coordinates, municipality, postal code.",
        "price_usd": "$0.005",
        "amount_atomic": "5000",
        "query_params": {"q": "Karl Johans gate 1"},
        "path_params": {},
        "output_example": {
            "results": [{
                "address": "Karl Johans gate 1", "postal_code": "0154", "city": "OSLO",
                "municipality": "Oslo", "lat": 59.9114, "lon": 10.7349,
            }],
            "total": 1,
        },
    },
    {
        "method": "GET",
        "path": "/place",
        "route_pattern": "GET /place",
        "description": "Norwegian place-name search (cities, mountains, lakes, fjords, etc.) via Kartverket Stedsnavn.",
        "price_usd": "$0.005",
        "amount_atomic": "5000",
        "query_params": {"name": "Galdhøpiggen"},
        "path_params": {},
        "output_example": {
            "results": [{
                "name": "Galdhøpiggen", "type": "Fjelltopp",
                "municipality": "Lom", "county": "Innlandet",
                "lat": 61.6363, "lon": 8.3124,
            }],
            "total": 1,
        },
    },
    {
        "method": "GET",
        "path": "/elevation",
        "route_pattern": "GET /elevation",
        "description": "Elevation in metres above sea level at a WGS84/ETRS89 coordinate (Kartverket DTM).",
        "price_usd": "$0.005",
        "amount_atomic": "5000",
        "query_params": {"lat": 61.6363, "lon": 8.3124},
        "path_params": {},
        "output_example": {"lat": 61.6363, "lon": 8.3124, "elevation_m": 2469, "source": "DTM1"},
    },
    {
        "method": "GET",
        "path": "/distance",
        "route_pattern": "GET /distance",
        "description": "Great-circle distance and initial bearing between two WGS84 points (haversine).",
        "price_usd": "$0.005",
        "amount_atomic": "5000",
        "query_params": {"from_lat": 59.91, "from_lon": 10.75, "to_lat": 60.39, "to_lon": 5.32},
        "path_params": {},
        "output_example": {
            "from": {"lat": 59.91, "lon": 10.75},
            "to": {"lat": 60.39, "lon": 5.32},
            "distance_km": 305.4, "bearing_deg": 278.0,
        },
    },
    {
        "method": "GET",
        "path": "/property",
        "route_pattern": "GET /property",
        "description": "Cadastral property lookup by (kommunenummer, gårdsnummer, bruksnummer).",
        "price_usd": "$0.01",
        "amount_atomic": "10000",
        "query_params": {"knr": "0301", "gnr": 208, "bnr": 350},
        "path_params": {},
        "output_example": {
            "municipality_code": "0301", "municipality": "Oslo",
            "gnr": 208, "bnr": 350, "area_sqm": 1250, "property_type": "Bolig",
            "address": "Exampleveien 1", "lat": 59.92, "lon": 10.75,
        },
    },
    {"method": "GET", "path": "/municipalities", "route_pattern": None,
     "description": "List of supported Norwegian municipalities with 4-digit codes (free).",
     "price_usd": None, "amount_atomic": None, "query_params": {}, "path_params": {}, "output_example": None},
    {"method": "GET", "path": "/health", "route_pattern": None,
     "description": "Service health check.", "price_usd": None, "amount_atomic": None,
     "query_params": {}, "path_params": {}, "output_example": {"status": "ok"}},
    {"method": "GET", "path": "/api-status", "route_pattern": None,
     "description": "Operational status — uptime and Kartverket-cache shape.",
     "price_usd": None, "amount_atomic": None, "query_params": {}, "path_params": {}, "output_example": None},
]


def _bazaar_info(entry: dict) -> dict:
    inp = {"type": "http", "method": entry["method"]}
    if entry["query_params"]:
        inp["queryParams"] = entry["query_params"]
    if entry["path_params"]:
        inp["pathParams"] = entry["path_params"]
    return {
        "info": {"input": inp, "output": {"type": "json", "example": entry["output_example"]}},
        "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "type": "object",
                   "properties": {"input": {"type": "object"}, "output": {"type": "object"}}},
    }


def _build_paid_routes(catalog: list[dict]) -> dict[str, RouteConfig]:
    return {
        e["route_pattern"]: RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=EVM_ADDRESS, price=e["price_usd"], network=EVM_NETWORK)],
            mime_type="application/json",
            description=e["description"],
            extensions={"bazaar": _bazaar_info(e)},
        )
        for e in catalog if e["route_pattern"] is not None
    }


routes = _build_paid_routes(ENDPOINT_CATALOG)
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
# Outer middleware that polishes 402 responses to match the x402 spec:
# JSON payload in body, https:// in resource.url (Fly TLS proxy fix),
# CORS headers, and an x-payment-required v1 fallback. Must be
# registered AFTER PaymentMiddlewareASGI so it wraps it.
from x402_polish import X402ResponsePolish  # noqa: E402
app.add_middleware(X402ResponsePolish)

# ── Shared HTTP client ──────────────────────────────────────────────

_http = httpx.AsyncClient(timeout=30, headers={"Accept": "application/json"})

_PROCESS_START_TS = time.time()


# ── Discovery / metadata endpoints ──────────────────────────────────


@app.get("/")
async def landing(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept and os.path.isfile("static/index.html"):
        return FileResponse("static/index.html")
    return {
        "service": SERVICE_NAME, "version": "0.1.0", "description": SERVICE_DESCRIPTION,
        "endpoints": {e["path"]: f"{e['description']} ({e['price_usd']} USDC)" if e["price_usd"]
                      else f"{e['description']} (free)"
                      for e in ENDPOINT_CATALOG} | {"/.well-known/x402.json": "Agent discovery"},
        "payment": "x402 protocol — USDC on Base network",
        "data_source": "Kartverket / Geonorge (https://ws.geonorge.no)",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_ID, "timestamp": int(time.time())}


@app.get("/api-status")
async def api_status():
    return {
        "status": "ok", "service": SERVICE_ID, "version": "0.1.0",
        "uptime_seconds": int(time.time() - _PROCESS_START_TS),
        "upstream": "ws.geonorge.no",
        "cache": cache.stats(),
    }


@app.get("/municipalities")
async def list_municipalities():
    rows = municipalities.all_municipalities()
    return {"count": len(rows), "municipalities": rows}


@app.get("/services.json")
async def services_manifest():
    return {
        "id": SERVICE_ID, "name": SERVICE_NAME, "description": SERVICE_DESCRIPTION,
        "category": SERVICE_CATEGORY, "x402Version": 2, "networks": [EVM_NETWORK],
        "website": SITE_URL,
        "endpoints": [{"method": e["method"], "path": e["path"], "description": e["description"],
                       "price": e["price_usd"] or "$0.00", "currency": "USDC"}
                      for e in ENDPOINT_CATALOG],
    }


@app.get("/.well-known/x402.json")
async def x402_manifest():
    return {
        "x402Version": 2,
        "service": {"id": SERVICE_ID, "name": SERVICE_NAME, "description": SERVICE_DESCRIPTION,
                    "category": SERVICE_CATEGORY, "website": SITE_URL,
                    "documentation": f"{SITE_URL}/llms.txt",
                    "servicesManifest": f"{SITE_URL}/services.json"},
        "payment": {"schemes": ["exact"], "networks": [EVM_NETWORK],
                    "asset": {"symbol": "USDC", "decimals": 6, "address": USDC_BASE_MAINNET, "chain": "Base"},
                    "payTo": EVM_ADDRESS, "facilitator": FACILITATOR_URL},
        "endpoints": [
            {"method": e["method"], "path": e["path"], "description": e["description"],
             "accepts": [{"scheme": "exact", "network": EVM_NETWORK, "asset": "USDC",
                          "amount": e["amount_atomic"], "amountDisplay": e["price_usd"], "payTo": EVM_ADDRESS}]
                        if e["amount_atomic"] else [],
             "input": {"type": "http", "method": e["method"],
                       **({"queryParams": e["query_params"]} if e["query_params"] else {}),
                       **({"pathParams": e["path_params"]} if e["path_params"] else {})},
             "output": ({"type": "json", "example": e["output_example"]}
                        if e["output_example"] is not None else {"type": "json"})}
            for e in ENDPOINT_CATALOG
        ],
    }


@app.get("/llms.txt")
async def llms_txt():
    lines = [f"# {SERVICE_NAME}", f"> {SERVICE_DESCRIPTION}", "", "## Endpoints"]
    for e in ENDPOINT_CATALOG:
        price = f"{e['price_usd']} USDC" if e["price_usd"] else "Free"
        lines.append(f"- {e['method']} {e['path']} — {price} — {e['description']}")
    lines += [
        "", "## Payment",
        "- Protocol: x402 (HTTP 402 micropayments)",
        "- Currency: USDC on Base",
        "- No API keys or accounts needed",
        "- Agent discovery: GET /.well-known/x402.json",
        "", "## Source data",
        "- Kartverket / Geonorge (ws.geonorge.no) — addresses, place names, elevation, cadastral",
        "- Free, no API key required; we identify ourselves with a User-Agent and cap concurrency at 10",
        "- Cached: addresses 7d, place names 7d, elevation 30d, property 7d",
        "", "## Coverage",
        f"- WGS84 coordinates within Norway/Scandinavia (lat {parsers.NORWAY_LAT_MIN}-{parsers.NORWAY_LAT_MAX}, lon {parsers.NORWAY_LON_MIN}-{parsers.NORWAY_LON_MAX})",
        "- ~50 Norwegian municipalities pre-loaded (see GET /municipalities)",
        "", "## Links",
        f"- Website: {SITE_URL}",
        f"- Services manifest: {SITE_URL}/services.json",
        "",
    ]
    return PlainTextResponse("\n".join(lines), media_type="text/plain")


@app.get("/robots.txt")
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\nAllow: /\n\n"
        "User-agent: GPTBot\nAllow: /\n\n"
        "User-agent: ClaudeBot\nAllow: /\n\n"
        "User-agent: PerplexityBot\nAllow: /\n\n"
        "User-agent: Google-Extended\nAllow: /\n",
        media_type="text/plain",
    )


# ── Helpers ─────────────────────────────────────────────────────────


def _validate_coords(lat: float, lon: float) -> None:
    if not parsers.in_norway(lat, lon):
        raise HTTPException(
            400,
            f"Coordinates ({lat}, {lon}) outside coverage area "
            f"(lat {parsers.NORWAY_LAT_MIN}-{parsers.NORWAY_LAT_MAX}, "
            f"lon {parsers.NORWAY_LON_MIN}-{parsers.NORWAY_LON_MAX}).",
        )


def _set_cache_header(response: Response, hit: bool) -> None:
    response.headers["X-Cache"] = "HIT" if hit else "MISS"


# ── Paid endpoints ──────────────────────────────────────────────────


@app.get("/address")
async def address_search(
    response: Response,
    q: str = Query(..., min_length=2, max_length=200, description="Free-text search query"),
    limit: int = Query(10, ge=1, le=50),
):
    try:
        data, hit = await kv.address_search(_http, q, limit=limit, ttl=TTL_ADDR)
    except KartverketError as e:
        raise HTTPException(503, f"Kartverket upstream: {e.message}")
    _set_cache_header(response, hit)
    return parsers.parse_address_search(data, limit=limit)


@app.get("/address/reverse")
async def address_reverse(
    response: Response,
    lat: float = Query(..., description="WGS84 latitude"),
    lon: float = Query(..., description="WGS84 longitude"),
    radius_m: int = Query(200, ge=1, le=2000, description="Search radius in metres"),
):
    _validate_coords(lat, lon)
    try:
        data, hit = await kv.address_reverse(_http, lat, lon, radius_m=radius_m, ttl=TTL_ADDR)
    except KartverketError as e:
        raise HTTPException(503, f"Kartverket upstream: {e.message}")
    _set_cache_header(response, hit)
    parsed = parsers.parse_address_reverse(data, lat, lon)
    if parsed.get("address") is None:
        raise HTTPException(404, f"No address within {radius_m} m of ({lat}, {lon})")
    return parsed


@app.get("/place")
async def place_search(
    response: Response,
    name: str = Query(..., min_length=2, max_length=200, description="Place-name query"),
    limit: int = Query(10, ge=1, le=50),
):
    try:
        data, hit = await kv.place_search(_http, name, limit=limit, ttl=TTL_PLACE)
    except KartverketError as e:
        raise HTTPException(503, f"Kartverket upstream: {e.message}")
    _set_cache_header(response, hit)
    return parsers.parse_place_search(data, limit=limit)


@app.get("/elevation")
async def elevation(
    response: Response,
    lat: float = Query(..., description="WGS84 latitude"),
    lon: float = Query(..., description="WGS84 longitude"),
):
    _validate_coords(lat, lon)
    try:
        data, hit = await kv.elevation(_http, lat, lon, ttl=TTL_ELEV)
    except KartverketError as e:
        raise HTTPException(503, f"Kartverket upstream: {e.message}")
    _set_cache_header(response, hit)
    parsed = parsers.parse_elevation(data, lat, lon)
    if parsed.get("elevation_m") is None:
        raise HTTPException(404, f"No elevation data at ({lat}, {lon})")
    return parsed


@app.get("/distance")
async def distance_endpoint(
    response: Response,
    from_lat: float = Query(..., description="Origin WGS84 latitude"),
    from_lon: float = Query(..., description="Origin WGS84 longitude"),
    to_lat: float = Query(..., description="Destination WGS84 latitude"),
    to_lon: float = Query(..., description="Destination WGS84 longitude"),
):
    """Pure haversine — no upstream call, instant response."""
    km = round(dist.haversine_km(from_lat, from_lon, to_lat, to_lon), 3)
    bearing = round(dist.initial_bearing_deg(from_lat, from_lon, to_lat, to_lon), 1)
    response.headers["X-Cache"] = "MISS"  # always fresh — no upstream
    return {
        "from": {"lat": from_lat, "lon": from_lon},
        "to": {"lat": to_lat, "lon": to_lon},
        "distance_km": km,
        "bearing_deg": bearing,
    }


@app.get("/property")
async def property_endpoint(
    response: Response,
    knr: str = Query(..., min_length=1, max_length=4, description="Kommunenummer (4-digit municipality code)"),
    gnr: int = Query(..., ge=0, description="Gårdsnummer"),
    bnr: int = Query(..., ge=0, description="Bruksnummer"),
):
    knr = knr.zfill(4)
    try:
        data, hit = await kv.property_lookup(_http, knr, gnr, bnr, ttl=TTL_PROP)
    except KartverketError as e:
        if e.status_code == 404:
            raise HTTPException(404, f"No property found for {knr}/{gnr}/{bnr}")
        raise HTTPException(503, f"Kartverket upstream: {e.message}")
    _set_cache_header(response, hit)
    return parsers.parse_property(data, knr, gnr, bnr)


# ── Static files ────────────────────────────────────────────────────

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
