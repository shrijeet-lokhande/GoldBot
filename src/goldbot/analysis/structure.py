"""Market structure and price-action detection for XAUUSD.

Every detector here has explicit, measurable rules and returns structured
evidence (indices, prices, rule names). Nothing is inferred from vague
"chart reading": each detected condition carries the numeric data that
triggered it so analysis output is reproducible and auditable.

Detectors:
- swings (fractal highs/lows) and swing-label sequence (HH/HL/LH/LL)
- break of structure (BOS) and change of character (CHOCH)
- liquidity sweeps (wick beyond a prior swing with close back inside)
- equal highs / equal lows (EQH/EQL)
- fair value gaps (FVG, three-candle imbalance)
- order blocks (last opposing candle before a displacement BOS)
- supply/demand zones (from order blocks, extended)
- consolidation (low-range contraction) and breakouts / false breakouts
- rejection zones (long wicks off a level)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from goldbot.core.models import Candle


def _r(v: float, nd: int = 4) -> float:
    """numpy-safe rounding for JSON output."""
    return round(float(v), nd)


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


@dataclass
class Swing:
    index: int  # index into the candle list
    price: float
    kind: str  # "high" | "low"
    label: str | None = None  # "HH" | "HL" | "LH" | "LL"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "price": _r(self.price),
            "kind": self.kind,
            "label": self.label,
        }


@dataclass
class StructureEvent:
    kind: str  # "bos" | "choch"
    direction: str  # "bullish" | "bearish"
    index: int
    broken_level: float
    close: float

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "direction": self.direction,
            "index": self.index,
            "broken_level": _r(self.broken_level),
            "close": _r(self.close),
        }


@dataclass
class LiquiditySweep:
    index: int
    side: str  # "high" | "low"
    swept_level: float
    extreme_price: float  # wick extreme
    close: float

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "side": self.side,
            "swept_level": _r(self.swept_level),
            "extreme_price": _r(self.extreme_price),
            "close": _r(self.close),
        }


@dataclass
class EqualLevels:
    side: str  # "highs" | "lows"
    price: float
    indices: list[int]
    tolerance: float

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "price": _r(self.price),
            "indices": self.indices,
            "tolerance": _r(self.tolerance),
        }


@dataclass
class FairValueGap:
    index: int  # index of the third (displacement) candle
    direction: str  # "bullish" | "bearish"
    top: float
    bottom: float
    filled: bool = False

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2.0

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "direction": self.direction,
            "top": _r(self.top),
            "bottom": _r(self.bottom),
            "midpoint": _r(self.midpoint),
            "filled": self.filled,
        }


@dataclass
class OrderBlock:
    index: int  # candle that forms the block
    direction: str  # "bullish" (demand) | "bearish" (supply)
    top: float
    bottom: float
    displacement_atr: float  # displacement magnitude in ATRs

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "direction": self.direction,
            "top": _r(self.top),
            "bottom": _r(self.bottom),
            "displacement_atr": _r(self.displacement_atr, 3),
        }


@dataclass
class Zone:
    kind: str  # "supply" | "demand" | "rejection"
    top: float
    bottom: float
    index: int
    strength: int = 1  # touches/wick size rank

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "top": _r(self.top),
            "bottom": _r(self.bottom),
            "index": self.index,
            "strength": self.strength,
        }


@dataclass
class Breakout:
    index: int
    direction: str  # "bullish" | "bearish"
    level: float
    is_false: bool  # close back inside range within confirmation bars

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "direction": self.direction,
            "level": _r(self.level),
            "is_false": self.is_false,
        }


@dataclass
class Consolidation:
    start_index: int
    end_index: int
    top: float
    bottom: float

    @property
    def range(self) -> float:
        return self.top - self.bottom

    def to_dict(self) -> dict:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "top": _r(self.top),
            "bottom": _r(self.bottom),
            "range": _r(self.range),
        }


@dataclass
class MarketStructure:
    """Full structural snapshot for one candle series."""

    swings: list[Swing] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    sweeps: list[LiquiditySweep] = field(default_factory=list)
    equal_highs: list[EqualLevels] = field(default_factory=list)
    equal_lows: list[EqualLevels] = field(default_factory=list)
    fvgs: list[FairValueGap] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    consolidations: list[Consolidation] = field(default_factory=list)
    breakouts: list[Breakout] = field(default_factory=list)

    # Trend verdict from labelled swing sequence.
    trend: str = "range"  # "up" | "down" | "range"
    last_event: StructureEvent | None = None

    def to_dict(self) -> dict:
        return {
            "trend": self.trend,
            "swings": [s.to_dict() for s in self.swings[-20:]],
            "events": [e.to_dict() for e in self.events[-10:]],
            "last_event": self.last_event.to_dict() if self.last_event else None,
            "sweeps": [s.to_dict() for s in self.sweeps[-5:]],
            "equal_highs": [e.to_dict() for e in self.equal_highs[-3:]],
            "equal_lows": [e.to_dict() for e in self.equal_lows[-3:]],
            "fvgs": [f.to_dict() for f in self.fvgs[-5:]],
            "order_blocks": [o.to_dict() for o in self.order_blocks[-5:]],
            "zones": [z.to_dict() for z in self.zones[-8:]],
            "consolidations": [c.to_dict() for c in self.consolidations[-3:]],
            "breakouts": [b.to_dict() for b in self.breakouts[-5:]],
        }


# ---------------------------------------------------------------------------
# Detector implementation
# ---------------------------------------------------------------------------


def analyze_structure(
    candles: list[Candle],
    atr_value: float | None = None,
    pivot_left: int = 3,
    pivot_right: int = 3,
) -> MarketStructure:
    """Run all structural detectors over a completed-candle series.

    ``candles`` must be completed bars in chronological order. ``atr_value``
    is the current ATR (price units); when None a fallback of 0.1% of the
    mean price is used for tolerances.
    """
    if len(candles) < pivot_left + pivot_right + 2:
        return MarketStructure()

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    fallback_atr = (sum(closes) / len(closes)) * 0.001
    atr = atr_value if atr_value and atr_value > 0 else fallback_atr

    ms = MarketStructure()

    # --- 1. Swings (fractal pivots) + HH/HL/LH/LL labels -------------------
    swing_highs: list[Swing] = []
    swing_lows: list[Swing] = []
    for i in range(pivot_left, len(candles) - pivot_right):
        if highs[i] == max(highs[i - pivot_left : i + pivot_right + 1]):
            swing_highs.append(Swing(i, highs[i], "high"))
        if lows[i] == min(lows[i - pivot_left : i + pivot_right + 1]):
            swing_lows.append(Swing(i, lows[i], "low"))

    all_swings = sorted(swing_highs + swing_lows, key=lambda s: s.index)
    last_high: Swing | None = None
    last_low: Swing | None = None
    for s in all_swings:
        if s.kind == "high":
            if last_high is not None:
                s.label = "HH" if s.price > last_high.price else "LH"
            last_high = s
        else:
            if last_low is not None:
                s.label = "HL" if s.price > last_low.price else "LL"
            last_low = s
    ms.swings = all_swings

    # Trend from the last two high and low labels.
    high_labels = [s.label for s in swing_highs if s.label]
    low_labels = [s.label for s in swing_lows if s.label]
    up_votes = (high_labels[-1:] == ["HH"]) + (low_labels[-1:] == ["HL"])
    down_votes = (high_labels[-1:] == ["LH"]) + (low_labels[-1:] == ["LL"])
    if up_votes > down_votes:
        ms.trend = "up"
    elif down_votes > up_votes:
        ms.trend = "down"
    else:
        ms.trend = "range"

    # --- 2. BOS / CHOCH -----------------------------------------------------
    # Rule: a close beyond the most recent opposite-fractal swing level.
    # BOS = break continues the current trend; CHOCH = break against it.
    struct_high: float | None = None
    struct_low: float | None = None
    trend_state = ms.trend
    for i in range(pivot_left + pivot_right, len(candles)):
        # Update confirmed structural levels from swings fully formed by i.
        for s in all_swings:
            if s.index + pivot_right == i:
                if s.kind == "high":
                    struct_high = s.price
                else:
                    struct_low = s.price
        c = closes[i]
        if struct_high is not None and c > struct_high:
            kind = "bos" if trend_state != "down" else "choch"
            event = StructureEvent(kind, "bullish", i, struct_high, c)
            ms.events.append(event)
            ms.last_event = event
            trend_state = "up"
            struct_high = None  # level consumed until the next swing forms
        elif struct_low is not None and c < struct_low:
            kind = "bos" if trend_state != "up" else "choch"
            event = StructureEvent(kind, "bearish", i, struct_low, c)
            ms.events.append(event)
            ms.last_event = event
            trend_state = "down"
            struct_low = None
    if ms.last_event is not None:
        ms.trend = trend_state

    # --- 3. Liquidity sweeps -------------------------------------------------
    # Rule: wick exceeds a prior swing level by > 0.05 ATR but the bar closes
    # back on the original side of that level.
    prior_highs = [(s.index, s.price) for s in swing_highs]
    prior_lows = [(s.index, s.price) for s in swing_lows]
    for i in range(pivot_left + pivot_right, len(candles)):
        for idx, price in prior_highs:
            if idx + pivot_right < i and highs[i] > price + 0.05 * atr and closes[i] < price:
                ms.sweeps.append(LiquiditySweep(i, "high", price, highs[i], closes[i]))
                break
        for idx, price in prior_lows:
            if idx + pivot_right < i and lows[i] < price - 0.05 * atr and closes[i] > price:
                ms.sweeps.append(LiquiditySweep(i, "low", price, lows[i], closes[i]))
                break

    # --- 4. Equal highs / lows ----------------------------------------------
    # Rule: >= 2 swing points within 0.15 ATR of each other.
    def _equal(points: list[tuple[int, float]], side: str) -> list[EqualLevels]:
        found: list[EqualLevels] = []
        used: set[int] = set()
        tol = 0.15 * atr
        for a in range(len(points)):
            ia, pa = points[a]
            if ia in used:
                continue
            group = [ia]
            for b in range(a + 1, len(points)):
                ib, pb = points[b]
                if ib not in used and abs(pb - pa) <= tol:
                    group.append(ib)
                    used.add(ib)
            if len(group) >= 2:
                used.add(ia)
                found.append(
                    EqualLevels(
                        side=side,
                        price=pa,
                        indices=group,
                        tolerance=tol,
                    )
                )
        return found

    ms.equal_highs = _equal([(s.index, s.price) for s in swing_highs], "highs")
    ms.equal_lows = _equal([(s.index, s.price) for s in swing_lows], "lows")

    # --- 5. Fair value gaps ---------------------------------------------------
    # Rule (3-candle): bullish FVG when low[i] > high[i-2] (gap between
    # candle i-2 high and candle i low); bearish mirrored. Mark filled when a
    # later bar trades through the gap.
    for i in range(2, len(candles)):
        gap_bottom, gap_top = highs[i - 2], lows[i]
        if lows[i] > highs[i - 2]:  # bullish imbalance
            filled = any(lows[j] <= gap_bottom for j in range(i + 1, len(candles)))
            ms.fvgs.append(FairValueGap(i, "bullish", gap_top, gap_bottom, filled))
        elif highs[i] < lows[i - 2]:  # bearish imbalance
            filled = any(highs[j] >= gap_top for j in range(i + 1, len(candles)))
            ms.fvgs.append(FairValueGap(i, "bearish", highs[i - 2], lows[i], filled))
    ms.fvgs = [f for f in ms.fvgs if not f.filled][-5:]  # keep unfilled, recent

    # --- 6. Order blocks --------------------------------------------------------
    # Rule: last opposing candle before a displacement move (> 1.0 ATR body
    # over the next candle) that breaks structure. Bullish OB = last down
    # candle before an up displacement; mirrored for bearish.
    for i in range(1, len(candles) - 1):
        body_next = abs(closes[i + 1] - candles[i + 1].open)
        if body_next <= atr:
            continue
        if closes[i + 1] > candles[i + 1].open and closes[i] < candles[i].open:
            # bullish displacement after a down candle
            ms.order_blocks.append(
                OrderBlock(
                    i,
                    "bullish",
                    top=max(candles[i].open, closes[i]),
                    bottom=lows[i],
                    displacement_atr=body_next / atr,
                )
            )
        elif closes[i + 1] < candles[i + 1].open and closes[i] > candles[i].open:
            ms.order_blocks.append(
                OrderBlock(
                    i,
                    "bearish",
                    top=highs[i],
                    bottom=min(candles[i].open, closes[i]),
                    displacement_atr=body_next / atr,
                )
            )
    ms.order_blocks = ms.order_blocks[-5:]

    # --- 7. Supply/demand zones from recent order blocks ---------------------
    for ob in ms.order_blocks[-4:]:
        ms.zones.append(
            Zone(
                kind="demand" if ob.direction == "bullish" else "supply",
                top=ob.top,
                bottom=ob.bottom,
                index=ob.index,
                strength=max(1, int(ob.displacement_atr)),
            )
        )

    # --- 8. Consolidation + breakouts ---------------------------------------
    # Rule: window of >= 5 bars whose total high-low range < 2.0 ATR is a
    # consolidation; a close outside its range is a breakout, and a close
    # back inside within 2 bars marks it false.
    window = 5
    i = 0
    while i + window <= len(candles):
        seg_high = max(highs[i : i + window])
        seg_low = min(lows[i : i + window])
        if (seg_high - seg_low) < 2.0 * atr:
            # extend while inside
            end = i + window
            while end < len(candles) and highs[end] <= seg_high and lows[end] >= seg_low:
                seg_high = max(seg_high, highs[end])
                seg_low = min(seg_low, lows[end])
                end += 1
            cons = Consolidation(i, end - 1, seg_high, seg_low)
            ms.consolidations.append(cons)
            # breakout check in the 5 bars after the consolidation ends
            for j in range(end, min(end + 5, len(candles))):
                if closes[j] > cons.top:
                    false_check = any(
                        closes[k] < cons.top for k in range(j + 1, min(j + 3, len(candles)))
                    )
                    ms.breakouts.append(Breakout(j, "bullish", cons.top, false_check))
                    break
                if closes[j] < cons.bottom:
                    false_check = any(
                        closes[k] > cons.bottom for k in range(j + 1, min(j + 3, len(candles)))
                    )
                    ms.breakouts.append(Breakout(j, "bearish", cons.bottom, false_check))
                    break
            i = end
        else:
            i += 1

    # --- 9. Rejection zones ----------------------------------------------------
    # Rule: wick >= 60% of the bar range beyond the body — clusters of
    # rejections. Keep the most recent ones.
    for i, c in enumerate(candles):
        rng = c.high - c.low
        if rng <= 0:
            continue
        upper_wick = c.high - max(c.open, c.close)
        lower_wick = min(c.open, c.close) - c.low
        if upper_wick >= 0.6 * rng:
            ms.zones.append(Zone("rejection", c.high, max(c.open, c.close), i))
        elif lower_wick >= 0.6 * rng:
            ms.zones.append(Zone("rejection", min(c.open, c.close), c.low, i))
    rejection = [z for z in ms.zones if z.kind == "rejection"]
    ms.zones = [z for z in ms.zones if z.kind != "rejection"] + rejection[-4:]

    return ms
