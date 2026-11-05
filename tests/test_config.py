"""Configuration loading and validation tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from goldbot.core.config import GoldBotSettings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_yaml_settings_load():
    s = load_settings(ROOT / "config" / "settings.yaml")
    assert s.mode == "paper"
    assert s.instrument_symbol == "XAUUSD"
    assert s.risk_per_trade_pct == pytest.approx(0.25)
    assert (s.ema_fast, s.ema_trend, s.ema_long) == (20, 50, 200)
    assert s.allow_live_orders is False
    # extra YAML keys are ignored
    assert s.app_name == "goldbot"


def test_yaml_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.yaml")


def test_paper_mode_allows_unset_instrument():
    s = GoldBotSettings(mode="paper")
    assert s.instrument_symbol in (None, "")
    assert s.allow_live_orders is False


def test_live_mode_requires_instrument_metadata():
    with pytest.raises(ValidationError):
        GoldBotSettings(mode="live")  # no symbol/venue/asset_type


def test_live_mode_requires_verified_metadata():
    with pytest.raises(ValidationError):
        GoldBotSettings(
            mode="live",
            instrument_symbol="XAUUSD",
            instrument_venue="broker",
            asset_type="spot",
            metadata_verified=False,
        )


def test_live_mode_valid_complete():
    s = GoldBotSettings(
        mode="live",
        instrument_symbol="XAUUSD",
        instrument_venue="broker",
        asset_type="spot",
        metadata_verified=True,
    )
    assert s.mode == "live"
    # safety gate: live orders remain impossible through configuration
    assert s.allow_live_orders is False


def test_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        GoldBotSettings(mode="yolo")


def test_negative_risk_rejected():
    with pytest.raises(ValidationError):
        GoldBotSettings(risk_per_trade_pct=-0.5)
    with pytest.raises(ValidationError):
        GoldBotSettings(daily_loss_limit_pct=0.0)


def test_nonpositive_counts_rejected():
    with pytest.raises(ValidationError):
        GoldBotSettings(max_open_positions=0)
    with pytest.raises(ValidationError):
        GoldBotSettings(max_consecutive_losses=0)


def test_negative_initial_equity_rejected():
    with pytest.raises(ValidationError):
        GoldBotSettings(initial_equity=-1)


def test_env_overrides_beat_yaml(monkeypatch):
    monkeypatch.setenv("GOLD_RISK_PER_TRADE_PCT", "0.75")
    s = load_settings(ROOT / "config" / "settings.yaml")
    assert s.risk_per_trade_pct == pytest.approx(0.75)


def test_env_paper_mode(monkeypatch):
    monkeypatch.setenv("GOLD_MODE", "paper")
    s = load_settings(ROOT / "config" / "settings.yaml")
    assert s.mode == "paper"
