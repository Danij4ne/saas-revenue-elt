"""Integration tests for raw_pipeline orchestration (no real GCP)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import GoogleAPIError

from src.load.gcs import GcsBatchUploadFailedError
from src.load.landing import LandingFetchBatchFailedError, LandingFetchBatchReport
from src.load.prepare import RUN_DATE_COLUMN
from src.load.raw_pipeline import run_raw_load_pipeline
from src.settings import AppSettings, PipelineRunContext
from src.validation.raw_validation import RawValidationFailedError


def _mock_gcs_client() -> MagicMock:
    """GCS client whose upload_from_filename is a no-op."""
    client = MagicMock()
    client.bucket.return_value.blob.return_value = MagicMock()
    return client


def _mock_bq_client(*, rows_loaded: int = 1) -> MagicMock:
    """BigQuery client with a successful load job (no network)."""
    job = MagicMock()
    job.job_id = "test-job-001"
    job.output_rows = rows_loaded
    job.result.return_value = job

    client = MagicMock()
    client.load_table_from_uri.return_value = job
    return client


@pytest.mark.usefixtures("raw_sources")
def test_run_raw_load_pipeline_happy_path(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """Full chain validate -> prepare -> gcs -> bq with cloud clients mocked."""
    mock_gcs = _mock_gcs_client()
    mock_bq = _mock_bq_client()

    with (
        patch("src.load.gcs._build_storage_client", return_value=mock_gcs),
        patch("src.load.bigquery._build_bigquery_client", return_value=mock_bq),
    ):
        report = run_raw_load_pipeline(settings=settings, run_context=run_context)

    assert report.all_succeeded is True
    assert report.run_context == run_context
    assert set(report.gcs_report.uploads_ok) == set(settings.raw.tables)
    assert set(report.bq_report.loads_ok) == set(settings.raw.tables)

    for _table_name, prepare_result in report.prepare_report.prepared_ok.items():
        assert RUN_DATE_COLUMN in prepare_result.added_columns
        assert prepare_result.run_context.run_date == run_context.run_date

    for table_name, load_result in report.bq_report.loads_ok.items():
        gcs_uri = report.gcs_report.uploads_ok[table_name].gs_uri
        assert load_result.source_uri == gcs_uri

    called_uris = [call.args[0] for call in mock_bq.load_table_from_uri.call_args_list]
    expected_uris = [
        report.gcs_report.uploads_ok[name].gs_uri
        for name in sorted(report.gcs_report.uploads_ok)
    ]
    assert called_uris == expected_uris


def test_pipeline_stops_on_validation_failure(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """Missing raw parquets: RawValidationFailedError; GCS/BQ never start."""
    with (
        patch("src.load.gcs._build_storage_client") as mock_gcs_build,
        patch("src.load.bigquery._build_bigquery_client") as mock_bq_build,
    ):
        with pytest.raises(RawValidationFailedError):
            run_raw_load_pipeline(settings=settings, run_context=run_context)

        mock_gcs_build.assert_not_called()
        mock_bq_build.assert_not_called()


@pytest.mark.usefixtures("raw_sources")
def test_pipeline_stops_on_gcs_failure(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """GCS upload failure: GcsBatchUploadFailedError; BigQuery never starts."""
    mock_gcs = _mock_gcs_client()
    mock_gcs.bucket.return_value.blob.return_value.upload_from_filename.side_effect = (
        GoogleAPIError("upload failed")
    )

    with (
        patch("src.load.gcs._build_storage_client", return_value=mock_gcs),
        patch("src.load.bigquery._build_bigquery_client") as mock_bq_build,
    ):
        with pytest.raises(GcsBatchUploadFailedError):
            run_raw_load_pipeline(settings=settings, run_context=run_context)

        mock_bq_build.assert_not_called()


@pytest.mark.usefixtures("raw_sources")
def test_pipeline_skips_fetch_when_raw_source_is_local(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """RAW_SOURCE=local (default) never calls the landing fetch stage."""
    mock_gcs = _mock_gcs_client()
    mock_bq = _mock_bq_client()

    with (
        patch(
            "src.load.raw_pipeline.fetch_all_raw_tables_from_gcs_or_raise"
        ) as mock_fetch,
        patch("src.load.gcs._build_storage_client", return_value=mock_gcs),
        patch("src.load.bigquery._build_bigquery_client", return_value=mock_bq),
    ):
        report = run_raw_load_pipeline(settings=settings, run_context=run_context)

    mock_fetch.assert_not_called()
    assert report.all_succeeded is True


@pytest.mark.usefixtures("raw_sources")
def test_pipeline_fetches_then_validates_when_raw_source_is_gcs(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """RAW_SOURCE=gcs downloads into a temp dir before validate/prepare."""
    env = settings.env.model_copy(update={"raw_source": "gcs"})
    gcs_settings = settings.model_copy(update={"env": env})
    original_dir = settings.local_raw_dir

    def _fake_fetch(_fetch_settings: AppSettings, dest_dir: Path) -> MagicMock:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        for table in gcs_settings.raw.tables.values():
            shutil.copy2(original_dir / table.file_name, dest / table.file_name)
        fetch_report = MagicMock()
        fetch_report.fetches_ok = dict.fromkeys(gcs_settings.raw.tables)
        return fetch_report

    mock_gcs = _mock_gcs_client()
    mock_bq = _mock_bq_client()

    with (
        patch(
            "src.load.raw_pipeline.fetch_all_raw_tables_from_gcs_or_raise",
            side_effect=_fake_fetch,
        ) as mock_fetch,
        patch("src.load.gcs._build_storage_client", return_value=mock_gcs),
        patch("src.load.bigquery._build_bigquery_client", return_value=mock_bq),
    ):
        report = run_raw_load_pipeline(settings=gcs_settings, run_context=run_context)

    mock_fetch.assert_called_once()
    assert report.all_succeeded is True


def test_pipeline_stops_on_fetch_failure(
    settings: AppSettings,
    run_context: PipelineRunContext,
) -> None:
    """Landing fetch failure: LandingFetchBatchFailedError; GCS/BQ never start."""
    env = settings.env.model_copy(update={"raw_source": "gcs"})
    gcs_settings = settings.model_copy(update={"env": env})
    fetch_error = LandingFetchBatchFailedError(
        LandingFetchBatchReport(
            fetches_ok={}, fetches_failed={"customers": MagicMock()}
        )
    )

    with (
        patch(
            "src.load.raw_pipeline.fetch_all_raw_tables_from_gcs_or_raise",
            side_effect=fetch_error,
        ),
        patch("src.load.gcs._build_storage_client") as mock_gcs_build,
        patch("src.load.bigquery._build_bigquery_client") as mock_bq_build,
    ):
        with pytest.raises(LandingFetchBatchFailedError):
            run_raw_load_pipeline(settings=gcs_settings, run_context=run_context)

        mock_gcs_build.assert_not_called()
        mock_bq_build.assert_not_called()
