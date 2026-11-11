"""Naive baselines the statistical model must beat to justify its existence."""

from __future__ import annotations

import numpy as np


def drift_baseline(y: np.ndarray, train_frac: float = 0.7) -> float:
    """Predict the majority class of the TRAINING split for every test row.

    For gold this is usually "up" (positive historical drift) — exactly the
    lazy baseline a gold model must beat to prove it adds anything.
    """
    n_train = int(len(y) * train_frac)
    majority = 1.0 if y[:n_train].mean() >= 0.5 else 0.0
    preds = np.full(len(y) - n_train, majority)
    truth = y[n_train:]
    return float((preds == truth).mean()) if len(truth) else float("nan")


def momentum_baseline(
    forward_return: np.ndarray, lag_return: np.ndarray, train_frac: float = 0.7
) -> float:
    """Predict up if the most recent 1-bar return was positive (test rows only)."""
    n_train = int(len(forward_return) * train_frac)
    preds = (lag_return[n_train:] > 0).astype(float)
    truth = (forward_return[n_train:] > 0).astype(float)
    return float((preds == truth).mean()) if len(truth) else float("nan")


def coin_flip_baseline(y: np.ndarray, train_frac: float = 0.7, seed: int = 7) -> float:
    """Deterministic-seeded 50/50 predictor (sanity floor)."""
    rng = np.random.default_rng(seed)
    n_train = int(len(y) * train_frac)
    preds = rng.integers(0, 2, size=len(y) - n_train).astype(float)
    truth = y[n_train:]
    return float((preds == truth).mean()) if len(truth) else float("nan")


__all__ = ["drift_baseline", "momentum_baseline", "coin_flip_baseline"]
