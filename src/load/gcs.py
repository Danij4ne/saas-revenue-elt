"""Upload validated raw parquet files to Google Cloud Storage."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from google.api_core import retry as api_retry
from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY

from src.logging_config import get_run_logger
from src.settings import AppSettings, PipelineRunContext, RawTableContract


@dataclass(slots=True)
class GcsUploadResult:
    """Successful upload result for a single raw table."""

    table_name: str
    local_path: Path
    object_name: str
    gs_uri: str
    run_context: PipelineRunContext


def _format_gcs_upload_failure(
    table_name: str,
    local_path: Path,
    bucket_name: str,
    object_name: str,
    run_context: PipelineRunContext,
    original: GoogleAPIError,
) -> str:
    """Build a readable error message for a failed GCS upload."""
    return (
        f"GCS upload failed for table '{table_name}' "
        f"(bucket={bucket_name}, object={object_name}, "
        f"run_id={run_context.run_id}, local_path={local_path}): {original}"
    )


class GcsUploadFailedError(Exception):
    """Raised when a single raw table upload to GCS fails."""

    def __init__(
        self,
        table_name: str,
        local_path: Path,
        bucket_name: str,
        object_name: str,
        run_context: PipelineRunContext,
        original: GoogleAPIError,
    ) -> None:
        self.table_name = table_name
        self.local_path = local_path
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.run_context = run_context
        self.original = original
        super().__init__(
            _format_gcs_upload_failure(
                table_name=table_name,
                local_path=local_path,
                bucket_name=bucket_name,
                object_name=object_name,
                run_context=run_context,
                original=original,
            )
        )


@dataclass(slots=True)
class GcsBatchUploadReport:
    """Batch upload report with per-table successes and failures."""

    run_context: PipelineRunContext
    uploads_ok: dict[str, GcsUploadResult]
    uploads_failed: dict[str, GcsUploadFailedError]

    @property
    def all_succeeded(self) -> bool:
        """Return True when every table upload in the batch succeeded."""
        return len(self.uploads_failed) == 0


def _format_gcs_batch_upload_failure(report: GcsBatchUploadReport) -> str:
    """Build a readable error message for a failed GCS batch upload report."""
    total = len(report.uploads_ok) + len(report.uploads_failed)
    lines = [
        (
            f"GCS batch upload failed "
            f"(run_id={report.run_context.run_id}, "
            f"run_date={report.run_context.run_date})."
        ),
        f"Failed tables: {len(report.uploads_failed)}/{total}.",
    ]
    for table_name, error in report.uploads_failed.items():
        lines.append(f"- {table_name}: {error}")
    return "\n".join(lines)


class GcsBatchUploadFailedError(Exception):
    """Raised when one or more GCS uploads fail after the full batch."""

    def __init__(self, report: GcsBatchUploadReport) -> None:
        self.report = report
        super().__init__(_format_gcs_batch_upload_failure(report))


def _build_storage_client(settings: AppSettings) -> storage.Client:
    """Create a GCS client bound to the configured GCP project."""
    return storage.Client(project=settings.env.gcp_project_id)


def _get_bucket(client: storage.Client, settings: AppSettings) -> storage.Bucket:
    """Return a local bucket reference without calling the GCS API."""
    return client.bucket(settings.env.gcs_bucket_name)


def _build_gcs_retry(settings: AppSettings) -> api_retry.Retry:
    """Adapt runtime retry policy onto the official GCS default retry strategy."""
    defaults = settings.retry.defaults
    gcs = settings.retry.gcs

    return DEFAULT_RETRY.with_delay(
        initial=defaults.initial_delay_seconds,
        maximum=defaults.max_delay_seconds,
        multiplier=defaults.multiplier,
    ).with_deadline(gcs.retry_deadline_seconds)


def _build_gcs_object_name(
    settings: AppSettings,
    table_name: str,
    contract: RawTableContract,
    run_context: PipelineRunContext,
) -> str:
    """Build the versioned GCS object path for one raw table upload."""
    layout = settings.raw.gcs_layout
    date_key = layout.date_partition_key

    path_parts = [
        settings.raw.gcs_prefix,
        table_name,
        f"{date_key}={run_context.run_date}",
    ]

    if layout.include_run_id:
        path_parts.append(f"run_id={run_context.run_id}")

    path_parts.append(contract.file_name)

    return "/".join(path_parts)


def _build_gcs_uri(bucket_name: str, object_name: str) -> str:
    """Build the gs:// URI for a GCS object."""
    return f"gs://{bucket_name}/{object_name}"


