"""Forecast assembly — the 10-field prediction output.

Confidence is explicitly NOT a probability: it is a bounded heuristic score
(0-100) derived from out-of-sample edge over baselines and data volume. True
calibration status is reported separately (Brier + calibration bins).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from goldbot.core.models import Candle
from goldbot.indicators import atr


@dataclass(frozen=True)
class Forecast:
    directional_bias: str            # "up" | "down" | "neutral"
    regime: str                      # trending | range | transitional | unknown
    entry_zone: tuple[float, float]
    invalidation_level: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    horizon: str                     # e.g. "4 bars (1h on 15m data)"
    confidence: int                  # 0-100 heuristic, NOT a probability
    supporting_evidence: list[str]
    probability_up: float            # model output; calibration reported separately
    disclaimer: str

    def to_dict(self) -> dict:
        return {
            "directional_bias": self.directional_bias,
            "regime": self.regime,
            "entry_zone": [round(self.entry_zone[0], 2), round(self.entry_zone[1], 2)],
            "invalidation_level": round(self.invalidation_level, 2),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "risk_reward": round(self.risk_reward, 2),
            "horizon": self.horizon,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "probability_up": round(self.probability_up, 4),
            "disclaimer": self.disclaimer,
        }


DISCLAIMER = (
    "Confidence is a heuristic score, not a calibrated probability. "
    "Statistical forecast from historical XAUUSD data only; not financial advice. "
    "Levels are computed from ATR-scaled structure, not guaranteed by any broker feed."
)

# Risk/reward target: 1.5R minimum is the live-guard floor (docs/THRESHOLDS.md).
STOP_ATR_MULT = 1.5
TP_ATR_MULT = 2.25  # 1.5 x 1.5 keeps RR at the guard floor when structure allows
RR_TARGET = 1.5


def build_forecast(
    candles: list[Candle],
    probability_up: float,
    regime: str,
    horizon_bars: int,
    base_timeframe: str = "15m",
    evaluation: dict | None = None,
) -> Forecast:
    """Assemble the forecast levels from ATR-scaled structure on completed bars."""
    completed = [c for c in candles if c.is_complete]
    close = np.array([c.close for c in completed], dtype=float)
    high = np.array([c.high for c in completed], dtype=float)
    low = np.array([c.low for c in completed], dtype=float)

    atr_series = atr(pd.Series(high), pd.Series(low), pd.Series(close), 14)
    atr_value = float(atr_series.iloc[-1])
    if not np.isfinite(atr_value) or atr_value <= 0:
        atr_value = float(np.mean(high[-20:] - low[-20:])) or 1.0

    last = float(close[-1])
    bias = "up" if probability_up > 0.55 else "down" if probability_up < 0.45 else "neutral"

    if bias == "up":
        entry_lo, entry_hi = last - 0.25 * atr_value, last + 0.25 * atr_value
        stop = last - STOP_ATR_MULT * atr_value
        tp = last + TP_ATR_MULT * atr_value
        invalidation = stop
    elif bias == "down":
        entry_lo, entry_hi = last - 0.25 * atr_value, last + 0.25 * atr_value
        stop = last + STOP_ATR_MULT * atr_value
        tp = last - TP_ATR_MULT * atr_value
        invalidation = tp if bias == "down" else stop
        # For a short, the idea is invalidated when price reaches the TP zone;
        # structural invalidation is the ATR stop above.
        invalidation = stop
    else:
        entry_lo, entry_hi = last - 0.5 * atr_value, last + 0.5 * atr_value
        stop = last - STOP_ATR_MULT * atr_value
        tp = last + TP_ATR_MULT * atr_value
        invalidation = stop

    risk = abs(last - stop)
    reward = abs(tp - last)
    rr = reward / risk if risk > 0 else 0.0

    # Confidence heuristic (0-100): out-of-sample edge + data volume. Explicitly
    # NOT calibrated; see disclaimer and the evaluation block for true scores.
    confidence = 0
    evidence: list[str] = []
    if evaluation:
        acc = evaluation.get("directional_accuracy")
        base = max(
            evaluation.get("baseline_majority_accuracy") or 0.0,
            evaluation.get("momentum_accuracy") or 0.0,
        )
        wf = evaluation.get("walk_forward_accuracy")
        if isinstance(acc, (int, float)) and isinstance(base, (int, float)):
            edge = acc - base
            confidence += int(max(0.0, min(edge, 0.1)) * 500)  # 0-50 from edge
            evidence.append(
                f"out-of-sample directional accuracy {acc:.1%} vs best baseline {base:.1%} "
                f"(edge {edge:+.1%})"
            )
        if evaluation.get("beats_baselines"):
            evidence.append("model beats drift and momentum baselines out-of-sample")
        else:
            confidence = int(confidence * 0.5)
            evidence.append("model does NOT beat baselines — confidence halved")
        if isinstance(wf, (int, float)):
            confidence += int(max(0.0, min(wf - 0.5, 0.1)) * 200)  # 0-20 walk-forward
            evidence.append(f"walk-forward accuracy {wf:.1%}")
        n_train = evaluation.get("train_rows") or 0
        if n_train >= 800:
            confidence += 10
        evidence.append(f"trained on {n_train} chronological rows (no shuffling)")
    evidence.append(f"regime: {regime} (ADX 25/20 thresholds)")
    evidence.append(
        f"levels are ATR-scaled: stop 1.5x ATR ({atr_value:.2f} USD), target 2.25x ATR"
    )
    confidence = int(max(0, min(confidence, 90)))

    hours = horizon_bars * (15 if base_timeframe == "15m" else 1) / 60
    horizon = f"{horizon_bars} bars (~{hours:g}h on {base_timeframe} data)"

    return Forecast(
        directional_bias=bias,
        regime=regime,
        entry_zone=(entry_lo, entry_hi),
        invalidation_level=invalidation,
        stop_loss=stop,
        take_profit=tp,
        risk_reward=rr,
        horizon=horizon,
        confidence=confidence,
        supporting_evidence=evidence,
        probability_up=probability_up,
        disclaimer=DISCLAIMER,
    )


__all__ = ["Forecast", "build_forecast", "DISCLAIMER"]
