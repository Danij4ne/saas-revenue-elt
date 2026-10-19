"""Logging setup for the ELT process (entrypoint config; libraries only log)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.settings import AppSettings


def _load_settings() -> AppSettings:
    """Import get_settings lazily to avoid a settings <-> logging cycle."""
    from src.settings import get_settings

    return get_settings()


_CONSOLE_HANDLER_NAME = "saas_elt_console"
_FILE_HANDLER_NAME = "saas_elt_file"
_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | "
    "run_id=%(run_id)s | run_date=%(run_date)s | %(message)s"
)


class _RunContextDefaults(logging.Filter):
    """Fill run_id / run_date on records that did not go through get_run_logger.

    Without this, ``%(run_id)s`` in the format raises KeyError for library loggers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = "-"
        if not hasattr(record, "run_date"):
            record.run_date = "-"
        return True


def _resolve_log_level(explicit_level: str | None) -> int:
    """Resolve log level: explicit arg > LOG_LEVEL env > settings > INFO."""
    if explicit_level is not None:
        return getattr(logging, explicit_level.upper(), logging.INFO)

    env_level = os.getenv("LOG_LEVEL")
    if env_level:
        return getattr(logging, env_level.upper(), logging.INFO)

    settings_level = _load_settings().logging.level
    return getattr(logging, settings_level.upper(), logging.INFO)


def _resolve_log_file(explicit_file: Path | str | None) -> Path | None:
    """Resolve optional log file: explicit arg > settings.runtime.logging.file."""
    if explicit_file is not None:
        return Path(explicit_file).expanduser().resolve()
    return _load_settings().logging.file


def setup_logging(
    level: str | None = None,
    log_file: Path | str | None = None,
) -> None:
    """Configure root logger once (stdout always, file optional).

    Called by the process entrypoint (CLI today; Airflow/Cloud Run tomorrow).
    Libraries only use ``logging.getLogger(__name__)`` and propagate here.
    """
    log_level = _resolve_log_level(level)
    resolved_file = _resolve_log_file(log_file)
    settings = _load_settings()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    formatter = logging.Formatter(_LOG_FORMAT)

    has_console = any(
        getattr(handler, "name", "") == _CONSOLE_HANDLER_NAME
        for handler in root_logger.handlers
    )
    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(_RunContextDefaults())
        console_handler.name = _CONSOLE_HANDLER_NAME
        root_logger.addHandler(console_handler)

    if resolved_file is None:
        return

    has_file = any(
        getattr(handler, "name", "") == _FILE_HANDLER_NAME
        for handler in root_logger.handlers
    )
    if has_file:
        return

    resolved_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        resolved_file,
        maxBytes=settings.logging.max_bytes,
        backupCount=settings.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RunContextDefaults())
    file_handler.name = _FILE_HANDLER_NAME
    root_logger.addHandler(file_handler)


def get_run_logger(
    name: str,
    run_id: str,
    run_date: object,
) -> logging.LoggerAdapter[logging.Logger]:
    """Return a logger that carries run_id / run_date on every record."""
    base_logger = logging.getLogger(name)
    return logging.LoggerAdapter(
        base_logger,
        {"run_id": run_id, "run_date": str(run_date)},
    )
