"""Unit tests for settings lookup: tables, project root, cache, missing .env."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.settings import (
    AppSettings,
    clear_settings_cache,
    find_env_file,
    find_project_root,
    get_settings,
)

_DUMMY_ENV = """\
GCP_PROJECT_ID=test-project
GCP_LOCATION=EU
GCS_BUCKET_NAME=test-bucket
BIGQUERY_RAW_DATASET=raw
ENVIRONMENT=test
"""

_MIN_RAW_CONTRACT = {
    "raw": {
        "local_base_dir": "sources",
        "file_format": "parquet",
        "gcs_prefix": "raw",
        "landing_gcs_prefix": "landing",
        "gcs_layout": {
            "strategy": "partitioned_by_run_date_and_run_id",
            "date_partition_key": "dt",
            "include_run_id": True,
        },
        "load_metadata": {
            "include_run_date": True,
            "include_run_id": True,
            "include_ingested_at": True,
        },
        "default_write_disposition": "WRITE_APPEND",
        "tables": {
            "customers": {
                "description": "test customers",
                "grain": "one row per customer_id",
                "file_name": "customers.parquet",
                "bq_table": "customers",
                "required_columns": ["customer_id"],
            }
        },
    }
}

_MIN_RUNTIME = {
    "retry": {
        "defaults": {
            "initial_delay_seconds": 1.0,
            "max_delay_seconds": 60.0,
            "multiplier": 2.0,
        },
        "gcs": {
            "retry_deadline_seconds": 120.0,
            "operation_timeout_seconds": 60.0,
        },
        "bigquery": {
            "retry_deadline_seconds": 600.0,
            "operation_timeout_seconds": 300.0,
        },
    },
    "logging": {
        "level": "INFO",
        "file": None,
        "max_bytes": 2000000,
        "backup_count": 5,
    },
}


@pytest.fixture(autouse=True)
def _isolate_settings_lookup(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Drop override env vars and always clear the settings LRU cache."""
    for var in (
        "SAAS_REVENUE_ELT_BASE_DIR",
        "SAAS_REVENUE_ELT_ENV_FILE",
        "SAAS_REVENUE_ELT_RAW_CONTRACT_FILE",
        "SAAS_REVENUE_ELT_RUNTIME_CONFIG_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    clear_settings_cache()
    yield
    clear_settings_cache()


def _mark_project_root(path: Path) -> Path:
    """Make path look like this repo: required YAML + confirming pyproject.toml."""
    config_dir = path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "raw_contract.yaml").write_text("raw: {}\n", encoding="utf-8")
    (path / "pyproject.toml").write_text('[project]\nname = "fake"\n', encoding="utf-8")
    return path


def _write_fake_project(path: Path, *, with_env: bool) -> Path:
    """Minimal loadable project for get_settings (dummy .env, no GCP)."""
    _mark_project_root(path)
    (path / "sources").mkdir(exist_ok=True)
    (path / "config" / "raw_contract.yaml").write_text(
        yaml.safe_dump(_MIN_RAW_CONTRACT, sort_keys=False),
        encoding="utf-8",
    )
    (path / "config" / "runtime.yaml").write_text(
        yaml.safe_dump(_MIN_RUNTIME, sort_keys=False),
        encoding="utf-8",
    )
    if with_env:
        (path / ".env").write_text(_DUMMY_ENV, encoding="utf-8")
    return path


def test_raw_table_unknown_raises_with_available_names(settings: AppSettings) -> None:
    """Unknown table: KeyError names the typo and lists contract tables."""
    with pytest.raises(KeyError, match="no_existe") as exc:
        settings.raw_table("no_existe")

    assert "customers" in str(exc.value)


def test_find_project_root_uses_marked_base_dir(tmp_path: Path) -> None:
    """Explicit base_dir with contract YAML + pyproject.toml is the root."""
    root = _mark_project_root(tmp_path / "repo")

    assert find_project_root(base_dir=root) == root.resolve()


def test_find_project_root_does_not_treat_empty_dir_as_root(tmp_path: Path) -> None:
    """Unmarked base_dir is skipped; fallback must not be that empty directory."""
    empty = tmp_path / "empty"
    empty.mkdir()

    found = find_project_root(base_dir=empty)

    assert found != empty.resolve()


def test_get_settings_returns_cached_instance_until_cleared(tmp_path: Path) -> None:
    """Same args hit the LRU cache; clear_settings_cache forces a new object."""
    root = _write_fake_project(tmp_path / "repo", with_env=True)
    env_file = root / ".env"

    first = get_settings(base_dir=root, env_file=env_file)
    second = get_settings(base_dir=root, env_file=env_file)
    assert first is second

    clear_settings_cache()
    third = get_settings(base_dir=root, env_file=env_file)
    assert third is not first
    assert third.project_root == first.project_root


def test_find_env_file_missing_explicit_path_returns_none(tmp_path: Path) -> None:
    """Missing explicit .env (and none in the fake root) is None, not an exception."""
    root = _write_fake_project(tmp_path / "repo", with_env=False)
    missing = tmp_path / "does-not-exist.env"

    assert find_env_file(explicit_env_file=missing, base_dir=root) is None


def test_settings_assignment_raises_validation_error(tmp_path: Path) -> None:
    """Cached AppSettings and EnvSettings reject in-place field assignment."""
    root = _write_fake_project(tmp_path / "repo", with_env=True)
    settings = get_settings(base_dir=root, env_file=root / ".env")

    with pytest.raises(ValidationError):
        settings.raw.gcs_prefix = "otro"

    with pytest.raises(ValidationError):
        settings.env.gcp_project_id = "otro-proyecto"


def test_get_settings_resolves_relative_log_file(tmp_path: Path) -> None:
    """Relative logging.file is resolved against project_root, not mutated in-place."""
    root = _write_fake_project(tmp_path / "repo", with_env=True)
    runtime = {
        **_MIN_RUNTIME,
        "logging": {**_MIN_RUNTIME["logging"], "file": "logs/app.log"},
    }
    (root / "config" / "runtime.yaml").write_text(
        yaml.safe_dump(runtime, sort_keys=False),
        encoding="utf-8",
    )

    settings = get_settings(base_dir=root, env_file=root / ".env")

    assert settings.logging.file == (root / "logs" / "app.log").resolve()
