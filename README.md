# x402-agent-template

Skeleton for x402 micropayment agents. Fork this to bring up a new tool that:

- Charges per-call in USDC on Base via the [x402 protocol](https://x402.org)
- Is discoverable by AI agents via standard `/services.json`, `/llms.txt`, and `/.well-known/x402.json` manifests — all generated from a single `ENDPOINT_CATALOG` so prices/paths can never drift
- Deploys to Fly.io with `auto_stop_machines = 'stop'` so idle cost is ~$0
- Has CI (pytest) and auto-deploy on push to main

This template is a working app on its own (a single `/example` paid endpoint). Replace the example handler with your real logic.

## Bring up a new agent

```bash
# 1. Use this template on GitHub (UI: "Use this template" button)
#    Repo name convention: x402-<your-agent-name>
#
#    Or via CLI:
gh repo create x402-<name> --template andreasbjornsund-hub/x402-agent-template --public

# 2. Clone and rename
git clone https://github.com/<you>/x402-<name>
cd x402-<name>

# 3. Replace the placeholders in main.py:
#    - SERVICE_ID, SERVICE_NAME, SERVICE_DESCRIPTION (env defaults)
#    - ENDPOINT_CATALOG: replace /example with your real paid endpoint(s)
#    - The /example handler at the bottom: replace with your business logic
#
#    Replace the placeholder in fly.toml:
#    - app = 'x402-<name>'
#
#    Replace the placeholder in pyproject.toml:
#    - name = "x402-<name>"

# 4. Register the Fly app and set ALL FOUR required secrets.
#    The default x402.org facilitator only supports Base SEPOLIA.
#    Mainnet (where the real wallet is) requires the CDP facilitator,
#    which needs an API key from https://portal.cdp.coinbase.com/projects.
flyctl apps create x402-<name>
flyctl secrets set -a x402-<name> \
  EVM_ADDRESS=0x2D8cFC122D13971EEf8cfB4CBC047F527eB76FAd \
  FACILITATOR_URL=https://api.cdp.coinbase.com/platform/v2/x402 \
  CDP_API_KEY_NAME='<paste from CDP dashboard>' \
  CDP_API_KEY_SECRET='<paste from CDP dashboard>'

# 5. Add a Fly deploy token to GitHub Actions secrets
gh secret set FLY_API_TOKEN -R <you>/x402-<name> -b "$(flyctl tokens create deploy -x 8760h)"

# 6. First deploy (triggers via push, or run locally)
git push origin main
# or: flyctl deploy --remote-only -a x402-<name>
```

## What to replace, in order

1. **`SERVICE_ID` / `SERVICE_NAME` / `SERVICE_DESCRIPTION` / `SERVICE_CATEGORY`** in `main.py`. These flow into every manifest.

2. **`ENDPOINT_CATALOG`** in `main.py`. Each paid endpoint needs:
   - `path` — public-facing path (e.g. `/lookup/{id}`)
   - `route_pattern` — x402 middleware pattern (e.g. `GET /lookup/*`). For longer paths that share a prefix with shorter ones, list the longer pattern FIRST.
   - `description`
   - `price_usd` — display string (`"$0.05"`)
   - `amount_atomic` — microUSDC (`"50000"` for $0.05; USDC has 6 decimals)
   - `query_params` / `path_params` — example values for the bazaar manifest
   - `output_example` — what a successful response looks like

3. **The handler functions** at the bottom of `main.py`. Replace the `/example` handler with the real one. Add helper functions, an httpx client for upstream APIs, etc.

4. **Tests**. The skeleton has `tests/test_skeleton.py` covering the catalog/manifest contract. Add tests for your handlers (use the `fake_http` fixture in `tests/conftest.py` to stub upstream APIs).

5. **`static/index.html`** (optional). If present, served at `/` for browsers; the JSON response is served to API clients.

## Architecture (don't change unless you know why)

- **`ENDPOINT_CATALOG` is the source of truth.** Don't hand-write `/services.json` or `/.well-known/x402.json` — they're generated.
- **`_v2_payload_to_v1` and `_v2_requirements_to_v1`** are the CDP facilitator compatibility shim. Don't modify; CDP only supports x402 v1 while the SDK speaks v2.
- **Settlement only happens on 2xx.** Raising `HTTPException(status_code >= 400)` cancels settlement so the customer isn't charged on errors. Use this for "no result found" cases (return 404, not 200 with empty data).

## Cost expectations on Fly

With `auto_stop_machines = 'stop'` + `min_machines_running = 0`:
- Idle: ~$0/month
- Active (256 MB shared CPU): $0.00000857/sec ≈ $0.0005/min of execution time
- Volume / IPv4: not allocated by default
- Bandwidth: $0.02/GB outbound after included tier

## What the marketing site / discovery bot consumes

Once the agent is live at `https://x402-<name>.fly.dev/`, the discovery bot at [x402agent.no](http://x402agent.no/) can pull these endpoints:

- **`GET /.well-known/x402.json`** — full manifest, recommended for indexing. Includes payTo, atomic prices, examples, JSON schemas.
- **`GET /services.json`** — flatter format if you want a simpler listing.
- **`GET /llms.txt`** — human-readable summary for LLM crawlers.

All are generated from `ENDPOINT_CATALOG` and reflect the live `EVM_ADDRESS` / `FACILITATOR_URL` env vars, so they can't drift from production.

## Local development

```bash
pip install -e .[dev]
export EVM_ADDRESS=0xYourTestWalletAddress  # or a real one
uvicorn main:app --reload
# → http://localhost:8000/.well-known/x402.json

pytest -v
```
