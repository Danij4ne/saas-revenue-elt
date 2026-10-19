"""Fetch dumps from the GCS landing prefix and seed that prefix from local files.

Landing objects are the extract without technical metadata. Prepared, versioned
uploads still live under ``raw/`` via ``gcs.py``. This module does not transform
rows.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from google.api_core import retry as api_retry
from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY

from src.settings import AppSettings, RawTableContract, get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LandingFetchResult:
    """Successful download of one landing object to local disk."""

    table_name: str
    local_path: Path
    object_name: str
    gs_uri: str


@dataclass(slots=True)
class LandingSeedResult:
    """Successful upload of one local dump to the landing prefix."""

    table_name: str
    local_path: Path
    object_name: str
    gs_uri: str


def _format_landing_fetch_failure(
    table_name: str,
    local_path: Path,
    bucket_name: str,
    object_name: str,
    gs_uri: str,
    original: BaseException,
) -> str:
    """Build a readable error message for a failed landing download."""
    return (
        f"Landing fetch failed for table '{table_name}' "
        f"(bucket={bucket_name}, object={object_name}, "
        f"gs_uri={gs_uri}, local_path={local_path}): {original}"
    )


class LandingFetchFailedError(Exception):
    """Raised when a single landing object cannot be downloaded."""

    def __init__(
        self,
        table_name: str,
        local_path: Path,
        bucket_name: str,
        object_name: str,
        gs_uri: str,
        original: BaseException,
    ) -> None:
        self.table_name = table_name
        self.local_path = local_path
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.gs_uri = gs_uri
        self.original = original
        super().__init__(
            _format_landing_fetch_failure(
                table_name=table_name,
                local_path=local_path,
                bucket_name=bucket_name,
                object_name=object_name,
                gs_uri=gs_uri,
                original=original,
            )
        )


def _format_landing_seed_failure(
    table_name: str,
    local_path: Path,
    bucket_name: str,
    object_name: str,
    gs_uri: str,
    original: BaseException,
) -> str:
    """Build a readable error message for a failed landing seed upload."""
    return (
        f"Landing seed failed for table '{table_name}' "
        f"(bucket={bucket_name}, object={object_name}, "
        f"gs_uri={gs_uri}, local_path={local_path}): {original}"
    )


class LandingSeedFailedError(Exception):
    """Raised when a single local dump cannot be uploaded to landing."""

    def __init__(
        self,
        table_name: str,
        local_path: Path,
        bucket_name: str,
        object_name: str,
        gs_uri: str,
        original: BaseException,
    ) -> None:
        self.table_name = table_name
        self.local_path = local_path
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.gs_uri = gs_uri
        self.original = original
        super().__init__(
            _format_landing_seed_failure(
                table_name=table_name,
                local_path=local_path,
                bucket_name=bucket_name,
                object_name=object_name,
                gs_uri=gs_uri,
                original=original,
            )
        )


@dataclass(slots=True)
class LandingFetchBatchReport:
    """Batch download report with per-table successes and failures."""

    fetches_ok: dict[str, LandingFetchResult]
    fetches_failed: dict[str, LandingFetchFailedError]

    @property
    def all_succeeded(self) -> bool:
        """Return True when every table download in the batch succeeded."""
        return len(self.fetches_failed) == 0


def _format_landing_fetch_batch_failure(report: LandingFetchBatchReport) -> str:
    """Build a readable error message for a failed landing fetch batch."""
    total = len(report.fetches_ok) + len(report.fetches_failed)
    lines = [
        "Landing fetch batch failed.",
        f"Failed tables: {len(report.fetches_failed)}/{total}.",
    ]
    for table_name, error in report.fetches_failed.items():
        lines.append(f"- {table_name}: {error}")
    return "\n".join(lines)


class LandingFetchBatchFailedError(Exception):
    """Raised when one or more landing downloads fail after the full batch."""

    def __init__(self, report: LandingFetchBatchReport) -> None:
        self.report = report
        super().__init__(_format_landing_fetch_batch_failure(report))


@dataclass(slots=True)
class LandingSeedBatchReport:
    """Batch seed report with per-table successes and failures."""

    seeds_ok: dict[str, LandingSeedResult]
    seeds_failed: dict[str, LandingSeedFailedError]

    @property
    def all_succeeded(self) -> bool:
        """Return True when every table seed in the batch succeeded."""
        return len(self.seeds_failed) == 0


def _format_landing_seed_batch_failure(report: LandingSeedBatchReport) -> str:
    """Build a readable error message for a failed landing seed batch."""
    total = len(report.seeds_ok) + len(report.seeds_failed)
    lines = [
        "Landing seed batch failed.",
        f"Failed tables: {len(report.seeds_failed)}/{total}.",
    ]
    for table_name, error in report.seeds_failed.items():
        lines.append(f"- {table_name}: {error}")
    return "\n".join(lines)


class LandingSeedBatchFailedError(Exception):
    """Raised when one or more landing seeds fail after the full batch."""

    def __init__(self, report: LandingSeedBatchReport) -> None:
        self.report = report
        super().__init__(_format_landing_seed_batch_failure(report))


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


def _build_landing_object_name(
    settings: AppSettings,
    contract: RawTableContract,
) -> str:
    """Build the flat landing object path for one raw dump."""
    return f"{settings.raw.landing_gcs_prefix}/{contract.file_name}"


def _build_landing_gs_uri(bucket_name: str, object_name: str) -> str:
    """Build the gs:// URI for a landing object."""
    return f"gs://{bucket_name}/{object_name}"


