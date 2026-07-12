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
├── data/
│   └── payment_training_data.csv
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
  "token": "4111111111111111",
  "amount": 100.50,
  "card_scheme": "visa",
  "card_class": "commercial",
  "transaction_type": "recurring",
  "simulate_issuer_lag": false
}
```

- `token` (string, required) – Exactly 16 numeric digits
- `amount` (number, required) – Transaction amount (must be > 0)
- `card_scheme` (string, required) – `visa|mastercard|amex|discover`
- `card_class` (string, required) – `credit|debit|premium|commercial`
- `transaction_type` (string, required) – `cit|mit|recurring`
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
  },
  "model_trace": {
    "selected_gateway": "gateway_alpha",
    "feature_vector": {
      "bin": 411111,
      "card_scheme": "visa",
      "card_class": "commercial",
      "transaction_type": "recurring",
      "token_lifecycle_status": "active",
      "historical_decline_rate": 0.02,
      "amount": 100.5
    },
    "gateway_confidence_scores": {
      "gateway_alpha": 0.71,
      "gateway_beta": 0.29
    }
  }
}
```

- `gateway` – Selected gateway (`gateway_alpha` or `gateway_beta`)
- `failover` – Whether the secondary gateway was used due to primary failure
- `response` – The gateway's response payload
- `model_trace` – Feature payload and confidence scores produced by the ML route selector

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
    "token": "4111111111111111",
    "amount": 100.50,
    "card_scheme": "visa",
    "card_class": "commercial",
    "transaction_type": "recurring",
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
  },
  "model_trace": {
    "selected_gateway": "gateway_alpha",
    "feature_vector": {
      "bin": 411111,
      "card_scheme": "visa",
      "card_class": "commercial",
      "transaction_type": "recurring",
      "token_lifecycle_status": "active",
      "historical_decline_rate": 0.02,
      "amount": 100.5
    },
    "gateway_confidence_scores": {
      "gateway_alpha": 0.8,
      "gateway_beta": 0.2
    }
  }
}
```

**Response Fields:**
- `gateway` – The selected gateway that processed the request (`gateway_alpha` or `gateway_beta`)
- `failover` – Boolean indicating if the secondary gateway was used
- `response` – The gateway's response payload

---

### 3. Process Payment (With Failover Scenario)

Simulate issuer transitional lag to bias selection toward gateway beta:

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "5555551111111111",
    "amount": 250.75,
    "card_scheme": "mastercard",
    "card_class": "commercial",
    "transaction_type": "recurring",
    "simulate_issuer_lag": true
  }'
```

**Expected Output (Failover to Secondary Gateway):**
```json
{
  "gateway": "gateway_beta",
  "failover": false,
  "response": {
    "gateway": "gateway_beta",
    "approved": true,
    "auth_code": "BETA-TX-OK"
  },
  "model_trace": {
    "selected_gateway": "gateway_beta",
    "feature_vector": {
      "bin": 555555,
      "card_scheme": "mastercard",
      "card_class": "commercial",
      "transaction_type": "recurring",
      "token_lifecycle_status": "transitional_lag",
      "historical_decline_rate": 0.42,
      "amount": 250.75
    },
    "gateway_confidence_scores": {
      "gateway_alpha": 0.19,
      "gateway_beta": 0.81
    }
  }
}
```

When `simulate_issuer_lag` is `true`, token lifecycle and decline-rate features are mapped to transitional values that increase beta routing confidence.

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

#### Invalid Token (Not 16 Digits)

```bash
curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{
    "token": "123",
    "amount": 100.00,
    "card_scheme": "visa",
    "card_class": "credit",
    "transaction_type": "cit",
    "simulate_issuer_lag": false
  }'
```

**Expected Output (422 Unprocessable Entity):**
```json
{
  "detail": [
    {
      "type": "string_pattern_mismatch",
      "loc": ["body", "token"],
      "msg": "String should match pattern '^\\d{16}$'",
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
    "token": "4111111111111111",
    "card_scheme": "visa",
    "card_class": "credit",
    "transaction_type": "cit",
    "simulate_issuer_lag": false
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
    "token": "4111111111111111",
    "amount": -50.00,
    "card_scheme": "visa",
    "card_class": "credit",
    "transaction_type": "cit",
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
  -d '{"token":"3782821111111111","amount":50.00,"card_scheme":"amex","card_class":"premium","transaction_type":"cit","simulate_issuer_lag":false}'

curl -X POST http://localhost:8000/v1/process-payment \
  -H "Content-Type: application/json" \
  -d '{"token":"6011111111111111","amount":75.00,"card_scheme":"discover","card_class":"debit","transaction_type":"mit","simulate_issuer_lag":false}'
```

Each BIN prefix may be routed to a different gateway based on the predictive routing model's decision.

## Production Testing Scenario Manual (Windows CMD)

### Scenario A — Normal State (Commercial Recurring via Alpha)

```cmd
curl -X POST http://localhost:8000/v1/process-payment ^
  -H "Content-Type: application/json" ^
  -d "{\"token\":\"4111111111111111\",\"amount\":1249.95,\"card_scheme\":\"visa\",\"card_class\":\"commercial\",\"transaction_type\":\"recurring\",\"simulate_issuer_lag\":false}"
```

**Expected response**
```json
{
  "gateway": "gateway_alpha",
  "failover": false,
  "response": {
    "gateway": "gateway_alpha",
    "approved": true,
    "auth_code": "ALPHA-TX-OK"
  },
  "model_trace": {
    "selected_gateway": "gateway_alpha",
    "feature_vector": {
      "bin": 411111,
      "card_scheme": "visa",
      "card_class": "commercial",
      "transaction_type": "recurring",
      "token_lifecycle_status": "active",
      "historical_decline_rate": 0.02,
      "amount": 1249.95
    },
    "gateway_confidence_scores": {
      "gateway_alpha": 0.84,
      "gateway_beta": 0.16
    }
  }
}
```

### Scenario B — Intercepting Issuer Migration (Failover via Beta)

```cmd
curl -X POST http://localhost:8000/v1/process-payment ^
  -H "Content-Type: application/json" ^
  -d "{\"token\":\"4111111111111111\",\"amount\":1249.95,\"card_scheme\":\"visa\",\"card_class\":\"commercial\",\"transaction_type\":\"recurring\",\"simulate_issuer_lag\":true}"
```

**Expected response**
```json
{
  "gateway": "gateway_beta",
  "failover": false,
  "response": {
    "gateway": "gateway_beta",
    "approved": true,
    "auth_code": "BETA-TX-OK"
  },
  "model_trace": {
    "selected_gateway": "gateway_beta",
    "feature_vector": {
      "bin": 411111,
      "card_scheme": "visa",
      "card_class": "commercial",
      "transaction_type": "recurring",
      "token_lifecycle_status": "transitional_lag",
      "historical_decline_rate": 0.42,
      "amount": 1249.95
    },
    "gateway_confidence_scores": {
      "gateway_alpha": 0.12,
      "gateway_beta": 0.88
    }
  }
}
```
