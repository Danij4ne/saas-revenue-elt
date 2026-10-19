"""Load raw tables into BigQuery from GCS URIs produced by the upload step."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from google.api_core import retry as api_retry
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery
from google.cloud.bigquery.retry import DEFAULT_RETRY

from src.load.gcs import GcsBatchUploadReport
from src.logging_config import get_run_logger
from src.settings import AppSettings, PipelineRunContext, RawTableContract


@dataclass(slots=True)
class BigQueryLoadResult:
    """Successful load result for a single raw table."""

    table_name: str
    source_uri: str
    destination_table: str
    job_id: str | None
    run_context: PipelineRunContext
    loaded_at: datetime
    rows_loaded: int | None


def _format_bigquery_load_failure(
    table_name: str,
    source_uri: str,
    destination_table: str,
    job_id: str | None,
    run_context: PipelineRunContext,
    error_reason: str | None,
    original: GoogleAPIError,
) -> str:
    """Build a readable error message for a failed BigQuery load."""
    job_id_display = job_id if job_id is not None else "n/a"
    reason_display = error_reason if error_reason is not None else "n/a"
    return (
        f"BigQuery load failed for table '{table_name}' "
        f"(destination={destination_table}, source={source_uri}, "
        f"job_id={job_id_display}, reason={reason_display}, "
        f"run_id={run_context.run_id}, "
        f"run_date={run_context.run_date}): {original}"
    )


class BigQueryLoadFailedError(Exception):
    """Raised when a single raw table load to BigQuery fails."""

    def __init__(
        self,
        table_name: str,
        source_uri: str,
        destination_table: str,
        job_id: str | None,
        run_context: PipelineRunContext,
        error_reason: str | None,
        original: GoogleAPIError,
    ) -> None:
        self.table_name = table_name
        self.source_uri = source_uri
        self.destination_table = destination_table
        self.job_id = job_id
        self.run_context = run_context
        self.error_reason = error_reason
        self.original = original
        super().__init__(
            _format_bigquery_load_failure(
                table_name=table_name,
                source_uri=source_uri,
                destination_table=destination_table,
                job_id=job_id,
                run_context=run_context,
                error_reason=error_reason,
                original=original,
            )
        )


@dataclass(slots=True)
class BigQueryBatchLoadReport:
    """Batch load report with per-table successes and failures."""

    run_context: PipelineRunContext
    loads_ok: dict[str, BigQueryLoadResult]
    loads_failed: dict[str, BigQueryLoadFailedError]

    @property
    def all_succeeded(self) -> bool:
        """Return True when every table load in the batch succeeded."""
        return len(self.loads_failed) == 0


def _format_bigquery_batch_load_failure(report: BigQueryBatchLoadReport) -> str:
    """Build a readable error message for a failed BigQuery batch load report."""
    total = len(report.loads_ok) + len(report.loads_failed)
    lines = [
        (
            f"BigQuery batch load failed "
            f"(run_id={report.run_context.run_id}, "
            f"run_date={report.run_context.run_date})."
        ),
        f"Failed tables: {len(report.loads_failed)}/{total}.",
    ]
    for table_name, error in report.loads_failed.items():
        lines.append(f"- {table_name}: {error}")
    return "\n".join(lines)


class BigQueryBatchLoadFailedError(Exception):
    def __init__(self, report: BigQueryBatchLoadReport) -> None:
        self.report = report
        super().__init__(_format_bigquery_batch_load_failure(report))


def _build_bigquery_client(settings: AppSettings) -> bigquery.Client:
    return bigquery.Client(
        project=settings.env.gcp_project_id,
        location=settings.env.gcp_location,
    )


def _build_bigquery_retry(settings: AppSettings) -> api_retry.Retry:
    """Adapt runtime retry policy onto the official BigQuery default retry strategy."""
    defaults = settings.retry.defaults
    bq = settings.retry.bigquery

    return DEFAULT_RETRY.with_delay(
        initial=defaults.initial_delay_seconds,
        maximum=defaults.max_delay_seconds,
        multiplier=defaults.multiplier,
    ).with_deadline(bq.retry_deadline_seconds)


def _iter_loadable_tables(gcs_report: GcsBatchUploadReport) -> tuple[str, ...]:
    """Return sorted table names with successful GCS uploads in this batch."""
    return tuple(sorted(gcs_report.uploads_ok))


def _resolve_source_uri(gcs_report: GcsBatchUploadReport, table_name: str) -> str:
    """Return the gs:// URI for a table from the GCS batch upload report."""
    return gcs_report.uploads_ok[table_name].gs_uri


def _build_destination_table_id(
    settings: AppSettings,
    contract: RawTableContract,
) -> str:
    """Build the fully qualified BigQuery table id for one raw table."""
    return (
        f"{settings.env.gcp_project_id}."
        f"{settings.env.bigquery_raw_dataset}."
        f"{contract.bq_table}"
    )


def _build_load_job_config(settings: AppSettings) -> bigquery.LoadJobConfig:
    """Build load job config for raw parquet append, partitioned by _run_date.

    The technical metadata columns (_run_date, _run_id, _ingested_at) already
    travel inside the parquet (see src/load/prepare.py); a Parquet load job
    cannot inject constant columns, so this config only appends the file and
    declares run-date partitioning.
    """
    return bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=settings.raw.default_write_disposition,
        autodetect=True,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="_run_date",
        ),
    )


