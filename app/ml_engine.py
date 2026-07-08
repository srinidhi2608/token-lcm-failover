from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
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
    """CSV-driven model predicting the best gateway from payment features."""

    _CATEGORICAL_COLUMNS = [
        "card_scheme",
        "card_class",
        "transaction_type",
        "token_lifecycle_status",
    ]
    _NUMERICAL_COLUMNS = ["bin", "historical_decline_rate", "amount"]
    _FEATURE_COLUMNS = _CATEGORICAL_COLUMNS + _NUMERICAL_COLUMNS
    _TARGET_COLUMN = "recommended_gateway"

    def __init__(self, dataset_path: str | None = None) -> None:
        default_path = Path(__file__).resolve().parents[1] / "data" / "payment_training_data.csv"
        self._dataset_path = Path(dataset_path) if dataset_path else default_path
        self._model = self._train_model()

    def _load_training_data(self) -> pd.DataFrame:
        train_df = pd.read_csv(self._dataset_path)
        missing_columns = [
            column
            for column in self._FEATURE_COLUMNS + [self._TARGET_COLUMN]
            if column not in train_df.columns
        ]
        if missing_columns:
            raise ValueError(
                f"Training dataset is missing required columns: {', '.join(missing_columns)}"
            )
        return train_df

    def _train_model(self) -> Pipeline:
        train_df = self._load_training_data()
        preprocessor = ColumnTransformer(
            transformers=[
                (
                    "categorical",
                    OneHotEncoder(handle_unknown="ignore"),
                    self._CATEGORICAL_COLUMNS,
                ),
                ("numerical", "passthrough", self._NUMERICAL_COLUMNS),
            ]
        )
        model = Pipeline(
            steps=[
                ("preprocessor", preprocessor),
                ("classifier", LogisticRegression(random_state=RANDOM_SEED, max_iter=1000)),
            ]
        )
        model.fit(train_df[self._FEATURE_COLUMNS], train_df[self._TARGET_COLUMN])
        return model

    def _normalize_features(self, features: dict) -> dict:
        return {
            "bin": int(features["bin"]),
            "card_scheme": str(features["card_scheme"]).lower(),
            "card_class": str(features["card_class"]).lower(),
            "transaction_type": str(features["transaction_type"]).lower(),
            "token_lifecycle_status": str(features["token_lifecycle_status"]).lower(),
            "historical_decline_rate": float(features["historical_decline_rate"]),
            "amount": float(features["amount"]),
        }

    def _probability_trace(self, features: dict) -> dict[str, float]:
        payload = pd.DataFrame([self._normalize_features(features)])
        classes = self._model.named_steps["classifier"].classes_
        probabilities = self._model.predict_proba(payload)[0]
        return {
            gateway: float(probability)
            for gateway, probability in zip(classes, probabilities, strict=True)
        }

    def predict_best_route(self, features: dict) -> tuple[str, dict]:
        probabilities = self._probability_trace(features)
        selected_gateway = max(probabilities, key=probabilities.get)
        return selected_gateway, probabilities
