"""Backtest metrics tests."""

import pytest

from goldbot.backtest import (
    MIN_TRADES_FOR_CLAIMS,
    MIN_TRADES_FOR_SHARPE,
    consecutive_runs,
    evaluate_trades,
    expectancy,
    sharpe_ratio,
)


def test_sharpe_none_below_sample_floor():
    assert sharpe_ratio([10.0, -5.0]) is None


def test_sharpe_positive_for_positive_edge():
    pnls = [10.0] * 20 + [-5.0] * 10
    s = sharpe_ratio(pnls)
    assert s is not None and s > 0


def test_expectancy_math():
    # 40% win rate, avg win 200, avg loss 100 -> 0.4*200 - 0.6*100 = 20
    assert expectancy(0.4, 200.0, 100.0) == pytest.approx(20.0)


def test_consecutive_runs():
    wins, losses = consecutive_runs([5, 5, -3, 5, -3, -3, -3, 5, 5, 5, 5])
    assert wins == 4
    assert losses == 3


def test_evaluate_trades_full_shape():
    trades = [{"pnl": p} for p in ([15.0] * 18 + [-10.0] * 12)]
    m = evaluate_trades(trades, risk_per_trade_amount=10.0)
    assert m["total_trades"] == 30
    assert m["win_rate"] == 60.0
    assert m["profit_factor"] == pytest.approx(2.25)
    assert m["expectancy"] > 0
    assert m["sharpe_ratio"] is not None
    assert m["max_consecutive_wins"] >= 1
    assert m["max_consecutive_losses"] >= 1
    assert m["average_risk_reward"] is not None
    assert m["insufficient_sample"] is False


def test_evaluate_trades_small_sample_is_flagged():
    trades = [{"pnl": 10.0}, {"pnl": -5.0}]
    m = evaluate_trades(trades)
    assert m["insufficient_sample"] is True
    assert "claim" in (m["caveat"] or "").lower()


def test_evaluate_trades_empty():
    m = evaluate_trades([])
    assert m["total_trades"] == 0
    assert m["sharpe_ratio"] is None


def test_profit_factor_infinite_when_no_losses():
    m = evaluate_trades([{"pnl": 10.0}] * MIN_TRADES_FOR_CLAIMS)
    assert m["profit_factor"] == float("inf")


def test_sample_floor_constants():
    assert MIN_TRADES_FOR_SHARPE >= 10
    assert MIN_TRADES_FOR_CLAIMS >= 30
