from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.orchestrator import RoutingOrchestrator

app = FastAPI(title="token-lcm-failover", version="0.1.0")
orchestrator = RoutingOrchestrator()


class RouteRequest(BaseModel):
    bin: str = Field(min_length=6, max_length=8)
    amount: float = Field(gt=0)
    last_error_code: str | None = None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/route")
async def route(request: RouteRequest) -> dict:
    return await orchestrator.route_authorization(
        card_bin=request.bin,
        amount=request.amount,
        last_error_code=request.last_error_code,
    )
