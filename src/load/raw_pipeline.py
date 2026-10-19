"""Orchestrate the raw pipeline: optional landing fetch, validate, enrich, upload, load.

This module is the single high-level entry point for a local/manual run. It only
coordinates: the real work lives in ``landing`` (GCS dump fetch when
``RAW_SOURCE=gcs``), ``raw_validation`` (validate), ``prepare`` (technical
metadata), ``gcs`` (upload) and ``bigquery`` (load). Each stage uses its
``_or_raise`` variant, so a failure in any stage stops the run before the
next one (fail-fast between stages).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from src.load.bigquery import (
    BigQueryBatchLoadReport,
    load_all_raw_tables_from_gcs_to_bigquery_or_raise,
)
from src.load.gcs import GcsBatchUploadReport, upload_all_raw_tables_to_gcs_or_raise
from src.load.landing import fetch_all_raw_tables_from_gcs_or_raise
from src.load.prepare import RawPrepareBatchReport, prepare_all_raw_tables_or_raise
from src.logging_config import get_run_logger
from src.settings import (
    AppSettings,
    PipelineRunContext,
    build_local_run_context,
    get_settings,
)
from src.validation.raw_validation import (
    RawValidationReport,
    validate_raw_inputs_or_raise,
)


@dataclass(slots=True)
class RawPipelineRunReport:
    """Full result of one raw pipeline run, with the per-stage reports."""

    run_context: PipelineRunContext
    validation_report: RawValidationReport
    prepare_report: RawPrepareBatchReport
    gcs_report: GcsBatchUploadReport
    bq_report: BigQueryBatchLoadReport

    @property
    def all_succeeded(self) -> bool:
        """Return True when every stage of the run succeeded."""
        return (
            self.validation_report.all_valid
            and self.prepare_report.all_succeeded
            and self.gcs_report.all_succeeded
            and self.bq_report.all_succeeded
        )


def run_raw_load_pipeline(
    settings: AppSettings | None = None,
    run_context: PipelineRunContext | None = None,
) -> RawPipelineRunReport:
    """Run the raw pipeline: optional fetch, then validate → prepare → upload → load."""
    settings = settings or get_settings()
    run_context = run_context or build_local_run_context()

    logger = get_run_logger(__name__, run_context.run_id, run_context.run_date)
    start = time.monotonic()
    logger.info("pipeline start")

    with TemporaryDirectory(prefix="raw_source_") as source_dir:
        if settings.env.raw_source == "gcs":
            fetch_report = fetch_all_raw_tables_from_gcs_or_raise(
                settings,
                Path(source_dir),
            )
            settings = settings.model_copy(
                update={"local_raw_dir": Path(source_dir)},
            )
            logger.info("stage fetch ok (%s tables)", len(fetch_report.fetches_ok))

        validation_report = validate_raw_inputs_or_raise(settings)
        logger.info(
            "stage validate ok (%s/%s tables)",
            validation_report.valid_table_count,
            validation_report.validated_table_count,
        )

        with TemporaryDirectory(prefix="raw_prepare_") as tmp_dir:
            prepare_report = prepare_all_raw_tables_or_raise(
                settings,
                run_context,
                Path(tmp_dir),
            )
            logger.info("stage prepare ok (%s tables)", len(prepare_report.prepared_ok))

            gcs_report = upload_all_raw_tables_to_gcs_or_raise(
                settings,
                prepare_report.prepared_paths,
                run_context,
            )
            logger.info("stage gcs ok (%s tables)", len(gcs_report.uploads_ok))

        bq_report = load_all_raw_tables_from_gcs_to_bigquery_or_raise(
            settings, gcs_report
        )
        logger.info("stage bigquery ok (%s tables)", len(bq_report.loads_ok))

        report = RawPipelineRunReport(
            run_context=run_context,
            validation_report=validation_report,
            prepare_report=prepare_report,
            gcs_report=gcs_report,
            bq_report=bq_report,
        )

        logger.info(
            "pipeline end status=%s duration_s=%.2f",
            "ok" if report.all_succeeded else "failed",
            time.monotonic() - start,
        )

        return report
