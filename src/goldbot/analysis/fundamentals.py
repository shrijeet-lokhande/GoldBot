"""Fundamental / macroeconomic analysis framework for XAUUSD.

Gold's price is sensitive to: US Dollar strength (DXY), US Treasury yields,
Federal Reserve policy (rate decisions, FOMC statements), inflation prints
(CPI, PCE), labour data (NFP, unemployment), geopolitical risk, and the
economic calendar.

GoldBot treats fundamental data strictly:

- Data comes only from a provider explicitly configured by the operator
  (an appropriately licensed source). No provider is bundled or scraped.
- Without a configured provider, every field reports ``available: false``
  and the analysis engine surfaces that as a data-quality limitation and an
  avoid-trading consideration around event risk — it never fabricates data
  or conflates forecasts with actuals.

The :class:`EconomicEvent` model distinguishes ``actual`` values from
``forecast`` values; events missing an actual value are labelled
``forecast_only`` and flagged as such to consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Event types most relevant to gold volatility (used for relevance ranking).
GOLD_HIGH_IMPACT_EVENTS = frozenset(
    {
        "fomc_rate_decision",
        "fomc_statement",
        "cpi",
        "core_cpi",
        "pce",
        "core_pce",
        "nonfarm_payrolls",
        "unemployment_rate",
        "dxy_print",
        "treasury_yield_10y",
        "fed_speech_chair",
        "geopolitical_event",
    }
)


@dataclass
class EconomicEvent:
    """A macroeconomic event with actual vs forecast separation."""

    event_id: str
    event_type: str  # keys of GOLD_HIGH_IMPACT_EVENTS or custom
    scheduled_at_utc: datetime
    country: str = "US"
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    description: str = ""

    @property
    def is_high_impact_for_gold(self) -> bool:
        return self.event_type in GOLD_HIGH_IMPACT_EVENTS

    @property
    def status(self) -> str:
        """``actual`` | ``forecast_only`` | ``scheduled``."""
        if self.actual is not None:
            return "actual"
        if self.forecast is not None:
            return "forecast_only"
        return "scheduled"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "scheduled_at_utc": self.scheduled_at_utc.isoformat(),
            "country": self.country,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "status": self.status,
            "high_impact_for_gold": self.is_high_impact_for_gold,
            "description": self.description,
        }


@dataclass
class MacroSnapshot:
    """Point-in-time macro context relevant to gold."""

    dxy: float | None = None
    dxy_change_pct_1d: float | None = None
    treasury_yield_10y: float | None = None
    treasury_yield_2y: float | None = None
    fed_rate: float | None = None
    events: list[EconomicEvent] = field(default_factory=list)
    source: str = "none"
    available: bool = False

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "source": self.source,
            "dxy": self.dxy,
            "dxy_change_pct_1d": self.dxy_change_pct_1d,
            "treasury_yield_10y": self.treasury_yield_10y,
            "treasury_yield_2y": self.treasury_yield_2y,
            "fed_rate": self.fed_rate,
            "upcoming_high_impact_events": [
                e.to_dict() for e in self.events if e.is_high_impact_for_gold
            ][:10],
        }


class MacroDataProvider:
    """Base class for licensed macro-data providers.

    Operators may implement this interface and register it with the analysis
    engine. GoldBot ships no bundled provider: ``UnavailableMacroProvider``
    is the default and reports the data as unavailable.
    """

    name: str = "base"

    def get_snapshot(self, now_utc: datetime | None = None) -> MacroSnapshot:
        raise NotImplementedError


class UnavailableMacroProvider(MacroDataProvider):
    """Default provider: no fundamental data configured/available."""

    name = "unavailable"

    def get_snapshot(self, now_utc: datetime | None = None) -> MacroSnapshot:
        return MacroSnapshot(available=False, source=self.name)


__all__ = [
    "GOLD_HIGH_IMPACT_EVENTS",
    "EconomicEvent",
    "MacroSnapshot",
    "MacroDataProvider",
    "UnavailableMacroProvider",
]
