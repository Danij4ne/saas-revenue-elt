"""Unit tests for BigQuery load helpers (policy only; no real jobs)."""

from __future__ import annotations

from pathlib import Path

from google.cloud import bigquery

from src.load.bigquery import (
    _build_destination_table_id,
    _build_load_job_config,
    _resolve_source_uri,
)
from src.load.gcs import GcsBatchUploadReport, GcsUploadResult
from src.settings import AppSettings, PipelineRunContext


def test_build_destination_table_id(settings: AppSettings) -> None:
    """Destination is project.dataset.bq_table from settings + contract."""
    table_name = next(iter(settings.raw.tables))
    contract = settings.raw_table(table_name)

    table_id = _build_destination_table_id(settings, contract)

    assert table_id == (
        f"{settings.env.gcp_project_id}."
        f"{settings.env.bigquery_raw_dataset}."
        f"{contract.bq_table}"
    )


def test_build_load_job_config_append_and_partition(settings: AppSettings) -> None:
    """Job config: WRITE_APPEND, ALLOW_FIELD_ADDITION, partition on _run_date."""
    config = _build_load_job_config(settings)

    assert config.source_format == bigquery.SourceFormat.PARQUET
    assert config.write_disposition == settings.raw.default_write_disposition
    assert (
        bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION in config.schema_update_options
    )
    assert config.time_partitioning is not None
    assert config.time_partitioning.field == "_run_date"


def test_resolve_source_uri_from_gcs_report(
    run_context: PipelineRunContext,
) -> None:
    """_resolve_source_uri reads gs_uri from the GCS report (does not rebuild paths)."""
    table_name = "customers"
    expected_uri = (
        "gs://test-bucket/raw/customers/"
        f"dt={run_context.run_date}/run_id={run_context.run_id}/customers.parquet"
    )
    upload = GcsUploadResult(
        table_name=table_name,
        local_path=Path("prepared/customers.parquet"),
        object_name=(
            f"raw/customers/dt={run_context.run_date}/"
            f"run_id={run_context.run_id}/customers.parquet"
        ),
        gs_uri=expected_uri,
        run_context=run_context,
    )
    report = GcsBatchUploadReport(
        run_context=run_context,
        uploads_ok={table_name: upload},
        uploads_failed={},
    )

    assert _resolve_source_uri(report, table_name) == expected_uri
