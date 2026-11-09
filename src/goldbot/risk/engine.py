"""GoldBot risk engine - the final authority before trade execution.

The risk engine is independent of strategy code. It receives a proposed
Signal from the strategy engine and must approve, modify, or reject it.

Every proposed trade MUST pass through this engine before execution.
"""

from __future__ import annotations

from goldbot.core.exceptions import (
    MetadataError,
    RiskError,
)
from goldbot.core.models import Candle, InstrumentMetadata, Signal
from goldbot.risk.limits import KillSwitch, RiskLimits
from goldbot.risk.position_sizing import calculate_position_size


class RiskEngine:
    """Independent risk engine that evaluates every proposed trade.

    The strategy engine proposes a signal; the risk engine approves,
    modifies, or rejects it. This ensures a clear separation of concerns
    and prevents strategy code from bypassing risk controls.
    """

    def __init__(
        self,
        risk_limits: RiskLimits,
        kill_switch: KillSwitch,
        instrument_metadata: InstrumentMetadata,
        equity: float,
        max_spread: float | None = None,
        max_slippage: float | None = None,
    ):
        self.risk_limits = risk_limits
        self.kill_switch = kill_switch
        self.instrument_metadata = instrument_metadata
        self.equity = equity

        # Apply user-configured max spread/slippage if not set in risk_limits
        if max_spread is not None:
            self.risk_limits.max_spread = max_spread
        if max_slippage is not None:
            self.risk_limits.max_slippage = max_slippage

    def evaluate_signal(
        self,
        signal: Signal,
        entry_price: float,
        stop_price: float,
        current_candle: Candle | None = None,
        realised_pnl: float = 0.0,
        unrealised_pnl: float = 0.0,
        current_positions: int = 0,
        current_equity: float | None = None,
    ) -> dict:
        """Evaluate a proposed signal and return a risk decision.

        The decision one of:
            - "APPROVE": signal passes all checks, size is calculated
            - "REJECT": signal is rejected
            - "MODIFY": signal can be modified (e.g. position size reduced)

        Args:
            signal: The proposed Signal from the strategy engine.
            entry_price: The proposed entry price.
            stop_price: The proposed stop loss price.
            current_candle: The candle that triggered the signal (optional).
            realised_pnl: Realised P&L (e.g. from closed positions).
            unrealised_pnl: Unrealised P&L from open positions.
            current_positions: Number of currently open positions.
            current_equity: Live account equity; falls back to the
                constructor value when not supplied.

        Returns:
            A dict with keys:
                - "decision": "approve" | "reject" | "modify"
                - "reason": Description of the decision
                - "position_size": Calculated position size in lots (if approved)
                - "kill_switched": Whether the kill switch was activated
        """

        def reject(reason: str, kill_switched: bool = False) -> dict:
            return {
                "decision": "reject",
                "reason": reason,
                "position_size": 0.0,
                "kill_switched": kill_switched,
            }

        equity = current_equity if current_equity is not None else self.equity

        # --- Step 1: Kill switch check ---
        if self.kill_switch.active:
            return {
                "decision": "reject",
                "reason": "kill switch is active",
                "position_size": 0.0,
                "kill_switched": True,
            }

        # --- Step 2: Instrument metadata verification ---
        if not self.instrument_metadata.verified:
            return reject("instrument metadata must be verified before trading")

        # --- Step 3: Daily loss limit ---
        if not self.risk_limits.check_daily_loss_limit(current_equity=equity):
            return {
                "decision": "reject",
                "reason": f"daily loss limit ({self.risk_limits.daily_loss_limit_pct}%) reached",
                "position_size": 0.0,
                "kill_switched": False,
            }

        # --- Step 4: Weekly drawdown limit ---
        if not self.risk_limits.check_weekly_drawdown_limit(current_equity=equity):
            weekly_pct = self.risk_limits.weekly_drawdown_limit_pct
            reason = f"weekly drawdown limit ({weekly_pct}%) reached"
            return {
                "decision": "reject",
                "reason": reason,
                "position_size": 0.0,
                "kill_switched": False,
            }

        # --- Step 5: Max consecutive losses check ---
        if not self.risk_limits.check_max_consecutive_losses():
            return reject(
                f"maximum consecutive losses ({self.risk_limits.max_consecutive_losses}) reached"
            )

        # --- Step 6: Max open positions check ---
        if not self.risk_limits.check_max_open_positions(current_positions=current_positions):
            return reject(f"maximum open positions ({self.risk_limits.max_open_positions}) reached")

        # --- Step 7: Max entries per day check ---
        if not self.risk_limits.check_max_entries_per_day():
            return reject(
                f"maximum entries per day ({self.risk_limits.max_entries_per_day}) reached"
            )

        # --- Step 8: Position sizing calculation ---
        try:
            position_size = calculate_position_size(
                equity=equity,
                risk_per_trade_pct=self.risk_limits.risk_per_trade_pct,
                entry_price=entry_price,
                stop_price=stop_price,
                instrument=self.instrument_metadata,
                side=signal.direction,
                current_position_lots=current_positions,
            )
        except (MetadataError, RiskError) as e:
            return reject(f"position sizing failed: {e}")

        # --- Step 9: Return approval with position size ---
        # Ensure position size is at least minimum round lot
        if position_size <= 0:
            return reject("position size calculated as zero or negative")

        return {
            "decision": "approve",
            "reason": "signal passed all risk checks",
            "position_size": position_size,
            "kill_switched": False,
        }
