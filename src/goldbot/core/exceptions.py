"""GoldBot custom exceptions."""

from __future__ import annotations


class GoldBotError(Exception):
    """Base exception for all GoldBot errors."""

    pass


class ConfigurationError(GoldBotError):
    """Raised when configuration is invalid or missing."""

    pass


class DataError(GoldBotError):
    """Raised when market data is invalid or unavailable."""

    pass


class IndicatorError(GoldBotError):
    """Raised when indicator calculation fails."""

    pass


class RiskError(GoldBotError):
    """Raised when a trade violates risk limits."""

    pass


class ExecutionError(GoldBotError):
    """Raised when order execution fails."""

    pass


class MetadataError(GoldBotError):
    """Raised when instrument metadata is missing or unverified."""

    pass


class StaleDataError(GoldBotError):
    """Raised when market data is stale."""

    pass


class KillSwitchError(GoldBotError):
    """Raised when the kill switch is active."""

    pass


class DuplicateOrderError(GoldBotError):
    """Raised when a duplicate order is detected."""


class OrderRejectedError(GoldBotError):
    """Raised when an order is rejected by the broker."""


class OrderTimeoutError(GoldBotError):
    """Raised when an order times out."""

    pass