def _download_blob_with_retry(
    blob: storage.Blob,
    file_path: Path,
    retry: api_retry.Retry,
    timeout: float,
) -> None:
    """Download one GCS object to a local path with retry and per-attempt timeout."""
    blob.download_to_filename(file_path, retry=retry, timeout=int(timeout))


def _upload_blob_with_retry(
    blob: storage.Blob,
    file_path: Path,
    retry: api_retry.Retry,
    timeout: float,
) -> None:
    """Upload a local dump to landing with retry and per-attempt timeout."""
    blob.upload_from_filename(file_path, retry=retry, timeout=int(timeout))


def _fetch_single_table(
    settings: AppSettings,
    table_name: str,
    dest_dir: Path,
    client: storage.Client,
) -> LandingFetchResult:
    """Download one landing object into ``dest_dir`` and return the result."""
    contract = settings.raw_table(table_name)
    object_name = _build_landing_object_name(settings, contract)
    bucket_name = settings.env.gcs_bucket_name
    gs_uri = _build_landing_gs_uri(bucket_name, object_name)
    local_path = (dest_dir / contract.file_name).resolve()
    local_path.parent.mkdir(parents=True, exist_ok=True)

    bucket = _get_bucket(client, settings)
    blob = bucket.blob(object_name)
    retry = _build_gcs_retry(settings)
    timeout = settings.retry.gcs.operation_timeout_seconds

    logger.info("landing fetch start table=%s gs_uri=%s", table_name, gs_uri)
    start = time.monotonic()

    try:
        _download_blob_with_retry(blob, local_path, retry, timeout)
    except GoogleAPIError as original:
        logger.exception("landing fetch failed table=%s gs_uri=%s", table_name, gs_uri)
        raise LandingFetchFailedError(
            table_name=table_name,
            local_path=local_path,
            bucket_name=bucket_name,
            object_name=object_name,
            gs_uri=gs_uri,
            original=original,
        ) from original

    logger.info(
        "landing fetch ok table=%s gs_uri=%s duration_s=%.2f",
        table_name,
        gs_uri,
        time.monotonic() - start,
    )

    return LandingFetchResult(
        table_name=table_name,
        local_path=local_path,
        object_name=object_name,
        gs_uri=gs_uri,
    )


