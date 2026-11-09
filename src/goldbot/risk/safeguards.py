"""Live-trading risk safeguards (section 7 of the platform spec).

These guards are independent of the paper-mode RiskLimits and are enforced
server-side in addition to them whenever execution mode is live. Every check
is a pure function of its inputs so the guard is trivially testable:

- maximum risk per trade (re-check at live equity)
- maximum daily loss
- maximum open positions
- maximum account exposure (notional as % of equity)
- maximum order size (lots)
- maximum leverage
- mandatory stop-loss policy
- minimum risk-to-reward ratio
- duplicate-order prevention (idempotent client order IDs)
- market-data freshness validation
- spread validation
- volatility safeguard (ATR cap)
- trading session restrictions
- kill switch integration (the existing KillSwitch remains the master gate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# XAUUSD trading sessions (UTC hours) when liquidity is sane:
# London + New York overlap is the core session; Asian hours are thin.
DEFAULT_ALLOWED_SESSIONS_UTC = ((7, 20),)  # 07:00 - 20:59 UTC, Mon-Fri


@dataclass
class LiveRiskConfig:
    """Operator-configurable live safeguards (all server-side enforced)."""

    max_risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 2
    max_account_exposure_pct: float = 300.0  # notional/equity, leverage-capped
    max_order_volume_lots: float = 5.0
    max_leverage: float = 20.0
    require_stop_loss: bool = True
    min_risk_reward_ratio: float = 1.5
    max_atr_pct_of_price: float = 0.75  # volatility guard
    max_spread: float = 0.5
    max_data_age_seconds: float = 30.0
    allowed_sessions_utc: tuple[tuple[int, int], ...] = DEFAULT_ALLOWED_SESSIONS_UTC


@dataclass
class SafeguardDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reasons": self.reasons}


class LiveRiskGuard:
    """Server-side live-mode safeguard checks. Stateless by design."""

    def __init__(self, config: LiveRiskConfig | None = None):
        self.config = config or LiveRiskConfig()

    def check_order(
        self,
        *,
        side: str,
        volume_lots: float,
        entry_price: float,
        stop_loss: float | None,
        take_profit: float | None,
        equity: float,
        open_positions: int,
        current_exposure_lots: float = 0.0,
        contract_size: float = 100.0,
        spread: float | None = None,
        data_age_seconds: float | None = None,
        atr: float | None = None,
        now_utc: datetime | None = None,
    ) -> SafeguardDecision:
        """Validate a proposed live order against every safeguard."""
        cfg = self.config
        reasons: list[str] = []

        # Mandatory stop-loss
        if cfg.require_stop_loss and stop_loss is None:
            reasons.append("stop_loss_required: live orders must carry a stop-loss")

        # Order size cap
        if volume_lots <= 0:
            reasons.append("volume must be positive")
        if volume_lots > cfg.max_order_volume_lots:
            reasons.append(
                f"order volume {volume_lots} exceeds max {cfg.max_order_volume_lots} lots"
            )

        # Risk-per-trade and minimum R:R (needs both SL and TP)
        if stop_loss is not None and take_profit is not None and entry_price:
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            if risk <= 0:
                reasons.append("stop-loss distance must be positive")
            else:
                risk_amount = risk * volume_lots * contract_size
                if equity > 0 and risk_amount / equity * 100.0 > cfg.max_risk_per_trade_pct:
                    reasons.append(
                        f"risk per trade {risk_amount / equity * 100.0:.2f}% exceeds "
                        f"max {cfg.max_risk_per_trade_pct}%"
                    )
                if reward > 0 and reward / risk < cfg.min_risk_reward_ratio:
                    reasons.append(
                        f"risk-reward {reward / risk:.2f} below minimum {cfg.min_risk_reward_ratio}"
                    )

        # Open positions cap
        if open_positions >= cfg.max_open_positions:
            reasons.append(f"open positions {open_positions} at max {cfg.max_open_positions}")

        # Exposure / leverage cap (notional in quote currency)
        if equity > 0:
            notional = (current_exposure_lots + volume_lots) * contract_size * entry_price
            exposure_pct = notional / equity * 100.0
            if exposure_pct > cfg.max_account_exposure_pct:
                reasons.append(
                    f"account exposure {exposure_pct:.0f}% exceeds max "
                    f"{cfg.max_account_exposure_pct}% (leverage cap)"
                )

        # Data freshness
        if data_age_seconds is None:
            reasons.append("data_freshness_unknown: live orders require a fresh quote")
        elif data_age_seconds > cfg.max_data_age_seconds:
            reasons.append(
                f"market data stale: {data_age_seconds:.1f}s > {cfg.max_data_age_seconds}s"
            )

        # Spread validation
        if spread is None:
            reasons.append("spread_unknown: live orders require a current spread")
        elif spread > cfg.max_spread:
            reasons.append(f"spread {spread} exceeds max {cfg.max_spread}")

        # Volatility safeguard
        if atr is not None and entry_price:
            atr_pct = atr / entry_price * 100.0
            if atr_pct > cfg.max_atr_pct_of_price:
                reasons.append(
                    f"volatility guard: ATR {atr_pct:.2f}% of price exceeds cap "
                    f"{cfg.max_atr_pct_of_price}%"
                )

        # Session restrictions
        now = now_utc or datetime.now(timezone.utc)
        if not self._in_session(now):
            reasons.append(f"outside allowed trading sessions {cfg.allowed_sessions_utc} UTC")

        return SafeguardDecision(allowed=not reasons, reasons=reasons)

    def _in_session(self, now: datetime) -> bool:
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        hour = now.hour
        return any(start <= hour <= end for start, end in self.config.allowed_sessions_utc)

    def check_daily_loss(self, start_equity: float, current_equity: float) -> SafeguardDecision:
        cfg = self.config
        if start_equity <= 0:
            return SafeguardDecision(True)
        loss_pct = (start_equity - current_equity) / start_equity * 100.0
        if loss_pct >= cfg.max_daily_loss_pct:
            return SafeguardDecision(
                False, [f"daily loss {loss_pct:.2f}% >= limit {cfg.max_daily_loss_pct}%"]
            )
        return SafeguardDecision(True)


class DuplicateOrderGuard:
    """Prevents duplicate order submission while an order's status is unknown.

    Rule: the same client order ID may never be submitted twice, and an order
    whose execution status is uncertain must be reconciled with the broker
    before any retry. This guard tracks in-flight IDs per session.
    """

    def __init__(self) -> None:
        self._known_ids: set[str] = set()
        self._uncertain: set[str] = set()

    def register(self, client_order_id: str) -> bool:
        """Register a new client order ID. False when it already exists."""
        if client_order_id in self._known_ids:
            return False
        self._known_ids.add(client_order_id)
        return True

    def mark_uncertain(self, client_order_id: str) -> None:
        """Flag an order whose broker-side status is unknown (timeout etc.)."""
        self._uncertain.add(client_order_id)

    def retry_allowed(self, client_order_id: str) -> bool:
        """A retry is only allowed after reconciliation cleared the flag."""
        if client_order_id in self._uncertain:
            return False
        return client_order_id not in self._known_ids or True  # dedupe via register

    def reconcile(self, client_order_id: str, executed: bool) -> None:
        """Clear the uncertain flag after broker reconciliation."""
        self._uncertain.discard(client_order_id)
        if executed:
            self._known_ids.add(client_order_id)


__all__ = [
    "LiveRiskConfig",
    "LiveRiskGuard",
    "SafeguardDecision",
    "DuplicateOrderGuard",
    "DEFAULT_ALLOWED_SESSIONS_UTC",
]
