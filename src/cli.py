"""Command-line entrypoint for the ELT pipeline.

This is a thin adapter: it parses arguments, builds the ``PipelineRunContext``
and delegates to ``run_raw_load_pipeline``, ``seed-landing``, and (for
``run-all``) to the dbt CLI. It holds no load or metric logic. Airflow
and Cloud Run invoke the same commands instead of importing
``src`` internals.

Usage:
    python -m src run-raw-load
    python -m src run-raw-load --run-date 2024-06-01
    python -m src run-all
    python -m src run-all --run-date 2024-06-01
    python -m src seed-landing
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from src.load.bigquery import BigQueryBatchLoadFailedError
from src.load.gcs import GcsBatchUploadFailedError
from src.load.landing import (
    LandingFetchBatchFailedError,
    LandingSeedBatchFailedError,
    seed_all_raw_tables_to_gcs_landing_or_raise,
)
from src.load.prepare import RawPrepareBatchFailedError
from src.load.raw_pipeline import run_raw_load_pipeline
from src.logging_config import setup_logging
from src.settings import build_local_run_context, find_project_root
from src.validation.raw_validation import RawValidationFailedError

RUN_RAW_LOAD_COMMAND = "run-raw-load"
RUN_ALL_COMMAND = "run-all"
SEED_LANDING_COMMAND = "seed-landing"

# Errors the pipeline raises on an expected, per-stage failure. They already
# carry pipeline context (table, run_id, uri...), so the CLI turns them into a
# clean message + exit code 1. Anything else is unexpected and propagates with
# its full traceback.
PIPELINE_STAGE_ERRORS = (
    RawValidationFailedError,
    RawPrepareBatchFailedError,
    GcsBatchUploadFailedError,
    BigQueryBatchLoadFailedError,
    LandingFetchBatchFailedError,
    LandingSeedBatchFailedError,
)


class DbtBuildFailedError(Exception):
    """Raised when ``dbt build`` exits non-zero (expected operator failure)."""

    def __init__(self, returncode: int, command: tuple[str, ...]) -> None:
        self.returncode = returncode
        self.command = command
        super().__init__(
            f"dbt build failed with exit code {returncode}: {' '.join(command)}"
        )


def _add_run_date_argument(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--run-date`` flag used by load and run-all."""
    parser.add_argument(
        "--run-date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Logical run date for backfill/reprocess (ISO format). "
            "Defaults to today. Re-running a past date creates a new run_id."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with one subcommand per pipeline entrypoint."""
    parser = argparse.ArgumentParser(
        prog="python -m src",
        description="ELT pipeline commands (raw load and optional dbt build).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_raw_load = subparsers.add_parser(
        RUN_RAW_LOAD_COMMAND,
        help="Validate, prepare, upload to GCS and load raw tables into BigQuery.",
    )
    _add_run_date_argument(run_raw_load)

    run_all = subparsers.add_parser(
        RUN_ALL_COMMAND,
        help="Run raw load then dbt build (image default / Cloud Run).",
    )
    _add_run_date_argument(run_all)

    subparsers.add_parser(
        SEED_LANDING_COMMAND,
        help=(
            "Copy local dumps to gs://<lake>/landing/ (no metadata). "
            "Bootstrap for RAW_SOURCE=gcs; not part of run-all."
        ),
    )

    return parser


def _run_raw_load(run_date: date | None) -> int:
    """Execute the raw load pipeline; map expected failures to exit code 1."""
    run_context = build_local_run_context(run_date=run_date)
    try:
        report = run_raw_load_pipeline(run_context=run_context)
    except PIPELINE_STAGE_ERRORS as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        return 1
    return 0 if report.all_succeeded else 1


def _dbt_executable() -> Path:
    """Resolve the dbt CLI from this Python's venv, then from PATH."""
    bin_dir = Path(sys.executable).resolve().parent
    for name in ("dbt.exe", "dbt"):
        candidate = bin_dir / name
        if candidate.is_file():
            return candidate
    found = shutil.which("dbt")
    if found is None:
        raise FileNotFoundError(
            "dbt executable not found next to the Python interpreter or on PATH. "
            "Install project dependencies (uv sync) so dbt-bigquery provides dbt."
        )
    return Path(found)


def _run_dbt_build(project_root: Path) -> None:
    """Run ``dbt build`` for this repo; raise if dbt exits non-zero."""
    command = (
        str(_dbt_executable()),
        "build",
        "--project-dir",
        str(project_root / "dbt_project"),
    )
    completed = subprocess.run(command, cwd=project_root, check=False)
    if completed.returncode != 0:
        raise DbtBuildFailedError(completed.returncode, command)


def _run_all(run_date: date | None) -> int:
    """Load raw then dbt build; skip dbt if the load already failed."""
    load_exit = _run_raw_load(run_date)
    if load_exit != 0:
        return load_exit
    try:
        _run_dbt_build(find_project_root())
    except (DbtBuildFailedError, FileNotFoundError) as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        return 1
    return 0


def _seed_landing() -> int:
    """Copy local dumps to the lake landing prefix; map expected failures to 1."""
    try:
        report = seed_all_raw_tables_to_gcs_landing_or_raise()
    except PIPELINE_STAGE_ERRORS as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        return 1
    return 0 if report.all_succeeded else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the matching command; return exit code."""
    setup_logging()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == RUN_RAW_LOAD_COMMAND:
        return _run_raw_load(args.run_date)
    if args.command == RUN_ALL_COMMAND:
        return _run_all(args.run_date)
    if args.command == SEED_LANDING_COMMAND:
        return _seed_landing()

    parser.error(f"Unknown command: {args.command}")
    return 2
