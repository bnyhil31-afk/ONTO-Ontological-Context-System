"""
core/logging.py

Structured logging for ONTO — stdlib only, no third-party dependencies.

In production mode (ONTO_LOG_FORMAT=json or ONTO_ENVIRONMENT=production),
emits newline-delimited JSON records suitable for ingestion by SIEM systems
(ELK, Splunk, Datadog, CloudWatch, etc.).

In development mode, emits human-readable text to stderr.

JSON record field names mirror the existing memory.record() audit trail fields
so that log correlation tools can join on shared keys (event, identity,
request_id).

Usage:
    from core.logging import onto_logger
    onto_logger.info("AUTH_SUCCESS", identity="operator", request_id="abc123")
    onto_logger.warning("CHAIN_INTEGRITY_WARNING", gap_count=2)
    onto_logger.error("POSTURE_CHECK_FAILED", detail=str(exc))

Plain English: This module writes structured log lines that monitoring systems
can parse. It never logs secrets — only event names, identifiers, and status.
"""

import json
import logging
import sys
import threading
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# LOG FORMAT CONFIGURATION
# Reads from the shared config lazily to avoid circular imports.
# Pattern mirrors core/ratelimit.py.
# ---------------------------------------------------------------------------

_config_cache = None
_config_lock = threading.Lock()


def _get_log_format() -> str:
    """
    Return the configured log format: 'json' or 'text'.
    Lazy-loads core.config to avoid circular imports.
    Defaults to 'json' in production, 'text' in development.
    """
    global _config_cache
    with _config_lock:
        if _config_cache is None:
            try:
                from core.config import config as _cfg
                _config_cache = _cfg
            except ImportError:
                return "text"
    cfg = _config_cache
    fmt = getattr(cfg, "LOG_FORMAT", None)
    if fmt in ("json", "text"):
        return fmt
    # Fallback: json in production, text elsewhere
    return "json" if getattr(cfg, "IS_PRODUCTION", False) else "text"


# ---------------------------------------------------------------------------
# JSON FORMATTER
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """
    Formats log records as newline-delimited JSON.
    Extra kwargs passed to onto_logger.info/warning/error are embedded
    directly in the JSON object alongside the standard fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        # Embed any extra fields attached to the record
        for key, value in record.__dict__.items():
            if key.startswith("_onto_"):
                obj[key[6:]] = value  # strip "_onto_" prefix
        return json.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# TEXT FORMATTER (development)
# ---------------------------------------------------------------------------

class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        extras = {
            k[6:]: v
            for k, v in record.__dict__.items()
            if k.startswith("_onto_")
        }
        extra_str = " ".join(f"{k}={v}" for k, v in extras.items())
        msg = record.getMessage()
        return f"[ONTO {ts}] {record.levelname}: {msg}" + (
            f"  {extra_str}" if extra_str else ""
        )


# ---------------------------------------------------------------------------
# ONTO LOGGER WRAPPER
# Provides a clean API: onto_logger.info("EVENT", key=value, ...)
# ---------------------------------------------------------------------------

class ONTOLogger:
    """
    Thin wrapper around a stdlib logging.Logger that:
    - Auto-selects JSON vs text format based on config
    - Accepts keyword arguments as structured fields in the log record
    - Never raises — logging failures must not crash the main process
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("onto")
        self._logger.setLevel(logging.DEBUG)
        self._handler: logging.Handler | None = None
        self._setup_lock = threading.Lock()

    def _ensure_handler(self) -> None:
        """Lazily attach the correct handler on first use."""
        with self._setup_lock:
            if self._handler is not None:
                return
            fmt = _get_log_format()
            handler = logging.StreamHandler(sys.stderr)
            if fmt == "json":
                handler.setFormatter(_JsonFormatter())
            else:
                handler.setFormatter(_TextFormatter())
            self._logger.addHandler(handler)
            self._handler = handler

    def _make_record(
        self,
        level: int,
        message: str,
        **kwargs: Any,
    ) -> None:
        try:
            self._ensure_handler()
            # Attach extra fields to the LogRecord via extra dict with
            # "_onto_" prefix to avoid collisions with stdlib fields.
            extra = {f"_onto_{k}": v for k, v in kwargs.items()}
            self._logger.log(level, message, extra=extra)
        except Exception:
            pass  # Never let logging crash the main process

    def debug(self, message: str, **kwargs: Any) -> None:
        self._make_record(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._make_record(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._make_record(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._make_record(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._make_record(logging.CRITICAL, message, **kwargs)

    def reconfigure(self) -> None:
        """
        Force the handler to be re-created on the next log call.
        Called by tests that change ONTO_LOG_FORMAT between test cases.
        """
        with self._setup_lock:
            if self._handler is not None:
                self._logger.removeHandler(self._handler)
                self._handler = None
        global _config_cache
        with _config_lock:
            _config_cache = None


# Single shared instance — import this everywhere
onto_logger = ONTOLogger()
