"""Instrument identity for GoldBot.

GoldBot uses one canonical internal symbol for its primary instrument and
maps provider-specific symbols separately. The internal symbol is the plain
string ``XAUUSD``; provider symbols (TradingView, OANDA REST, ...) are never
used inside the engine, database, or signals — only at provider boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass

CANONICAL_SYMBOL = "XAUUSD"

# TradingView chart reference (charting layer only — never a data source).
TRADINGVIEW_SYMBOL = "OANDA:XAUUSD"
TRADINGVIEW_CHART_URL = "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD"


@dataclass(frozen=True)
class InstrumentIdentity:
    """Canonical instrument with provider-specific symbol mappings."""

    symbol: str = CANONICAL_SYMBOL
    name: str = "Gold / US Dollar"
    asset_type: str = "spot"
    quote_currency: str = "USD"
    tradingview: str = TRADINGVIEW_SYMBOL
    oanda: str = "XAU_USD"
    contract_size: float = 100.0  # 1 lot = 100 oz (standard XAUUSD assumption)
    tick_size: float = 0.1

    def symbol_for(self, provider: str) -> str:
        """Provider-specific symbol (provider names are lower-case)."""
        mapping = {
            "internal": self.symbol,
            "tradingview": self.tradingview,
            "oanda": self.oanda,
            "csv": self.symbol,
        }
        try:
            return mapping[provider.lower()]
        except KeyError:
            raise ValueError(f"unknown provider {provider!r}; known: {sorted(mapping)}") from None


PRIMARY_INSTRUMENT = InstrumentIdentity()


def normalize_symbol(raw: str | None) -> str:
    """Normalise a provider symbol to the canonical internal symbol.

    Accepts common variants ("XAUUSD", "XAU_USD", "OANDA:XAUUSD",
    "GOLD", "xau-usd") and returns the canonical ``XAUUSD``. Unknown symbols
    are upper-cased and returned with separators stripped so the engine never
    receives provider-prefixed identifiers.
    """
    if not raw:
        return CANONICAL_SYMBOL
    cleaned = raw.strip().upper()
    if ":" in cleaned:  # strip a "OANDA:" style provider prefix
        cleaned = cleaned.split(":", 1)[1]
    compact = cleaned.replace("_", "").replace("-", "").replace("/", "")
    aliases = {
        "XAUUSD": CANONICAL_SYMBOL,
        "XAUSD": CANONICAL_SYMBOL,
        "GOLD": CANONICAL_SYMBOL,
        "XAU": CANONICAL_SYMBOL,
    }
    return aliases.get(compact, compact)


def is_primary_instrument(raw: str | None) -> bool:
    return normalize_symbol(raw) == CANONICAL_SYMBOL


__all__ = [
    "CANONICAL_SYMBOL",
    "TRADINGVIEW_SYMBOL",
    "TRADINGVIEW_CHART_URL",
    "InstrumentIdentity",
    "PRIMARY_INSTRUMENT",
    "normalize_symbol",
    "is_primary_instrument",
]
