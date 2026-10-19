"""Unit tests for landing URI helpers (no network)."""

from __future__ import annotations

from src.load.landing import _build_landing_gs_uri, _build_landing_object_name
from src.settings import AppSettings


def test_build_landing_object_name_is_flat_prefix(
    settings: AppSettings,
) -> None:
    """Landing path is prefix/file.parquet, not raw/dt=/run_id=."""
    table_name = next(iter(settings.raw.tables))
    contract = settings.raw_table(table_name)

    name = _build_landing_object_name(settings, contract)

    assert name == f"{settings.raw.landing_gcs_prefix}/{contract.file_name}"
    assert "run_id=" not in name
    assert "/dt=" not in name
    assert settings.raw.gcs_prefix not in name.split("/")[0]


def test_build_landing_gs_uri() -> None:
    """gs://bucket/landing/file is well-formed."""
    uri = _build_landing_gs_uri("test-bucket", "landing/customers.parquet")
    assert uri == "gs://test-bucket/landing/customers.parquet"
