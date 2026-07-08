from __future__ import annotations

import os
from dataclasses import asdict, dataclass

import httpx

from app.ml_engine import GATEWAY_ALPHA, GATEWAY_BETA, MLEngine, PredictiveRoutingModel, RoutingFeatures


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

        return {"decision": asdict(decision), "gateway_response": gateway_response}

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Module-level route_transaction function (uses PredictiveRoutingModel)
# ---------------------------------------------------------------------------

_WIREMOCK_BASE_URL: str = os.getenv("WIREMOCK_BASE_URL", "http://wiremock:8080")

_GATEWAY_TRANSACT_ENDPOINTS: dict[str, str] = {
    GATEWAY_ALPHA: "/v1/gateway_alpha/transact",
    GATEWAY_BETA: "/v1/gateway_beta/transact",
}

_TRANSITION_ERRORS: frozenset[str] = frozenset({"issuer_transitional_lag"})

_predictive_model: PredictiveRoutingModel | None = None


def _get_predictive_model() -> PredictiveRoutingModel:
    global _predictive_model
    if _predictive_model is None:
        _predictive_model = PredictiveRoutingModel()
    return _predictive_model


def _is_failover_response(response: httpx.Response) -> bool:
    """Return True when the gateway response indicates a 504 or transition error."""
    if response.status_code == 504:
        return True
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("error") in _TRANSITION_ERRORS:
            return True
    except Exception:
        pass
    return False


async def route_transaction(payload: dict) -> dict:
    """Determine the optimal gateway via ML and execute an HTTP POST to it.

    If the chosen gateway returns a 504 timeout or a simulated transition error
    (``issuer_transitional_lag``), the call is immediately retried against the
    secondary gateway.

    Parameters
    ----------
    payload:
        Transaction data.  Must include ``bin_id`` (int) and may include
        ``issuer_lag_detected`` (int, 0 or 1; defaults to 0).

    Returns
    -------
    dict
        ``gateway`` – name of the gateway that handled the request,
        ``failover`` – True when the secondary gateway was used,
        ``response`` – parsed JSON body from the gateway.
    """
    bin_id: int = int(payload["bin_id"])
    issuer_lag_detected: int = int(payload.get("issuer_lag_detected", 0))

    model = _get_predictive_model()
    primary: str = model.predict_best_route(bin_id, issuer_lag_detected)
    secondary: str = GATEWAY_BETA if primary == GATEWAY_ALPHA else GATEWAY_ALPHA

    async with httpx.AsyncClient(base_url=_WIREMOCK_BASE_URL, timeout=10.0) as client:
        # Try primary gateway first
        try:
            primary_response = await client.post(
                _GATEWAY_TRANSACT_ENDPOINTS[primary], json=payload
            )
            if not _is_failover_response(primary_response):
                # Primary succeeded, return its response
                primary_response.raise_for_status()
                return {"gateway": primary, "failover": False, "response": primary_response.json()}
        except httpx.TimeoutException:
            # Primary timed out, proceed to failover
            pass

        # Primary failed or timed out; failover to secondary
        secondary_response = await client.post(
            _GATEWAY_TRANSACT_ENDPOINTS[secondary], json=payload
        )
        secondary_response.raise_for_status()
        return {"gateway": secondary, "failover": True, "response": secondary_response.json()}
