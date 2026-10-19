"""Validate local raw parquet files against the raw contract before load."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import pyarrow.parquet as pq

from src.settings import AppSettings, RawTableContract

logger = logging.getLogger(__name__)


class RawValidationErrorCode(StrEnum):
    FILE_NOT_FOUND = "file_not_found"
    PARQUET_NOT_READABLE = "parquet_not_readable"
    EMPTY_PARQUET = "empty_parquet"
    MISSING_COLUMNS = "missing_columns"


class RawValidationIssueCategory(StrEnum):
    IO = "io"
    CONTRACT = "contract"


class RawValidationFailedError(Exception):
    """Raised when one or more raw inputs fail blocking validation."""

    def __init__(self, report: RawValidationReport) -> None:
        self.report = report
        super().__init__(_format_raw_validation_failure(report))


@dataclass(slots=True)
class ParquetMetadata:
    row_count: int
    columns: list[str]


@dataclass(slots=True)
class RawValidationIssue:
    code: RawValidationErrorCode
    message: str
    category: RawValidationIssueCategory
    is_blocking: bool = True


@dataclass(slots=True)
class RawTableValidationResult:
    table_name: str
    file_path: Path
    exists: bool
    readable: bool
    row_count: int | None = None
    columns: list[str] | None = None
    missing_columns: list[str] | None = None
    issues: list[RawValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (
            self.exists
            and self.readable
            and self.row_count is not None
            and self.row_count > 0
            and self.missing_columns is not None
            and not self.missing_columns
            and not any(issue.is_blocking for issue in self.issues)
        )


@dataclass(slots=True)
class RawValidationReport:
    raw_dir: Path
    table_results: list[RawTableValidationResult]

    @property
    def validated_table_count(self) -> int:
        return len(self.table_results)

    @property
    def valid_table_count(self) -> int:
        return sum(result.is_valid for result in self.table_results)

    @property
    def invalid_table_count(self) -> int:
        return self.validated_table_count - self.valid_table_count

    @property
    def all_valid(self) -> bool:
        return self.invalid_table_count == 0


def _format_raw_validation_failure(report: RawValidationReport) -> str:
    """Build a readable error message for a failed raw validation report."""
    lines = [
        f"Raw input validation failed for {report.raw_dir}.",
        (
            f"Invalid tables: {report.invalid_table_count}/"
            f"{report.validated_table_count}."
        ),
    ]

    for result in report.table_results:
        if result.is_valid:
            continue

        if result.issues:
            issue_summary = "; ".join(
                f"{issue.code.value}: {issue.message}" for issue in result.issues
            )
        else:
            issue_summary = "validation failed without detailed issues"

        lines.append(f"- {result.table_name}: {issue_summary}")

    return "\n".join(lines)


def _validate_raw_dir_exists(settings: AppSettings) -> bool:
    return settings.local_raw_dir.is_dir()


def _build_expected_file_paths(settings: AppSettings) -> dict[str, Path]:
    """Build the expected absolute parquet file path for each raw table."""
    expected_paths = {}

    for table_name in settings.raw.tables:
        expected_paths[table_name] = settings.raw_file_path(table_name)

    return expected_paths


def _read_parquet_metadata(file_path: Path) -> ParquetMetadata:
    """Read the minimal parquet metadata needed for raw validation."""
    metadata = pq.read_metadata(file_path)

    return ParquetMetadata(
        row_count=metadata.num_rows,
        columns=metadata.schema.names,
    )


def _find_missing_required_columns(
    table_contract: RawTableContract,
    parquet_columns: list[str],
) -> list[str]:
    """Return the required contract columns that are missing from the parquet file."""
    parquet_column_set = set(parquet_columns)
    return [
        column
        for column in table_contract.required_columns
        if column not in parquet_column_set
    ]


def _validate_single_table(
    table_name: str,
    table_contract: RawTableContract,
    file_path: Path,
) -> RawTableValidationResult:
    """Validate one raw parquet: existence, readability, and contract rules."""
    issues: list[RawValidationIssue] = []

    if not file_path.is_file():
        issues.append(
            RawValidationIssue(
                code=RawValidationErrorCode.FILE_NOT_FOUND,
                message=f"Raw parquet file not found: {file_path}",
                category=RawValidationIssueCategory.IO,
            )
        )
        return RawTableValidationResult(
            table_name=table_name,
            file_path=file_path,
            exists=False,
            readable=False,
            issues=issues,
        )

    try:
        metadata = _read_parquet_metadata(file_path)
    except Exception as exc:
        issues.append(
            RawValidationIssue(
                code=RawValidationErrorCode.PARQUET_NOT_READABLE,
                message=f"Could not read parquet metadata for {file_path}: {exc}",
                category=RawValidationIssueCategory.IO,
            )
        )
        return RawTableValidationResult(
            table_name=table_name,
            file_path=file_path,
            exists=True,
            readable=False,
            issues=issues,
        )

    missing_columns = _find_missing_required_columns(table_contract, metadata.columns)

    if metadata.row_count == 0:
        issues.append(
            RawValidationIssue(
                code=RawValidationErrorCode.EMPTY_PARQUET,
                message=f"Raw parquet file is empty: {file_path}",
                category=RawValidationIssueCategory.CONTRACT,
            )
        )

    if missing_columns:
        issues.append(
            RawValidationIssue(
                code=RawValidationErrorCode.MISSING_COLUMNS,
                message=(
                    f"Missing required columns for '{table_name}': "
                    f"{', '.join(missing_columns)}"
                ),
                category=RawValidationIssueCategory.CONTRACT,
            )
        )

    return RawTableValidationResult(
        table_name=table_name,
        file_path=file_path,
        exists=True,
        readable=True,
        row_count=metadata.row_count,
        columns=metadata.columns,
        missing_columns=missing_columns,
        issues=issues,
    )


def validate_raw_inputs(settings: AppSettings) -> RawValidationReport:
    """Validate all configured raw parquet inputs and return a batch report."""
    raw_dir = settings.local_raw_dir
    expected_file_paths = _build_expected_file_paths(settings)

    if not _validate_raw_dir_exists(settings):
        table_results = [
            RawTableValidationResult(
                table_name=table_name,
                file_path=file_path,
                exists=False,
                readable=False,
                issues=[
                    RawValidationIssue(
                        code=RawValidationErrorCode.FILE_NOT_FOUND,
                        message=f"Raw input directory does not exist: {raw_dir}",
                        category=RawValidationIssueCategory.IO,
                    )
                ],
            )
            for table_name, file_path in expected_file_paths.items()
        ]
        return RawValidationReport(raw_dir=raw_dir, table_results=table_results)

    table_results = []
    for table_name, table_contract in settings.raw.tables.items():
        file_path = expected_file_paths[table_name]
        table_results.append(
            _validate_single_table(
                table_name=table_name,
                table_contract=table_contract,
                file_path=file_path,
            )
        )

    return RawValidationReport(raw_dir=raw_dir, table_results=table_results)


def validate_raw_inputs_or_raise(settings: AppSettings) -> RawValidationReport:
    """Validate raw inputs and raise a custom error when blocking issues exist."""
    report = validate_raw_inputs(settings)

    if not report.all_valid:
        logger.error(
            "raw validation failed: %s/%s invalid tables (raw_dir=%s)",
            report.invalid_table_count,
            report.validated_table_count,
            report.raw_dir,
        )
        raise RawValidationFailedError(report)

    return report
