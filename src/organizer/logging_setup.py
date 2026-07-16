"""Centralized logging configuration."""

from __future__ import annotations

import logging

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once, with a consistent structured format."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # httpx is noisy at INFO (logs every Telegram poll request).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _CONFIGURED = True
