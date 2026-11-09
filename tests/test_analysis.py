"""Analysis engine tests: report shape, reproducibility, honest data gaps."""

import pytest

from goldbot.analysis import AnalysisEngine
from goldbot.analysis.fundamentals import EconomicEvent, MacroDataProvider, MacroSnapshot
from goldbot.analysis.timeframes import resample_candles
from goldbot.core.models import Candle
from tests.conftest import make_candle


def _make_history(n: int = 300, timeframe: str = "15m") -> list[Candle]:
    """Deterministic trending series with pullbacks."""
    import math
    from datetime import datetime, timedelta, timezone

    candles = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        trend = i * 0.15
        wave = 8.0 * math.sin(i / 9.0)
        close = 1950.0 + trend + wave
        open_ = 1950.0 + (i - 1) * 0.15 + 8.0 * math.sin((i - 1) / 9.0)
        high = max(open_, close) + 2.0
        low = min(open_, close) - 2.0
        candles.append(
            Candle(
                symbol="XAUUSD",
                timeframe=timeframe,
                timestamp_utc=start + timedelta(minutes=15 * i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
    return candles


def test_resample_to_1h_aggregates():
    candles = _make_history(96)  # 24h of 15m bars
    hourly = resample_candles(candles, "1h")
    assert len(hourly) == 24
    assert all(c.timeframe == "1h" for c in hourly)


def test_resample_weekly_aligns_to_monday():
    candles = _make_history(14 * 96)  # 14 days
    weekly = resample_candles(candles, "1w")
    assert all(c.timestamp_utc.weekday() == 0 for c in weekly)


def test_resample_rejects_lower_timeframes():
    candles = _make_history(20)
    with pytest.raises(ValueError, match="1m"):
        resample_candles(candles, "1m")


def test_analysis_rejects_insufficient_data():
    engine = AnalysisEngine()
    with pytest.raises(ValueError, match="insufficient"):
        engine.analyze(_make_history(10))


def test_analysis_report_shape():
    engine = AnalysisEngine(base_timeframe="15m")
    report = engine.analyze(_make_history(300)).to_dict()
    for key in (
        "symbol",
        "market_regime",
        "directional_bias",
        "htf_trend",
        "ltf_setup",
        "support_levels",
        "resistance_levels",
        "liquidity_levels",
        "volatility",
        "bullish_scenarios",
        "bearish_scenarios",
        "trade_plan",
        "confidence",
        "avoid_trading_reasons",
        "data_quality",
        "indicators",
        "structure",
        "fundamentals",
        "timeframes",
    ):
        assert key in report, f"missing report key {key}"
    assert report["symbol"] == "XAUUSD"
    assert report["directional_bias"] in ("bullish", "bearish", "neutral")
    assert 0 <= report["confidence"]["score"] <= 100
    assert report["confidence"]["explanation"]


def test_analysis_is_reproducible():
    candles = _make_history(300)
    engine = AnalysisEngine(base_timeframe="15m")
    a = engine.analyze(candles).to_dict()
    b = engine.analyze(candles).to_dict()
    a.pop("generated_at_utc")
    b.pop("generated_at_utc")
    assert a == b


def test_analysis_reports_unavailable_sub_timeframes():
    engine = AnalysisEngine(base_timeframe="15m")
    report = engine.analyze(_make_history(300)).to_dict()
    dq = report["data_quality"]
    assert dq["15m"]["available"] is True
    assert dq["1h"]["available"] is True
    assert dq["1m"]["available"] is False
    assert dq["5m"]["available"] is False


def test_analysis_flags_missing_fundamentals():
    engine = AnalysisEngine(base_timeframe="15m")
    report = engine.analyze(_make_history(300)).to_dict()
    assert report["fundamentals"]["available"] is False
    assert any("fundamental" in r.lower() for r in report["avoid_trading_reasons"])


class _FakeMacro(MacroDataProvider):
    name = "fake"

    def get_snapshot(self, now_utc=None) -> MacroSnapshot:
        event = EconomicEvent(
            event_id="1",
            event_type="fomc_rate_decision",
            scheduled_at_utc=make_candle(0).timestamp_utc,
            forecast=5.25,
        )
        return MacroSnapshot(
            dxy=104.2,
            treasury_yield_10y=4.3,
            fed_rate=5.25,
            events=[event],
            source="fake",
            available=True,
        )


def test_analysis_with_macro_provider_includes_events():
    engine = AnalysisEngine(base_timeframe="15m", macro_provider=_FakeMacro())
    report = engine.analyze(_make_history(300)).to_dict()
    assert report["fundamentals"]["available"] is True
    events = report["fundamentals"]["upcoming_high_impact_events"]
    assert events and events[0]["event_type"] == "fomc_rate_decision"
    # forecast vs actual separation
    assert events[0]["status"] == "forecast_only"


def test_economic_event_status_semantics():
    from datetime import datetime, timezone

    e = EconomicEvent("1", "cpi", datetime.now(timezone.utc), forecast=3.2)
    assert e.status == "forecast_only"
    e2 = EconomicEvent("2", "cpi", datetime.now(timezone.utc), actual=3.4, forecast=3.2)
    assert e2.status == "actual"
    e3 = EconomicEvent("3", "cpi", datetime.now(timezone.utc))
    assert e3.status == "scheduled"
    assert e.is_high_impact_for_gold


def test_trade_plan_has_rr_when_directional():
    engine = AnalysisEngine(base_timeframe="15m")
    report = engine.analyze(_make_history(300)).to_dict()
    plan = report["trade_plan"]
    if plan["direction"] is not None:
        assert plan["stop_loss"] is not None
        assert plan["risk_reward_ratio"] is not None