def _upload_blob_with_retry(
    blob: storage.Blob,
    file_path: Path,
    retry: api_retry.Retry,
    timeout: float,
) -> None:
    """Upload a local parquet file to GCS with retry and per-attempt timeout."""
    blob.upload_from_filename(file_path, retry=retry, timeout=int(timeout))


def _upload_single_table(
    settings: AppSettings,
    table_name: str,
    local_path: Path,
    run_context: PipelineRunContext,
    client: storage.Client,
) -> GcsUploadResult:
    """Upload one raw table (resolved local path) to GCS and return the result."""
    contract = settings.raw_table(table_name)
    object_name = _build_gcs_object_name(settings, table_name, contract, run_context)

    bucket_name = settings.env.gcs_bucket_name
    gs_uri = _build_gcs_uri(bucket_name, object_name)

    bucket = _get_bucket(client, settings)
    blob = bucket.blob(object_name)

    retry = _build_gcs_retry(settings)
    timeout = settings.retry.gcs.operation_timeout_seconds

    logger = get_run_logger(__name__, run_context.run_id, run_context.run_date)
    logger.info("gcs upload start table=%s gs_uri=%s", table_name, gs_uri)
    start = time.monotonic()

    try:
        _upload_blob_with_retry(blob, local_path, retry, timeout)
    except GoogleAPIError as original:
        logger.exception("gcs upload failed table=%s gs_uri=%s", table_name, gs_uri)
        raise GcsUploadFailedError(
            table_name=table_name,
            local_path=local_path,
            bucket_name=bucket_name,
            object_name=object_name,
            run_context=run_context,
            original=original,
        ) from original

    logger.info(
        "gcs upload ok table=%s gs_uri=%s duration_s=%.2f",
        table_name,
        gs_uri,
        time.monotonic() - start,
    )

    return GcsUploadResult(
        table_name=table_name,
        local_path=local_path,
        object_name=object_name,
        gs_uri=gs_uri,
        run_context=run_context,
    )


def upload_raw_table_to_gcs(
    settings: AppSettings,
    table_name: str,
    local_path: Path,
    run_context: PipelineRunContext,
    client: storage.Client | None = None,
) -> GcsUploadResult:
    """Upload one raw table to GCS (debug, reprocess, tests)."""
    if client is None:
        client = _build_storage_client(settings)

    return _upload_single_table(settings, table_name, local_path, run_context, client)


def upload_all_raw_tables_to_gcs(
    settings: AppSettings,
    local_paths: dict[str, Path],
    run_context: PipelineRunContext,
) -> GcsBatchUploadReport:
    """Upload all prepared raw tables to GCS and collect successes and failures."""
    client = _build_storage_client(settings)

    uploads_ok: dict[str, GcsUploadResult] = {}
    uploads_failed: dict[str, GcsUploadFailedError] = {}

    for table_name in sorted(local_paths):
        try:
            uploads_ok[table_name] = upload_raw_table_to_gcs(
                settings,
                table_name,
                local_paths[table_name],
                run_context,
                client=client,
            )
        except GcsUploadFailedError as error:
            uploads_failed[table_name] = error

    return GcsBatchUploadReport(
        run_context=run_context,
        uploads_ok=uploads_ok,
        uploads_failed=uploads_failed,
    )


def upload_all_raw_tables_to_gcs_or_raise(
    settings: AppSettings,
    local_paths: dict[str, Path],
    run_context: PipelineRunContext,
) -> GcsBatchUploadReport:
    """Upload all prepared raw tables to GCS and raise if any upload fails."""
    report = upload_all_raw_tables_to_gcs(settings, local_paths, run_context)

    if not report.all_succeeded:
        raise GcsBatchUploadFailedError(report)

    return report
