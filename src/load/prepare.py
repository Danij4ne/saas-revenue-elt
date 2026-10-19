"""Enrich validated raw parquet files with technical metadata before GCS upload.

This step is the reason raw loads can carry ``_run_date`` / ``_run_id`` /
``_ingested_at``: a BigQuery Parquet load job cannot inject constant columns, so
the technical metadata is written into the parquet here, before it is uploaded.
It runs locally (no network), so it has no retry policy, but it mirrors the
single / batch / ``_or_raise`` shape of ``gcs.py`` and ``bigquery.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.logging_config import get_run_logger
from src.settings import AppSettings, PipelineRunContext

RUN_DATE_COLUMN = "_run_date"
RUN_ID_COLUMN = "_run_id"
INGESTED_AT_COLUMN = "_ingested_at"


@dataclass(slots=True)
class RawPrepareResult:
    """Successful enrichment result for a single raw table."""

    table_name: str
    source_path: Path
    prepared_path: Path
    run_context: PipelineRunContext
    row_count: int
    added_columns: tuple[str, ...]


def _format_raw_prepare_failure(
    table_name: str,
    source_path: Path,
    run_context: PipelineRunContext,
    original: Exception,
) -> str:
    """Build a readable error message for a failed raw table enrichment."""
    return (
        f"Raw metadata enrichment failed for table '{table_name}' "
        f"(source_path={source_path}, run_id={run_context.run_id}, "
        f"run_date={run_context.run_date}): {original}"
    )


class RawPrepareFailedError(Exception):
    """Raised when enriching a single raw table with technical metadata fails."""

    def __init__(
        self,
        table_name: str,
        source_path: Path,
        run_context: PipelineRunContext,
        original: Exception,
    ) -> None:
        self.table_name = table_name
        self.source_path = source_path
        self.run_context = run_context
        self.original = original
        super().__init__(
            _format_raw_prepare_failure(
                table_name=table_name,
                source_path=source_path,
                run_context=run_context,
                original=original,
            )
        )


@dataclass(slots=True)
class RawPrepareBatchReport:
    """Batch enrichment report with per-table successes and failures."""

    run_context: PipelineRunContext
    prepared_ok: dict[str, RawPrepareResult]
    prepared_failed: dict[str, RawPrepareFailedError]

    @property
    def all_succeeded(self) -> bool:
        """Return True when every table enrichment in the batch succeeded."""
        return len(self.prepared_failed) == 0

    @property
    def prepared_paths(self) -> dict[str, Path]:
        """Return the mapping table_name -> enriched parquet path for the batch."""
        return {
            table_name: result.prepared_path
            for table_name, result in self.prepared_ok.items()
        }


def _format_raw_prepare_batch_failure(report: RawPrepareBatchReport) -> str:
    """Build a readable error message for a failed raw enrichment batch report."""
    total = len(report.prepared_ok) + len(report.prepared_failed)
    lines = [
        (
            f"Raw metadata enrichment batch failed "
            f"(run_id={report.run_context.run_id}, "
            f"run_date={report.run_context.run_date})."
        ),
        f"Failed tables: {len(report.prepared_failed)}/{total}.",
    ]
    for table_name, error in report.prepared_failed.items():
        lines.append(f"- {table_name}: {error}")
    return "\n".join(lines)


class RawPrepareBatchFailedError(Exception):
    """Raised when one or more table enrichments fail after the full batch."""

    def __init__(self, report: RawPrepareBatchReport) -> None:
        self.report = report
        super().__init__(_format_raw_prepare_batch_failure(report))


def _iter_raw_table_names(settings: AppSettings) -> tuple[str, ...]:
    """Return sorted raw table names declared in the contract."""
    return tuple(sorted(settings.raw.tables))


def _build_metadata_columns(
    settings: AppSettings,
    run_context: PipelineRunContext,
    row_count: int,
) -> dict[str, pa.Array]:
    """Build the constant technical metadata columns enabled by the contract."""
    metadata_config = settings.raw.load_metadata
    columns: dict[str, pa.Array] = {}

    if metadata_config.include_run_date:
        columns[RUN_DATE_COLUMN] = pa.array(
            [run_context.run_date] * row_count, type=pa.date32()
        )

    if metadata_config.include_run_id:
        columns[RUN_ID_COLUMN] = pa.array(
            [run_context.run_id] * row_count, type=pa.string()
        )

    if metadata_config.include_ingested_at:
        ingested_at = datetime.now(UTC)
        columns[INGESTED_AT_COLUMN] = pa.array(
            [ingested_at] * row_count, type=pa.timestamp("us", tz="UTC")
        )

    return columns


def _enrich_table(table: pa.Table, metadata_columns: dict[str, pa.Array]) -> pa.Table:
    """Append the constant technical metadata columns to a parquet table."""
    enriched = table
    for column_name, column_values in metadata_columns.items():
        enriched = enriched.append_column(column_name, column_values)
    return enriched


def _prepare_single_table(
    settings: AppSettings,
    table_name: str,
    run_context: PipelineRunContext,
    dest_dir: Path,
) -> RawPrepareResult:
    """Enrich one raw table with technical metadata and write it to ``dest_dir``."""
    contract = settings.raw_table(table_name)
    source_path = settings.raw_file_path(table_name)
    prepared_path = (dest_dir / contract.file_name).resolve()

    table = pq.read_table(source_path)
    metadata_columns = _build_metadata_columns(settings, run_context, table.num_rows)
    enriched_table = _enrich_table(table, metadata_columns)
    pq.write_table(enriched_table, prepared_path)

    return RawPrepareResult(
        table_name=table_name,
        source_path=source_path,
        prepared_path=prepared_path,
        run_context=run_context,
        row_count=enriched_table.num_rows,
        added_columns=tuple(metadata_columns),
    )


def prepare_raw_table(
    settings: AppSettings,
    table_name: str,
    run_context: PipelineRunContext,
    dest_dir: Path,
) -> RawPrepareResult:
    """Enrich one raw table with technical metadata (debug, reprocess, tests)."""
    try:
        return _prepare_single_table(settings, table_name, run_context, dest_dir)
    except Exception as original:
        raise RawPrepareFailedError(
            table_name=table_name,
            source_path=settings.raw_file_path(table_name),
            run_context=run_context,
            original=original,
        ) from original


def prepare_all_raw_tables(
    settings: AppSettings,
    run_context: PipelineRunContext,
    dest_dir: Path,
) -> RawPrepareBatchReport:
    """Enrich all raw tables with technical metadata; collect ok and failures."""
    prepared_ok: dict[str, RawPrepareResult] = {}
    prepared_failed: dict[str, RawPrepareFailedError] = {}

    for table_name in _iter_raw_table_names(settings):
        try:
            prepared_ok[table_name] = prepare_raw_table(
                settings,
                table_name,
                run_context,
                dest_dir,
            )
        except RawPrepareFailedError as error:
            prepared_failed[table_name] = error

    return RawPrepareBatchReport(
        run_context=run_context,
        prepared_ok=prepared_ok,
        prepared_failed=prepared_failed,
    )


def prepare_all_raw_tables_or_raise(
    settings: AppSettings,
    run_context: PipelineRunContext,
    dest_dir: Path,
) -> RawPrepareBatchReport:
    """Enrich all raw tables with technical metadata and raise if any table fails."""
    report = prepare_all_raw_tables(settings, run_context, dest_dir)

    if not report.all_succeeded:
        logger = get_run_logger(__name__, run_context.run_id, run_context.run_date)
        logger.error(
            "prepare batch failed: %s/%s tables failed",
            len(report.prepared_failed),
            len(report.prepared_ok) + len(report.prepared_failed),
        )
        raise RawPrepareBatchFailedError(report)

    return report
