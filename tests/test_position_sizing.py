"""Position sizing math tests."""

import pytest

from goldbot.core.exceptions import MetadataError, RiskError
from goldbot.risk.position_sizing import calculate_position_size


@pytest.fixture()
def instrument():
    from goldbot.core.models import InstrumentMetadata

    return InstrumentMetadata(
        symbol="XAUUSD",
        contract_size=100.0,
        tick_size=0.1,
        tick_value=1.0,
        volume_step=0.01,
        min_volume=0.01,
        max_volume=100.0,
        verified=True,
    )


def test_basic_long_sizing(instrument):
    size = calculate_position_size(
        equity=10_000.0,
        risk_per_trade_pct=0.25,
        entry_price=2000.0,
        stop_price=1980.0,  # 20 USD stop distance
        instrument=instrument,
        side="long",
    )
    # $25 risk / (20 * 100) = 0.0125 -> floor to 0.01
    assert size == pytest.approx(0.01)


def test_exact_multiple_rounds_down(instrument):
    size = calculate_position_size(
        equity=100_000.0, risk_per_trade_pct=0.5,
        entry_price=2000.0, stop_price=1975.0,  # 25 distance
        instrument=instrument, side="long",
    )
    # $500 / (25*100) = 0.20 exactly
    assert size == pytest.approx(0.20)


def test_short_sizing_symmetry(instrument):
    size = calculate_position_size(
        equity=100_000.0, risk_per_trade_pct=0.5,
        entry_price=2000.0, stop_price=2025.0,
        instrument=instrument, side="short",
    )
    assert size == pytest.approx(0.20)


def test_below_minimum_volume_rejects(instrument):
    with pytest.raises(RiskError, match="below minimum"):
        calculate_position_size(
            equity=100.0, risk_per_trade_pct=0.25,
            entry_price=2000.0, stop_price=1980.0,
            instrument=instrument, side="long",
        )


def test_zero_stop_distance_rejects(instrument):
    with pytest.raises(RiskError, match="positive"):
        calculate_position_size(
            equity=10_000.0, risk_per_trade_pct=0.25,
            entry_price=2000.0, stop_price=2000.0,
            instrument=instrument, side="long",
        )


def test_inverted_stop_rejects(instrument):
    with pytest.raises(RiskError, match="positive"):
        calculate_position_size(
            equity=10_000.0, risk_per_trade_pct=0.25,
            entry_price=2000.0, stop_price=2020.0,  # stop above entry for a long
            instrument=instrument, side="long",
        )


def test_unverified_metadata_raises(instrument):
    instrument.verified = False
    with pytest.raises(MetadataError):
        calculate_position_size(
            equity=10_000.0, risk_per_trade_pct=0.25,
            entry_price=2000.0, stop_price=1980.0,
            instrument=instrument, side="long",
        )


def test_max_volume_clamps(instrument):
    instrument.max_volume = 0.5
    size = calculate_position_size(
        equity=1_000_000.0, risk_per_trade_pct=1.0,
        entry_price=2000.0, stop_price=1980.0,
        instrument=instrument, side="long",
    )
    assert size == pytest.approx(0.5)
