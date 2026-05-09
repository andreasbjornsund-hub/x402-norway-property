# Marketing-site integration spec

Hand this to whichever bot manages [x402agent.no](http://x402agent.no/). Every agent built from this template emits the same set of discovery endpoints, so the indexing logic is identical for all of them.

## Per-agent inputs the bot needs

For each agent the user wants listed, the bot needs:

1. **Slug** (e.g. `norwegian-weather`) — used in URLs.
2. **Base URL** (e.g. `https://x402-norwegian-weather.fly.dev`) — confirmed by visiting `/health`.

That's it. Everything else is fetched from the agent's manifests.

## Manifests to pull

### 1. `GET <base>/.well-known/x402.json`

The canonical agent-discovery manifest. Recommended primary source.

```json
{
  "x402Version": 2,
  "service": {
    "id": "norwegian-weather",
    "name": "Norwegian Weather",
    "description": "Weather data for Norwegian municipalities. Pay per query with USDC via x402.",
    "category": "data",
    "website": "https://x402-norwegian-weather.fly.dev",
    "documentation": "https://x402-norwegian-weather.fly.dev/llms.txt",
    "servicesManifest": "https://x402-norwegian-weather.fly.dev/services.json"
  },
  "payment": {
    "schemes": ["exact"],
    "networks": ["eip155:8453"],
    "asset": {
      "symbol": "USDC",
      "decimals": 6,
      "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "chain": "Base"
    },
    "payTo": "0x2D8cFC122D13971EEf8cfB4CBC047F527eB76FAd",
    "facilitator": "https://x402.org/facilitator"
  },
  "endpoints": [
    {
      "method": "GET",
      "path": "/forecast/{municipality}",
      "description": "5-day forecast for a Norwegian municipality.",
      "accepts": [
        {
          "scheme": "exact",
          "network": "eip155:8453",
          "asset": "USDC",
          "amount": "20000",
          "amountDisplay": "$0.02",
          "payTo": "0x2D8cFC122D13971EEf8cfB4CBC047F527eB76FAd"
        }
      ],
      "input": {
        "type": "http",
        "method": "GET",
        "pathParams": {"municipality": "oslo"}
      },
      "output": {
        "type": "json",
        "example": {"municipality": "oslo", "forecast": [/*...*/]}
      }
    }
  ]
}
```

### 2. `GET <base>/services.json` (alternative, flatter format)

Use this if a flatter list is preferred. Same data, less detail per endpoint.

### 3. `GET <base>/llms.txt` (human-readable description)

Plain-text summary suitable for inserting into an LLM-readable knowledge base.

## What to render on x402agent.no per agent

Suggested page sections:

1. **Hero**: `service.name` and `service.description`
2. **Pricing table**: one row per endpoint, columns: method, path, price (`amountDisplay`), description
3. **Quickstart**: a curl/python example using the first paid endpoint
4. **Wallet info**: link the `payment.payTo` to a Basescan address page; show `payment.networks` and `payment.asset.symbol`
5. **Live status badge** (optional): hit `<base>/health` periodically; show green/red

## Stable contract

Every agent built from `x402-agent-template` will:

- Always serve `/.well-known/x402.json` with `x402Version == 2`
- Always include `service.id`, `service.name`, `service.description`, `service.website`, `service.category`
- Always include `payment.payTo`, `payment.networks`, `payment.asset.address`
- Always include an `endpoints` array; paid endpoints have `accepts: [{...}]`, free endpoints have `accepts: []`
- Always include `amount` (atomic microUSDC) AND `amountDisplay` (`"$0.05"`) on paid `accepts`

## Changes to expect over time

- **New endpoints added** — appear automatically in the manifest as soon as deployed
- **Price changes** — same; the manifest reflects the live config. If pinning historical prices matters, snapshot the manifest with a timestamp.
- **Schema bumps** — `x402Version` will only increment on breaking changes. Watch this field.
- **New free endpoints** — like `/api-status`. Renders alongside paid ones with `accepts: []`.

## Agent → marketing-site sync

There's no callback when an agent updates. The bot should re-poll `/.well-known/x402.json` periodically (every ~hour or on-demand) to pick up changes.
