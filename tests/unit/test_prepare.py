"""Unit tests for prepare: technical metadata columns on parquet."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from src.load.prepare import (
    INGESTED_AT_COLUMN,
    RUN_DATE_COLUMN,
    RUN_ID_COLUMN,
    prepare_all_raw_tables,
    prepare_raw_table,
)
from src.settings import AppSettings, PipelineRunContext


@pytest.mark.usefixtures("raw_sources")
def test_prepare_raw_table_adds_run_metadata(
    settings: AppSettings,
    run_context: PipelineRunContext,
    tmp_path: Path,
) -> None:
    """prepare_raw_table writes parquet with _run_date, _run_id, _ingested_at."""
    dest_dir = tmp_path / "prepared"
    dest_dir.mkdir()
    table_name = next(iter(settings.raw.tables))

    result = prepare_raw_table(settings, table_name, run_context, dest_dir)
    table = pq.read_table(result.prepared_path)

    assert RUN_DATE_COLUMN in table.column_names
    assert RUN_ID_COLUMN in table.column_names
    assert INGESTED_AT_COLUMN in table.column_names
    assert table.column(RUN_DATE_COLUMN).to_pylist() == [run_context.run_date]
    assert table.column(RUN_ID_COLUMN).to_pylist() == [run_context.run_id]


@pytest.mark.usefixtures("raw_sources")
def test_prepare_raw_table_keeps_original_columns(
    settings: AppSettings,
    run_context: PipelineRunContext,
    tmp_path: Path,
) -> None:
    """Original required_columns survive enrichment (prepare only appends metadata)."""
    dest_dir = tmp_path / "prepared"
    dest_dir.mkdir()
    table_name = next(iter(settings.raw.tables))
    required = settings.raw_table(table_name).required_columns

    result = prepare_raw_table(settings, table_name, run_context, dest_dir)
    cols = pq.read_table(result.prepared_path).column_names

    for column in required:
        assert column in cols


@pytest.mark.usefixtures("raw_sources")
def test_prepare_all_raw_tables_batch_ok(
    settings: AppSettings,
    run_context: PipelineRunContext,
    tmp_path: Path,
) -> None:
    """Batch prepare succeeds for all tables in the fake contract."""
    dest_dir = tmp_path / "prepared"
    dest_dir.mkdir()

    report = prepare_all_raw_tables(settings, run_context, dest_dir)

    assert report.all_succeeded is True
    assert set(report.prepared_ok) == set(settings.raw.tables)
