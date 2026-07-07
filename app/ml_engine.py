from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

RANDOM_SEED = 42


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
