"""
x402 Agent — REPLACE THIS DESCRIPTION

Endpoints (free):
  GET /                   — landing page (HTML or JSON)
  GET /health             — health check
  GET /api-status         — uptime + cache shape (operational visibility)
  GET /services.json      — agent-readable services manifest
  GET /llms.txt           — LLMs.txt for AI crawlers
  GET /robots.txt         — robots policy
  GET /.well-known/x402.json — x402 agent-discovery manifest

Endpoints (paid — REPLACE):
  GET /example             — $0.01: replace with your paid endpoint
"""

import os
import time
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from cdp_auth import create_cdp_auth_provider

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────

# Override these for each agent. Defaults match the shared payTo wallet.
SERVICE_ID = os.getenv("SERVICE_ID", "x402-agent-template")
SERVICE_NAME = os.getenv("SERVICE_NAME", "x402 Agent Template")
SERVICE_DESCRIPTION = os.getenv(
    "SERVICE_DESCRIPTION",
    "REPLACE: short description of what this agent does. Pay per query with USDC via x402.",
)
SERVICE_CATEGORY = os.getenv("SERVICE_CATEGORY", "data")

EVM_ADDRESS = os.getenv("EVM_ADDRESS")
EVM_NETWORK: Network = "eip155:8453"  # Base mainnet
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")
SITE_URL = os.getenv("SITE_URL", f"https://{SERVICE_ID}.fly.dev")

# USDC contract on Base mainnet — embedded in agent-discovery manifests so
# payers can sign EIP-3009 transferWithAuthorization without an extra lookup.
USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

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

# ── x402 payment middleware ─────────────────────────────────────────

import json as _json

cdp_auth = None
if "cdp.coinbase.com" in FACILITATOR_URL:
    cdp_auth = create_cdp_auth_provider()
facilitator_config = FacilitatorConfig(url=FACILITATOR_URL, auth_provider=cdp_auth)
facilitator = HTTPFacilitatorClient(facilitator_config)

# ── V2→V1 conversion shim for CDP facilitator ──────────────────────
# CDP only supports x402 v1; the SDK speaks v2. This shim translates
# in both directions. Keep verbatim — modifying it breaks payments.

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
    v1_payload = _v2_payload_to_v1(payload_dict)
    v1_reqs = _v2_requirements_to_v1(requirements_dict)
    return await _orig_verify(1, v1_payload, v1_reqs)


async def _v1_settle(version, payload_dict, requirements_dict):
    v1_payload = _v2_payload_to_v1(payload_dict)
    v1_reqs = _v2_requirements_to_v1(requirements_dict)
    return await _orig_settle(1, v1_payload, v1_reqs)


facilitator._verify_http = _v1_verify
facilitator._settle_http = _v1_settle

server = x402ResourceServer(facilitator)
server.register(EVM_NETWORK, ExactEvmServerScheme())

# ── Endpoint catalog ────────────────────────────────────────────────
# Single source of truth. Drives x402 middleware routes, /services.json,
# /llms.txt, /.well-known/x402.json, and the root JSON response. Add a
# new entry here + one handler below = new endpoint everywhere.


ENDPOINT_CATALOG: list[dict] = [
    # ── REPLACE: paid endpoints ──
    {
        "method": "GET",
        "path": "/example",
        "route_pattern": "GET /example",
        "description": "REPLACE: short description of this paid endpoint.",
        "price_usd": "$0.01",
        "amount_atomic": "10000",  # USDC has 6 decimals; $0.01 = 10000 microUSDC
        "query_params": {"q": "example"},
        "path_params": {},
        "output_example": {"result": "replace me"},
    },
    # ── Free endpoints (don't remove /health) ──
    {
        "method": "GET",
        "path": "/health",
        "route_pattern": None,
        "description": "Service health check.",
        "price_usd": None,
        "amount_atomic": None,
        "query_params": {},
        "path_params": {},
        "output_example": {"status": "ok"},
    },
    {
        "method": "GET",
        "path": "/api-status",
        "route_pattern": None,
        "description": "Operational status — uptime and cache shape.",
        "price_usd": None,
        "amount_atomic": None,
        "query_params": {},
        "path_params": {},
        "output_example": None,
    },
]


def _bazaar_info(entry: dict) -> dict:
    inp = {"type": "http", "method": entry["method"]}
    if entry["query_params"]:
        inp["queryParams"] = entry["query_params"]
    if entry["path_params"]:
        inp["pathParams"] = entry["path_params"]
    return {
        "info": {
            "input": inp,
            "output": {"type": "json", "example": entry["output_example"]},
        },
        "schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"input": {"type": "object"}, "output": {"type": "object"}},
        },
    }


def _build_paid_routes(catalog: list[dict]) -> dict[str, RouteConfig]:
    return {
        e["route_pattern"]: RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=EVM_ADDRESS,
                    price=e["price_usd"],
                    network=EVM_NETWORK,
                ),
            ],
            mime_type="application/json",
            description=e["description"],
            extensions={"bazaar": _bazaar_info(e)},
        )
        for e in catalog
        if e["route_pattern"] is not None
    }


routes = _build_paid_routes(ENDPOINT_CATALOG)
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

# ── HTTP client (reuse for upstream API calls) ──────────────────────

