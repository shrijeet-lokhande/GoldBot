"""GoldBot trading engine - the live paper-trading orchestration loop.

The engine owns the simulated market (candle replay), periodically calls the
strategy on completed candles, funnels signals through the independent risk
engine, and stores trade proposals that an operator can approve or reject
from the dashboard. Approved proposals fill through the paper broker.

Nothing in here may bypass the risk engine. Paper mode always requires a
stop-loss price on every order (REQUIRE_STOP_LOSS default).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from goldbot.core.config import GoldBotSettings
from goldbot.core.exceptions import GoldBotError
from goldbot.core.models import (
    Candle,
    InstrumentMetadata,
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
)
from goldbot.execution.paper_broker import PaperBroker
from goldbot.indicators import adx, atr, ema, rsi
from goldbot.market_data.csv_provider import CsvMarketDataProvider
from goldbot.risk.engine import RiskEngine
from goldbot.risk.limits import KillSwitch, RiskLimits
from goldbot.strategies.trend_pullback import TrendPullbackStrategy

logger = logging.getLogger("goldbot.engine")


# ---------------------------------------------------------------------------
# Market context passed to the strategy
# ---------------------------------------------------------------------------

@dataclass
class MarketContext:
    """Minimal market context consumed by ``BaseStrategy.generate_signal``."""
    symbol: str
    entry_timeframe: str
    trend_timeframe: str
    candles: dict[str, list[Candle]]


# ---------------------------------------------------------------------------
# Trade proposal (what the operator sees on the dashboard)
# ---------------------------------------------------------------------------

def proposal_to_dict(p: "TradeProposal") -> dict:
    return p.to_dict()


@dataclass
class TradeProposal:
    """A proposed trade awaiting operator (or auto) approval."""
    proposal_id: str
    symbol: str
    direction: str          # "long" | "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float    # lots (filled after risk evaluation)
    risk_pct: float
    reason_text: str
    confidence: str
    strategy_name: str
    timeframe: str
    created_at: str
    status: str = "pending"          # pending | approved | rejected | expired | executed
    decision_reason: str | None = None
    order_id: str | None = None
    signal_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size": self.position_size,
            "risk_pct": self.risk_pct,
            "reason_text": self.reason_text,
            "confidence": self.confidence,
            "strategy_name": self.strategy_name,
            "timeframe": self.timeframe,
            "created_at": self.created_at,
            "status": self.status,
            "decision_reason": self.decision_reason,
            "order_id": self.order_id,
            "signal_snapshot": self.signal_snapshot,
        }


# ---------------------------------------------------------------------------
# Trading engine
# ---------------------------------------------------------------------------

class TradingEngine:
    """Orchestrates the full paper-trading loop.

    The engine replays candle data at a configurable speed (so the bot can be
    observed live without waiting real 15-minute intervals). Each replay step:

        1. Walks the intrabar price path (low/high/close) through the paper
           broker so SL/TP triggers are honoured.
        2. Recomputes the indicator snapshot on all completed candles.
        3. Runs the strategy on the entry timeframe.
        4. Creates a trade proposal for each fresh signal (or auto-executes it
           when ``auto_approve`` is enabled), passing it through the risk
           engine first.
        5. Publishes events to subscribers (WebSocket dashboards).
    """

    def __init__(
        self,
        settings: GoldBotSettings,
        csv_path: str | Path | None = None,
        auto_approve: bool = False,
        replay_speed: float = 1.0,
        persistence_path: str | Path | None = None,
    ):
        self.settings = settings
        self.symbol = settings.instrument_symbol or "XAUUSD"
        self.entry_timeframe = settings.entry_timeframe or "15m"
        self.trend_timeframe = settings.trend_timeframe or "1h"
        self.auto_approve = auto_approve
        self.replay_speed = replay_speed  # simulated bars per step multiplier

        # --- Paper broker & risk engine (verified in paper mode) ---
        # Paper mode: contract specs are deterministic simulation assumptions
        # (documented). Live mode still requires settings.metadata_verified.
        verified = True if settings.mode == "paper" else bool(settings.metadata_verified)
        self.instrument = InstrumentMetadata(
            symbol=self.symbol,
            venue=settings.instrument_venue or "paper",
            asset_type=settings.asset_type or "spot",
            contract_size=100.0,   # 1 lot = 100 oz (XAUUSD standard assumption)
            tick_size=0.1,
            tick_value=1.0,
            volume_step=0.01,
            min_volume=0.01,
            max_volume=100.0,
            verified=verified,
            source="paper_defaults" if settings.mode == "paper" else "settings",
        )

        self.risk_limits = RiskLimits(
            risk_per_trade_pct=settings.risk_per_trade_pct,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            weekly_drawdown_limit_pct=settings.weekly_drawdown_limit_pct,
            max_open_positions=settings.max_open_positions,
            max_entries_per_day=settings.max_entries_per_day,
            max_consecutive_losses=settings.max_consecutive_losses,
            max_spread=settings.max_spread,
            max_slippage=settings.max_slippage,
        )
        self.kill_switch = KillSwitch(
            max_spread=settings.max_spread,
            max_slippage=settings.max_slippage,
        )
        self.risk_engine = RiskEngine(
            risk_limits=self.risk_limits,
            kill_switch=self.kill_switch,
            instrument_metadata=self.instrument,
            equity=settings.initial_equity,
        )
        self.paper_broker = PaperBroker(
            symbol=self.symbol,
            spread=0.1,
            commission=0.0,
            slippage=settings.max_slippage if settings.max_slippage else 0.5,
            partial_fill_probability=0.0,
            timeout_seconds=settings.order_timeout_seconds or 10,
            initial_equity=settings.initial_equity,
            persistence_path=persistence_path or Path("logs") / f"orders_{self.symbol}.json",
            contract_size=self.instrument.contract_size,
        )
        self.strategy = TrendPullbackStrategy(
            ema_fast=settings.ema_fast,
            ema_trend=settings.ema_trend,
            ema_long=settings.ema_long,
            rsi_period=settings.rsi_period,
            rsi_threshold=settings.rsi_threshold,
            atr_period=settings.atr_period,
            adx_period=settings.adx_period,
            minimum_adx=settings.minimum_adx,
        )

        # --- Market data ---
        self.csv_path = Path(csv_path) if csv_path else Path(
            "data/fixtures/sample_xauusd_15m.csv"
        )
        self.provider = CsvMarketDataProvider(self.csv_path)
        self._all_candles: list[Candle] = []
        self._load_candles()

        # --- Runtime state ---
        self._replay_index = 0
        self.proposals: list[TradeProposal] = []
        # Deduplicate: candle key -> proposal (reject duplicate signals)
        self._signal_for_candle: dict[str, str] = {}
        self._entries_today = 0
        self._current_sim_date: str | None = None
        self._started_at = datetime.now(timezone.utc)
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._subscribers: list[Callable[[dict], Any]] = []

        # Initial risk tracking baseline
        self.risk_limits.set_start_of_day_equity(settings.initial_equity)
        self.risk_limits.set_weekly_equity_high(settings.initial_equity)

        # Indicator caches
        self._indicators: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_candles(self) -> None:
        from datetime import datetime as dt
        self._all_candles = self.provider.get_historical_bars(
            symbol=self.symbol,
            timeframe=self.entry_timeframe,
            start=dt.min.replace(tzinfo=timezone.utc),
            end=dt.now(timezone.utc),
        )
        if not self._all_candles:
            raise GoldBotError(f"No candles loaded from {self.csv_path}")
        # Seed the broker price with real data so pre-replay quotes are sane
        self.paper_broker.set_price(self._all_candles[0].close)
        logger.info("Engine loaded %d candles from %s", len(self._all_candles), self.csv_path)

    @property
    def candles(self) -> list[Candle]:
        """Candles revealed so far in the replay (completed bars)."""
        return self._all_candles[: self._replay_index]

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    def compute_indicators(self) -> dict[str, Any]:
        """Recompute the indicator snapshot for all revealed candles."""
        reveals = self.candles
        if not reveals:
            return {}
        df = pd.DataFrame(
            {
                "open": [c.open for c in reveals],
                "high": [c.high for c in reveals],
                "low": [c.low for c in reveals],
                "close": [c.close for c in reveals],
            }
        )
        close = df["close"]
        out: dict[str, Any] = {}
        ema_fast = ema(close, self.settings.ema_fast)
        ema_trend = ema(close, self.settings.ema_trend)
        ema_long_s = ema(close, self.settings.ema_long)
        out["ema_fast"] = _last(ema_fast)
        out["ema_trend"] = _last(ema_trend)
        out["ema_long"] = _last(ema_long_s)
        out["rsi"] = _last(rsi(close, self.settings.rsi_period))
        out["atr"] = _last(atr(df["high"], df["low"], close, self.settings.atr_period))
        out["adx"] = _last(adx(df["high"], df["low"], close, self.settings.adx_period))
        # Series heads for the chart
        out["series"] = {
            "ema_fast": ema_fast.tolist(),
            "ema_trend": ema_trend.tolist(),
            "ema_long": ema_long_s.tolist(),
        }
        self._indicators = out
        return out

    def get_indicators(self) -> dict[str, Any]:
        return dict(self._indicators or {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_quote(self) -> dict:
        mid = self.paper_broker.current_price
        spread = self.paper_broker.spread
        return {
            "bid": round(mid - spread / 2.0, 2),
            "ask": round(mid + spread / 2.0, 2),
            "spread": spread,
            "mid_price": round(mid, 2),
        }

    def get_account(self) -> dict:
        equity = self.paper_broker.get_account_equity()
        realised = self.paper_broker._realised_pnl_total
        unrealised = float(
            sum(
                p.unrealised_pnl for p in self.paper_broker.get_positions()
            )
        )
        return {
            "equity": round(equity, 2),
            "balance": round(self.paper_broker.initial_equity + realised, 2),
            "realised_pnl": round(realised, 2),
            "unrealised_pnl": round(unrealised, 2),
            "initial_equity": self.paper_broker.initial_equity,
        }

    def get_positions(self) -> list[dict]:
        positions = []
        for p in self.paper_broker.get_positions():
            positions.append({
                "symbol": p.symbol,
                "side": p.side.value,
                "direction": "LONG" if p.side == OrderSide.BUY else "SHORT",
                "volume": p.volume,
                "entry_price": round(p.entry_price, 2),
                "current_price": round(p.current_price or p.entry_price, 2),
                "unrealised_pnl": round(p.unrealised_pnl, 2),
                "realised_pnl": round(p.realised_pnl, 2),
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "pnl_percent": round(p.pnl_percent, 3),
            })
        return positions

    def get_trades(self, limit: int | None = None) -> list[dict]:
        return self.paper_broker.get_trades(limit)

    def get_orders(self) -> list[dict]:
        orders = self.paper_broker.get_orders()
        return [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "volume": o.volume,
                "fill_price": o.fill_price,
                "stop_loss": o.stop_loss,
                "take_profit": o.take_profit,
                "status": o.status.value,
                "submitted_at": o.submitted_at.isoformat(),
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            }
            for o in orders
        ]

    def get_proposals(self, status: str | None = None) -> list[dict]:
        props = [p.to_dict() for p in self.proposals]
        if status:
            props = [p for p in props if p["status"] == status]
        return props

    def get_performance(self) -> dict:
        trades = self.paper_broker.get_trades()
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        total_pnl = gross_win - gross_loss
        win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
        profit_factor = (
            (gross_win / gross_loss) if gross_loss > 0
            else (None if gross_win == 0 else float("inf"))
        )
        equity = self.paper_broker.get_account_equity()
        peak = self.get_account()["initial_equity"]
        # simple max drawdown from the trade ledger
        eq, max_dd = peak, 0.0
        dd_curve = [eq]
        for t in trades:
            eq += t["pnl"]
            dd_curve.append(eq)
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100.0 if peak > 0 else 0.0)
        return {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 2),
            "profit_factor": profit_factor if profit_factor is None else round(profit_factor, 3),
            "total_pnl": round(total_pnl, 2),
            "average_win": round((sum(t['pnl'] for t in wins) / len(wins)) if wins else 0.0, 2),
            "average_loss": round(
                (sum(t['pnl'] for t in losses) / len(losses)) if losses else 0.0, 2,
            ),
            "max_drawdown_pct": round(max_dd, 2),
            "current_equity": round(equity, 2),
        }

    def get_health(self) -> dict:
        return {
            "status": "ok" if not self.kill_switch.active else "kill_switch_active",
            "mode": self.settings.mode,
            "environment": self.settings.environment,
            "instrument_symbol": self.symbol,
            "metadata_verified": self.instrument.verified,
            "running": self._running,
            "replay_index": self._replay_index,
            "total_bars": len(self._all_candles),
            "paper_broker_healthy": self.paper_broker.health_check(),
            "data_source": str(self.csv_path),
            "kill_switch": self.kill_switch.active,
            "kill_switch_reasons": self.kill_switch.reasons,
        }

    def get_config(self) -> dict:
        s = self.settings
        return {
            "instrument_symbol": self.symbol,
            "mode": s.mode,
            "environment": s.environment,
            "risk_per_trade_pct": s.risk_per_trade_pct,
            "daily_loss_limit_pct": s.daily_loss_limit_pct,
            "weekly_drawdown_limit_pct": s.weekly_drawdown_limit_pct,
            "max_open_positions": s.max_open_positions,
            "max_entries_per_day": s.max_entries_per_day,
            "max_consecutive_losses": s.max_consecutive_losses,
            "max_spread": s.max_spread,
            "max_slippage": s.max_slippage,
            "strategy_name": s.strategy_name,
            "entry_timeframe": self.entry_timeframe,
            "trend_timeframe": self.trend_timeframe,
            "auto_approve": self.auto_approve,
            "replay_index": self._replay_index,
            "total_bars": len(self._all_candles),
        }

    # ------------------------------------------------------------------
    # Proposals lifecycle
    # ------------------------------------------------------------------

    def _make_proposal(self, signal: Signal) -> TradeProposal | None:
        """Convert a strategy signal into a dashboard trade proposal."""
        # Risk engine pre-evaluation (sizing + limits); it must approve for
        # the proposal to be worth showing.
        current_positions = len(self.paper_broker.get_positions())
        entry_price = self.paper_broker.current_price
        is_long = signal.direction == SignalDirection.LONG
        stop_distance = max(signal.stop_distance, 0.0)
        if stop_distance <= 0:
            return None
        if is_long:
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance
        take_profit = entry_price + (signal.stop_distance * signal.take_profit_multiple
                                      * (1 if is_long else -1))
        try:
            decision = self.risk_engine.evaluate_signal(
                signal=signal,
                entry_price=entry_price,
                stop_price=stop_price,
                current_candle=None,
                current_positions=current_positions,
                current_equity=self.paper_broker.get_account_equity(),
            )
            error_reason = None
        except GoldBotError as exc:
            decision = {"decision": "reject", "reason": str(exc), "position_size": 0.0}
            error_reason = str(exc)

        proposal = TradeProposal(
            proposal_id=str(uuid.uuid4()),
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_price, 2),
            take_profit=round(take_profit, 2),
            position_size=round(decision.get("position_size") or 0.0, 2),
            risk_pct=self.settings.risk_per_trade_pct,
            reason_text=", ".join(signal.reason_codes),
            confidence=("high" if decision["decision"] == "approve" else "low"),
            strategy_name=self.strategy.name,
            timeframe=signal.timeframe,
            created_at=datetime.now(timezone.utc).isoformat(),
            signal_snapshot=signal.indicator_snapshot,
        )
        # Status semantics: the risk engine gates entry into the approval
        # register, but the operator gate comes afterwards:
        #   rejected  -> risk engine refused the signal (terminal)
        #   pending   -> risk-approved, awaiting operator decision
        #   executed  -> filled via the paper broker (operator approved whatever,
        #                or auto-approval mode was on)
        if decision["decision"] != "approve":
            proposal.status = "rejected"
            proposal.decision_reason = decision.get("reason") or error_reason
        else:
            # Size is evaluated again at execution time against live state.
            proposal.status = "pending"
            proposal.decision_reason = "risk_approved"

        self.proposals.append(proposal)
        # Keep the proposal register bounded
        if len(self.proposals) > 500:
            self.proposals = self.proposals[-500:]

        self._publish({"type": "proposal", "data": proposal.to_dict()})

        if self.auto_approve and proposal.status == "pending":
            self.execute_proposal(proposal.proposal_id)
        return proposal

    def create_proposal(self, signal: Signal) -> dict:
        prop = self._make_proposal(signal)
        return prop.to_dict() if prop is not None else {"status": "no_signal"}

    def approve_proposal(self, proposal_id: str) -> dict:
        for prop in self.proposals:
            if prop.proposal_id == proposal_id:
                return self.execute_proposal(prop)
        return {"status": "not_found", "proposal_id": proposal_id}

    def reject_proposal(self, proposal_id: str, reason: str = "user_rejected") -> dict:
        for prop in self.proposals:
            if prop.proposal_id == proposal_id and prop.status == "pending":
                prop.status = "rejected"
                prop.decision_reason = reason
                logger.info("Proposal %s rejected: %s", proposal_id, reason)
                self._publish({"type": "proposal", "data": prop.to_dict()})
                return prop.to_dict()
        return {"status": "not_found", "proposal_id": proposal_id}

    def execute_proposal(self, prop: TradeProposal | str) -> dict:
        """Execute an approved proposal through the risk engine + paper broker."""
        if isinstance(prop, str):
            match = next((p for p in self.proposals if p.proposal_id == prop), None)
            if match is None:
                return {"status": "not_found", "proposal_id": prop}
            prop = match

        if prop.status == "executed":
            return {"status": "already_executed", "proposal": prop.to_dict()}
        if prop.status == "rejected":
            return {"status": "rejected_by_risk", "proposal": prop.to_dict()}

        current_positions = len(self.paper_broker.get_positions())

        # Re-run the risk engine with live state at the live price
        entry_price = self.paper_broker.current_price
        stop_distance = abs(prop.entry_price - prop.stop_loss) or 5.0
        is_long = prop.direction == SignalDirection.LONG
        stop_price = entry_price - stop_distance if is_long else entry_price + stop_distance
        take_profit = entry_price + (stop_distance * 2.0 if is_long else -stop_distance * 2.0)

        signal = Signal(
            symbol=prop.symbol,
            direction=prop.direction,
            created_at_utc=datetime.now(timezone.utc),
            reference_price=entry_price,
            stop_distance=stop_distance,
            take_profit_multiple=2.0,
            timeframe=prop.timeframe,
            reason_codes=["manual_approval"],
            indicator_snapshot=prop.signal_snapshot,
        )
        try:
            decision = self.risk_engine.evaluate_signal(
                signal=signal,
                entry_price=entry_price,
                stop_price=stop_price,
                current_candle=None,
                current_positions=current_positions,
                current_equity=self.paper_broker.get_account_equity(),
            )
        except GoldBotError as exc:
            decision = {"decision": "reject", "reason": str(exc), "position_size": 0.0}

        if decision["decision"] != "approve":
            prop.status = "rejected"
            prop.decision_reason = decision.get("reason")
            self._publish({"type": "proposal", "data": prop.to_dict()})
            return {"status": "rejected_by_risk", "reason": decision.get("reason"),
                    "proposal": prop.to_dict()}

        side = OrderSide.BUY if is_long else OrderSide.SELL
        order = self.paper_broker.send_order(
            symbol=prop.symbol,
            side=side,
            order_type=OrderType.MARKET,
            volume=decision["position_size"],
            price=None,
            stop_loss=round(stop_price, 2),
            take_profit=round(take_profit, 2),
            timeout_seconds=self.settings.order_timeout_seconds,
        )
        if order.status.value in ("filled", "partial"):
            prop.status = "executed"
            prop.order_id = order.order_id
            self.risk_limits.increment_entries_today()
            self._publish({"type": "order", "data": {
                "order_id": order.order_id,
                "proposal_id": prop.proposal_id,
                "side": order.side.value,
                "volume": order.volume,
                "fill_price": order.fill_price,
            }})
            self._publish({"type": "proposal", "data": prop.to_dict()})
            return {"status": "order_submitted", "order_id": order.order_id,
                    "fill_price": order.fill_price, "proposal": prop.to_dict()}
        prop.status = "rejected"
        prop.decision_reason = f"order {order.status.value}"
        return {"status": "order_rejected", "proposal": prop.to_dict()}

    def close_position(self, symbol: str | None = None) -> dict:
        trade = self.paper_broker.close_position(symbol or self.symbol)
        if trade:
            self._publish({"type": "trade", "data": trade})
        return trade or {"status": "no_open_position"}

    def set_kill_switch(self, active: bool, reason: str = "manual") -> None:
        if active:
            self.kill_switch.activate(reason)
        else:
            self.kill_switch.deactivate()
        self._publish({"type": "risk", "data": self.get_health()})

    def update_config(self, new_values: dict) -> dict:
        """Apply live-safe configuration updates."""
        s = self.settings
        float_fields = {
            "risk_per_trade_pct": "risk_per_trade_pct",
            "daily_loss_limit_pct": "daily_loss_limit_pct",
            "weekly_drawdown_limit_pct": "weekly_drawdown_limit_pct",
        }
        optional_float_fields = ("max_spread", "max_slippage")
        int_fields = {
            "max_open_positions": "max_open_positions",
            "max_entries_per_day": "max_entries_per_day",
            "max_consecutive_losses": "max_consecutive_losses",
        }
        bool_keys = ("auto_approve",)
        for key, value in new_values.items():
            if key in float_fields and isinstance(value, (int, float)) and value > 0:
                setattr(s, key, float(value))
                setattr(self.risk_limits, float_fields[key], float(value))
            elif key in optional_float_fields and isinstance(value, (int, float)):
                if value <= 0:
                    value = None  # clears the limit
                setattr(s, key, value)
                setattr(self.risk_limits, key, value)
                setattr(self.kill_switch, key, value)
            elif key in int_fields and isinstance(value, (int, float)) and int(value) >= 1:
                setattr(s, key, int(value))
                setattr(self.risk_limits, int_fields[key], int(value))
            elif key == "order_timeout_seconds" and isinstance(value, (int, float)) \
                    and int(value) >= 1:
                setattr(s, key, int(value))
            elif key in bool_keys and isinstance(value, bool):
                self.auto_approve = value
            elif key == "replay_index" and isinstance(value, int):
                self.jump_to_bar(value)
        return self.get_config()

    # ------------------------------------------------------------------
    # Replay loop
    # ------------------------------------------------------------------

    def step_bar(self) -> dict:
        """Advance the replay by one bar; returns processed event summary."""
        if self._replay_index >= len(self._all_candles):
            # Wrap the replay: restart from the first bar (session state kept)
            logger.info("Replay exhausted; wrapping to bar 0")
            self._replay_index = 0

        candle = self._all_candles[self._replay_index]

        # Daily risk counters reset on a new simulated day
        sim_date = str(candle.timestamp_utc.date())
        if self._current_sim_date != sim_date:
            self._current_sim_date = sim_date
            day_equity = self.paper_broker.get_account_equity()
            self.risk_limits.set_start_of_day_equity(day_equity)
            self.risk_limits.reset_daily_counter()
            # Keep the weekly high-water mark up to date with realised P&L
            weekly_high = max(
                self.risk_limits._weekly_equity_high or day_equity,
                day_equity,
            )
            self.risk_limits.set_weekly_equity_high(weekly_high)

        # Walk the intrabar path so SL/TP triggers in-between are honoured:
        # prev_close -> low -> high -> close
        events: list[dict] = []
        for step_price in (candle.low, candle.high, candle.close):
            closed = self.paper_broker.update_market_price(step_price)
            for trade in closed or []:
                events.append({"type": "trade", "data": trade})
                self._publish({"type": "trade", "data": trade})
                # Feed the risk engine's consecutive-loss counter
                self.risk_limits.record_trade_result(float(trade.get("pnl", 0.0)))

        # Reveal the completed candle
        self._replay_index += 1

        # Strategy evaluation on the completed bar
        self.compute_indicators()
        signal = self.evaluate_strategy()
        proposal = None
        if signal is not None:
            proposal = self._make_proposal(signal)
            if proposal is not None:
                events.append({"type": "proposal", "data": proposal.to_dict()})

        # Publish market updates
        self._publish({"type": "candle", "data": {
            "time": int(candle.timestamp_utc.timestamp()),
            "open": candle.open, "high": candle.high,
            "low": candle.low, "close": candle.close,
            "volume": candle.volume,
        }})
        self._publish({"type": "price", "data": {
            **self.get_quote(),
            "equity": round(self.paper_broker.get_account_equity(), 2),
        }})

        return {
            "candle": candle,
            "signal": signal is not None,
            "proposal": proposal.to_dict() if proposal else None,
            "events": events,
        }

    def evaluate_strategy(self) -> Signal | None:
        """Run the strategy on the current revealed candles."""
        reveals = self.candles
        if len(reveals) < self.settings.ema_long + self.settings.ema_trend:
            return None  # not enough history yet

        context = MarketContext(
            symbol=self.symbol,
            entry_timeframe=self.entry_timeframe,
            trend_timeframe=self.trend_timeframe,
            candles={
                self.entry_timeframe: reveals,
                # Trend timeframe: resample entry candles into 1h bars
                self.trend_timeframe: self._build_trend_candles(reveals),
            },
        )
        indicators = self.get_indicators()
        indicator_results = {
            k: {"value": v if not isinstance(v, dict) else None}
            for k, v in indicators.items() if k != "series"
        }
        try:
            signal = self.strategy.generate_signal(context, indicator_results)
        except Exception as exc:  # never let strategy errors kill the loop
            logger.exception("Strategy error: %s", exc)
            return None
        return signal

    def _build_trend_candles(self, reveals: list[Candle]) -> list[Candle]:
        """Aggregate 15m candles into the configured trend timeframe (1h)."""
        if self.trend_timeframe in (self.entry_timeframe, None):
            return reveals
        if not reveals:
            return []
        bucket_minutes = 60 if self.trend_timeframe in ("1h", "60m") else 4 * 60
        out: list[Candle] = []
        cur: list[Candle] = []
        bucket_start: datetime | None = None
        for c in reveals:
            ts = c.timestamp_utc
            start = ts.replace(minute=(ts.minute // bucket_minutes) * bucket_minutes,
                               second=0, microsecond=0)
            if bucket_start is None or start != bucket_start:
                if cur:
                    out.append(_merge_candles(cur))
                bucket_start = start
                cur = [c]
            else:
                cur.append(c)
        if cur:
            out.append(_merge_candles(cur))
        return out

    # ------------------------------------------------------------------

    def run_background(self, interval_seconds: float = 1.0) -> asyncio.Task:
        """Start the replay loop as a background asyncio task."""
        if self._loop_task is not None and not self._loop_task.done():
            return self._loop_task

        async def _loop():
            self._running = True
            logger.info("Engine loop started (interval=%.2fs, speed=%.1fx)",
                        interval_seconds, self.replay_speed)
            try:
                while True:
                    await asyncio.sleep(interval_seconds)
                    try:
                        self.step_bar()
                    except Exception:
                        logger.exception("Engine step failed")
            except asyncio.CancelledError:
                pass
            finally:
                self._running = False

        self._loop_task = asyncio.create_task(_loop())
        return self._loop_task

    def stop_background(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            self._loop_task = None
            self._running = False

    def save_state(self) -> None:
        """Persist broker state to disk (call on shutdown)."""
        try:
            self.paper_broker._save_persistence()
        except Exception:  # never fail shutdown on persistence
            logger.exception("Failed to persist paper broker state")

    def jump_to_bar(self, index: int) -> None:
        """Jump the replay pointer (does not rebuild historic positions)."""
        self._replay_index = max(0, min(index, len(self._all_candles)))
        last_revealed = max(0, self._replay_index - 1)
        candle = self._all_candles[last_revealed]
        self.paper_broker.set_price(candle.close)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[dict], Any]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
        return _unsubscribe

    def _publish(self, event: dict) -> None:
        for callback in list(self._subscribers):
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                logger.exception("Event subscriber failed")


def _merge_candles(candles: list[Candle]) -> Candle:
    """Merge a bucket of candles into one higher-timeframe candle."""
    return Candle(
        symbol=candles[0].symbol,
        timeframe=f"{len(candles)}x",
        timestamp_utc=candles[0].timestamp_utc,
        open=candles[0].open,
        high=max(c.high for c in candles),
        low=min(c.low for c in candles),
        close=candles[-1].close,
        volume=sum(c.volume for c in candles),
        is_complete=True,
    )


def _last(series: pd.Series) -> float | None:
    if len(series) == 0:
        return None
    val = series.iloc[-1]
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return float(val)
