"""Unit tests for GCS naming helpers (no network, no upload)."""

from __future__ import annotations

from src.load.gcs import _build_gcs_object_name, _build_gcs_uri
from src.settings import AppSettings, PipelineRunContext


def test_build_gcs_object_name_with_run_id(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """Object path is prefix/table/dt=YYYY-MM-DD/run_id=.../file.parquet."""
    table_name = next(iter(settings.raw.tables))
    contract = settings.raw_table(table_name)

    name = _build_gcs_object_name(settings, table_name, contract, run_context)

    assert name == (
        f"{settings.raw.gcs_prefix}/{table_name}/"
        f"dt={run_context.run_date}/run_id={run_context.run_id}/"
        f"{contract.file_name}"
    )


def test_build_gcs_object_name_without_run_id(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """When include_run_id is False, path has no run_id= segment."""
    layout = settings.raw.gcs_layout.model_copy(update={"include_run_id": False})
    raw = settings.raw.model_copy(update={"gcs_layout": layout})
    raw_contract = settings.raw_contract.model_copy(update={"raw": raw})
    settings_no_run_id = settings.model_copy(update={"raw_contract": raw_contract})

    table_name = next(iter(settings_no_run_id.raw.tables))
    contract = settings_no_run_id.raw_table(table_name)
    name = _build_gcs_object_name(settings_no_run_id, table_name, contract, run_context)

    assert "run_id=" not in name
    assert f"dt={run_context.run_date}" in name
    assert name.endswith(contract.file_name)


def test_build_gcs_uri() -> None:
    """gs://bucket/object is well-formed for BigQuery consumption."""
    uri = _build_gcs_uri(
        "test-bucket",
        "raw/customers/dt=2024-06-01/file.parquet",
    )
    assert uri == "gs://test-bucket/raw/customers/dt=2024-06-01/file.parquet"
