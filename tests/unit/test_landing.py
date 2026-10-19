"""Unit tests for landing fetch/seed APIs (mocked GCS, no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import GoogleAPIError

from src.load.landing import (
    LandingFetchBatchFailedError,
    LandingSeedBatchFailedError,
    fetch_all_raw_tables_from_gcs,
    fetch_all_raw_tables_from_gcs_or_raise,
    seed_all_raw_tables_to_gcs_landing,
    seed_all_raw_tables_to_gcs_landing_or_raise,
)
from src.settings import AppSettings


def _mock_storage_client() -> MagicMock:
    """GCS client whose blob methods are no-ops until a test overrides them."""
    client = MagicMock()
    client.bucket.return_value.blob.return_value = MagicMock()
    return client


def test_fetch_all_writes_landing_objects_to_dest_dir(
    settings: AppSettings,
    tmp_path: Path,
) -> None:
    """Happy-path fetch downloads each contract file under dest_dir."""
    client = _mock_storage_client()
    blob = client.bucket.return_value.blob.return_value

    def _download(file_path: str | Path, **_kwargs: object) -> None:
        Path(file_path).write_bytes(b"parquet-bytes")

    blob.download_to_filename.side_effect = _download
    dest_dir = tmp_path / "fetched"

    with patch("src.load.landing._build_storage_client", return_value=client):
        report = fetch_all_raw_tables_from_gcs(settings, dest_dir)

    assert report.all_succeeded is True
    assert set(report.fetches_ok) == set(settings.raw.tables)
    for table_name, result in report.fetches_ok.items():
        contract = settings.raw_table(table_name)
        assert result.object_name == f"landing/{contract.file_name}"
        assert result.gs_uri == f"gs://test-bucket/landing/{contract.file_name}"
        assert "run_id=" not in result.object_name
        assert result.local_path.is_file()
        blob_name = client.bucket.return_value.blob.call_args.args[0]
        assert blob_name == f"landing/{contract.file_name}"


def test_fetch_all_collects_failures_and_or_raise(
    settings: AppSettings,
    tmp_path: Path,
) -> None:
    """A GCS error on download is collected; _or_raise surfaces the batch error."""
    client = _mock_storage_client()
    blob = client.bucket.return_value.blob.return_value
    blob.download_to_filename.side_effect = GoogleAPIError("not found")

    with patch("src.load.landing._build_storage_client", return_value=client):
        report = fetch_all_raw_tables_from_gcs(settings, tmp_path / "fetched")
        assert report.all_succeeded is False
        assert set(report.fetches_failed) == set(settings.raw.tables)

        with pytest.raises(LandingFetchBatchFailedError) as exc_info:
            fetch_all_raw_tables_from_gcs_or_raise(settings, tmp_path / "fetched")

    assert set(exc_info.value.report.fetches_failed) == set(settings.raw.tables)
    assert "customers" in str(exc_info.value)


@pytest.mark.usefixtures("raw_sources")
def test_seed_all_uploads_to_landing_not_raw(settings: AppSettings) -> None:
    """Seed writes gs://bucket/landing/<file>, never the versioned raw/ layout."""
    client = _mock_storage_client()
    blob = client.bucket.return_value.blob.return_value

    with patch("src.load.landing._build_storage_client", return_value=client):
        report = seed_all_raw_tables_to_gcs_landing(settings)

    assert report.all_succeeded is True
    assert set(report.seeds_ok) == set(settings.raw.tables)
    for table_name, result in report.seeds_ok.items():
        contract = settings.raw_table(table_name)
        assert result.object_name == f"landing/{contract.file_name}"
        assert result.gs_uri == f"gs://test-bucket/landing/{contract.file_name}"
        assert result.object_name.startswith("landing/")
        assert not result.object_name.startswith("raw/")
        assert "run_id=" not in result.object_name

    uploaded_object = client.bucket.return_value.blob.call_args.args[0]
    assert uploaded_object == "landing/customers.parquet"
    blob.upload_from_filename.assert_called()
    uploaded_path = Path(blob.upload_from_filename.call_args.args[0])
    assert uploaded_path == settings.raw_file_path("customers")


def test_seed_or_raise_when_local_dump_missing(settings: AppSettings) -> None:
    """Missing local dumps become LandingSeedBatchFailedError, not a GCS call."""
    client = _mock_storage_client()

    with patch("src.load.landing._build_storage_client", return_value=client):
        with pytest.raises(LandingSeedBatchFailedError) as exc_info:
            seed_all_raw_tables_to_gcs_landing_or_raise(settings)

    assert "customers" in exc_info.value.report.seeds_failed
    client.bucket.return_value.blob.return_value.upload_from_filename.assert_not_called()
