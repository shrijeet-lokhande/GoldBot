"""Market structure detector tests with synthetic, rule-verifiable series."""

from goldbot.analysis.structure import analyze_structure
from goldbot.core.models import Candle
from tests.conftest import make_candle


def _series(prices: list[tuple[float, float, float, float]]) -> list[Candle]:
    """(open, high, low, close) tuples -> candles."""
    return [
        make_candle(i, open_=o, high=h, low=lo, close=c) for i, (o, h, lo, c) in enumerate(prices)
    ]


def _flat(n: int = 40) -> list[tuple[float, float, float, float]]:
    return [(1950.0, 1955.0, 1948.0, 1952.0)] * n


def test_insufficient_data_returns_empty():
    ms = analyze_structure(_series(_flat(5)))
    assert ms.swings == []
    assert ms.trend == "range"


def test_uptrend_labels_higher_highs_and_lows():
    # Rising stair-step: every 5 bars a new, higher pivot.
    bars = []
    price = 1950.0
    for step in range(8):
        for _ in range(5):
            bars.append((price, price + 4, price - 2, price + 2))
        price += 5.0
    ms = analyze_structure(_series(bars))
    high_labels = [s.label for s in ms.swings if s.kind == "high" and s.label]
    low_labels = [s.label for s in ms.swings if s.kind == "low" and s.label]
    assert "HH" in high_labels
    assert "HL" in low_labels
    assert ms.trend == "up"


def test_downtrend_labels_lower_highs_and_lows():
    bars = []
    price = 2000.0
    for step in range(8):
        for _ in range(5):
            bars.append((price, price + 2, price - 4, price - 2))
        price -= 5.0
    ms = analyze_structure(_series(bars))
    assert ms.trend == "down"
    high_labels = [s.label for s in ms.swings if s.kind == "high" and s.label]
    low_labels = [s.label for s in ms.swings if s.kind == "low" and s.label]
    assert "LH" in high_labels
    assert "LL" in low_labels


def test_bos_bullish_detected_on_close_above_prior_high():
    # Rising structure establishes an uptrend, then a strong new high close
    # continues it -> continuation BOS (not a CHOCH).
    bars = []
    price = 1950.0
    for _step in range(4):
        for _ in range(5):
            bars.append((price, price + 4, price - 2, price + 2))
        price += 5.0
    bars.append((price, price + 25, price - 1, price + 22))  # displacement up
    ms = analyze_structure(_series(bars), atr_value=2.0)
    bullish_bos = [e for e in ms.events if e.kind == "bos" and e.direction == "bullish"]
    assert bullish_bos, f"expected a bullish BOS, got {ms.events}"
    assert bullish_bos[-1].close > bullish_bos[-1].broken_level


def test_choch_detected_on_trend_break():
    # Established uptrend (higher highs) then a decisive close below the
    # last higher low -> change of character (bearish CHOCH).
    bars = []
    price = 1950.0
    for step in range(6):
        for _ in range(5):
            bars.append((price, price + 4, price - 2, price + 2))
        price += 5.0
    # break down through the last swing low
    bars.append((price - 10, price - 8, price - 30, price - 28))
    ms = analyze_structure(_series(bars), atr_value=2.0)
    chochs = [e for e in ms.events if e.kind == "choch"]
    assert chochs, f"expected a CHOCH, got {[e.to_dict() for e in ms.events]}"
    assert chochs[-1].direction == "bearish"


def test_liquidity_sweep_wick_and_close_back():
    bars = _flat(20)
    # Wick above the flat-range highs but close back inside.
    bars.append((1952.0, 1965.0, 1951.0, 1953.0))
    ms = analyze_structure(_series(bars), atr_value=2.0)
    sweeps = [s for s in ms.sweeps if s.side == "high"]
    assert sweeps, "expected a high-side liquidity sweep"
    assert sweeps[-1].extreme_price > sweeps[-1].swept_level
    assert sweeps[-1].close < sweeps[-1].swept_level


