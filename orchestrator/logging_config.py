"""Utility to configure logging for the orchestrator.

This centralises logging configuration so all modules share the same
settings and makes it easy to switch between plain-text and JSON logs
that are simple to parse by log aggregation systems.

Environment variables supported
--------------------------------
LOG_FORMAT: "json" (default) or "plain"
LOG_LEVEL:  Python logging level name (default: INFO)
LOG_FILE:   Path to write logs to a rotating file (default: ./orchestrator.log).
            Set to empty string to disable file logging.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

try:
    # `python-json-logger` is lightweight and already whitelisted in requirements.
    from pythonjsonlogger import jsonlogger  # type: ignore
except ImportError:  # pragma: no cover – fallback for runtime without dep
    jsonlogger = None  # type: ignore


def setup_logging():
    """Configure root logger for the orchestrator.

    This should be called once as early as possible in the main entry
    point before any other modules configure logging.
    """

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    log_format = os.getenv("LOG_FORMAT", "json").lower()

    handlers: list[logging.Handler] = []

    # Stream handler (stdout)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_build_formatter(log_format))
    handlers.append(stream_handler)

    # File handler with rotation - DEFAULT to creating logs
    log_file = os.getenv("LOG_FILE", "./orchestrator.log")  # Default to current directory
    if log_file:  # Empty string disables file logging
        # Ensure log directory exists
        import pathlib
        log_path = pathlib.Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
        file_handler.setFormatter(_build_formatter(log_format))
        handlers.append(file_handler)

    # Apply configuration atomically via basicConfig (only takes effect once)
    logging.basicConfig(level=log_level, handlers=handlers, force=True)
    
    # Suppress noisy HTTP request logs to focus on health and process information
    _configure_third_party_loggers()


def _configure_third_party_loggers():
    """Configure third-party library loggers to reduce noise."""
    
    # Suppress verbose HTTP request logging from httpx (used by Supabase client)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    # Suppress other noisy HTTP libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    
    # Suppress Supabase client verbose logs
    logging.getLogger("supabase").setLevel(logging.WARNING)
    logging.getLogger("postgrest").setLevel(logging.WARNING)
    
    # Keep our orchestrator logs at the configured level
    orchestrator_loggers = [
        "orchestrator",
        "orchestrator.control_loop", 
        "orchestrator.database",
        "orchestrator.runpod_client",
        "__main__"
    ]
    
    for logger_name in orchestrator_loggers:
        logger = logging.getLogger(logger_name)
        # Don't override if already explicitly set
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_formatter(log_format: str) -> logging.Formatter:  # pragma: no cover
    """Return a suitable Formatter instance for *log_format*."""

    if log_format == "json" and jsonlogger is not None:
        # Use JSON formatting – fields are flattened for easy parsing
        return jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")

    # Fallback to plain-text formatter identical to previous output
    return logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s") 