"""Structured analysis report model.

Every GoldBot analysis produces this shape (section 4-E of the platform
spec): regime, bias, trends, levels, scenarios, trade plan, confidence with
explanation, and explicit reasons to avoid trading. Missing data is reported
as such — the engine never manufactures analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ConfidenceLevel:
    """Heuristic confidence score with its justification.

    This is NOT a statistically calibrated probability; it is a transparent
    0-100 self-assessment produced by the rule engine. ``explanation`` lists
    the factors that raised/lowered it.
    """

    score: int  # 0..100
    explanation: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.score = max(0, min(100, int(self.score)))

    def to_dict(self) -> dict:
        return {"score": self.score, "explanation": self.explanation}


@dataclass
class TradePlan:
    """Potential trade plan derived from the analysis (informational)."""

    direction: str | None = None  # "long" | "short" | None
    entry_zones: list[float] = field(default_factory=list)
    invalidation_level: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    risk_reward_ratio: float | None = None

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "entry_zones": [round(e, 4) for e in self.entry_zones],
            "invalidation_level": self.invalidation_level,
            "stop_loss": self.stop_loss,
            "take_profits": [round(t, 4) for t in self.take_profits],
            "risk_reward_ratio": (
                round(self.risk_reward_ratio, 2) if self.risk_reward_ratio else None
            ),
        }


@dataclass
class AnalysisReport:
    """Full analysis output for one symbol at one point in time."""

    symbol: str
    generated_at_utc: str
    market_regime: str  # trending_up | trending_down | ranging | volatile | unclear
    directional_bias: str  # bullish | bearish | neutral
    htf_trend: str  # higher-timeframe trend
    ltf_setup: str  # lower-timeframe setup description
    support_levels: list[float]
    resistance_levels: list[float]
    liquidity_levels: list[float]  # equal highs/lows, sweep levels
    volatility: dict  # atr, bandwidth, regime label
    bullish_scenarios: list[str]
    bearish_scenarios: list[str]
    trade_plan: TradePlan
    confidence: ConfidenceLevel
    avoid_trading_reasons: list[str]
    data_quality: dict  # per-timeframe bar counts / availability
    indicators: dict  # numeric indicator snapshot
    structure: dict  # structure engine output (dict form)
    fundamentals: dict  # macro/event availability + events
    timeframes: dict  # per-timeframe trend/confluence votes

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "generated_at_utc": self.generated_at_utc,
            "market_regime": self.market_regime,
            "directional_bias": self.directional_bias,
            "htf_trend": self.htf_trend,
            "ltf_setup": self.ltf_setup,
            "support_levels": [round(s, 4) for s in self.support_levels],
            "resistance_levels": [round(r, 4) for r in self.resistance_levels],
            "liquidity_levels": [round(x, 4) for x in self.liquidity_levels],
            "volatility": self.volatility,
            "bullish_scenarios": self.bullish_scenarios,
            "bearish_scenarios": self.bearish_scenarios,
            "trade_plan": self.trade_plan.to_dict(),
            "confidence": self.confidence.to_dict(),
            "avoid_trading_reasons": self.avoid_trading_reasons,
            "data_quality": self.data_quality,
            "indicators": self._safe(self.indicators),
            "structure": self.structure,
            "fundamentals": self.fundamentals,
            "timeframes": self.timeframes,
        }

    @staticmethod
    def _safe(indicators: dict) -> dict:
        """Round floats for stable, reproducible JSON output (numpy-safe)."""
        out: dict = {}
        for key, value in indicators.items():
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                out[key] = round(float(value), 5)
            else:
                out[key] = value
        return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