def test_equal_highs_detected():
    bars = []
    # Two swing highs at exactly the same level separated by a valley.
    for i in range(10):
        bars.append((1950.0, 1952.0, 1948.0, 1951.0))
    bars.append((1951.0, 1960.0, 1950.0, 1951.0))  # high #1 at 1960
    for i in range(8):
        bars.append((1950.0, 1952.0, 1948.0, 1951.0))
    bars.append((1951.0, 1960.02, 1950.0, 1951.0))  # high #2 ~1960 (EQH)
    for i in range(6):
        bars.append((1950.0, 1952.0, 1948.0, 1951.0))
    ms = analyze_structure(_series(bars), atr_value=2.0)
    assert ms.equal_highs, "expected equal highs"
    eqh = next(e for e in ms.equal_highs if abs(e.price - 1960.0) < 1.0)
    assert len(eqh.indices) >= 2
    assert abs(eqh.price - 1960.0) <= eqh.tolerance


def test_fair_value_gap_detected_and_filled_tracking():
    bars = _flat(15)
    # Bullish displacement: candle i low far above candle i-2 high.
    bars.append((1952.0, 1975.0, 1962.0, 1974.0))
    bars.append((1974.0, 1980.0, 1970.0, 1978.0))
    ms = analyze_structure(_series(bars), atr_value=2.0)
    bullish = [f for f in ms.fvgs if f.direction == "bullish"]
    assert bullish, "expected a bullish FVG"
    gap = bullish[-1]
    assert gap.bottom < gap.top
    assert not gap.filled


def test_order_block_requires_displacement():
    bars = _flat(15)
    # Down candle followed by a >1 ATR displacement up.
    bars.append((1952.0, 1953.0, 1944.0, 1945.0))  # down candle (OB)
    bars.append((1945.0, 1975.0, 1944.0, 1974.0))  # 29-point displacement
    ms = analyze_structure(_series(bars), atr_value=2.0)
    bullish_obs = [o for o in ms.order_blocks if o.direction == "bullish"]
    assert bullish_obs, "expected a bullish order block"
    ob = bullish_obs[-1]
    assert ob.displacement_atr > 1.0
    assert ob.top >= ob.bottom


def test_consolidation_and_breakout_detection():
    bars = _flat(12)
    breakout = (1952.0, 1975.0, 1951.0, 1974.0)
    bars.append(breakout)
    bars.append((1974.0, 1980.0, 1970.0, 1978.0))
    # ATR 10: the flat 7-point range qualifies as consolidation (<2*ATR).
    ms = analyze_structure(_series(bars), atr_value=10.0)
    assert ms.consolidations, "expected consolidation in the flat range"
    bull_breakouts = [b for b in ms.breakouts if b.direction == "bullish"]
    assert bull_breakouts, "expected a bullish breakout"


def test_false_breakout_flagged_when_close_reenters():
    bars = _flat(12)
    bars.append((1952.0, 1975.0, 1951.0, 1974.0))  # breakout close above
    bars.append((1974.0, 1976.0, 1950.0, 1951.0))  # close back inside
    ms = analyze_structure(_series(bars), atr_value=10.0)
    bull_breakouts = [b for b in ms.breakouts if b.direction == "bullish"]
    assert bull_breakouts
    assert bull_breakouts[-1].is_false


def test_rejection_zone_long_upper_wick():
    bars = _flat(12)
    bars.append((1952.0, 1970.0, 1951.0, 1953.0))  # huge upper wick
    ms = analyze_structure(_series(bars), atr_value=2.0)
    rejections = [z for z in ms.zones if z.kind == "rejection"]
    assert rejections
    top = rejections[-1]
    assert top.top == 1970.0


def test_structure_output_serialisable():
    bars = _flat(40)
    bars.append((1952.0, 1970.0, 1951.0, 1968.0))
    import json

    ms = analyze_structure(_series(bars), atr_value=2.0)
    json.dumps(ms.to_dict())  # must not raise
