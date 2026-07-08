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

## Testing the Application

### Start the application with Docker

```bash
docker compose up --build
```

This will start:
- **API server** on `http://localhost:8000`
- **WireMock server** on `http://localhost:8080` (mock gateway responses)

### 1. Health Check

Test if the API is running:

```bash
curl -X GET http://localhost:8000/health
```

**Expected Output:**
```json
{
  "status": "ok"
}
```

---

### 2. Process Payment (Normal Route)

Process a payment transaction with intelligent gateway routing. The system will select between `gateway_alpha` and `gateway_beta` based on the ML model.

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "400000",
    "amount": 100.50,
    "simulate_issuer_lag": false
  }'
```

**Expected Output (Primary Gateway Success):**
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

**Response Fields:**
- `gateway` – The selected gateway that processed the request (`gateway_alpha` or `gateway_beta`)
- `failover` – Boolean indicating if the secondary gateway was used
- `response` – The gateway's response payload

---

### 3. Process Payment (With Failover Scenario)

Simulate issuer transitional lag to trigger failover to the secondary gateway:

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "500000",
    "amount": 250.75,
    "simulate_issuer_lag": true
  }'
```

**Expected Output (Failover to Secondary Gateway):**
```json
{
  "gateway": "gateway_beta",
  "failover": true,
  "response": {
    "gateway": "gateway_beta",
    "approved": true,
    "auth_code": "BETA-TX-OK"
  }
}
```

When `simulate_issuer_lag` is `true`, the primary gateway will simulate an issuer transition error, causing the system to automatically failover to the secondary gateway.

---

### 4. Legacy Route Endpoint

The `/route` endpoint is the legacy authorization routing API. It accepts a card BIN (6-8 digits) and routes to an optimal gateway.

```bash
curl -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{
    "bin": "400000",
    "amount": 150.00
  }'
```

**Expected Output:**
```json
{
  "decision": {
    "selected_gateway": "alpha",
    "alpha_probability": 0.65,
    "beta_probability": 0.35
  },
  "gateway_response": {
    "gateway": "gateway_alpha",
    "approved": true,
    "auth_code": "ALPHA-ROUTE-OK"
  }
}
```

**Response Fields:**
- `decision.selected_gateway` – The chosen gateway (`alpha` or `beta`)
- `decision.alpha_probability` – ML model's predicted success probability for gateway_alpha
- `decision.beta_probability` – ML model's predicted success probability for gateway_beta
- `gateway_response` – The authorization response from the selected gateway

---

### 5. Error Scenarios

#### Invalid Token (Too Small)

A token must extract to a BIN ID >= 100,000:

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "123",
    "amount": 100.00,
    "simulate_issuer_lag": false
  }'
```

**Expected Output (400 Bad Request):**
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "token"],
      "msg": "Value error, Extracted BIN ID 123 is too small (expected >= 100000)",
      "input": "123"
    }
  ]
}
```

#### Missing Required Field

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "400000"
  }'
```

**Expected Output (422 Unprocessable Entity):**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "amount"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

#### Invalid Amount (Must be > 0)

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "400000",
    "amount": -50.00,
    "simulate_issuer_lag": false
  }'
```

**Expected Output (422 Unprocessable Entity):**
```json
{
  "detail": [
    {
      "type": "greater_than",
      "loc": ["body", "amount"],
      "msg": "Input should be greater than 0",
      "input": -50.0
    }
  ]
}
```

---

### 6. Testing with Different BIN Ranges

The ML model may route transactions differently based on the BIN prefix:

```bash
# Test with different BIN prefixes
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{"token": "300000", "amount": 50.00}'

curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{"token": "600000", "amount": 75.00}'
```

Each BIN prefix may be routed to a different gateway based on the predictive routing model's decision.
