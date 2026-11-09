"""Instrument identity and symbol-normalisation tests."""

from goldbot.core.instruments import (
    CANONICAL_SYMBOL,
    PRIMARY_INSTRUMENT,
    TRADINGVIEW_SYMBOL,
    is_primary_instrument,
    normalize_symbol,
)


def test_canonical_symbol_is_xauusd():
    assert CANONICAL_SYMBOL == "XAUUSD"
    assert PRIMARY_INSTRUMENT.symbol == "XAUUSD"


def test_tradingview_symbol_mapping():
    assert TRADINGVIEW_SYMBOL == "OANDA:XAUUSD"
    assert PRIMARY_INSTRUMENT.symbol_for("tradingview") == "OANDA:XAUUSD"


def test_oanda_symbol_mapping():
    assert PRIMARY_INSTRUMENT.symbol_for("oanda") == "XAU_USD"


def test_unknown_provider_raises():
    import pytest

    with pytest.raises(ValueError):
        PRIMARY_INSTRUMENT.symbol_for("bitmex")


def test_normalize_symbol_variants():
    assert normalize_symbol("XAUUSD") == "XAUUSD"
    assert normalize_symbol("XAU_USD") == "XAUUSD"
    assert normalize_symbol("OANDA:XAUUSD") == "XAUUSD"
    assert normalize_symbol("xau-usd") == "XAUUSD"
    assert normalize_symbol("GOLD") == "XAUUSD"
    assert normalize_symbol(None) == "XAUUSD"


def test_is_primary_instrument():
    assert is_primary_instrument("XAU_USD")
    assert is_primary_instrument("OANDA:XAUUSD")
    assert not is_primary_instrument("EURUSD")
