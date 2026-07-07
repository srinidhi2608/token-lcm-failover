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
│       └── gateway_beta_success.json
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
