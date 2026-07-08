# token-lcm-failover

Predictive Lifecycle Failover Routing Engine for payment processing.

## Project structure

```
token-lcm-failover/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── ml_engine.py
│   └── orchestrator.py
├── wiremock/
│   └── mappings/
│       ├── gateway_alpha_success.json
│       ├── gateway_alpha_lag.json
│       ├── gateway_beta_success.json
│       ├── gateway_alpha_v1_transact_success.json
│       ├── gateway_alpha_v1_transact_lag.json
│       └── gateway_beta_v1_transact_success.json
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Run locally with Docker

```bash
docker compose up --build
```

## API endpoints

- `GET /health` – Health check
- `POST /route` – Route authorization request (legacy, uses card BIN)
- `POST /v1/process-payment` – Process a payment transaction with intelligent gateway routing

### POST /v1/process-payment

Accepts a JSON payload and routes the transaction to the optimal gateway using `PredictiveRoutingModel`.

**Request body:**
```json
{
  "token": "400000",
  "amount": 100.50,
  "simulate_issuer_lag": false
}
```

- `token` (string, required) – Payment token or card BIN identifier (must contain numeric digits)
- `amount` (number, required) – Transaction amount (must be > 0)
- `simulate_issuer_lag` (boolean, optional) – Simulate issuer transitional lag (defaults to false)

**Response:**
```json
{
  "gateway": "gateway_alpha",
  "failover": false,
  "response": {
    "gateway": "gateway_alpha",
    "approved": true,
    "auth_code": "ALPHA-TX-OK"
  }
}
```

- `gateway` – Selected gateway (`gateway_alpha` or `gateway_beta`)
- `failover` – Whether the secondary gateway was used due to primary failure
- `response` – The gateway's response payload

## Module-level function

`app.orchestrator.route_transaction(payload: dict)` is an async function that uses
`PredictiveRoutingModel` to select the optimal gateway (`gateway_alpha` or `gateway_beta`),
POSTs the transaction to `http://wiremock:8080/v1/<gateway>/transact`, and automatically
fails over to the secondary gateway on a 504 response, an `issuer_transitional_lag` error,
or a network timeout.
