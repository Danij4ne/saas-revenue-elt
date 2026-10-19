"""Unit tests for the pre-load raw parquet gate (public API)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.settings import AppSettings
from src.validation.raw_validation import (
    RawValidationErrorCode,
    RawValidationFailedError,
    RawValidationReport,
    validate_raw_inputs,
    validate_raw_inputs_or_raise,
)


def _codes(report: RawValidationReport, table_name: str) -> set[RawValidationErrorCode]:
    result = next(r for r in report.table_results if r.table_name == table_name)
    return {issue.code for issue in result.issues}


def _write_empty_parquet(path: Path, column_names: list[str]) -> None:
    """Write a 0-row parquet with an explicit schema (pyarrow needs types)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(name, pa.string()) for name in column_names])
    table = pa.Table.from_pylist([], schema=schema)
    pq.write_table(table, path)


def test_missing_file_is_reported(settings: AppSettings) -> None:
    """No parquet on disk: FILE_NOT_FOUND and the table is not valid."""
    report = validate_raw_inputs(settings)

    assert RawValidationErrorCode.FILE_NOT_FOUND in _codes(report, "customers")
    result = next(r for r in report.table_results if r.table_name == "customers")
    assert result.is_valid is False
    assert report.all_valid is False


def test_unreadable_parquet_is_reported(settings: AppSettings) -> None:
    """Corrupt bytes: PARQUET_NOT_READABLE, not a raw pyarrow exception."""
    settings.raw_file_path("customers").write_bytes(b"not a parquet")

    report = validate_raw_inputs(settings)

    assert RawValidationErrorCode.PARQUET_NOT_READABLE in _codes(report, "customers")


def test_empty_parquet_is_reported(settings: AppSettings) -> None:
    """Zero rows with the contract columns: EMPTY_PARQUET."""
    contract = settings.raw_table("customers")
    _write_empty_parquet(settings.raw_file_path("customers"), contract.required_columns)

    report = validate_raw_inputs(settings)

    assert RawValidationErrorCode.EMPTY_PARQUET in _codes(report, "customers")


def test_missing_required_column_is_reported(settings: AppSettings) -> None:
    """One required column absent: MISSING_COLUMNS with that exact name."""
    contract = settings.raw_table("customers")
    missing = contract.required_columns[-1]
    partial = contract.required_columns[:-1]
    pq.write_table(
        pa.table({name: ["x"] for name in partial}),
        settings.raw_file_path("customers"),
    )

    report = validate_raw_inputs(settings)
    result = next(r for r in report.table_results if r.table_name == "customers")

    assert RawValidationErrorCode.MISSING_COLUMNS in _codes(report, "customers")
    assert result.missing_columns == [missing]


def test_empty_and_missing_column_reports_both_codes(settings: AppSettings) -> None:
    """No early-return between empty and schema: both contract codes land."""
    contract = settings.raw_table("customers")
    missing = contract.required_columns[-1]
    partial = contract.required_columns[:-1]
    _write_empty_parquet(settings.raw_file_path("customers"), partial)

    report = validate_raw_inputs(settings)
    result = next(r for r in report.table_results if r.table_name == "customers")

    assert _codes(report, "customers") == {
        RawValidationErrorCode.EMPTY_PARQUET,
        RawValidationErrorCode.MISSING_COLUMNS,
    }
    assert result.missing_columns == [missing]


def test_missing_raw_dir_is_reported(settings: AppSettings, tmp_path: Path) -> None:
    """Absent local_raw_dir: FILE_NOT_FOUND on every configured table."""
    missing_dir = tmp_path / "does-not-exist"
    settings = settings.model_copy(update={"local_raw_dir": missing_dir})

    report = validate_raw_inputs(settings)

    assert RawValidationErrorCode.FILE_NOT_FOUND in _codes(report, "customers")
    assert str(missing_dir) in str(
        next(
            issue.message for result in report.table_results for issue in result.issues
        )
    )
    assert report.all_valid is False


@pytest.mark.usefixtures("raw_sources")
def test_valid_inputs_pass(settings: AppSettings) -> None:
    """Happy path: every table valid, no issues."""
    report = validate_raw_inputs(settings)

    assert report.all_valid is True
    assert report.invalid_table_count == 0
    assert _codes(report, "customers") == set()


def test_or_raise_message_lists_every_invalid_table(settings: AppSettings) -> None:
    """Failure message names the table and error code without extra debugging."""
    with pytest.raises(RawValidationFailedError) as exc:
        validate_raw_inputs_or_raise(settings)

    assert "customers" in str(exc.value)
    assert RawValidationErrorCode.FILE_NOT_FOUND.value in str(exc.value)


@pytest.mark.usefixtures("raw_sources")
def test_or_raise_returns_report_when_valid(settings: AppSettings) -> None:
    """Valid inputs: or_raise returns the same report, does not raise."""
    report = validate_raw_inputs_or_raise(settings)

    assert report.all_valid is True
