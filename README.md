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

- `GET /health`
- `POST /route`

## Module-level function

`app.orchestrator.route_transaction(payload: dict)` is an async function that uses
`PredictiveRoutingModel` to select the optimal gateway (`gateway_alpha` or `gateway_beta`),
POSTs the transaction to `http://wiremock:8080/v1/<gateway>/transact`, and automatically
fails over to the secondary gateway on a 504 response, an `issuer_transitional_lag` error,
or a network timeout.
