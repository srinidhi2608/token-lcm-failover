from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from app.orchestrator import RoutingOrchestrator, route_transaction


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
    token: str = Field(min_length=1, description="Payment token (card token or BIN identifier)")
    amount: float = Field(gt=0)
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


def _extract_bin_id(token: str) -> int:
    """Extract a numeric BIN ID from a payment token string.
    
    Extracts all digits from the token and converts to int.
    The resulting BIN ID should be a valid card BIN identifier (typically 6-8 digits).
    
    Examples:
        "400000" -> 400000
        "TKN-400000" -> 400000
        "500000-ABC" -> 500000
    
    Raises
    ------
    ValueError
        If token contains no digits or if extracted number is not a valid BIN ID
    """
    numeric_str = ''.join(c for c in token if c.isdigit())
    if not numeric_str:
        raise ValueError("Token must contain at least one digit")
    
    bin_id = int(numeric_str)
    # Basic validation: BIN IDs are typically numeric identifiers for card networks
    if bin_id < 100000:
        raise ValueError(f"Extracted BIN ID {bin_id} is too small (expected >= 100000)")
    
    return bin_id


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
    issuer_lag_detected = 1 if payload.simulate_issuer_lag else 0
    
    transaction_payload = {
        "bin_id": bin_id,
        "amount": payload.amount,
        "issuer_lag_detected": issuer_lag_detected,
    }
    
    return await route_transaction(transaction_payload)
