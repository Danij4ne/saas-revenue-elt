"""Unit tests for logging setup policy (handlers, level, optional file)."""

from __future__ import annotations

import logging
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from src.logging_config import (
    _CONSOLE_HANDLER_NAME,
    _FILE_HANDLER_NAME,
    _LOG_FORMAT,
    _RunContextDefaults,
    get_run_logger,
    setup_logging,
)
from src.settings import AppSettings
from tests.conftest import (
    _make_fake_env,
    _make_fake_runtime,
    _make_min_raw_contract,
)


def _fake_settings(tmp_path: Path) -> AppSettings:
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(exist_ok=True)
    return AppSettings(
        project_root=tmp_path,
        env_file=None,
        raw_contract_file=tmp_path / "raw_contract.yaml",
        runtime_config_file=tmp_path / "runtime.yaml",
        local_raw_dir=sources_dir,
        env=_make_fake_env(),
        raw_contract=_make_min_raw_contract(local_base_dir=sources_dir),
        runtime_config=_make_fake_runtime(),
    )


def _named_handlers(name: str) -> list[logging.Handler]:
    root = logging.getLogger()
    return [h for h in root.handlers if getattr(h, "name", "") == name]


def _remove_saas_elt_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "name", "") in {_CONSOLE_HANDLER_NAME, _FILE_HANDLER_NAME}:
            root.removeHandler(handler)
            handler.close()


@pytest.fixture(autouse=True)
def _isolate_root_logger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Fake settings + clean saas_elt handlers so tests stay deterministic."""
    settings = _fake_settings(tmp_path)
    monkeypatch.setattr("src.logging_config._load_settings", lambda: settings)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    _remove_saas_elt_handlers()
    yield
    _remove_saas_elt_handlers()


def test_setup_logging_adds_console_once() -> None:
    """Calling setup_logging twice must not duplicate the console handler."""
    setup_logging()
    setup_logging()

    assert len(_named_handlers(_CONSOLE_HANDLER_NAME)) == 1


def test_setup_logging_respects_log_level_env(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LOG_LEVEL=DEBUG must make debug records visible."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    setup_logging()

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("tests.logging_config").debug("debug-visible")

    assert "debug-visible" in caplog.text


def test_setup_logging_without_file_has_no_file_handler() -> None:
    """Default settings (file=None) must not attach a file handler."""
    setup_logging()

    assert _named_handlers(_FILE_HANDLER_NAME) == []
    assert len(_named_handlers(_CONSOLE_HANDLER_NAME)) == 1


def test_setup_logging_with_file_creates_rotating_handler(tmp_path: Path) -> None:
    """Explicit log_file must add a RotatingFileHandler and write records."""
    log_file = tmp_path / "logs" / "pipeline.log"
    setup_logging(log_file=log_file)

    file_handlers = _named_handlers(_FILE_HANDLER_NAME)
    assert len(file_handlers) == 1
    assert isinstance(file_handlers[0], RotatingFileHandler)

    logging.getLogger("tests.logging_config").info("written-to-file")
    for handler in file_handlers:
        handler.flush()

    assert log_file.exists()
    assert "written-to-file" in log_file.read_text(encoding="utf-8")


def test_log_format_includes_run_id(caplog: pytest.LogCaptureFixture) -> None:
    """get_run_logger extra must appear in the project formatter output."""
    setup_logging()
    handler = _named_handlers(_CONSOLE_HANDLER_NAME)[0]
    log = get_run_logger("t", "local-20260911-101010", date(2026, 9, 11))

    with caplog.at_level(logging.INFO):
        log.info("gcs upload ok")

    line = handler.format(caplog.records[-1])
    assert "run_id=local-20260911-101010" in line
    assert "run_date=2026-09-11" in line
    assert "gcs upload ok" in line


def test_log_format_without_adapter_uses_defaults() -> None:
    """Records without extra must format as run_id=- instead of raising KeyError."""
    record = logging.LogRecord(
        name="lib",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="from-library",
        args=(),
        exc_info=None,
    )

    assert not hasattr(record, "run_id")
    assert _RunContextDefaults().filter(record) is True
    line = logging.Formatter(_LOG_FORMAT).format(record)

    assert "run_id=-" in line
    assert "run_date=-" in line
    assert "from-library" in line
