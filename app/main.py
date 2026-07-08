from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from app.orchestrator import RoutingOrchestrator, route_transaction


def _extract_bin_id(token: str) -> int:
    """Extract the first six digits from a 16-digit token as BIN."""
    return int(token[:6])


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.orchestrator = RoutingOrchestrator()
    yield
    await app.state.orchestrator.aclose()


app = FastAPI(title="token-lcm-failover", version="0.1.0", lifespan=lifespan)


class RouteRequest(BaseModel):
    card_bin: str = Field(alias="bin", min_length=6, max_length=8)
    amount: float = Field(gt=0)
    last_error_code: str | None = None


class ProcessPaymentRequest(BaseModel):
    token: str = Field(
        pattern=r"^\d{16}$",
        description="16-digit payment token",
    )
    amount: float = Field(gt=0.0)
    card_scheme: Literal["visa", "mastercard", "amex", "discover"]
    card_class: Literal["credit", "debit", "premium", "commercial"]
    transaction_type: Literal["cit", "mit", "recurring"]
    simulate_issuer_lag: bool = Field(default=False, description="Simulate issuer transitional lag")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/route")
async def route(request: Request, payload: RouteRequest) -> dict:
    orchestrator: RoutingOrchestrator = request.app.state.orchestrator
    return await orchestrator.route_authorization(
        card_bin=payload.card_bin,
        amount=payload.amount,
        last_error_code=payload.last_error_code,
    )


@app.post("/v1/process-payment")
async def process_payment(payload: ProcessPaymentRequest) -> dict:
    """Process a payment transaction with intelligent gateway routing.
    
    Uses PredictiveRoutingModel to select the optimal gateway (alpha or beta),
    sends the transaction to the chosen gateway, and automatically fails over
    to the secondary gateway on 504 errors or issuer transitional lag.
    
    Parameters
    ----------
    payload : ProcessPaymentRequest
        token : str
            Payment token or card BIN identifier (numeric string)
        amount : float
            Transaction amount (must be > 0)
        simulate_issuer_lag : bool
            Whether to simulate issuer transitional lag (defaults to False)
    
    Returns
    -------
    dict
        Orchestrator result including selected gateway, failover status, and gateway response
    """
    bin_id = _extract_bin_id(payload.token)
    token_lifecycle_status = "transitional_lag" if payload.simulate_issuer_lag else "active"
    historical_decline_rate = 0.42 if payload.simulate_issuer_lag else 0.02

    transaction_payload = {
        "bin": bin_id,
        "card_scheme": payload.card_scheme.lower(),
        "card_class": payload.card_class.lower(),
        "transaction_type": payload.transaction_type.lower(),
        "token_lifecycle_status": token_lifecycle_status,
        "historical_decline_rate": historical_decline_rate,
        "amount": payload.amount,
    }

    return await route_transaction(transaction_payload)
