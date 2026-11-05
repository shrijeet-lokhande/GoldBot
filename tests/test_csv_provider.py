"""CSV market data provider tests."""

from datetime import datetime, timezone

import pytest

from goldbot.core.exceptions import DataError
from goldbot.core.models import Candle
from goldbot.market_data.csv_provider import CsvMarketDataProvider

UTC = timezone.utc
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


@pytest.fixture()
def fixture_csv() -> str:
    return ROOT / "data" / "fixtures" / "sample_xauusd_15m.csv"


@pytest.fixture()
def provider(fixture_csv) -> CsvMarketDataProvider:
    return CsvMarketDataProvider(fixture_csv)


def test_loads_fixture_bars(provider):
    candles = provider.get_historical_bars(
        "XAUUSD", "15m",
        datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC),
    )
    assert len(candles) > 1000
    assert candles[0].open == pytest.approx(1950.00)
    assert candles[0].close == pytest.approx(1951.75)
    assert candles[0].timestamp_utc.tzinfo is not None


def test_bars_sorted_ascending(provider):
    candles = provider.get_historical_bars(
        "XAUUSD", "15m",
        datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC),
    )
    stamps = [c.timestamp_utc for c in candles]
    assert stamps == sorted(stamps)


def test_range_filter(provider):
    candles = provider.get_historical_bars(
        "XAUUSD", "15m",
        datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
        datetime(2024, 1, 15, 11, 0, tzinfo=UTC),
    )
    assert all(
        datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        <= c.timestamp_utc <= datetime(2024, 1, 15, 11, 0, tzinfo=UTC)
        for c in candles
    )
    assert candles  # the fixture spans this window


def test_missing_file_raises(tmp_path):
    provider = CsvMarketDataProvider(tmp_path / "nope.csv")
    with pytest.raises(DataError):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_missing_required_columns(tmp_path):
    bad = tmp_path / "bad_columns.csv"
    bad.write_text("ts,open,close\n2024-01-01T00:00:00Z,1,2\n")
    provider = CsvMarketDataProvider(bad)
    with pytest.raises(DataError, match="required columns"):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_empty_csv(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("timestamp,open,high,low,close\n")
    provider = CsvMarketDataProvider(empty)
    with pytest.raises(DataError, match="empty"):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_invalid_quote_rejected(tmp_path):
    bad = tmp_path / "bad_values.csv"
    bad.write_text(
        "timestamp,open,high,low,close\n"
        "2024-01-01T00:00:00Z,x,y,z,1.0\n"
    )
    provider = CsvMarketDataProvider(bad)
    with pytest.raises(DataError, match="Non-numeric"):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_ohlc_integrity_violation(tmp_path):
    # high < open must be rejected
    bad = tmp_path / "bad_ohlc.csv"
    bad.write_text(
        "timestamp,open,high,low,close\n"
        "2024-01-01T00:00:00Z,10.0,5.0,4.0,9.0\n"
    )
    provider = CsvMarketDataProvider(bad)
    with pytest.raises(DataError, match="high"):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_low_above_open_rejected(tmp_path):
    bad = tmp_path / "bad_low.csv"
    bad.write_text(
        "timestamp,open,high,low,close\n"
        "2024-01-01T00:00:00Z,10.0,15.0,11.0,9.0\n"
    )
    provider = CsvMarketDataProvider(bad)
    with pytest.raises(DataError, match="low"):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_unix_seconds_timestamps(tmp_path):
    ok = tmp_path / "unix.csv"
    ok.write_text(
        "timestamp,open,high,low,close\n"
        "1705936800,10.0,15.0,9.0,12.0\n"  # 2024-01-22T15:20:00Z
    )
    provider = CsvMarketDataProvider(ok)
    candles = provider.get_historical_bars("XAUUSD", "15m",
                                           datetime(1970, 1, 1, tzinfo=UTC),
                                           datetime.now(UTC))
    assert len(candles) == 1
    assert candles[0].timestamp_utc.year == 2024


def test_milliseconds_timestamps(tmp_path):
    ok = tmp_path / "ms.csv"
    ok.write_text(
        "timestamp,open,high,low,close\n"
        "1705936800000,10.0,15.0,9.0,12.0\n"
    )
    provider = CsvMarketDataProvider(ok)
    candles = provider.get_historical_bars("XAUUSD", "15m",
                                           datetime(1970, 1, 1, tzinfo=UTC),
                                           datetime.now(UTC))
    assert candles[0].timestamp_utc.year == 2024


def test_garbage_timestamp_rejected(tmp_path):
    bad = tmp_path / "garbage.csv"
    bad.write_text(
        "timestamp,open,high,low,close\n"
        "not-a-time,10.0,15.0,9.0,12.0\n"
    )
    provider = CsvMarketDataProvider(bad)
    with pytest.raises((ValueError, DataError)):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))


def test_latest_bar_and_quote_conventions(provider):
    candles = provider.get_historical_bars(
        "XAUUSD", "15m",
        datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC),
    )
    latest = provider.get_latest_bar("XAUUSD", "15m")
    assert isinstance(latest, Candle)
    assert latest.close == candles[-1].close
    # CSV source has no bid/ask
    assert provider.get_quote("XAUUSD") is None


def test_cached_results_consistent(provider):
    rng = (datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))
    first = provider.get_historical_bars("XAUUSD", "15m", *rng)
    second = provider.get_historical_bars("XAUUSD", "15m", *rng)
    assert len(first) == len(second)


def test_provider_without_path_raises():
    provider = CsvMarketDataProvider()
    with pytest.raises(DataError):
        provider.get_historical_bars("XAUUSD", "15m",
                                     datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC))
