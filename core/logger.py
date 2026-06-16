"""
core/logger.py — WALL-E AI structured logger
Outputs colored text in development, JSON in production.
Replaces all raw print() calls across the codebase.
Created by K.Astra and its members.
"""

import logging
import json
import sys
import time
from typing import Any

from core.config import settings


class _ColorFormatter(logging.Formatter):
    """Pretty colored logs for local development."""
    COLORS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        ts = self.formatTime(record, "%H:%M:%S")
        tag = f"[{record.name}]"
        return f"{color}{ts} {tag:<22} {record.getMessage()}{self.RESET}"


class _JsonFormatter(logging.Formatter):
    """Machine-readable JSON logs for production / Railway / Render."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":      time.time(),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def get_logger(name: str) -> logging.Logger:
    """
    Returns a named logger configured for the current environment.
    Usage:
        from core.logger import get_logger
        log = get_logger(__name__)
        log.info("Pipeline started")
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured — avoid double-adding handlers

    logger.setLevel(logging.DEBUG if not settings.is_production else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _JsonFormatter() if settings.is_production else _ColorFormatter()
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


# ── Root app logger (used for startup/shutdown messages) ──────────────────────
log = get_logger("walle")
