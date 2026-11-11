"""XAUUSD analysis engine.

Combines technical indicators, market structure, multi-timeframe confluence
and (when configured) fundamental data into a single structured
:class:`AnalysisReport`. Deterministic: the same revealed candles produce the
same report byte-for-byte apart from the generation timestamp.

Timeframe model (section 4-C of the spec):
- The base dataset timeframe and every resamplable higher timeframe are
  analysed. Timeframes finer than the native data are reported as
  unavailable in ``data_quality`` — never approximated.
- Higher timeframes vote on direction; the lowest available timeframe
  provides the setup description.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from goldbot.analysis import timeframes as tf
from goldbot.analysis.fundamentals import MacroDataProvider, UnavailableMacroProvider
from goldbot.analysis.report import AnalysisReport, ConfidenceLevel, TradePlan, now_iso
from goldbot.analysis.session_levels import reference_levels
from goldbot.analysis.structure import MarketStructure, analyze_structure
from goldbot.core.instruments import PRIMARY_INSTRUMENT
from goldbot.core.models import Candle
from goldbot.indicators import (
    adx,
    atr,
    bollinger_bands,
    detect_levels,
    ema,
    macd,
    rsi,
    sma,
    stochastic_rsi,
    vwap,
)

logger = logging.getLogger("goldbot.analysis")

REGIME_TREND_UP = "trending_up"
REGIME_TREND_DOWN = "trending_down"
REGIME_RANGING = "ranging"
REGIME_VOLATILE = "volatile"
REGIME_UNCLEAR = "unclear"

_BIAS_WEIGHTS = {
    "1w": 4,
    "1d": 4,
    "4h": 3,
    "1h": 2,
    "30m": 1,
    "15m": 1,
    "5m": 1,
    "1m": 1,
}


class AnalysisEngine:
    """Produces structured XAUUSD analysis reports from revealed candles."""

    def __init__(
        self,
        base_timeframe: str = "15m",
        analysis_timeframes: tuple[str, ...] | None = None,
        macro_provider: MacroDataProvider | None = None,
        atr_period: int = 14,
    ):
        self.base_timeframe = base_timeframe
        self.analysis_timeframes = analysis_timeframes or (
            "1m",
            "5m",
            "15m",
            "30m",
            "1h",
            "4h",
            "1d",
            "1w",
        )
        self.macro_provider = macro_provider or UnavailableMacroProvider()
        self.atr_period = atr_period

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        candles: list[Candle],
        symbol: str | None = None,
    ) -> AnalysisReport:
        """Generate the structured analysis report.

        ``candles`` must be completed base-timeframe bars in chronological
        order. The same input always yields the same output (except the
        timestamp), so reports are reproducible.
        """
        if len(candles) < 30:
            raise ValueError(
                f"insufficient data for analysis: {len(candles)} bars "
                "(>= 30 required); not manufacturing an analysis"
            )
        symbol = symbol or candles[0].symbol or PRIMARY_INSTRUMENT.symbol

        # --- per-timeframe series -----------------------------------------
        series: dict[str, list[Candle]] = {}
        data_quality: dict[str, object] = {}
        for name in self.analysis_timeframes:
            try:
                res = tf.resample_candles(candles, name)
            except ValueError as exc:
                data_quality[name] = {"available": False, "reason": str(exc)}
                continue
            series[name] = res
            data_quality[name] = {"available": True, "bars": len(res)}
        if self.base_timeframe not in series:
            raise ValueError(f"base timeframe {self.base_timeframe} not analysable from input")

        # --- indicator snapshot on the base timeframe ----------------------
        ind = self._indicator_snapshot(series[self.base_timeframe])
        atr_value = ind.get("atr")

        # --- structure on base + trend timeframes --------------------------
        base_structure = analyze_structure(series[self.base_timeframe], atr_value)
        htf_name = self._highest_available(series, ("1d", "4h", "1h"))
        htf_structure = analyze_structure(series[htf_name], atr_value)
        self._lowest_available(series)  # included in timeframe votes below

        # --- multi-timeframe confluence ------------------------------------
        timeframe_votes = self._timeframe_votes(series, ind)
        bias, bias_score = self._bias_from_votes(timeframe_votes)

        # --- levels ----------------------------------------------------------
        level_set = detect_levels(
            pd.Series([c.high for c in series[self.base_timeframe]]),
            pd.Series([c.low for c in series[self.base_timeframe]]),
            atr_value=atr_value,
            min_touches=2,
        )
        supports = [round(float(sup.price), 4) for sup in level_set.supports][:4]
        resistances = [round(float(res.price), 4) for res in level_set.resistances][:4]
        liquidity: list[float] = []
        for eq in base_structure.equal_highs[-2:]:
            liquidity.append(round(eq.price, 4))
        for eq in base_structure.equal_lows[-2:]:
            liquidity.append(round(eq.price, 4))

        # --- regime ----------------------------------------------------------
        regime = self._regime(ind, base_structure, htf_structure)

        # --- volatility --------------------------------------------------------
        volatility = {
            "atr": round(atr_value, 4) if atr_value else None,
            "atr_regime": self._atr_regime(atr_value, series[self.base_timeframe]),
        }
        if ind.get("bb_bandwidth") is not None:
            volatility["bb_bandwidth"] = ind["bb_bandwidth"]

        # --- fundamentals ------------------------------------------------------
        fundamentals = self.macro_provider.get_snapshot(datetime.now(timezone.utc)).to_dict()

        # --- scenarios, plan, confidence, avoid-reasons -----------------------
        last = candles[-1].close
        bullish, bearish = self._scenarios(ind, base_structure, htf_structure, bias)
        plan = self._trade_plan(bias, last, supports, resistances, atr_value, base_structure)
        confidence, explanation = self._confidence(
            ind, timeframe_votes, base_structure, htf_structure, fundamentals
        )
        avoid = self._avoid_reasons(ind, timeframe_votes, base_structure, fundamentals, series)

        ltf_setup = self._setup_description(base_structure, ind)

        return AnalysisReport(
            symbol=symbol,
            generated_at_utc=now_iso(),
            market_regime=regime,
            directional_bias=bias,
            htf_trend=f"{htf_name}:{htf_structure.trend}",
            ltf_setup=ltf_setup,
            support_levels=supports,
            resistance_levels=resistances,
            liquidity_levels=liquidity,
            volatility=volatility,
            bullish_scenarios=bullish,
            bearish_scenarios=bearish,
            trade_plan=plan,
            confidence=ConfidenceLevel(confidence, explanation),
            avoid_trading_reasons=avoid,
            data_quality=data_quality,
            indicators=ind,
            structure=base_structure.to_dict(),
            fundamentals=fundamentals,
            timeframes=timeframe_votes,
            reference_levels=reference_levels(series[self.base_timeframe]),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _indicator_snapshot(self, candles: list[Candle]) -> dict:
        close = pd.Series([c.close for c in candles], dtype=float)
        high = pd.Series([c.high for c in candles], dtype=float)
        low = pd.Series([c.low for c in candles], dtype=float)
        volume = pd.Series([c.volume for c in candles], dtype=float)

        out: dict = {}
        out["ema_fast"] = self._f(ema(close, 20))
        out["ema_trend"] = self._f(ema(close, 50))
        out["ema_long"] = self._f(ema(close, 200))
        out["sma_20"] = self._f(sma(close, 20))
        out["rsi"] = self._f(rsi(close, 14))
        atr_series = atr(high, low, close, self.atr_period)
        out["atr"] = self._f(atr_series)
        out["adx"] = self._f(adx(high, low, close, 14))
        m = macd(close)
        out["macd"] = m.last_macd
        out["macd_signal"] = m.last_signal
        out["macd_histogram"] = m.last_histogram
        out["macd_crossover"] = m.crossover
        k, d = stochastic_rsi(close)
        out["stoch_rsi_k"] = self._f(k)
        out["stoch_rsi_d"] = self._f(d)
        bb = bollinger_bands(close, 20, 2.0)
        out["bb_upper"] = self._f(bb.upper)
        out["bb_lower"] = self._f(bb.lower)
        out["bb_bandwidth"] = bb.bandwidth
        vw = vwap(high, low, close, volume)
        out["vwap"] = self._f(vw) if vw is not None else None
        out["vwap_available"] = vw is not None
        out["close"] = self._f(close)
        return out

    @staticmethod
    def _f(series: pd.Series) -> float | None:
        if series is None or len(series) == 0:
            return None
        val = series.iloc[-1]
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            return None
        return float(val)

    @staticmethod
    def _highest_available(series: dict, names: tuple[str, ...]) -> str:
        for name in names:
            if name in series and len(series[name]) >= 5:
                return name
        # fall back to anything available
        return next(iter(series))

    @staticmethod
    def _lowest_available(series: dict) -> str:
        ordered = sorted(series.keys(), key=lambda n: tf.timeframe_minutes(n))
        return ordered[0] if ordered else "15m"

    def _timeframe_votes(self, series: dict, ind: dict) -> dict:
        """Per-timeframe trend vote: +1 bullish, -1 bearish, 0 neutral."""
        votes: dict[str, dict] = {}
        for name, candles in series.items():
            if len(candles) < 25:
                votes[name] = {"trend": "unknown", "vote": 0, "bars": len(candles)}
                continue
            close = pd.Series([c.close for c in candles], dtype=float)
            e_fast = self._f(ema(close, 20))
            e_slow = self._f(ema(close, 50))
            structure = analyze_structure(candles, ind.get("atr"))
            vote = 0
            if e_fast is not None and e_slow is not None:
                vote += 1 if e_fast > e_slow else -1
            if structure.trend == "up":
                vote += 1
            elif structure.trend == "down":
                vote -= 1
            label = "bullish" if vote > 0 else ("bearish" if vote < 0 else "neutral")
            votes[name] = {
                "trend": structure.trend,
                "vote": vote,
                "label": label,
                "bars": len(candles),
            }
        return votes

    @staticmethod
    def _bias_from_votes(votes: dict) -> tuple[str, float]:
        score = 0.0
        for name, vote in votes.items():
            weight = _BIAS_WEIGHTS.get(name, 1)
            score += vote.get("vote", 0) * weight
        if score > 1.0:
            return "bullish", score
        if score < -1.0:
            return "bearish", score
        return "neutral", score

    def _regime(self, ind: dict, base: MarketStructure, htf: MarketStructure) -> str:
        adx_val = ind.get("adx")
        bw = ind.get("bb_bandwidth")
        if adx_val is not None and adx_val >= 25:
            return (
                REGIME_TREND_UP
                if base.trend == "up"
                else (REGIME_TREND_DOWN if base.trend == "down" else REGIME_UNCLEAR)
            )
        if bw is not None and bw > 6.0 and (adx_val is None or adx_val < 20):
            # Bands wide but no directional strength: elevated volatility chop
            return REGIME_VOLATILE
        if base.trend == "up" and htf.trend != "down":
            return REGIME_TREND_UP
        if base.trend == "down" and htf.trend != "up":
            return REGIME_TREND_DOWN
        return REGIME_RANGING

    @staticmethod
    def _atr_regime(atr_value: float | None, candles: list[Candle]) -> str:
        if atr_value is None or not candles:
            return "unknown"
        closes = [c.close for c in candles]
        mean_price = sum(closes) / len(closes)
        atr_pct = atr_value / mean_price * 100.0
        if atr_pct < 0.15:
            return "low"
        if atr_pct < 0.45:
            return "normal"
        return "high"

    def _scenarios(
        self,
        ind: dict,
        base: MarketStructure,
        htf: MarketStructure,
        bias: str,
    ) -> tuple[list[str], list[str]]:
        close = ind.get("close")
        bb_upper, bb_lower = ind.get("bb_upper"), ind.get("bb_lower")
        rsi_val = ind.get("rsi")
        bullish: list[str] = []
        bearish: list[str] = []

        if base.trend == "up" or htf.trend == "up":
            bullish.append(
                "Higher-timeframe structure is up: pullbacks into the most "
                "recent demand/order-block zone that hold offer continuation."
            )
        if base.trend == "down" or htf.trend == "down":
            bearish.append(
                "Higher-timeframe structure is down: rallies into the most "
                "recent supply/order-block zone that reject offer continuation lower."
            )
        if ind.get("macd_crossover") == "bullish":
            bullish.append("MACD histogram flipped positive (bullish momentum crossover).")
        elif ind.get("macd_crossover") == "bearish":
            bearish.append("MACD histogram flipped negative (bearish momentum crossover).")
        if rsi_val is not None and close is not None:
            if rsi_val < 30:
                bullish.append(f"RSI {rsi_val:.1f} is oversold; watch for reversal confirmation.")
            elif rsi_val > 70:
                bearish.append(f"RSI {rsi_val:.1f} is overbought; watch for exhaustion.")
        if close is not None and bb_upper is not None and bb_lower is not None:
            if close >= bb_upper:
                bearish.append("Price closed at/above the upper Bollinger band: stretched.")
            elif close <= bb_lower:
                bullish.append("Price closed at/below the lower Bollinger band: stretched.")
        unfilled_fvgs = [f for f in base.fvgs if not f.filled]
        if unfilled_fvgs:
            f = unfilled_fvgs[-1]
            side = "bullish" if f.direction == "bullish" else "bearish"
            gap_desc = (
                f"Unfilled {f.direction} fair value gap "
                f"{f.bottom:.2f}-{f.top:.2f} may attract price."
            )
            (bullish if side == "bullish" else bearish).append(gap_desc)
        if not bullish:
            bullish.append("No clearly measurable bullish condition detected.")
        if not bearish:
            bearish.append("No clearly measurable bearish condition detected.")
        return bullish, bearish

    def _trade_plan(
        self,
        bias: str,
        close: float,
        supports: list[float],
        resistances: list[float],
        atr_value: float | None,
        structure: MarketStructure,
    ) -> TradePlan:
        plan = TradePlan()
        if bias == "neutral" or close is None:
            return plan
        demand_zones = [z for z in structure.zones if z.kind == "demand"]
        supply_zones = [z for z in structure.zones if z.kind == "supply"]
        if bias == "bullish":
            plan.direction = "long"
            zones = sorted([z.top for z in demand_zones if z.top < close], reverse=True)
            plan.entry_zones = zones[:2] or (
                supports[:1] if supports else [close - (atr_value or 5.0)]
            )
            stop = min(plan.entry_zones) - (atr_value or 5.0)
            plan.stop_loss = round(stop, 4)
            plan.invalidation_level = plan.stop_loss
            res_above = [r for r in resistances if r > close]
            tp1 = res_above[0] if res_above else close + (atr_value or 5.0) * 2
            tp2 = tp1 + (tp1 - plan.stop_loss) if plan.stop_loss < tp1 else tp1
            plan.take_profits = [round(tp1, 4), round(tp2, 4)]
        else:
            plan.direction = "short"
            zones = sorted([z.bottom for z in supply_zones if z.bottom > close])
            plan.entry_zones = zones[:2] or (
                resistances[:1] if resistances else [close + (atr_value or 5.0)]
            )
            stop = max(plan.entry_zones) + (atr_value or 5.0)
            plan.stop_loss = round(stop, 4)
            plan.invalidation_level = plan.stop_loss
            sup_below = [s for s in supports if s < close]
            tp1 = sup_below[0] if sup_below else close - (atr_value or 5.0) * 2
            tp2 = tp1 - (plan.stop_loss - tp1) if plan.stop_loss > tp1 else tp1
            plan.take_profits = [round(tp1, 4), round(tp2, 4)]
        risk = abs(plan.entry_zones[0] - plan.stop_loss) if plan.entry_zones else None
        if risk and plan.take_profits:
            reward = abs(plan.take_profits[0] - plan.entry_zones[0])
            plan.risk_reward_ratio = reward / risk if risk > 0 else None
        return plan

    def _confidence(
        self,
        ind: dict,
        votes: dict,
        base: MarketStructure,
        htf: MarketStructure,
        fundamentals: dict,
    ) -> tuple[int, list[str]]:
        score = 50
        explanation: list[str] = []
        aligned = sum(1 for v in votes.values() if v.get("vote", 0) > 0)
        bearish_aligned = sum(1 for v in votes.values() if v.get("vote", 0) < 0)
        total = max(1, len(votes))
        if aligned >= total - 1:
            score += 20
            explanation.append(f"{aligned}/{total} analysed timeframes vote bullish.")
        elif bearish_aligned >= total - 1:
            score += 20
            explanation.append(f"{bearish_aligned}/{total} analysed timeframes vote bearish.")
        elif aligned == bearish_aligned:
            score -= 15
            explanation.append("Timeframes disagree evenly: confluence is low.")
        adx_val = ind.get("adx")
        if adx_val is not None:
            if adx_val >= 25:
                score += 10
                explanation.append(f"ADX {adx_val:.1f} indicates a trending market.")
            elif adx_val < 20:
                score -= 10
                explanation.append(f"ADX {adx_val:.1f} indicates a weak/ranging market.")
        if base.last_event is not None:
            score += 5
            explanation.append(
                f"Recent structure event: {base.last_event.direction} "
                f"{base.last_event.kind.upper()}."
            )
        if not fundamentals.get("available", False):
            score -= 5
            explanation.append("Fundamental/macro data unavailable: analysis is technical-only.")
        if ind.get("vwap_available") is False:
            explanation.append("VWAP unavailable (volume data not reliable).")
        return max(5, min(90, score)), explanation

    def _avoid_reasons(
        self,
        ind: dict,
        votes: dict,
        structure: MarketStructure,
        fundamentals: dict,
        series: dict,
    ) -> list[str]:
        reasons: list[str] = []
        if ind.get("adx") is not None and ind["adx"] < 20:
            reasons.append(
                f"ADX {ind['adx']:.1f} below 20: range conditions punish breakout entries."
            )
        votes_present = [v.get("vote", 0) for v in votes.values()]
        if votes_present and max(votes_present) > 0 > min(votes_present):
            reasons.append("Timeframes conflict: higher and lower timeframe trends disagree.")
        if ind.get("atr") is not None and ind.get("close"):
            atr_pct = ind["atr"] / ind["close"] * 100.0
            if atr_pct > 0.6:
                reasons.append(
                    f"Volatility elevated (ATR {atr_pct:.2f}% of price): widen stops "
                    "or stand aside."
                )
        if not fundamentals.get("available", False):
            reasons.append(
                "No fundamental data: high-impact scheduled events (FOMC, CPI, NFP) "
                "cannot be seen by this analysis."
            )
        recent_false = [b for b in structure.breakouts[-3:] if b.is_false]
        if recent_false:
            reasons.append("Recent false breakout detected: range edges are unreliable.")
        lowest = self._lowest_available(series)
        if tf.timeframe_minutes(lowest) > tf.timeframe_minutes("15m"):
            reasons.append("Sub-15m data unavailable: entry timing cannot be refined.")
        if not reasons:
            reasons.append("No blocking conditions detected by rule checks.")
        return reasons

    @staticmethod
    def _setup_description(structure: MarketStructure, ind: dict) -> str:
        parts: list[str] = []
        if structure.last_event is not None:
            e = structure.last_event
            parts.append(
                f"last structure event: {e.direction} {e.kind.upper()} at {e.broken_level:.2f}"
            )
        if structure.fvgs:
            f = structure.fvgs[-1]
            parts.append(f"unfilled {f.direction} FVG {f.bottom:.2f}-{f.top:.2f}")
        if structure.order_blocks:
            ob = structure.order_blocks[-1]
            parts.append(f"nearest {ob.direction} order block {ob.bottom:.2f}-{ob.top:.2f}")
        if not parts:
            parts.append("no measurable setup: structure is quiet")
        return "; ".join(parts)


__all__ = ["AnalysisEngine", "AnalysisReport"]
