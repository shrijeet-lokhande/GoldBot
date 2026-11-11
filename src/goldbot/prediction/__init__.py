"""XAUUSD prediction pipeline.

Pipeline: validated candles -> features (no look-ahead) -> transparent
logistic model -> honest validation (chronological split, walk-forward,
baselines, Brier, calibration) -> 10-field forecast.

Data-availability limitation is stated, not hidden: the only dataset
currently available is 1,510 x 15m bars (~15.7 days). The model trains on
whatever validated history exists; accuracy figures are computed
out-of-sample within that window and MUST NOT be read as a general claim.
`scripts/fetch_history.py` extends the dataset when broker credentials
are provided.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from goldbot.core.models import Candle
from goldbot.prediction.features import (
    FeatureMatrix,
    adx_regime,
    build_features,
    latest_feature_row,
)
from goldbot.prediction.forecast import DISCLAIMER, Forecast, build_forecast
from goldbot.prediction.model import LogisticModel
from goldbot.prediction.validation import (
    EvaluationReport,
    calibration_bins,
    evaluate_single_split,
    walk_forward,
)

MIN_ROWS_FOR_EVAL = 250  # below this, honest out-of-sample evaluation is impossible


@dataclass
class PredictionResult:
    forecast: Forecast
    evaluation: EvaluationReport | None
    data_limitation: str | None
    features_used: tuple[str, ...]
    coefficients: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "forecast": self.forecast.to_dict(),
            "features_used": list(self.features_used),
            "model_coefficients": {k: round(v, 4) for k, v in self.coefficients.items()},
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "data_limitation": self.data_limitation,
        }


def run_prediction(
    candles: list[Candle],
    horizon_bars: int = 4,
    base_timeframe: str = "15m",
    train_frac: float = 0.7,
) -> PredictionResult:
    """End-to-end prediction: features -> fit -> validate -> forecast."""
    completed = [c for c in candles if c.is_complete]
    matrix: FeatureMatrix = build_features(completed, horizon_bars)
    regime = adx_regime(completed)

    limitation: str | None = None
    evaluation: EvaluationReport | None = None

    if len(matrix.y) < MIN_ROWS_FOR_EVAL:
        limitation = (
            f"Only {len(matrix.y)} usable feature rows available; honest "
            f"out-of-sample evaluation requires >= {MIN_ROWS_FOR_EVAL}. The "
            "forecast below is UNVALIDATED — treat with maximum skepticism. "
            "Extend the dataset with scripts/fetch_history.py."
        )
        model = LogisticModel().fit(matrix.x, matrix.y)
        prob_up = _live_probability(model, completed, horizon_bars)
        forecast = build_forecast(
            completed, prob_up, regime, horizon_bars, base_timeframe, evaluation=None
        )
        return PredictionResult(
            forecast=forecast,
            evaluation=None,
            data_limitation=limitation,
            features_used=matrix.names,
            coefficients=model.coefficients,
        )

    # Full pipeline: chronological split -> out-of-sample metrics -> baselines.
    # The momentum baseline uses the ret_1 feature column (last completed
    # bar's return) — exactly what a "predict up if last bar was up" rule does.
    report, model = evaluate_single_split(
        matrix.x,
        matrix.y,
        matrix.forward_return,
        matrix.x[:, 0],
        train_frac,
    )
    evaluation = report

    folds = walk_forward(matrix.x, matrix.y)
    if folds:
        evaluation.walk_forward_folds = folds
        evaluation.walk_forward_accuracy = float(np.mean([f["accuracy"] for f in folds]))

    prob_up = _live_probability(model, completed, horizon_bars)
    forecast = build_forecast(
        completed,
        prob_up,
        regime,
        horizon_bars,
        base_timeframe,
        evaluation=evaluation.to_dict(),
    )
    return PredictionResult(
        forecast=forecast,
        evaluation=evaluation,
        data_limitation=None,
        features_used=matrix.names,
        coefficients=model.coefficients,
    )


def _live_probability(
    model: LogisticModel, completed: list, horizon_bars: int
) -> float:
    """Model probability of up over the horizon for the latest completed bar."""
    row = latest_feature_row(completed, horizon_bars)
    # Keep column order identical to training features.
    values = [float(row[name]) for name in model.feature_names]
    return float(model.predict_proba(np.array([values]))[0])


# Re-exported so API/docs can reference calibration output directly.
__all__ = [
    "PredictionResult",
    "run_prediction",
    "DISCLAIMER",
    "calibration_bins",
]
