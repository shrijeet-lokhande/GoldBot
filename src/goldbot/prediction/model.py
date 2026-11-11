"""Transparent logistic model for XAUUSD directional forecasting.

Deliberately simple and fully inspectable: standardised features -> logistic
regression trained by full-batch gradient descent with L2 regularisation.
No hidden layers, no black-box dependencies — every coefficient can be read
and published in the API response.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from goldbot.prediction.features import FEATURE_NAMES


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


@dataclass
class LogisticModel:
    """Logistic regression P(up over horizon | features).

    Attributes are exposed for transparency: ``coefficients`` maps feature
    name -> weight, ``intercept`` is the bias term, and the standardisation
    statistics come from the TRAINING split only (no look-ahead).
    """

    learning_rate: float = 0.1
    epochs: int = 800
    l2: float = 1e-3
    coefficients: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    mean: np.ndarray | None = None
    std: np.ndarray | None = None
    feature_names: tuple[str, ...] = FEATURE_NAMES

    def fit(self, x: np.ndarray, y: np.ndarray) -> "LogisticModel":
        if x.ndim != 2 or x.shape[0] != y.shape[0]:
            raise ValueError("x must be (rows, features) and y (rows,)")
        if x.shape[0] < 30:
            raise ValueError(
                f"too few training rows ({x.shape[0]}); refusing to fit"
            )
        # Standardisation statistics from the training rows only.
        self.mean = x.mean(axis=0)
        std = x.std(axis=0)
        std[std == 0] = 1.0
        self.std = std

        xs = (x - self.mean) / self.std
        n_rows, n_feat = xs.shape
        w = np.zeros(n_feat)
        b = 0.0
        for _ in range(self.epochs):
            p = _sigmoid(xs @ w + b)
            err = p - y
            grad_w = (xs.T @ err) / n_rows + self.l2 * w
            grad_b = float(err.mean())
            w -= self.learning_rate * grad_w
            b -= self.learning_rate * grad_b

        self.coefficients = {
            name: float(wi) for name, wi in zip(self.feature_names, w)
        }
        # In case the caller passed fewer columns than the canonical names
        # (unit tests do this), keep the names aligned with the fit.
        self.feature_names = tuple(self.feature_names[:n_feat])
        self.intercept = float(b)
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        if self.mean is None or self.std is None:
            raise RuntimeError("model is not fitted")
        xs = (x - self.mean) / self.std
        return _sigmoid(xs @ self._weights() + self.intercept)

    def _weights(self) -> np.ndarray:
        return np.array([self.coefficients[n] for n in self.feature_names])

    @property
    def is_fitted(self) -> bool:
        return self.mean is not None and bool(self.coefficients)


__all__ = ["LogisticModel"]
