from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

RANDOM_SEED = 42

GATEWAY_ALPHA = "gateway_alpha"
GATEWAY_BETA = "gateway_beta"


@dataclass(frozen=True)
class RoutingFeatures:
    bin_prefix: str
    gateway: str
    error_code: str


class MLEngine:
    """Tiny mock model used to estimate authorization probability."""

    def __init__(self) -> None:
        self._pipeline = self._train_mock_model()

    @staticmethod
    def _train_mock_model() -> Pipeline:
        train_df = pd.DataFrame(
            [
                {"bin_prefix": "4", "gateway": "alpha", "error_code": "none", "authorized": 1},
                {"bin_prefix": "4", "gateway": "beta", "error_code": "none", "authorized": 1},
                {"bin_prefix": "4", "gateway": "alpha", "error_code": "05", "authorized": 0},
                {"bin_prefix": "4", "gateway": "beta", "error_code": "05", "authorized": 1},
                {"bin_prefix": "5", "gateway": "alpha", "error_code": "none", "authorized": 1},
                {"bin_prefix": "5", "gateway": "beta", "error_code": "none", "authorized": 1},
                {"bin_prefix": "5", "gateway": "alpha", "error_code": "timeout", "authorized": 0},
                {"bin_prefix": "5", "gateway": "beta", "error_code": "timeout", "authorized": 1},
            ]
        )

        categorical = ["bin_prefix", "gateway", "error_code"]
        preprocessor = ColumnTransformer(
            transformers=[
                ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical),
            ]
        )
        model = Pipeline(
            steps=[
                ("preprocessor", preprocessor),
                ("classifier", LogisticRegression(random_state=RANDOM_SEED)),
            ]
        )
        model.fit(train_df[categorical], train_df["authorized"])
        return model

    def predict_auth_probability(self, features: RoutingFeatures) -> float:
        payload = pd.DataFrame(
            [
                {
                    "bin_prefix": features.bin_prefix,
                    "gateway": features.gateway,
                    "error_code": features.error_code,
                }
            ]
        )
        probability = self._pipeline.predict_proba(payload)[0][1]
        return float(probability)


class PredictiveRoutingModel:
    """RandomForest-based model predicting gateway authorization probability.

    Training features
    -----------------
    bin_id : int
        Numeric identifier representing the card BIN group.
    issuer_lag_detected : int (0 or 1)
        Binary flag indicating whether transitional issuer lag has been detected.
    historical_decline_rate : float
        Fraction of recent transactions that resulted in a decline (0.0–1.0).
    gateway : int (0 = gateway_alpha, 1 = gateway_beta)
        Target gateway rail encoded as a binary integer.
    """

    _GATEWAY_ENCODING: dict[str, int] = {GATEWAY_ALPHA: 0, GATEWAY_BETA: 1}
    _FEATURE_COLUMNS = ["bin_id", "issuer_lag_detected", "historical_decline_rate", "gateway"]

    def __init__(self) -> None:
        self._model = self._train_mock_model()

    @staticmethod
    def _train_mock_model() -> RandomForestClassifier:
        """Fit a RandomForestClassifier on synthetic training data."""
        train_df = pd.DataFrame(
            [
                # BIN group 400000 – alpha performs well under normal conditions
                {"bin_id": 400000, "issuer_lag_detected": 0, "historical_decline_rate": 0.05, "gateway": 0, "authorized": 1},
                {"bin_id": 400000, "issuer_lag_detected": 0, "historical_decline_rate": 0.05, "gateway": 1, "authorized": 1},
                # Alpha degrades when issuer lag is detected; beta stays reliable
                {"bin_id": 400000, "issuer_lag_detected": 1, "historical_decline_rate": 0.40, "gateway": 0, "authorized": 0},
                {"bin_id": 400000, "issuer_lag_detected": 1, "historical_decline_rate": 0.40, "gateway": 1, "authorized": 1},
                # BIN group 500000 – both gateways fine under normal conditions
                {"bin_id": 500000, "issuer_lag_detected": 0, "historical_decline_rate": 0.08, "gateway": 0, "authorized": 1},
                {"bin_id": 500000, "issuer_lag_detected": 0, "historical_decline_rate": 0.08, "gateway": 1, "authorized": 1},
                # High decline rate + lag → alpha fails, beta succeeds
                {"bin_id": 500000, "issuer_lag_detected": 1, "historical_decline_rate": 0.65, "gateway": 0, "authorized": 0},
                {"bin_id": 500000, "issuer_lag_detected": 1, "historical_decline_rate": 0.65, "gateway": 1, "authorized": 1},
                # BIN group 411111 – additional samples to strengthen signal
                {"bin_id": 411111, "issuer_lag_detected": 0, "historical_decline_rate": 0.10, "gateway": 0, "authorized": 1},
                {"bin_id": 411111, "issuer_lag_detected": 0, "historical_decline_rate": 0.10, "gateway": 1, "authorized": 1},
                {"bin_id": 411111, "issuer_lag_detected": 1, "historical_decline_rate": 0.55, "gateway": 0, "authorized": 0},
                {"bin_id": 411111, "issuer_lag_detected": 1, "historical_decline_rate": 0.55, "gateway": 1, "authorized": 1},
            ]
        )
        features = train_df[PredictiveRoutingModel._FEATURE_COLUMNS]
        labels = train_df["authorized"]
        model = RandomForestClassifier(n_estimators=100, random_state=RANDOM_SEED)
        model.fit(features, labels)
        return model

    def _auth_probability(self, bin_id: int, issuer_lag_detected: int, gateway_code: int) -> float:
        """Return the predicted authorization probability for a single gateway."""
        payload = pd.DataFrame(
            [
                {
                    "bin_id": bin_id,
                    "issuer_lag_detected": issuer_lag_detected,
                    "historical_decline_rate": 0.0,
                    "gateway": gateway_code,
                }
            ]
        )
        return float(self._model.predict_proba(payload)[0][1])

    def predict_best_route(self, bin_id: int, issuer_lag_detected: int) -> str:
        """Return the gateway name with the highest predicted authorization probability.

        Parameters
        ----------
        bin_id : int
            Numeric BIN identifier for the card being routed.
        issuer_lag_detected : int
            1 if transitional issuer lag is currently detected, 0 otherwise.

        Returns
        -------
        str
            Either ``'gateway_alpha'`` or ``'gateway_beta'``.
        """
        if issuer_lag_detected not in (0, 1):
            raise ValueError("issuer_lag_detected must be 0 or 1")

        probabilities: dict[str, float] = {
            name: self._auth_probability(bin_id, issuer_lag_detected, code)
            for name, code in self._GATEWAY_ENCODING.items()
        }
        return max(probabilities, key=lambda g: probabilities[g])
