from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from app.orchestrator import RoutingOrchestrator


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