_http = httpx.AsyncClient(timeout=30, headers={"Accept": "application/json"})

# ── Discovery / metadata endpoints ──────────────────────────────────

_PROCESS_START_TS = time.time()


@app.get("/")
async def landing(request: Request):
    """Content-negotiate: HTML for browsers, JSON for API clients."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept and os.path.isfile("static/index.html"):
        return FileResponse("static/index.html")
    return {
        "service": SERVICE_NAME,
        "version": "0.1.0",
        "description": SERVICE_DESCRIPTION,
        "endpoints": {
            e["path"]: f"{e['description']} ({e['price_usd']} USDC)" if e["price_usd"]
            else f"{e['description']} (free)"
            for e in ENDPOINT_CATALOG
        }
        | {"/.well-known/x402.json": "Agent discovery"},
        "payment": "x402 protocol — USDC on Base network",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_ID, "timestamp": int(time.time())}


@app.get("/api-status")
async def api_status():
    """Free operational status endpoint. Extend with cache stats etc."""
    return {
        "status": "ok",
        "service": SERVICE_ID,
        "version": "0.1.0",
        "uptime_seconds": int(time.time() - _PROCESS_START_TS),
    }


@app.get("/services.json")
async def services_manifest():
    """Agentic Market / Bazaar service manifest for auto-discovery."""
    return {
        "id": SERVICE_ID,
        "name": SERVICE_NAME,
        "description": SERVICE_DESCRIPTION,
        "category": SERVICE_CATEGORY,
        "x402Version": 2,
        "networks": [EVM_NETWORK],
        "website": SITE_URL,
        "endpoints": [
            {
                "method": e["method"],
                "path": e["path"],
                "description": e["description"],
                "price": e["price_usd"] or "$0.00",
                "currency": "USDC",
            }
            for e in ENDPOINT_CATALOG
        ],
    }


@app.get("/.well-known/x402.json")
async def x402_manifest():
    """x402 agent-discovery manifest, generated from the endpoint catalog."""
    return {
        "x402Version": 2,
        "service": {
            "id": SERVICE_ID,
            "name": SERVICE_NAME,
            "description": SERVICE_DESCRIPTION,
            "category": SERVICE_CATEGORY,
            "website": SITE_URL,
            "documentation": f"{SITE_URL}/llms.txt",
            "servicesManifest": f"{SITE_URL}/services.json",
        },
        "payment": {
            "schemes": ["exact"],
            "networks": [EVM_NETWORK],
            "asset": {
                "symbol": "USDC",
                "decimals": 6,
                "address": USDC_BASE_MAINNET,
                "chain": "Base",
            },
            "payTo": EVM_ADDRESS,
            "facilitator": FACILITATOR_URL,
        },
        "endpoints": [
            {
                "method": e["method"],
                "path": e["path"],
                "description": e["description"],
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": EVM_NETWORK,
                        "asset": "USDC",
                        "amount": e["amount_atomic"],
                        "amountDisplay": e["price_usd"],
                        "payTo": EVM_ADDRESS,
                    }
                ] if e["amount_atomic"] else [],
                "input": {
                    "type": "http",
                    "method": e["method"],
                    **({"queryParams": e["query_params"]} if e["query_params"] else {}),
                    **({"pathParams": e["path_params"]} if e["path_params"] else {}),
                },
                "output": (
                    {"type": "json", "example": e["output_example"]}
                    if e["output_example"] is not None
                    else {"type": "json"}
                ),
            }
            for e in ENDPOINT_CATALOG
        ],
    }


@app.get("/llms.txt")
async def llms_txt():
    """LLMs.txt convention — agent-readable plain-text manifest."""
    lines = [
        f"# {SERVICE_NAME}",
        f"> {SERVICE_DESCRIPTION}",
        "",
        "## Endpoints",
    ]
    for e in ENDPOINT_CATALOG:
        price = f"{e['price_usd']} USDC" if e["price_usd"] else "Free"
        lines.append(f"- {e['method']} {e['path']} — {price} — {e['description']}")
    lines += [
        "",
        "## Payment",
        "- Protocol: x402 (HTTP 402 micropayments)",
        "- Currency: USDC on Base",
        "- No API keys or accounts needed",
        "- Agent discovery: GET /.well-known/x402.json",
        "",
        "## Links",
        f"- Website: {SITE_URL}",
        f"- Services manifest: {SITE_URL}/services.json",
        "",
    ]
    return PlainTextResponse("\n".join(lines), media_type="text/plain")


@app.get("/robots.txt")
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "# AI crawlers\n"
        "User-agent: GPTBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: ClaudeBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: PerplexityBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: Google-Extended\n"
        "Allow: /\n",
        media_type="text/plain",
    )


# ── Paid endpoints (REPLACE these with your agent's logic) ──────────


@app.get("/example")
async def example_endpoint(q: str = Query(..., min_length=1, max_length=200)):
    """REPLACE: this is a paid endpoint. Add your business logic here.

    The x402 middleware has already verified payment by the time this
    handler runs. Returning a non-error response triggers settlement;
    raising HTTPException with status >= 400 cancels settlement (the
    customer is not charged).
    """
    return {"q": q, "result": "replace me with real data"}


# ── Static files ────────────────────────────────────────────────────

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
