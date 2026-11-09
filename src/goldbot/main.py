"""GoldBot CLI entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from goldbot.core.config import GoldBotSettings, load_settings
from goldbot.core.exceptions import GoldBotError
from goldbot.core.logging import get_logger, setup_logging

logger = get_logger("goldbot.cli")


def _ensure_config_dirs() -> None:
    """Ensure config and data directories exist."""
    config_dir = Path("config")
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("raw", "processed", "fixtures"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """GoldBot - Algorithmic Gold Trading System."""


@cli.command()
@click.option(
    "--config",
    default="config/settings.yaml",
    show_default=True,
    help="Path to settings YAML file.",
)
def config_check(config: str) -> None:
    """Validate configuration without connecting to a broker."""
    try:
        settings = load_settings(Path(config))
        click.echo(
            f"Configuration OK: mode={settings.mode}, "
            f"instrument_symbol={settings.instrument_symbol}"
        )
        click.echo(f"  environment: {settings.environment}")
        click.echo(f"  mode: {settings.mode}")
        click.echo(f"  metadata_verified: {settings.metadata_verified}")
        click.echo(f"  max_open_positions: {settings.max_open_positions}")
        click.echo(f"  risk_per_trade_pct: {settings.risk_per_trade_pct}")
        click.echo(f"  daily_loss_limit_pct: {settings.daily_loss_limit_pct}")
        click.echo(f"  weekly_drawdown_limit_pct: {settings.weekly_drawdown_limit_pct}")
        sys.exit(0)
    except Exception as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)


@cli.command()
def health() -> None:
    """Check application and provider health."""
    try:
        settings = GoldBotSettings()
    except Exception as exc:
        click.echo(f"Failed to load settings: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Mode: {settings.mode}")
    click.echo(f"Environment: {settings.environment}")
    click.echo(f"Instrument symbol: {settings.instrument_symbol}")
    click.echo(f"Metadata verified: {settings.metadata_verified}")
    click.echo(f"Adapter: {settings.adapter}")
    click.echo(f"Allow live orders: {settings.allow_live_orders}")

    if settings.mode == "paper":
        click.echo("Status: Paper trading mode active (safe default)")
    elif settings.mode == "live":
        click.echo("Status: Live mode configured - ensure all safety gates are configured")
    sys.exit(0)


@cli.command()
@click.option(
    "--file",
    default="data/fixtures/sample_xauusd_15m.csv",
    show_default=True,
    help="Path to CSV file to import.",
)
def data_import(file: str) -> None:
    """Import a historical CSV dataset (validate + report)."""
    from datetime import datetime as dt
    from datetime import timezone

    from goldbot.market_data.csv_provider import CsvMarketDataProvider

    _ensure_config_dirs()
    csv_path = Path(file)
    if not csv_path.exists():
        click.echo(f"CSV file not found: {csv_path}", err=True)
        sys.exit(1)

    provider = CsvMarketDataProvider(csv_path)
    try:
        candles = provider.get_historical_bars(
            symbol="XAUUSD",
            timeframe="15m",
            start=dt.min.replace(tzinfo=timezone.utc),
            end=dt.now(timezone.utc),
        )
        click.echo(f"Successfully imported {len(candles)} candles from {csv_path}")
        click.echo(f"Sample candle: {candles[0] if candles else 'none'}")
    except GoldBotError as exc:
        click.echo(f"Failed to import data: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--file",
    default="data/fixtures/sample_xauusd_15m.csv",
    show_default=True,
    help="Path to CSV data file.",
)
def data_status(file: str) -> None:
    """Inspect available data."""
    from datetime import datetime as dt
    from datetime import timezone

    from goldbot.market_data.csv_provider import CsvMarketDataProvider

    csv_path = Path(file)
    if not csv_path.exists():
        click.echo(f"No data file found: {csv_path}", err=True)
        sys.exit(1)

    provider = CsvMarketDataProvider(csv_path)
    try:
        candles = provider.get_historical_bars(
            symbol="XAUUSD",
            timeframe="15m",
            start=dt.min.replace(tzinfo=timezone.utc),
            end=dt.now(timezone.utc),
        )
        if candles:
            click.echo(f"Total candles: {len(candles)}")
            click.echo(f"First candle: {candles[0]}")
            click.echo(f"Last candle: {candles[-1]}")
        else:
            click.echo("No candles loaded.")
    except GoldBotError as exc:
        click.echo(f"Error reading data: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--file",
    default="data/fixtures/sample_xauusd_15m.csv",
    show_default=True,
    help="Path to CSV data file.",
)
def indicators(file: str) -> None:
    """Calculate indicators for a dataset."""
    import pandas as pd

    from goldbot.indicators import adx, atr, ema, rsi

    sample = Path(file)
    if not sample.exists():
        click.echo(f"No data file found: {sample}", err=True)
        sys.exit(1)

    try:
        df = pd.read_csv(sample)
        df.columns = [c.strip().lower() for c in df.columns]

        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(set(df.columns)):
            click.echo(f"CSV missing required columns: {required - set(df.columns)}", err=True)
            sys.exit(1)

        close = df["close"]
        high = df["high"]
        low = df["low"]

        ema_20 = ema(close, 20).tolist()
        ema_50 = ema(close, 50).tolist()
        ema_200 = ema(close, 200).tolist()
        rsi_val = rsi(close, 14).tolist()
        atr_val = atr(high, low, close, 14).tolist()
        adx_val = adx(high, low, close, 14).tolist()

        click.echo("Indicator calculations (first 5 values):")
        for i in range(min(5, len(df))):
            click.echo(
                f"  row {i}: close={close.iloc[i]:.2f}, "
                f"EMA20={ema_20[i]:.2f}, EMA50={ema_50[i]:.2f}, "
                f"EMA200={ema_200[i]:.2f}, RSI={rsi_val[i]:.1f}, "
                f"ATR={atr_val[i]:.2f}, ADX={adx_val[i]:.1f}"
            )
    except GoldBotError as exc:
        click.echo(f"Error calculating indicators: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    default="config/settings.yaml",
    show_default=True,
    help="Path to settings YAML file.",
)
@click.option(
    "--bars", default=0, type=int, help="Number of bars to simulate (0 = full dataset, then wrap)."
)
@click.option("--interval", default=1.0, show_default=True, help="Seconds between bars.")
def paper(config: str, bars: int, interval: float) -> None:
    """Run a paper trading session in the terminal.

    Replays historical candles through the live engine (identical code path
    to the API server), then keeps wrapping the tape. Press Ctrl+C to stop.
    """
    import asyncio

    from goldbot.engine import TradingEngine

    setup_logging(level=logging.INFO)
    settings = load_settings(Path(config))
    engine = TradingEngine(
        settings,
        auto_approve=True,  # terminal session has no dashboard operator
    )

    click.echo(f"Starting GoldBot paper trading ({settings.mode} mode)...")
    click.echo(
        f"Symbol: {engine.symbol}  Bars available: "
        f"{len(engine._all_candles)}  All fills are simulated."
    )
    click.echo("Press Ctrl+C to stop.")

    def show_bar(result: dict) -> None:
        candle = result["candle"]
        quote = engine.get_quote()
        account = engine.get_account()
        click.echo(
            f"{candle.timestamp_utc:%Y-%m-%d %H:%M} "
            f"O={candle.open:.2f} H={candle.high:.2f} L={candle.low:.2f} "
            f"C={candle.close:.2f} | bid={quote['bid']:.2f} ask={quote['ask']:.2f}"
            f" | equity={account['equity']:.2f}"
            f" | trades={len(engine.get_trades())}"
        )
        for event in result.get("events", []):
            data = event.get("data", {})
            click.echo(
                f"    >> {event['type'].upper()}: "
                f"{data.get('symbol', '')} {data.get('side', '')} "
                f"vol={data.get('volume', '')} "
                f"close={data.get('close_price', '')} "
                f"pnl={data.get('pnl', '')} reason={data.get('reason', '')}"
            )

    async def _run() -> None:
        try:
            count = 0
            while True:
                show_bar(engine.step_bar())
                count += 1
                if bars and count >= bars:
                    click.echo(f"Reached {bars} bars; stopping.")
                    return
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            pass

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("\nPaper trading stopped by user.")
    finally:
        engine.save_state()
        click.echo("State saved. Goodbye.")


@cli.group()
def backtest() -> None:
    """Backtesting commands."""


@backtest.command("run")
@click.option(
    "--config",
    default="config/settings.yaml",
    show_default=True,
    help="Path to settings YAML file.",
)
@click.option(
    "--data",
    default="data/fixtures/sample_xauusd_15m.csv",
    show_default=True,
    help="Path to CSV data file.",
)
@click.option(
    "--auto-approve/--manual",
    default=True,
    show_default=True,
    help="Auto-approve every risk-passing proposal.",
)
def backtest_run(config: str, data: str, auto_approve: bool) -> None:
    """Replay the full historical dataset through the actual engine.

    Uses the identical strategy/risk/broker pipeline as live paper mode;
    results therefore include simulated spread, slippage and sizing.
    """
    setup_logging(level=logging.WARNING)  # quiet for the run

    try:
        from goldbot.engine import TradingEngine

        settings = load_settings(Path(config))
        engine = TradingEngine(
            settings,
            csv_path=Path(data) if data else None,
            auto_approve=auto_approve,
            # Disposable backtest artifact; explicit temp path is intentional.
            persistence_path=Path("/tmp/goldbot_backtest_orders.json"),  # noqa: S108
        )
    except (GoldBotError, Exception) as exc:
        click.echo(f"Backtest setup failed: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"Running backtest: {len(engine._all_candles)} bars, "
        f"strategy={settings.strategy_name}, "
        f"risk_per_trade={settings.risk_per_trade_pct}%"
    )

    while engine._replay_index < len(engine._all_candles):
        engine.step_bar()

    perf = engine.get_performance()
    account = engine.get_account()

    click.echo("\n=== Backtest Results ===")
    click.echo(f"Initial equity: {account['initial_equity']:.2f}")
    click.echo(f"Final equity:   {account['equity']:.2f}")
    click.echo(f"Total return:   {(account['equity'] / account['initial_equity'] - 1) * 100:.2f}%")
    click.echo(f"Total trades:   {perf['total_trades']}")
    click.echo(f"Win rate:       {perf['win_rate']}%")
    click.echo(f"Profit factor:  {perf['profit_factor']}")
    click.echo(f"Max drawdown:   {perf['max_drawdown_pct']}%")
    click.echo(f"Total P&L:      {perf['total_pnl']}")
    click.echo(
        f"Proposals:      {len(engine.proposals)} "
        f"(rejected: "
        f"{len([p for p in engine.proposals if p.status == 'rejected'])})"
    )


def main() -> None:
    """Console-script entry point."""
    cli()


if __name__ == "__main__":
    main()
