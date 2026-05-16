from __future__ import annotations

import logging
import sys

import structlog


def setup_logging() -> None:
    """Configure structlog for logging based on server config.

    Reads configuration from config/default/server.yaml:
    - server.observability.logging.enabled: Enable/disable logging
    - server.observability.logging.level: Log level (DEBUG, INFO, WARNING, ERROR)
    - server.observability.logging.format: Output format (json or console)

    Log format includes:
    - timestamp: ISO 8601 format
    - level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    - event: Log event name
    - request_id: Request correlation ID (from context)
    - Additional contextual fields
    """
    from havocforge.config import get_config_manager

    cm = get_config_manager()
    server_cfg = cm.get_root("server")

    try:
        log_enabled = server_cfg.observability.logging.enabled  # type: ignore
        log_level_str = server_cfg.observability.logging.level.upper()  # type: ignore
        log_format = server_cfg.observability.logging.format.lower()  # type: ignore
    except (AttributeError, TypeError):
        log_enabled = True
        log_level_str = "INFO"
        log_format = "json"

    if not log_enabled:
        logging.disable(logging.CRITICAL)
        return

    log_level = getattr(logging, log_level_str, logging.INFO)

    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()  # type: ignore[assignment]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Optional logger name (e.g., module name).

    Returns:
        structlog.BoundLogger: Configured logger instance.
    """
    return structlog.get_logger(name)


logger = get_logger(__name__)
