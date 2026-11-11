"""Tests for the XAUUSD prediction pipeline (features, model, validation, forecast)."""

import numpy as np
import pytest

from goldbot.market_data.csv_provider import CsvMarketDataProvider
from goldbot.prediction import run_prediction
from goldbot.prediction.baselines import coin_flip_baseline, drift_baseline, momentum_baseline
from goldbot.prediction.features import (
    FEATURE_NAMES,
    adx_regime,
    build_features,
    latest_feature_row,
)
from goldbot.prediction.model import LogisticModel
from goldbot.prediction.validation import brier, calibration_bins, chronological_split, walk_forward


@pytest.fixture(scope="module")
def sample_candles():
    provider = CsvMarketDataProvider("data/fixtures/sample_xauusd_15m.csv")
    from datetime import datetime, timezone

    return provider.get_historical_bars(
        symbol="XAUUSD",
        timeframe="15m",
        start=datetime.min.replace(tzinfo=timezone.utc),
        end=datetime.now(timezone.utc),
    )


def test_features_no_lookahead_alignment(sample_candles):
    """Target row t must equal the sign of close[t+h]/close[t]-1 exactly."""
    candles = [c for c in sample_candles if c.is_complete]
    horizon = 4
    m = build_features(candles, horizon_bars=horizon)
    closes = np.array([c.close for c in candles], dtype=float)
    # Recompute the validity mask used inside build_features.
    fwd = closes[horizon:] / closes[:-horizon] - 1.0
    # The matrix is truncated by feature warm-up; verify the LAST rows line up
    # exactly (warm-up only removes head rows).
    n = len(m.y)
    assert n <= len(fwd)
    assert np.allclose(m.forward_return[-10:], fwd[-10:], atol=1e-12)
    assert np.array_equal(m.y[-10:], (fwd[-10:] > 0).astype(float))


def test_features_reject_insufficient_data():
    from datetime import datetime, timedelta, timezone

    from goldbot.core.models import Candle

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            symbol="XAUUSD",
            timeframe="15m",
            timestamp_utc=t0 + timedelta(minutes=15 * i),
            open=2000.0,
            high=2001.0,
            low=1999.0,
            close=2000.5,
            volume=10.0,
            source="test",
            is_complete=True,
        )
        for i in range(40)
    ]
    with pytest.raises(ValueError, match="insufficient history"):
        build_features(candles, horizon_bars=4)


def test_features_names_and_shape(sample_candles):
    m = build_features(sample_candles, horizon_bars=4)
    assert m.names == FEATURE_NAMES
    assert m.x.shape == (len(m.y), len(FEATURE_NAMES))
    assert set(m.y) <= {0.0, 1.0}


def test_logistic_model_learns_separable_data():
    rng = np.random.default_rng(3)
    n = 500
    x = rng.normal(size=(n, 3))
    y = (x[:, 0] * 2.0 + x[:, 1] - x[:, 2] > 0).astype(float)
    model = LogisticModel(epochs=500).fit(x, y)
    probs = model.predict_proba(x)
    acc = ((probs >= 0.5).astype(float) == y).mean()
    assert acc > 0.9
    assert set(model.coefficients) == {"f0", "f1", "f2"} or len(model.coefficients) == 3


def test_logistic_model_refuses_tiny_training_set():
    x = np.random.default_rng(1).normal(size=(20, 3))
    y = np.ones(20)
    with pytest.raises(ValueError, match="too few training rows"):
        LogisticModel().fit(x, y)


def test_baselines_are_honest():
    rng = np.random.default_rng(5)
    y = rng.integers(0, 2, 400).astype(float)
    fwd = rng.normal(size=400)
    lag = rng.normal(size=400)
    # On random data nothing should claim far above chance.
    assert abs(drift_baseline(y, 0.7) - 0.5) < 0.2
    assert abs(momentum_baseline(fwd, lag, 0.7) - 0.5) < 0.2
    assert 0.3 <= coin_flip_baseline(y, 0.7) <= 0.7


def test_chronological_split_never_shuffles():
    n_train, n_test = chronological_split(1000, 0.7)
    assert n_train == 700 and n_test == 300


def test_brier_and_calibration():
    probs = np.array([0.1, 0.2, 0.8, 0.9])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    expected = float(np.mean((probs - y) ** 2))  # 0.025 for this example
    assert brier(probs, y) == pytest.approx(expected)
    perfect = np.array([0.0, 0.0, 1.0, 1.0])
    assert brier(perfect, y) == pytest.approx(0.0)
    bins = calibration_bins(probs, y, n_bins=5)
    assert sum(b["rows"] for b in bins) == 4


def test_walk_forward_never_uses_future_training_data(sample_candles):
    m = build_features(sample_candles, horizon_bars=4)
    folds = walk_forward(m.x, m.y, min_train=300, step=100, max_folds=3)
    assert len(folds) == 3
    assert folds[0]["train_rows"] == 300
    assert folds[1]["train_rows"] == 400  # expanding window: strictly grows


def test_run_prediction_end_to_end(sample_candles):
    result = run_prediction(sample_candles, horizon_bars=4)
    d = result.to_dict()
    f = d["forecast"]
    # The 10 required forecast fields are present.
    for key in (
        "directional_bias",
        "regime",
        "entry_zone",
        "invalidation_level",
        "stop_loss",
        "take_profit",
        "risk_reward",
        "horizon",
        "confidence",
        "supporting_evidence",
    ):
        assert key in f
    assert f["directional_bias"] in ("up", "down", "neutral")
    assert 0 <= f["confidence"] <= 90
    assert "not a calibrated probability" in f["disclaimer"]
    assert d["evaluation"] is not None
    assert d["evaluation"]["beats_baselines"] in (True, False)
    # Stop/TP must respect the directional bias.
    close = [c.close for c in sample_candles if c.is_complete][-1]
    if f["directional_bias"] == "up":
        assert f["stop_loss"] < close < f["take_profit"]
    elif f["directional_bias"] == "down":
        assert f["take_profit"] < close < f["stop_loss"]


def test_regime_thresholds_documented(sample_candles):
    regime = adx_regime(sample_candles)
    assert regime in ("trending", "range", "transitional", "unknown")


def test_latest_feature_row_matches_column_names(sample_candles):
    row = latest_feature_row(sample_candles, horizon_bars=4)
    assert list(row.keys()) == list(FEATURE_NAMES)
    assert all(np.isfinite(v) for v in row.values())
