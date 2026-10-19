"""Unit tests for the CLI adapter (parser, dispatch, exit codes)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli import DbtBuildFailedError, _run_dbt_build, build_parser, main
from src.load.landing import LandingSeedBatchFailedError, LandingSeedBatchReport
from src.load.raw_pipeline import RawPipelineRunReport
from src.validation.raw_validation import (
    RawTableValidationResult,
    RawValidationFailedError,
    RawValidationReport,
)


@pytest.fixture
def mute_cli_logging() -> Iterator[None]:
    """Skip setup_logging: it calls get_settings() and CI has no .env."""
    with patch("src.cli.setup_logging"):
        yield


def test_parse_run_raw_load_without_flags() -> None:
    """Parse `run-raw-load` with no flags: command set, run_date is None."""
    parser = build_parser()
    args = parser.parse_args(["run-raw-load"])
    assert args.command == "run-raw-load"
    assert args.run_date is None


def test_parse_run_date_iso() -> None:
    """Parse `--run-date YYYY-MM-DD` into a date object."""
    parser = build_parser()
    args = parser.parse_args(["run-raw-load", "--run-date", "2024-06-01"])
    assert args.run_date == date(2024, 6, 1)


def test_parse_invalid_run_date_exits() -> None:
    """Invalid --run-date must raise SystemExit (argparse), not a bare ValueError."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run-raw-load", "--run-date", "not-a-date"])


def test_parse_run_all_without_flags() -> None:
    """Parse `run-all` with no flags: command set, run_date is None."""
    parser = build_parser()
    args = parser.parse_args(["run-all"])
    assert args.command == "run-all"
    assert args.run_date is None


def test_parse_run_all_run_date_iso() -> None:
    """Parse `run-all --run-date` into a date object."""
    parser = build_parser()
    args = parser.parse_args(["run-all", "--run-date", "2024-06-01"])
    assert args.run_date == date(2024, 6, 1)


def test_parse_seed_landing_without_flags() -> None:
    """Parse `seed-landing` with no flags: command set, no run_date."""
    parser = build_parser()
    args = parser.parse_args(["seed-landing"])
    assert args.command == "seed-landing"
    assert not hasattr(args, "run_date") or args.run_date is None


def test_main_pipeline_ok_exits_zero(mute_cli_logging: None) -> None:
    """When the pipeline succeeds, main returns exit code 0."""
    report = MagicMock(spec=RawPipelineRunReport)
    report.all_succeeded = True
    with patch("src.cli.run_raw_load_pipeline", return_value=report):
        assert main(["run-raw-load"]) == 0


def test_main_pipeline_stage_error_exits_one(mute_cli_logging: None) -> None:
    """Expected stage FailedError maps to exit code 1 (not a crash)."""
    validation_report = RawValidationReport(
        raw_dir=Path("fake-sources"),
        table_results=[
            RawTableValidationResult(
                table_name="customers",
                file_path=Path("fake-sources/customers.parquet"),
                exists=False,
                readable=False,
            )
        ],
    )
    stage_error = RawValidationFailedError(validation_report)
    with patch("src.cli.run_raw_load_pipeline", side_effect=stage_error):
        assert main(["run-raw-load"]) == 1


def test_main_unexpected_error_propagates(mute_cli_logging: None) -> None:
    """Unexpected exceptions must NOT be swallowed by the CLI."""
    with patch(
        "src.cli.run_raw_load_pipeline",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            main(["run-raw-load"])


def test_run_all_runs_dbt_after_successful_load(mute_cli_logging: None) -> None:
    """run-all calls dbt build only after the raw load succeeds."""
    report = MagicMock(spec=RawPipelineRunReport)
    report.all_succeeded = True
    with patch("src.cli.run_raw_load_pipeline", return_value=report):
        with patch("src.cli._run_dbt_build") as dbt_build:
            assert main(["run-all"]) == 0
            dbt_build.assert_called_once()


def test_run_all_skips_dbt_when_load_fails(mute_cli_logging: None) -> None:
    """If raw load fails, run-all must not invoke dbt."""
    report = MagicMock(spec=RawPipelineRunReport)
    report.all_succeeded = False
    with patch("src.cli.run_raw_load_pipeline", return_value=report):
        with patch("src.cli._run_dbt_build") as dbt_build:
            assert main(["run-all"]) == 1
            dbt_build.assert_not_called()


def test_run_all_stage_error_skips_dbt(mute_cli_logging: None) -> None:
    """A load-stage FailedError aborts run-all before dbt."""
    validation_report = RawValidationReport(
        raw_dir=Path("fake-sources"),
        table_results=[
            RawTableValidationResult(
                table_name="customers",
                file_path=Path("fake-sources/customers.parquet"),
                exists=False,
                readable=False,
            )
        ],
    )
    stage_error = RawValidationFailedError(validation_report)
    with patch("src.cli.run_raw_load_pipeline", side_effect=stage_error):
        with patch("src.cli._run_dbt_build") as dbt_build:
            assert main(["run-all"]) == 1
            dbt_build.assert_not_called()


def test_run_all_dbt_failure_exits_one(mute_cli_logging: None) -> None:
    """A non-zero dbt build maps to exit code 1."""
    report = MagicMock(spec=RawPipelineRunReport)
    report.all_succeeded = True
    with patch("src.cli.run_raw_load_pipeline", return_value=report):
        with patch(
            "src.cli._run_dbt_build",
            side_effect=FileNotFoundError("dbt missing"),
        ):
            assert main(["run-all"]) == 1


def test_run_dbt_build_raises_on_nonzero(tmp_path: Path) -> None:
    """A non-zero dbt process becomes DbtBuildFailedError."""
    completed = MagicMock()
    completed.returncode = 2
    with patch("src.cli._dbt_executable", return_value=Path("/usr/bin/dbt")):
        with patch("src.cli.subprocess.run", return_value=completed):
            with pytest.raises(DbtBuildFailedError):
                _run_dbt_build(tmp_path)


def test_seed_landing_ok_exits_zero(mute_cli_logging: None) -> None:
    """seed-landing returns 0 when every dump reaches gs://…/landing/."""
    report = MagicMock()
    report.all_succeeded = True
    with patch(
        "src.cli.seed_all_raw_tables_to_gcs_landing_or_raise",
        return_value=report,
    ) as seed:
        assert main(["seed-landing"]) == 0
        seed.assert_called_once()


def test_seed_landing_stage_error_exits_one(mute_cli_logging: None) -> None:
    """Expected landing seed failure maps to exit code 1 (not a crash)."""
    stage_error = LandingSeedBatchFailedError(
        LandingSeedBatchReport(seeds_ok={}, seeds_failed={"customers": MagicMock()})
    )
    with patch(
        "src.cli.seed_all_raw_tables_to_gcs_landing_or_raise",
        side_effect=stage_error,
    ):
        assert main(["seed-landing"]) == 1


def test_run_all_does_not_seed_landing(mute_cli_logging: None) -> None:
    """run-all must not upload dumps to landing; seed-landing is a separate command."""
    report = MagicMock(spec=RawPipelineRunReport)
    report.all_succeeded = True
    with patch("src.cli.run_raw_load_pipeline", return_value=report):
        with patch("src.cli._run_dbt_build"):
            with patch("src.cli.seed_all_raw_tables_to_gcs_landing_or_raise") as seed:
                assert main(["run-all"]) == 0
                seed.assert_not_called()
