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
ENABLE_DB_LOGGING: "true" to enable database logging (default: false)
DB_LOG_LEVEL: Log level for database handler (default: INFO)
"""

import logging
import os
import socket
from logging.handlers import RotatingFileHandler
from typing import Optional

try:
    # `python-json-logger` is lightweight and already whitelisted in requirements.
    from pythonjsonlogger import jsonlogger  # type: ignore
except ImportError:  # pragma: no cover – fallback for runtime without dep
    jsonlogger = None  # type: ignore

# Global reference to database log handler
_db_log_handler: Optional['DatabaseLogHandler'] = None


def setup_logging(db_client=None, source_type: str = "orchestrator_gpu"):
    """Configure root logger for the orchestrator.

    This should be called once as early as possible in the main entry
    point before any other modules configure logging.
    
    Args:
        db_client: Optional DatabaseClient instance for centralized logging
        source_type: Type of source for database logs ('orchestrator_gpu' or 'orchestrator_api')
    
    Returns:
        DatabaseLogHandler instance if database logging is enabled, otherwise None
    """
    global _db_log_handler

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
    
    # Add database logging handler if enabled and db_client provided
    enable_db_logging = os.getenv("ENABLE_DB_LOGGING", "false").lower() == "true"
    if enable_db_logging and db_client:
        try:
            # Try relative import first (when run as package)
            try:
                from .database_log_handler import DatabaseLogHandler
            except ImportError:
                # Fall back to absolute import (when run as script)
                from database_log_handler import DatabaseLogHandler
            
            # Generate source ID (use instance ID if set, otherwise hostname)
            source_id = os.getenv(
                "ORCHESTRATOR_INSTANCE_ID",
                f"{source_type}-{socket.gethostname()}"
            )
            
            # Get database log level
            db_log_level_str = os.getenv("DB_LOG_LEVEL", "INFO").upper()
            db_log_level = getattr(logging, db_log_level_str, logging.INFO)
            
            # Create database handler
            _db_log_handler = DatabaseLogHandler(
                supabase_client=db_client.supabase,
                source_type=source_type,
                source_id=source_id,
                batch_size=int(os.getenv("DB_LOG_BATCH_SIZE", "50")),
                flush_interval=float(os.getenv("DB_LOG_FLUSH_INTERVAL", "5.0")),
                min_level=db_log_level
            )
            _db_log_handler.setFormatter(_build_formatter("json"))
            
            # Add to root logger
            logging.getLogger().addHandler(_db_log_handler)
            
            logger = logging.getLogger(__name__)
            logger.info(f"✅ Database logging enabled: {source_id} -> Supabase")
            
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"❌ CRITICAL: Database logging initialization FAILED: {e}")
            logger.error(f"   Exception type: {type(e).__name__}")
            logger.error(f"   This will cause LOSS OF OBSERVABILITY")
            
            # Save error to file for post-mortem
            try:
                import traceback
                from datetime import datetime
                error_file = "db_logging_errors.log"
                with open(error_file, "a") as f:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"Database Logging Failure: {datetime.now().isoformat()}\n")
                    f.write(f"Error: {e}\n")
                    f.write(f"{'='*80}\n")
                    f.write(traceback.format_exc())
                    f.write(f"\n")
                logger.error(f"   Error details saved to: {error_file}")
            except Exception as save_error:
                logger.error(f"   Could not save error to file: {save_error}")
            
            _db_log_handler = None
            
            # Check if we should fail fast
            if os.getenv("DB_LOGGING_REQUIRED", "false").lower() == "true":
                logger.error("   DB_LOGGING_REQUIRED=true, orchestrator will exit")
                raise RuntimeError(f"Database logging is required but failed to initialize: {e}")
    
    return _db_log_handler


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
        "gpu_orchestrator",
        "gpu_orchestrator.control_loop", 
        "gpu_orchestrator.database",
        "gpu_orchestrator.runpod_client",
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

def get_db_log_handler():
    """Get the global database log handler instance."""
    return _db_log_handler


def set_current_cycle(cycle_number: int):
    """Set current cycle number in database log handler for context tracking."""
    if _db_log_handler:
        _db_log_handler.set_current_cycle(cycle_number)


def set_current_worker(worker_id: Optional[str]):
    """Set current worker ID in database log handler for context tracking."""
    if _db_log_handler:
        _db_log_handler.set_current_worker(worker_id)


def set_current_task(task_id: Optional[str]):
    """Set current task ID in database log handler for context tracking."""
    if _db_log_handler:
        _db_log_handler.set_current_task(task_id)


def get_db_logging_stats():
    """Get statistics from database log handler."""
    if _db_log_handler:
        return _db_log_handler.get_stats()
    return None


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