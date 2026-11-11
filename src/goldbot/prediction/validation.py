"""Honest validation: chronological split, walk-forward, calibration.

Rules enforced here:
- Training data always precedes test data (no shuffling, ever).
- Walk-forward refits use only past rows at each fold.
- Brier score and calibration bins quantify how far the model's "confidence"
  is from real probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from goldbot.prediction.model import LogisticModel


@dataclass
class EvaluationReport:
    train_rows: int
    test_rows: int
    directional_accuracy: float          # test rows
    baseline_accuracy: float             # majority-class of train, on test
    momentum_accuracy: float
    brier_score: float | None = None     # None if never up predicted
    log_loss: float | None = None
    calibration_bins: list[dict] = field(default_factory=list)
    walk_forward_folds: list[dict] = field(default_factory=list)
    walk_forward_accuracy: float | None = None
    beats_baselines: bool | None = None

    def to_dict(self) -> dict:
        return {
            "train_rows": self.train_rows,
            "test_rows": self.test_rows,
            "directional_accuracy": round(self.directional_accuracy, 4),
            "baseline_majority_accuracy": round(self.baseline_accuracy, 4),
            "momentum_accuracy": round(self.momentum_accuracy, 4),
            "brier_score": None if self.brier_score is None else round(self.brier_score, 4),
            "log_loss": None if self.log_loss is None else round(self.log_loss, 4),
            "calibration_bins": self.calibration_bins,
            "walk_forward_folds": self.walk_forward_folds,
            "walk_forward_accuracy": None
            if self.walk_forward_accuracy is None
            else round(self.walk_forward_accuracy, 4),
            "beats_baselines": self.beats_baselines,
        }


def brier(probs: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((probs - y) ** 2))


def _log_loss(probs: np.ndarray, y: np.ndarray) -> float:
    eps = 1e-12
    p = np.clip(probs, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_bins(probs: np.ndarray, y: np.ndarray, n_bins: int = 5) -> list[dict]:
    """Empirical up-rate within each predicted-probability bin."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (probs >= lo) & (probs < hi if i < n_bins - 1 else probs <= hi)
        if mask.sum() == 0:
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "rows": 0, "empirical_up_rate": None})
            continue
        out.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "rows": int(mask.sum()),
                "empirical_up_rate": round(float(y[mask].mean()), 4),
            }
        )
    return out


def chronological_split(rows: int, train_frac: float = 0.7) -> tuple[int, int]:
    n_train = int(rows * train_frac)
    return n_train, rows - n_train


def evaluate_single_split(
    x: np.ndarray,
    y: np.ndarray,
    forward_return: np.ndarray,
    lag_return: np.ndarray,
    train_frac: float = 0.7,
) -> tuple[EvaluationReport, LogisticModel]:
    """One chronological train/test split with baseline comparison."""
    n_train, n_test = chronological_split(len(y), train_frac)
    model = LogisticModel().fit(x[:n_train], y[:n_train])
    probs = model.predict_proba(x[n_train:])
    preds = (probs >= 0.5).astype(float)
    truth = y[n_train:]

    from goldbot.prediction.baselines import drift_baseline, momentum_baseline

    report = EvaluationReport(
        train_rows=n_train,
        test_rows=n_test,
        directional_accuracy=float((preds == truth).mean()) if n_test else float("nan"),
        baseline_accuracy=drift_baseline(y, train_frac),
        momentum_accuracy=momentum_baseline(forward_return, lag_return, train_frac),
        brier_score=brier(probs, truth),
        log_loss=_log_loss(probs, truth),
        calibration_bins=calibration_bins(probs, truth),
    )
    report.beats_baselines = (
        report.directional_accuracy > max(report.baseline_accuracy, report.momentum_accuracy)
    )
    return report, model


def walk_forward(
    x: np.ndarray,
    y: np.ndarray,
    min_train: int = 300,
    step: int = 100,
    max_folds: int = 8,
) -> list[dict]:
    """Expanding-window walk-forward: refit on the past, test on the next step.

    Never looks ahead: fold k trains on rows [0, t_k) and tests on
    [t_k, t_k + step). Returns per-fold accuracy plus the pooled figure.
    """
    if len(y) <= min_train + step:
        return []
    folds: list[dict] = []
    for fold_no, start in enumerate(range(min_train, len(y) - step + 1, step)):
        if fold_no >= max_folds:
            break
        end = start + step
        model = LogisticModel().fit(x[:start], y[:start])
        probs = model.predict_proba(x[start:end])
        preds = (probs >= 0.5).astype(float)
        acc = float((preds == y[start:end]).mean())
        folds.append(
            {
                "train_rows": start,
                "test_rows": step,
                "accuracy": round(acc, 4),
            }
        )
    return folds


__all__ = [
    "EvaluationReport",
    "brier",
    "calibration_bins",
    "chronological_split",
    "evaluate_single_split",
    "walk_forward",
]
