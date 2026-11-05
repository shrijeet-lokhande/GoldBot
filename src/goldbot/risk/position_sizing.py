"""GoldBot position sizing - instrument-aware risk-based sizing."""

from __future__ import annotations

import math

from goldbot.core.exceptions import MetadataError, RiskError
from goldbot.core.models import InstrumentMetadata, SignalDirection


def calculate_position_size(
    equity: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_price: float,
    instrument: InstrumentMetadata,
    side: SignalDirection,
    current_position_lots: float = 0.0,
) -> float:
    """Calculate position size based on risk per trade.

    Uses the risk-based position sizing formula:
        risk_budget = account_equity * risk_per_trade_pct / 100
        cash_risk_per_unit = stop_distance * value_per_lot
        raw_lots = risk_budget / cash_risk_per_unit
        order_lots = round_down_to_broker_volume_step(raw_lots)

    Args:
        equity: Current account equity.
        risk_per_trade_pct: Risk as percentage of equity (e.g. 0.25 for 0.25%).
        entry_price: Entry price for the trade.
        stop_price: Stop loss price.
        instrument: Verified instrument metadata.
        side: Signal direction (long or short).
        current_position_lots: Existing position size in lots (for anti-averaging).

    Returns:
        Position size in lots (rounded to broker's volume step).

    Raises:
        MetadataError: If instrument metadata is missing or unverified.
        RiskError: If the calculated size is invalid or below minimum.
    """
    # --- Validate metadata ---
    if not instrument.verified:
        raise MetadataError(
            "Instrument metadata must be verified before position sizing."
        )

    required_fields = [
        "contract_size", "tick_size", "tick_value", "volume_step",
        "min_volume", "max_volume",
    ]
    missing = [f for f in required_fields if getattr(instrument, f) is None]
    if missing:
        raise MetadataError(
            f"Missing required instrument metadata fields: {missing}"
        )

    # --- Determine if long or short ---
    side_str = side.lower() if isinstance(side, str) else str(side)
    is_long = side_str in ("long", "buy")

    # --- Calculate stop distance in price units ---
    if is_long:
        # Long: stop is below entry, so stop_distance = entry - stop
        stop_distance = entry_price - stop_price
        if stop_distance <= 0:
            raise RiskError("Stop distance must be positive for long positions.")
    else:
        # Short: stop is above entry, so stop_distance = stop - entry
        stop_distance = stop_price - entry_price
        if stop_distance <= 0:
            raise RiskError("Stop distance must be positive for short positions.")

    # --- Calculate value per unit (per lot) ---
    # For a gold CFD or spot: P&L per 1.0 price-unit move per lot = contract_size
    # (e.g. 1 lot = 100 oz => $1 move = $100). tick_value/tick_size are
    # informational and must be consistent: tick_value = tick_size * contract_size.
    value_per_lot = instrument.contract_size

    cash_risk_per_unit = stop_distance * value_per_lot

    if cash_risk_per_unit <= 0:
        raise RiskError("Calculated cash risk per unit is non-positive.")

    # --- Calculate raw lots ---
    risk_budget = equity * (risk_per_trade_pct / 100.0)
    raw_lots = risk_budget / cash_risk_per_unit

    # --- Round down to broker volume step ---
    volume_step = instrument.volume_step
    min_volume = instrument.min_volume
    max_volume = instrument.max_volume

    if volume_step is None or volume_step <= 0:
        raise RiskError("Instrument volume step is not configured.")

    # Round down to nearest volume step using floor division
    rounded_lots = math.floor(raw_lots / volume_step) * volume_step

    # Enforce min/max volume constraints
    if rounded_lots < min_volume:
        raise RiskError(
            f"Rounded lot size {rounded_lots} is below minimum volume "
            f"{min_volume}. Trade rejected."
        )

    if max_volume is not None and rounded_lots > max_volume:
        rounded_lots = max_volume

    if rounded_lots <= 0:
        raise RiskError(
            f"Calculated position size {rounded_lots} lots is too small "
            f"(below minimum). Trade rejected."
        )

    return rounded_lots