def _seed_single_table(
    settings: AppSettings,
    table_name: str,
    client: storage.Client,
) -> LandingSeedResult:
    """Upload one local dump (no metadata) to the landing prefix."""
    contract = settings.raw_table(table_name)
    object_name = _build_landing_object_name(settings, contract)
    bucket_name = settings.env.gcs_bucket_name
    gs_uri = _build_landing_gs_uri(bucket_name, object_name)
    local_path = settings.raw_file_path(table_name)

    if not local_path.is_file():
        missing = FileNotFoundError(f"Local dump does not exist: {local_path}")
        raise LandingSeedFailedError(
            table_name=table_name,
            local_path=local_path,
            bucket_name=bucket_name,
            object_name=object_name,
            gs_uri=gs_uri,
            original=missing,
        ) from missing

    bucket = _get_bucket(client, settings)
    blob = bucket.blob(object_name)
    retry = _build_gcs_retry(settings)
    timeout = settings.retry.gcs.operation_timeout_seconds

    logger.info("landing seed start table=%s gs_uri=%s", table_name, gs_uri)
    start = time.monotonic()

    try:
        _upload_blob_with_retry(blob, local_path, retry, timeout)
    except GoogleAPIError as original:
        logger.exception("landing seed failed table=%s gs_uri=%s", table_name, gs_uri)
        raise LandingSeedFailedError(
            table_name=table_name,
            local_path=local_path,
            bucket_name=bucket_name,
            object_name=object_name,
            gs_uri=gs_uri,
            original=original,
        ) from original

    logger.info(
        "landing seed ok table=%s gs_uri=%s duration_s=%.2f",
        table_name,
        gs_uri,
        time.monotonic() - start,
    )

    return LandingSeedResult(
        table_name=table_name,
        local_path=local_path,
        object_name=object_name,
        gs_uri=gs_uri,
    )


def fetch_raw_table_from_gcs(
    settings: AppSettings,
    table_name: str,
    dest_dir: Path,
    client: storage.Client | None = None,
) -> LandingFetchResult:
    """Download one landing object (debug, reprocess, tests)."""
    if client is None:
        client = _build_storage_client(settings)

    return _fetch_single_table(settings, table_name, dest_dir, client)


def fetch_all_raw_tables_from_gcs(
    settings: AppSettings,
    dest_dir: Path,
) -> LandingFetchBatchReport:
    """Download all landing dumps and collect successes and failures."""
    client = _build_storage_client(settings)
    dest_dir.mkdir(parents=True, exist_ok=True)

    fetches_ok: dict[str, LandingFetchResult] = {}
    fetches_failed: dict[str, LandingFetchFailedError] = {}

    for table_name in sorted(settings.raw.tables):
        try:
            fetches_ok[table_name] = fetch_raw_table_from_gcs(
                settings,
                table_name,
                dest_dir,
                client=client,
            )
        except LandingFetchFailedError as error:
            fetches_failed[table_name] = error

    return LandingFetchBatchReport(
        fetches_ok=fetches_ok,
        fetches_failed=fetches_failed,
    )


def fetch_all_raw_tables_from_gcs_or_raise(
    settings: AppSettings,
    dest_dir: Path,
) -> LandingFetchBatchReport:
    """Download all landing dumps and raise if any download fails."""
    report = fetch_all_raw_tables_from_gcs(settings, dest_dir)

    if not report.all_succeeded:
        raise LandingFetchBatchFailedError(report)

    return report


def seed_raw_table_to_gcs_landing(
    settings: AppSettings,
    table_name: str,
    client: storage.Client | None = None,
) -> LandingSeedResult:
    """Upload one local dump to landing (debug, reprocess, tests)."""
    if client is None:
        client = _build_storage_client(settings)

    return _seed_single_table(settings, table_name, client)


def seed_all_raw_tables_to_gcs_landing(
    settings: AppSettings,
) -> LandingSeedBatchReport:
    """Upload all local dumps to landing and collect successes and failures."""
    client = _build_storage_client(settings)

    seeds_ok: dict[str, LandingSeedResult] = {}
    seeds_failed: dict[str, LandingSeedFailedError] = {}

    for table_name in sorted(settings.raw.tables):
        try:
            seeds_ok[table_name] = seed_raw_table_to_gcs_landing(
                settings,
                table_name,
                client=client,
            )
        except LandingSeedFailedError as error:
            seeds_failed[table_name] = error

    return LandingSeedBatchReport(
        seeds_ok=seeds_ok,
        seeds_failed=seeds_failed,
    )


def seed_all_raw_tables_to_gcs_landing_or_raise(
    settings: AppSettings | None = None,
) -> LandingSeedBatchReport:
    """Upload all local dumps to landing and raise if any upload fails."""
    settings = settings or get_settings()
    report = seed_all_raw_tables_to_gcs_landing(settings)

    if not report.all_succeeded:
        raise LandingSeedBatchFailedError(report)

    return report
