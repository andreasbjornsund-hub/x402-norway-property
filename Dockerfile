FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system "fastapi>=0.115" "uvicorn>=0.34" "x402[fastapi,evm]>=2.8,<2.9" "python-dotenv>=1.0" "httpx>=0.27" "PyJWT[crypto]>=2.8"

COPY main.py cdp_auth.py ./
# Optional static dir — copy if present (won't fail if absent thanks to glob).
COPY stati[c] static

# NOTE on facilitator + secrets: the default x402.org facilitator only supports
# Base SEPOLIA, not Base mainnet. To run on mainnet you MUST set:
#   FACILITATOR_URL=https://api.cdp.coinbase.com/platform/v2/x402
#   CDP_API_KEY_NAME=...     (from https://portal.cdp.coinbase.com/projects)
#   CDP_API_KEY_SECRET=...   (base64 Ed25519 seed from same dashboard)
# Set them via `flyctl secrets set` — never bake into the image.
# EVM_ADDRESS must also be set via flyctl secrets, not here.

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "60"]
