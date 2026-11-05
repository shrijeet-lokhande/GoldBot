"""GoldBot trend-pullback strategy - the reference strategy for v1."""

from __future__ import annotations

from goldbot.core.models import Signal, SignalDirection
from goldbot.indicators import adx, atr, ema, rsi  # noqa: F401 (re-exported)


class BaseStrategy:
    """Base class for all GoldBot strategies.

    Subclasses must implement `generate_signal` and define class-level
    parameters. The strategy never places orders directly; it only returns
    structured signals that the risk engine evaluates.
    """

    #: Strategy version, increment when logic changes
    strategy_version: str = "1.0.0"

    #: Strategy name, for logging and identification
    name: str = "base"

    #: Whether the strategy uses candle-close-only logic
    candle_close_only: bool = True

    #: Indicators required (set by subclasses)
    required_indicators: list[str] = []

    def __init__(self, **kwargs):
        """Initialize strategy with configurable parameters."""
        self.params = self._default_params() | kwargs
        # Overrides must be visible as plain attributes too, so class-level
        # defaults (e.g. minimum_adx) honour explicit configuration.
        for key, value in self.params.items():
            setattr(self, key, value)
        self._last_signal_key: tuple | None = None  # last signal key
        self.signals_emitted: int = 0  # total signals emitted (telemetry)

    def _default_params(self) -> dict:
        """Return default parameter values for this strategy."""
        return {}

    def generate_signal(
        self,
        market_data,
        indicator_results: dict[str, dict],
    ) -> Signal | None:
        """Generate a trade signal based on current market data.

        Args:
            market_data: The current market data/context.
            indicator_results: Dictionary of indicator values keyed by
                indicator name, each containing at least a 'value' key.

        Returns:
            A Signal object if a trade setup is confirmed, None otherwise.
            Must not return an order - only a signal.
        """
        raise NotImplementedError("Subclasses must implement generate_signal")

    # ------------------------------------------------------------------
    # Duplicate detection (candle-keyed)
    # ------------------------------------------------------------------

    def _seen_before(self, candle) -> bool:
        """True when a signal for this exact candle was already emitted."""
        key = self._candle_key(candle)
        return self._last_signal_key == key

    def _mark_signal_candle(self, candle) -> None:
        """Remember that a signal was (about to be) emitted for this candle."""
        self._last_signal_key = self._candle_key(candle)

    @staticmethod
    def _candle_key(candle) -> tuple:
        return (
            getattr(candle, "symbol", ""),
            getattr(candle, "timeframe", ""),
            getattr(candle, "timestamp_utc", None),
        )


