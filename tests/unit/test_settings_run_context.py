"""Unit tests for build_local_run_context (default today vs explicit run_date)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from src.settings import build_local_run_context


def test_build_local_run_context_defaults_to_today() -> None:
    """Without run_date, run_date equals today's date (frozen wall clock)."""
    fixed_now = datetime(2024, 6, 1, 12, 30, 45)
    with patch("src.settings.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        ctx = build_local_run_context()

    assert ctx.run_date == date(2024, 6, 1)
    assert ctx.run_id == "local-20240601-123045"


def test_build_local_run_context_with_explicit_run_date() -> None:
    """Explicit run_date is kept; run_id still comes from wall clock (new run)."""
    fixed_now = datetime(2024, 6, 1, 12, 30, 45)
    with patch("src.settings.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        ctx = build_local_run_context(run_date=date(2020, 1, 15))

    assert ctx.run_date == date(2020, 1, 15)
    assert ctx.run_id == "local-20240601-123045"
