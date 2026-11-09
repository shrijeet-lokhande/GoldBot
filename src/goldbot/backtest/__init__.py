"""Backtesting metrics.

Complements the engine's live performance output with the research-grade
metrics required for honest strategy evaluation. All functions are pure.

Bias policy (section 8 of the spec):
- Metrics never annualise from tiny samples; ``sharpe_ratio`` returns None
  below a minimum trade count.
- ``insufficient_sample`` flags result sets too small to claim anything.
"""

from __future__ import annotations

import math
from typing import Sequence

MIN_TRADES_FOR_SHARPE = 10
MIN_TRADES_FOR_CLAIMS = 30


def sharpe_ratio(pnl_series: Sequence[float], risk_free_per_trade: float = 0.0) -> float | None:
    """Per-trade Sharpe (mean/std of trade P&L). None below the sample floor."""
    if len(pnl_series) < MIN_TRADES_FOR_SHARPE:
        return None
    mean = sum(pnl_series) / len(pnl_series)
    variance = sum((p - mean) ** 2 for p in pnl_series) / (len(pnl_series) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return (mean - risk_free_per_trade) / std


def expectancy(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Expected value per trade in currency units.

    ``avg_loss`` must be a positive magnitude.
    """
    loss_rate = 1.0 - win_rate
    return win_rate * avg_win - loss_rate * avg_loss


def consecutive_runs(pnl_series: Sequence[float]) -> tuple[int, int]:
    """(max consecutive wins, max consecutive losses)."""
    max_wins = max_losses = wins = losses = 0
    for pnl in pnl_series:
        if pnl > 0:
            wins += 1
            losses = 0
        else:
            losses += 1
            wins = 0
        max_wins = max(max_wins, wins)
        max_losses = max(max_losses, losses)
    return max_wins, max_losses


def average_risk_reward(pnl_series: Sequence[float], risk_per_trade: float) -> float | None:
    """Mean reward:risk across trades, given a constant per-trade risk amount."""
    if not pnl_series or risk_per_trade <= 0:
        return None
    return sum(pnl_series) / len(pnl_series) / risk_per_trade


def evaluate_trades(
    trades: Sequence[dict],
    risk_per_trade_amount: float | None = None,
) -> dict:
    """Full metric set over a closed-trade ledger.

    Each trade dict needs at least ``{"pnl": float}`` (as produced by the
    paper broker's trade history). Returns metrics plus honest sample-size
    caveats — a small or selectively chosen dataset never supports a
    profitability claim.
    """
    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    max_wins, max_losses = consecutive_runs(pnls)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "total_trades": len(pnls),
        "win_rate": round(win_rate * 100.0, 2),
        "profit_factor": (
            round(gross_win / gross_loss, 3)
            if gross_loss > 0
            else (None if gross_win == 0 else float("inf"))
        ),
        "net_return": round(sum(pnls), 2),
        "max_drawdown": round(max_dd, 2),
        "average_win": round(avg_win, 2),
        "average_loss": round(avg_loss, 2),
        "average_risk_reward": (
            round(rr, 3)
            if risk_per_trade_amount
            and (rr := average_risk_reward(pnls, risk_per_trade_amount)) is not None
            else None
        ),
        "expectancy": round(expectancy(win_rate, avg_win, avg_loss), 4),
        "sharpe_ratio": (round(s, 3) if (s := sharpe_ratio(pnls)) is not None else None),
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "insufficient_sample": len(pnls) < MIN_TRADES_FOR_CLAIMS,
        "caveat": (
            f"Only {len(pnls)} trades: below the {MIN_TRADES_FOR_CLAIMS}-trade "
            "floor for any profitability claim."
            if len(pnls) < MIN_TRADES_FOR_CLAIMS
            else None
        ),
    }


__all__ = [
    "sharpe_ratio",
    "expectancy",
    "consecutive_runs",
    "average_risk_reward",
    "evaluate_trades",
    "MIN_TRADES_FOR_SHARPE",
    "MIN_TRADES_FOR_CLAIMS",
]
