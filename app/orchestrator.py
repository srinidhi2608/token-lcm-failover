from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ml_engine import MLEngine, RoutingFeatures


@dataclass(frozen=True)
class RouteDecision:
    selected_gateway: str
    alpha_probability: float
    beta_probability: float


class RoutingOrchestrator:
    def __init__(self, wiremock_base_url: str = "http://wiremock:8080", request_timeout: float = 5.0) -> None:
        self._wiremock_base_url = wiremock_base_url.rstrip("/")
        self._ml_engine = MLEngine()
        self._client = httpx.AsyncClient(base_url=self._wiremock_base_url, timeout=request_timeout)

    @staticmethod
    def _validate_card_bin(card_bin: str) -> None:
        if not card_bin:
            raise ValueError("card_bin must be a non-empty string")
        if not 6 <= len(card_bin) <= 8:
            raise ValueError("card_bin must be between 6 and 8 characters")

    def choose_gateway(self, card_bin: str, last_error_code: str | None = None) -> RouteDecision:
        self._validate_card_bin(card_bin)

        bin_prefix = card_bin[0]
        error_code = last_error_code or "none"

        alpha_probability = self._ml_engine.predict_auth_probability(
            RoutingFeatures(bin_prefix=bin_prefix, gateway="alpha", error_code=error_code)
        )
        beta_probability = self._ml_engine.predict_auth_probability(
            RoutingFeatures(bin_prefix=bin_prefix, gateway="beta", error_code=error_code)
        )

        selected = "alpha" if alpha_probability >= beta_probability else "beta"
        return RouteDecision(
            selected_gateway=selected,
            alpha_probability=alpha_probability,
            beta_probability=beta_probability,
        )

    async def route_authorization(self, card_bin: str, amount: float, last_error_code: str | None = None) -> dict:
        self._validate_card_bin(card_bin)
        decision = self.choose_gateway(card_bin=card_bin, last_error_code=last_error_code)
        endpoint = f"/gateway/{decision.selected_gateway}/authorize"
        request_payload = {"bin": card_bin, "amount": amount}

        response = await self._client.post(endpoint, json=request_payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Gateway '{decision.selected_gateway}' request to '{endpoint}' failed "
                f"with status {exc.response.status_code}"
            ) from exc
        gateway_response = response.json()

        return {"decision": decision.__dict__, "gateway_response": gateway_response}

    async def aclose(self) -> None:
        await self._client.aclose()
