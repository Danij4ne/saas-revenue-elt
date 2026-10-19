"""Load and validate runtime configuration from .env and YAML contracts."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT_REQUIRED_FILE_MARKERS = (Path("config/raw_contract.yaml"),)

PROJECT_ROOT_CONFIRMING_FILE_MARKERS = (Path("pyproject.toml"),)

PROJECT_ROOT_CONFIRMING_PATH_MARKERS = (Path(".git"),)

DEFAULT_ENV_FILE = Path(".env")
DEFAULT_RAW_CONTRACT_FILE = Path("config/raw_contract.yaml")
DEFAULT_RUNTIME_CONFIG_FILE = Path("config/runtime.yaml")


class _SettingsBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RawTableContract(_SettingsBaseModel):
    description: str
    grain: str
    file_name: str
    bq_table: str
    required_columns: list[str] = Field(min_length=1)


class GcsLayoutConfig(_SettingsBaseModel):
    strategy: Literal["partitioned_by_run_date_and_run_id"]
    date_partition_key: Literal["dt"]
    include_run_id: bool = True


class RawLoadMetadataConfig(_SettingsBaseModel):
    include_run_date: bool = True
    include_run_id: bool = True
    include_ingested_at: bool = True


class RawConfig(_SettingsBaseModel):
    local_base_dir: Path
    file_format: Literal["parquet"]
    gcs_prefix: str
    landing_gcs_prefix: str
    gcs_layout: GcsLayoutConfig
    load_metadata: RawLoadMetadataConfig
    default_write_disposition: Literal[
        "WRITE_TRUNCATE",
        "WRITE_APPEND",
        "WRITE_EMPTY",
    ]
    tables: dict[str, RawTableContract] = Field(min_length=1)


class RawContract(_SettingsBaseModel):
    raw: RawConfig


@dataclass(slots=True, frozen=True)
class PipelineRunContext:
    """Identify one pipeline execution for GCS layout and BigQuery load metadata."""

    run_date: date
    run_id: str


def build_local_run_context(run_date: date | None = None) -> PipelineRunContext:
    """Build a run context for local/manual pipeline execution.

    ``run_date`` overrides the logical date (backfill/reprocess of a past day).
    ``run_id`` is always derived from the wall clock, so re-running a past
    ``run_date`` still yields a new, immutable run instead of overwriting it.
    """
    now = datetime.now()
    return PipelineRunContext(
        run_date=run_date or now.date(),
        run_id=f"local-{now:%Y%m%d-%H%M%S}",
    )


class RetryDefaultsConfig(_SettingsBaseModel):
    initial_delay_seconds: float = Field(gt=0)
    max_delay_seconds: float = Field(gt=0)
    multiplier: float = Field(gt=1)


class RetryServiceConfig(_SettingsBaseModel):
    retry_deadline_seconds: float = Field(gt=0)
    operation_timeout_seconds: float = Field(gt=0)


class RetryConfig(_SettingsBaseModel):
    defaults: RetryDefaultsConfig
    gcs: RetryServiceConfig
    bigquery: RetryServiceConfig


class LoggingConfig(_SettingsBaseModel):
    level: str = "INFO"
    file: Path | None = None
    max_bytes: int = Field(default=2_000_000, gt=0)
    backup_count: int = Field(default=5, ge=0)


class RuntimeConfig(_SettingsBaseModel):
    retry: RetryConfig
    logging: LoggingConfig = LoggingConfig()


class EnvSettings(BaseSettings):
    gcp_project_id: str = Field(validation_alias="GCP_PROJECT_ID")
    gcp_location: str = Field(validation_alias="GCP_LOCATION")
    gcs_bucket_name: str = Field(validation_alias="GCS_BUCKET_NAME")
    bigquery_raw_dataset: str = Field(validation_alias="BIGQUERY_RAW_DATASET")
    environment: str = Field(validation_alias="ENVIRONMENT")
    raw_source: Literal["local", "gcs"] = Field(
        default="local",
        validation_alias="RAW_SOURCE",
    )

    model_config = SettingsConfigDict(
        env_file=None,
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )


class AppSettings(_SettingsBaseModel):
    project_root: Path
    env_file: Path | None = None
    raw_contract_file: Path
    runtime_config_file: Path
    local_raw_dir: Path
    env: EnvSettings
    raw_contract: RawContract
    runtime_config: RuntimeConfig

    @property
    def raw(self) -> RawConfig:
        return self.raw_contract.raw

    @property
    def runtime(self) -> RuntimeConfig:
        return self.runtime_config

    @property
    def retry(self) -> RetryConfig:
        return self.runtime.retry

    @property
    def logging(self) -> LoggingConfig:
        return self.runtime.logging

    def raw_table(self, table_name: str) -> RawTableContract:
        """Return the contract for a single raw table."""
        try:
            return self.raw.tables[table_name]
        except KeyError as exc:
            available_tables = ", ".join(sorted(self.raw.tables))
            raise KeyError(
                f"Unknown raw table '{table_name}'. "
                f"Available tables: {available_tables}"
            ) from exc

    def raw_file_path(self, table_name: str) -> Path:
        """Return the absolute local parquet path for a raw table."""
        table = self.raw_table(table_name)
        return (self.local_raw_dir / table.file_name).resolve()


def _path_from_env(var_name: str) -> Path | None:
    """Return a Path from an environment variable, or None if unset."""
    value = os.getenv(var_name)
    if not value or not value.strip():
        return None
    return Path(value.strip()).expanduser()


def _first_existing_file(candidates: Sequence[Path | str | None]) -> Path | None:
    """Return the first existing file from an ordered list of candidates."""
    for candidate in candidates:
        if candidate is None:
            continue

        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_file():
            return candidate_path

    return None


def _resolve_project_path(path: Path | str, project_root: Path) -> Path:
    """Resolve a project-relative path into an absolute path."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def _is_project_root(path: Path) -> bool:
    """Return True when the given path looks like the project root."""
    if not path.is_dir():
        return False

    has_required_files = all(
        (path / marker).is_file() for marker in PROJECT_ROOT_REQUIRED_FILE_MARKERS
    )
    has_confirming_file = any(
        (path / marker).is_file() for marker in PROJECT_ROOT_CONFIRMING_FILE_MARKERS
    )
    has_confirming_path = any(
        (path / marker).exists() for marker in PROJECT_ROOT_CONFIRMING_PATH_MARKERS
    )

    return has_required_files and (has_confirming_file or has_confirming_path)


