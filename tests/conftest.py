"""Shared fixtures for unit and integration tests (no real GCP, no .env)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.settings import (
    AppSettings,
    EnvSettings,
    GcsLayoutConfig,
    PipelineRunContext,
    RawConfig,
    RawContract,
    RawLoadMetadataConfig,
    RawTableContract,
    RetryConfig,
    RetryDefaultsConfig,
    RetryServiceConfig,
    RuntimeConfig,
)


def _make_fake_env() -> EnvSettings:
    """Build fake EnvSettings without reading .env or calling get_settings()."""
    # validation_alias requires GCP_* kwargs at runtime; pyright expects field names.
    return EnvSettings(  # type: ignore[call-arg]
        GCP_PROJECT_ID="test-project",  # type: ignore[call-arg]
        GCP_LOCATION="EU",  # type: ignore[call-arg]
        GCS_BUCKET_NAME="test-bucket",  # type: ignore[call-arg]
        BIGQUERY_RAW_DATASET="raw",  # type: ignore[call-arg]
        ENVIRONMENT="test",  # type: ignore[call-arg]
    )


def _make_fake_runtime() -> RuntimeConfig:
    """Build a minimal RuntimeConfig (retry) for tests without reading runtime.yaml."""
    defaults = RetryDefaultsConfig(
        initial_delay_seconds=1.0,
        max_delay_seconds=60.0,
        multiplier=2.0,
    )
    gcs = RetryServiceConfig(
        retry_deadline_seconds=120.0,
        operation_timeout_seconds=60.0,
    )
    bigquery = RetryServiceConfig(
        retry_deadline_seconds=600.0,
        operation_timeout_seconds=300.0,
    )
    retry = RetryConfig(defaults=defaults, gcs=gcs, bigquery=bigquery)
    return RuntimeConfig(retry=retry)


def _make_min_raw_contract(local_base_dir: Path) -> RawContract:
    """Build a minimal RawContract (customers only) under local_base_dir."""
    customers = RawTableContract(
        description="Customer master data with one row per customer company.",
        grain="one row per customer_id",
        file_name="customers.parquet",
        bq_table="customers",
        required_columns=[
            "customer_id",
            "company_name",
            "country",
            "industry",
            "company_size",
            "created_at",
            "is_deleted",
        ],
    )
    raw = RawConfig(
        local_base_dir=local_base_dir,
        file_format="parquet",
        gcs_prefix="raw",
        landing_gcs_prefix="landing",
        gcs_layout=GcsLayoutConfig(
            strategy="partitioned_by_run_date_and_run_id",
            date_partition_key="dt",
            include_run_id=True,
        ),
        load_metadata=RawLoadMetadataConfig(
            include_run_date=True,
            include_run_id=True,
            include_ingested_at=True,
        ),
        default_write_disposition="WRITE_APPEND",
        tables={"customers": customers},
    )
    return RawContract(raw=raw)


@pytest.fixture
def run_context() -> PipelineRunContext:
    """Fixed PipelineRunContext so tests stay deterministic across runs."""
    return PipelineRunContext(run_date=date(2026, 9, 29), run_id="test-run-001")


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    """Build fake AppSettings with a temp local_raw_dir (no .env / get_settings)."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
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


def _write_min_parquet(path: Path, column_names: list[str]) -> None:
    """Write a one-row parquet with the given columns (no _run_* metadata)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({name: ["dummy"] for name in column_names})
    pq.write_table(table, path)


@pytest.fixture
def raw_sources(settings: AppSettings) -> Path:
    """Materialize contract parquets under settings.local_raw_dir for tests."""
    for table_name, table in settings.raw.tables.items():
        _write_min_parquet(
            settings.raw_file_path(table_name),
            table.required_columns,
        )
    return settings.local_raw_dir
