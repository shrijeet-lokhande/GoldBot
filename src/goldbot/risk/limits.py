"""GoldBot risk limits - daily/weekly drawdown and position limits."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from goldbot.core.models import InstrumentMetadata

logger = logging.getLogger("goldbot.risk.limits")


class RiskLimits:
    """Independent risk limit checks that must pass before a trade is approved."""

    def __init__(
        self,
        risk_per_trade_pct: float,
        daily_loss_limit_pct: float,
        weekly_drawdown_limit_pct: float,
        max_open_positions: int,
        max_entries_per_day: int,
        max_consecutive_losses: int,
        max_spread: Optional[float] = None,
        max_slippage: Optional[float] = None,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.weekly_drawdown_limit_pct = weekly_drawdown_limit_pct
        self.max_open_positions = max_open_positions
        self.max_entries_per_day = max_entries_per_day
        self.max_consecutive_losses = max_consecutive_losses
        self.max_spread = max_spread
        self.max_slippage = max_slippage

        # Internal state tracking
        self._start_of_day_equity: Optional[float] = None
        self._weekly_equity_high: Optional[float] = None
        self._consecutive_losses: int = 0
        self._entries_today: int = 0
        self._last_trade_date: Optional[str] = None
        self._last_week_start: Optional[str] = None

    def set_start_of_day_equity(self, equity: float) -> None:
        """Set the equity at the start of the current day."""
        self._start_of_day_equity = equity
        self._entries_today = 0
        self._consecutive_losses = 0
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._last_trade_date = today_str

    def set_weekly_equity_high(self, high: float) -> None:
        """Set the weekly equity high."""
        self._weekly_equity_high = high

    def check_daily_loss_limit(
        self,
        current_equity: float,
        realised_pnl: float = 0.0,
        unrealised_pnl: float = 0.0,
    ) -> bool:
        """Check if daily loss limit is breached.

        Only *losses* count: a profitable day must never trigger this check.

        Args:
            current_equity: Current account equity (includes realised P&L
                and unrealised P&L of open positions).

        Returns:
            True if the daily loss limit has NOT been breached.
        """
        if self._start_of_day_equity is None:
            # If not set, assume no daily limit breach
            return True

        start_equity = self._start_of_day_equity
        if start_equity <= 0:
            return True

        loss = start_equity - current_equity
        if loss <= 0:
            return True  # equity flat or up: no drawdown

        loss_pct = loss / start_equity * 100.0
        return loss_pct < self.daily_loss_limit_pct

    def check_weekly_drawdown_limit(
        self,
        current_equity: float,
        realised_pnl: float = 0.0,
        unrealised_pnl: float = 0.0,
    ) -> bool:
        """Check if weekly drawdown limit is breached.

        Args:
            current_equity: Current account equity.
            realised_pnl: Realised P&L this week.
            unrealised_pnl: Unrealised P&L (open positions) this week.

        Returns:
            True if the weekly drawdown limit has NOT been breached.
        """
        if self._weekly_equity_high is None:
            # If not set, assume no weekly breach
            return True

        if self._weekly_equity_high <= 0:
            return True

        drawdown = self._weekly_equity_high - current_equity
        if drawdown <= 0:
            return True

        drawdown_pct = drawdown / self._weekly_equity_high * 100.0
        if drawdown_pct >= self.weekly_drawdown_limit_pct:
            return False
        return True

    def check_max_open_positions(self, current_positions: int) -> bool:
        """Check if max open positions limit is breached."""
        if current_positions >= self.max_open_positions:
            return False
        return True

    def check_max_entries_per_day(self) -> bool:
        """Check if max entries per day limit is breached."""
        if self._entries_today >= self.max_entries_per_day:
            return False
        return True

    def check_max_consecutive_losses(self, just_lost: bool = False) -> bool:
        """Check if max consecutive losses limit is breached.

        This check is side-effect free. Record actual trade outcomes via
        :meth:`record_trade_result` so the counter reflects the trade ledger.

        Args:
            just_lost: Whether the most recent trade was a loss.

        Returns:
            True if the limit has NOT been breached.
        """
        if self._consecutive_losses >= self.max_consecutive_losses:
            return False
        return True

    def record_trade_result(self, pnl: float) -> None:
        """Record a realised trade outcome (call on every closed trade).

        Losses increment the consecutive-loss counter; any non-loss resets it.
        """
        if pnl is None:
            return
        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.max_consecutive_losses:
                logger.warning(
                    "Max consecutive losses (%d) reached - entries blocked "
                    "until the daily reset",
                    self.max_consecutive_losses,
                )
        else:
            self._consecutive_losses = 0

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def increment_entries_today(self) -> None:
        """Increment the daily entry counter."""
        self._entries_today += 1

    def reset_daily_counter(self) -> None:
        """Reset the daily entry counter (call at start of new day)."""
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_trade_date != today_str:
            self._entries_today = 0
            self._last_trade_date = today_str


class KillSwitch:
    """Emergency kill switch that blocks new entries under adverse conditions."""

    def __init__(self, max_spread: float | None = None, max_slippage: float | None = None):
        self._active: bool = False
        self._reasons: list[str] = []
        self.max_spread = max_spread
        self.max_slippage = max_slippage

    @property
    def active(self) -> bool:
        """Whether the kill switch is currently active."""
        return self._active

    @property
    def reasons(self) -> list[str]:
        """List of reasons why the kill switch was activated."""
        return list(self._reasons)

    def activate(self, reason: str) -> None:
        """Activate the kill switch with a reason."""
        self._active = True
        self._reasons.append(reason)
        logger.error("[KILL SWITCH ACTIVATED] %s", reason)

    def deactivate(self) -> None:
        """Deactivate the kill switch."""
        self._active = False
        self._reasons.clear()
        logger.info("[KILL SWITCH DEACTIVATED]")

    def check_and_block(
        self,
        risk_limits: RiskLimits,
        instrument_metadata: InstrumentMetadata,
        current_equity: float = 0.0,
        spread: Optional[float] = None,
        slippage: Optional[float] = None,
        data_fresh: bool = True,
        metadata_verified: bool = True,
        stale_data: bool = False,
        position_agreement: bool = True,
    ) -> bool:
        """Run all kill-switch condition checks. Blocks if any condition triggers.

        Returns:
            True if new entries are BLOCKED, False if trading is allowed.
        """
        blocked = False

        # 1. Daily or weekly risk limit reached
        if not risk_limits.check_daily_loss_limit(current_equity=current_equity):
            self.activate("daily loss limit reached")
            blocked = True

        if not risk_limits.check_weekly_drawdown_limit(current_equity=current_equity):
            self.activate("weekly drawdown limit reached")
            blocked = True

        # 2. Market data is stale or invalid
        if stale_data:
            self.activate("stale market data")
            blocked = True

        # 3. Instrument metadata is missing or unverified
        if not metadata_verified or not instrument_metadata.is_verified:
            self.activate("instrument metadata unverified")
            blocked = True

        # 4. Spread exceeds limit
        if self.max_spread is not None and spread is not None and spread > self.max_spread:
            self.activate(f"spread {spread} exceeds max {self.max_spread}")
            blocked = True

        # 5. Slippage exceeds limit
        if self.max_slippage is not None and slippage is not None and slippage > self.max_slippage:
            self.activate(f"slippage {slippage} exceeds max {self.max_slippage}")
            blocked = True

        # 6. Local and broker position state disagree
        if not position_agreement:
            self.activate("local/broker position disagreement")
            blocked = True

        if blocked:
            self._active = True

        return blocked