def _candidate_project_root_paths(base_dir: Path | str | None = None) -> list[Path]:
    """Build ordered candidate paths for the project root."""
    candidates: list[Path] = []

    if base_dir is not None:
        candidates.append(Path(base_dir).expanduser())

    env_base_dir = _path_from_env("SAAS_REVENUE_ELT_BASE_DIR")
    if env_base_dir is not None:
        candidates.append(env_base_dir)

    return candidates


def _search_upwards_for_project_root(start_dir: Path) -> Path | None:
    """Search upwards from a starting directory for the first valid project root."""
    resolved_start_dir = start_dir.resolve()

    for candidate in (resolved_start_dir, *resolved_start_dir.parents):
        if _is_project_root(candidate):
            return candidate

    return None


def find_project_root(base_dir: Path | str | None = None) -> Path:
    """Resolve project root via explicit path, env, search-upwards, or fallback."""
    for candidate in _candidate_project_root_paths(base_dir=base_dir):
        candidate = candidate.resolve()
        if candidate.is_dir() and _is_project_root(candidate):
            return candidate

    start_dir = Path(__file__).resolve().parent
    searched_root = _search_upwards_for_project_root(start_dir)
    if searched_root is not None:
        return searched_root

    return Path(__file__).resolve().parents[1]


def _candidate_env_files(
    explicit_env_file: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> list[Path]:
    """Build ordered candidate paths for the local .env file."""
    candidates: list[Path] = []

    if explicit_env_file is not None:
        candidates.append(Path(explicit_env_file).expanduser())

    env_path = _path_from_env("SAAS_REVENUE_ELT_ENV_FILE")
    if env_path is not None:
        candidates.append(env_path)

    project_root = find_project_root(base_dir=base_dir)
    candidates.append(project_root / DEFAULT_ENV_FILE)

    return candidates


def find_env_file(
    explicit_env_file: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> Path | None:
    """Resolve the local .env file or return None when it does not exist."""
    return _first_existing_file(
        _candidate_env_files(
            explicit_env_file=explicit_env_file,
            base_dir=base_dir,
        )
    )


def _candidate_raw_contract_files(
    explicit_raw_contract_file: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> list[Path]:
    """Build ordered candidate paths for the raw contract YAML file."""
    candidates: list[Path] = []

    if explicit_raw_contract_file is not None:
        candidates.append(Path(explicit_raw_contract_file).expanduser())

    env_path = _path_from_env("SAAS_REVENUE_ELT_RAW_CONTRACT_FILE")
    if env_path is not None:
        candidates.append(env_path)

    project_root = find_project_root(base_dir=base_dir)
    candidates.append(project_root / DEFAULT_RAW_CONTRACT_FILE)

    return candidates


def _candidate_runtime_config_files(
    explicit_runtime_config_file: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> list[Path]:
    """Build ordered candidate paths for the runtime YAML file."""
    candidates: list[Path] = []

    if explicit_runtime_config_file is not None:
        candidates.append(Path(explicit_runtime_config_file).expanduser())

    env_path = _path_from_env("SAAS_REVENUE_ELT_RUNTIME_CONFIG_FILE")
    if env_path is not None:
        candidates.append(env_path)

    project_root = find_project_root(base_dir=base_dir)
    candidates.append(project_root / DEFAULT_RUNTIME_CONFIG_FILE)

    return candidates


def find_raw_contract_file(
    explicit_raw_contract_file: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> Path:
    """Resolve the raw contract file or raise an error if it cannot be found."""
    candidates = _candidate_raw_contract_files(
        explicit_raw_contract_file=explicit_raw_contract_file,
        base_dir=base_dir,
    )
    raw_contract_file = _first_existing_file(candidates)

    if raw_contract_file is not None:
        return raw_contract_file

    checked_paths = ", ".join(
        str(Path(candidate).expanduser()) for candidate in candidates
    )
    raise FileNotFoundError(
        f"Could not find raw contract file. Checked: {checked_paths}"
    )


def find_runtime_config_file(
    explicit_runtime_config_file: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> Path:
    """Resolve the runtime config file or raise an error if it cannot be found."""
    candidates = _candidate_runtime_config_files(
        explicit_runtime_config_file=explicit_runtime_config_file,
        base_dir=base_dir,
    )
    runtime_config_file = _first_existing_file(candidates)

    if runtime_config_file is not None:
        return runtime_config_file

    checked_paths = ", ".join(
        str(Path(candidate).expanduser()) for candidate in candidates
    )
    raise FileNotFoundError(
        f"Could not find runtime config file. Checked: {checked_paths}"
    )


def _load_yaml_dict(yaml_file: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary."""
    with yaml_file.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected YAML object at the root of {yaml_file}, "
            f"got {type(data).__name__}."
        )

    return data


def _load_raw_contract(raw_contract_file: Path) -> RawContract:
    """Load and validate the raw contract YAML file."""
    raw_contract_dict = _load_yaml_dict(raw_contract_file)
    return RawContract.model_validate(raw_contract_dict)


def _load_runtime_config(runtime_config_file: Path) -> RuntimeConfig:
    """Load and validate the runtime YAML file."""
    runtime_config_dict = _load_yaml_dict(runtime_config_file)
    return RuntimeConfig.model_validate(runtime_config_dict)


def _load_env_settings(env_file: Path | None) -> EnvSettings:
    """Load and validate environment settings from a .env file and process env."""
    return EnvSettings(_env_file=env_file)  # type: ignore[call-arg]  # Pylance doesn't recognize _env_file from BaseSettings.


def _normalize_cache_key_path(path: Path | str | None) -> str | None:
    """Normalize a path into a stable cache key string."""
    if path is None:
        return None

    raw_value = str(path).strip()
    if not raw_value:
        return None

    return str(Path(raw_value).expanduser().resolve())


@lru_cache(maxsize=1)
def _get_settings_cached(
    base_dir: str | None = None,
    env_file: str | None = None,
    raw_contract_file: str | None = None,
    runtime_config_file: str | None = None,
) -> AppSettings:
    """Load the complete project settings and cache the resulting object."""
    project_root = find_project_root(base_dir=base_dir)
    resolved_env_file = find_env_file(
        explicit_env_file=env_file,
        base_dir=project_root,
    )
    resolved_raw_contract_file = find_raw_contract_file(
        explicit_raw_contract_file=raw_contract_file,
        base_dir=project_root,
    )
    resolved_runtime_config_file = find_runtime_config_file(
        explicit_runtime_config_file=runtime_config_file,
        base_dir=project_root,
    )

    env_settings = _load_env_settings(resolved_env_file)
    raw_contract = _load_raw_contract(resolved_raw_contract_file)
    runtime_config = _load_runtime_config(resolved_runtime_config_file)
    local_raw_dir = _resolve_project_path(raw_contract.raw.local_base_dir, project_root)
    if runtime_config.logging.file is not None:
        resolved_log = _resolve_project_path(runtime_config.logging.file, project_root)
        runtime_config = runtime_config.model_copy(
            update={
                "logging": runtime_config.logging.model_copy(
                    update={"file": resolved_log}
                )
            }
        )

    return AppSettings(
        project_root=project_root.resolve(),
        env_file=resolved_env_file.resolve() if resolved_env_file is not None else None,
        raw_contract_file=resolved_raw_contract_file.resolve(),
        runtime_config_file=resolved_runtime_config_file.resolve(),
        local_raw_dir=local_raw_dir,
        env=env_settings,
        raw_contract=raw_contract,
        runtime_config=runtime_config,
    )


def get_settings(
    base_dir: Path | str | None = None,
    env_file: Path | str | None = None,
    raw_contract_file: Path | str | None = None,
    runtime_config_file: Path | str | None = None,
) -> AppSettings:
    """Return the typed application settings for the project."""
    return _get_settings_cached(
        base_dir=_normalize_cache_key_path(base_dir),
        env_file=_normalize_cache_key_path(env_file),
        raw_contract_file=_normalize_cache_key_path(raw_contract_file),
        runtime_config_file=_normalize_cache_key_path(runtime_config_file),
    )


def clear_settings_cache() -> None:
    """Clear the cached settings object."""
    _get_settings_cached.cache_clear()