class TrendPullbackStrategy(BaseStrategy):
    """Multi-timeframe trend-pullback strategy for gold.

    Long setup (all must hold on the last *completed* entry candle):
        1. Trend-timeframe EMA 50 > EMA 200 (uptrend)
        2. 15m price pulled back towards EMA 20 (low touched/below EMA fast)
        3. RSI above threshold (recovered from weakness)
        4. ADX above the minimum trend-strength filter
        5. Completed bullish candle confirms

    Short setup:
        1. Trend-timeframe EMA 50 < EMA 200 (downtrend)
        2. 15m price retraced towards EMA 20 (high touched/above EMA fast)
        3. RSI below (100 - threshold)
        4. ADX above the minimum filter
        5. Completed bearish candle confirms

    The strategy never places orders; it returns structured signals that
    the risk engine evaluates.
    """

    name: str = "trend_pullback"
    strategy_version: str = "1.0.0"
    candle_close_only: bool = True
    required_indicators = ["ema_fast", "ema_trend", "ema_long", "rsi", "atr", "adx"]

    # EMA parameters
    ema_fast: int = 20
    ema_trend: int = 50
    ema_long: int = 200

    # RSI parameters
    rsi_period: int = 14
    rsi_threshold: float = 40.0  # For long: RSI must be above this

    # ATR parameters
    atr_period: int = 14

    # ADX parameters
    adx_period: int = 14
    minimum_adx: float = 20.0

    #: Stop-loss distance as a multiple of ATR
    atr_stop_multiple: float = 1.5

    #: Risk/reward: take profit = stop distance * this
    take_profit_multiple: float = 2.0

    #: For short: RSI must be below this
    rsi_fall_threshold: float = 60.0

    def _default_params(self) -> dict:
        return {
            "ema_fast": self.ema_fast,
            "ema_trend": self.ema_trend,
            "ema_long": self.ema_long,
            "rsi_period": self.rsi_period,
            "rsi_threshold": self.rsi_threshold,
            "atr_period": self.atr_period,
            "adx_period": self.adx_period,
            "minimum_adx": self.minimum_adx,
            "atr_stop_multiple": self.atr_stop_multiple,
            "take_profit_multiple": self.take_profit_multiple,
        }

    def generate_signal(
        self,
        market_data,
        indicator_results: dict[str, dict],
    ) -> Signal | None:
        """Generate a signal using the multi-timeframe trend-pullback logic.

        Args:
            market_data: Context with ``symbol``, ``entry_timeframe``,
                ``trend_timeframe`` and ``candles: dict[tf, list[Candle]]``.
            indicator_results: dict of name -> {"value": float|None}.

        Returns:
            A Signal when the setup is confirmed, otherwise None.
        """
        symbol = getattr(market_data, "symbol", None)
        entry_tf = getattr(market_data, "entry_timeframe", "15m")

        if not symbol:
            return None

        candles_entry = (getattr(market_data, "candles", {}) or {}).get(entry_tf, [])
        if len(candles_entry) < 2:
            return None

        recent_candle = candles_entry[-1]
        prior_candle = candles_entry[-2]

        # Candle-close-only discipline
        if self.candle_close_only and not getattr(recent_candle, "is_complete", True):
            return None

        # Duplicate suppression: one signal per (symbol, timeframe, candle)
        if self._seen_before(recent_candle):
            return None

        def value(name: str) -> float | None:
            entry = indicator_results.get(name)
            if isinstance(entry, dict):
                return entry.get("value")
            return None

        ema_fast_val = value("ema_fast")
        ema_trend_val = value("ema_trend")
        ema_long_val = value("ema_long")
        rsi_value = value("rsi")
        atr_value = value("atr")
        adx_value = value("adx")

        if (ema_fast_val is None or ema_trend_val is None or ema_long_val is None
                or rsi_value is None or atr_value is None or adx_value is None):
            return None  # indicators not warmed up

        uptrend = ema_trend_val > ema_long_val
        downtrend = ema_trend_val < ema_long_val
        adx_ok = adx_value > self.minimum_adx
        is_bullish = recent_candle.close > recent_candle.open
        is_bearish = recent_candle.close < recent_candle.open

        # Pullback: the prior candle's extreme touched the fast EMA
        pullback_long = prior_candle.low <= ema_fast_val
        pullback_short = prior_candle.high >= ema_fast_val

        # --- Long setup ---
        if (uptrend and rsi_value > self.rsi_threshold and adx_ok
                and is_bullish and pullback_long):
            stop_distance = max(atr_value * self.atr_stop_multiple, 1e-6)
            reason_codes = [
                "ema_trend_above_ema_long",
                f"rsi_above_{self.rsi_threshold}",
                "adx_above_minimum",
                "bullish_candle_confirmed",
                "pullback_to_ema_fast",
            ]
            indicator_snapshot = {
                "ema_fast": ema_fast_val,
                "ema_trend": ema_trend_val,
                "ema_long": ema_long_val,
                "rsi": rsi_value,
                "atr": atr_value,
                "adx": adx_value,
            }
            signal = Signal(
                symbol=symbol,
                direction=SignalDirection.LONG,
                created_at_utc=recent_candle.timestamp_utc,
                reference_price=recent_candle.close,
                stop_distance=stop_distance,
                take_profit_multiple=self.take_profit_multiple,
                timeframe=entry_tf,
                strategy_version=self.strategy_version,
                reason_codes=reason_codes,
                indicator_snapshot=indicator_snapshot,
            )
            self._mark_signal_candle(recent_candle)
            self.signals_emitted += 1
            return signal

        # --- Short setup ---
        if (downtrend and rsi_value < self.rsi_fall_threshold and adx_ok
                and is_bearish and pullback_short):
            stop_distance = max(atr_value * self.atr_stop_multiple, 1e-6)
            reason_codes = [
                "ema_trend_below_ema_long",
                f"rsi_below_{self.rsi_fall_threshold}",
                "adx_above_minimum",
                "bearish_candle_confirmed",
                "pullback_to_ema_fast",
            ]
            indicator_snapshot = {
                "ema_fast": ema_fast_val,
                "ema_trend": ema_trend_val,
                "ema_long": ema_long_val,
                "rsi": rsi_value,
                "atr": atr_value,
                "adx": adx_value,
            }
            signal = Signal(
                symbol=symbol,
                direction=SignalDirection.SHORT,
                created_at_utc=recent_candle.timestamp_utc,
                reference_price=recent_candle.close,
                stop_distance=stop_distance,
                take_profit_multiple=self.take_profit_multiple,
                timeframe=entry_tf,
                strategy_version=self.strategy_version,
                reason_codes=reason_codes,
                indicator_snapshot=indicator_snapshot,
            )
            self._mark_signal_candle(recent_candle)
            self.signals_emitted += 1
            return signal

        # No setup on this candle
        return None
