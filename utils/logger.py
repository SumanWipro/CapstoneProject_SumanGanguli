"""
utils/logger.py
===============
Centralized structured JSON logger for the Loan Approval System.

Responsibilities:
- Configure structlog with JSON rendering for production
- Configure structlog with console rendering for development
- Expose get_logger(name) factory used by every module

Design decision: structlog is chosen over the stdlib logging module because
it produces machine-parseable JSON by default, supports bound context
(request_id, case_id), and integrates naturally with async FastAPI.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from config.settings import get_settings


# ---------------------------------------------------------------------------
# Internal setup — called once at import time
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    """
    Configure structlog processors and stdlib logging integration.

    JSON format is used when LOG_FORMAT=json (production default).
    Console format is used when LOG_FORMAT=console (local development).
    """
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


_configure_logging()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def get_logger(name: str, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """
    Return a named, optionally pre-bound structured logger.

    Args:
        name: Typically __name__ of the calling module.
        **initial_values: Key-value pairs permanently bound to every log
                          record emitted by this logger instance.

    Returns:
        A structlog BoundLogger instance.

    Usage:
        log = get_logger(__name__, component="profile_agent")
        log.info("validation_complete", applicant_id="A001", valid=True)
    """
    logger = structlog.get_logger(name)
    if initial_values:
        logger = logger.bind(**initial_values)
    return logger