def _extract_bigquery_error_reason(job_or_error: object) -> str | None:
    """Extract the structured BigQuery error reason from a failed job or API error."""
    if isinstance(job_or_error, bigquery.LoadJob):
        error_result = job_or_error.error_result
        if error_result:
            return error_result.get("reason")
        return None

    if isinstance(job_or_error, GoogleAPIError):
        errors = getattr(job_or_error, "errors", None)
        if errors:
            first_error = errors[0]
            if isinstance(first_error, dict):
                return first_error.get("reason")

    return None


def _start_load_job(
    client: bigquery.Client,
    source_uri: str,
    destination_table: str,
    job_config: bigquery.LoadJobConfig,
    retry: api_retry.Retry,
) -> bigquery.LoadJob:
    """Start a load job (gs:// -> BigQuery table) with SDK retry; does not wait."""
    return client.load_table_from_uri(
        source_uri,
        destination_table,
        job_config=job_config,
        retry=retry,
    )


def _wait_for_load_job(job: bigquery.LoadJob, timeout: float) -> bigquery.LoadJob:
    """Block until the load job finishes or the operation timeout elapses."""
    job.result(timeout=timeout)
    return job


def _load_single_table(
    settings: AppSettings,
    table_name: str,
    gcs_report: GcsBatchUploadReport,
    client: bigquery.Client,
) -> BigQueryLoadResult:
    """Load one raw table from its GCS URI into BigQuery and return the result."""
    contract = settings.raw_table(table_name)
    run_context = gcs_report.run_context
    source_uri = _resolve_source_uri(gcs_report, table_name)
    destination_table = _build_destination_table_id(settings, contract)
    job_config = _build_load_job_config(settings)
    retry = _build_bigquery_retry(settings)
    timeout = settings.retry.bigquery.operation_timeout_seconds

    logger = get_run_logger(__name__, run_context.run_id, run_context.run_date)
    logger.info(
        "bq load start table=%s source=%s destination=%s",
        table_name,
        source_uri,
        destination_table,
    )
    start = time.monotonic()

    job: bigquery.LoadJob | None = None
    job_id: str | None = None
    try:
        job = _start_load_job(client, source_uri, destination_table, job_config, retry)
        job_id = job.job_id
        completed_job = _wait_for_load_job(job, timeout)
    except GoogleAPIError as original:
        logger.exception(
            "bq load failed table=%s destination=%s job_id=%s",
            table_name,
            destination_table,
            job_id,
        )
        reason = _extract_bigquery_error_reason(job if job is not None else original)
        raise BigQueryLoadFailedError(
            table_name=table_name,
            source_uri=source_uri,
            destination_table=destination_table,
            job_id=job_id,
            run_context=run_context,
            error_reason=reason,
            original=original,
        ) from original

    logger.info(
        "bq load ok table=%s destination=%s job_id=%s rows=%s duration_s=%.2f",
        table_name,
        destination_table,
        job_id,
        completed_job.output_rows,
        time.monotonic() - start,
    )

    return BigQueryLoadResult(
        table_name=table_name,
        source_uri=source_uri,
        destination_table=destination_table,
        job_id=job_id,
        run_context=run_context,
        loaded_at=datetime.now(UTC),
        rows_loaded=completed_job.output_rows,
    )


def load_raw_table_from_gcs_to_bigquery(
    settings: AppSettings,
    table_name: str,
    gcs_report: GcsBatchUploadReport,
    client: bigquery.Client | None = None,
) -> BigQueryLoadResult:
    """Load one raw table from GCS into BigQuery (debug, reprocess, tests)."""
    if client is None:
        client = _build_bigquery_client(settings)

    return _load_single_table(settings, table_name, gcs_report, client)


def load_all_raw_tables_from_gcs_to_bigquery(
    settings: AppSettings,
    gcs_report: GcsBatchUploadReport,
) -> BigQueryBatchLoadReport:
    """Load all uploaded raw tables into BigQuery and collect successes and failures."""
    client = _build_bigquery_client(settings)

    loads_ok: dict[str, BigQueryLoadResult] = {}
    loads_failed: dict[str, BigQueryLoadFailedError] = {}

    for table_name in _iter_loadable_tables(gcs_report):
        try:
            loads_ok[table_name] = load_raw_table_from_gcs_to_bigquery(
                settings,
                table_name,
                gcs_report,
                client=client,
            )
        except BigQueryLoadFailedError as error:
            loads_failed[table_name] = error

    return BigQueryBatchLoadReport(
        run_context=gcs_report.run_context,
        loads_ok=loads_ok,
        loads_failed=loads_failed,
    )


def load_all_raw_tables_from_gcs_to_bigquery_or_raise(
    settings: AppSettings,
    gcs_report: GcsBatchUploadReport,
) -> BigQueryBatchLoadReport:
    """Load all uploaded raw tables into BigQuery and raise if any load fails."""
    report = load_all_raw_tables_from_gcs_to_bigquery(settings, gcs_report)

    if not report.all_succeeded:
        raise BigQueryBatchLoadFailedError(report)

    return report
