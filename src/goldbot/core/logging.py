"""GoldBot structured logging setup."""

from __future__ import annotations

import logging
import sys

DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] %(filename)s:%(lineno)d - %(message)s"
)
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def setup_logging(
    level: int = DEFAULT_LOG_LEVEL,
    format_string: str = DEFAULT_LOG_FORMAT,
    handler: logging.Handler | None = None,
) -> logging.Logger:
    """Configure the root GoldBot logger.

    Args:
        level: Logging level (e.g. logging.INFO, logging.DEBUG).
        format_string: Format string for log messages.
        handler: Optional custom handler; if None, a stderr handler is used.

    Returns:
        The root logger instance.
    """
    root = logging.getLogger("goldbot")
    root.setLevel(level)

    # Avoid adding duplicate handlers if called multiple times
    if not root.handlers:
        if handler is None:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(level)
        formatter = logging.Formatter(format_string, datefmt=DATE_FORMAT)
        handler.setFormatter(formatter)
        root.addHandler(handler)

    # Ensure no propagation to parent loggers that might add duplicate output
    root.propagate = False

    return root


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for a GoldBot module."""
    return logging.getLogger(f"goldbot.{name}")
