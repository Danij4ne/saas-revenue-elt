"""Local Airflow DAG : coordinate raw load then dbt, without business logic.

Each task launches the app image (``saas-revenue-app``) via DockerOperator.
Airflow does not import ``src``; it only sequences commands the CLI already
exposes. Cloud Run keeps using ``run-all`` as a single process.

Host paths (repo, ADC) come from ``.env.airflow`` — see
``.env.airflow.example``. The dbt profile is baked into the app image
(``DBT_PROFILES_DIR=/app/dbt_profiles``; DECISIONS #16).
Triggering this DAG talks to real GCS/BigQuery.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import DAG
from docker.types import Mount

logger = logging.getLogger(__name__)

APP_IMAGE = "saas-revenue-app"
APP_WORKDIR = "/app"
# Parent /app exists in the app image; bind-mounting a file requires that parent.
ADC_IN_CONTAINER = "/app/adc.json"
DOTENV_IN_CONTAINER = "/app/.env"
SOURCES_IN_CONTAINER = "/app/data/sources"

# dbt does not read /app/.env by itself (local CLI uses `uv run --env-file .env`).
# python-dotenv is already an app-image dependency (pydantic-settings). It tolerates
# Windows CRLF; `sh . /app/.env` would not. Airflow never sees those values.
_DBT_WITH_DOTENV = (
    "from dotenv import load_dotenv; import subprocess, sys; "
    f"load_dotenv({DOTENV_IN_CONTAINER!r}); "
    "raise SystemExit(subprocess.call(sys.argv[1:]))"
)


def _join_host(base: str, *parts: str) -> str:
    """Join host path segments without pathlib.

    The DAG parses inside a Linux container; the Docker daemon is on the host
    (Windows or Unix). pathlib would mangle ``C:\\Users\\...``.
    """
    windows = "\\" in base or (len(base) >= 2 and base[1] == ":")
    sep = "\\" if windows else "/"
    chunks = [base.rstrip("/\\"), *[part.strip("/\\") for part in parts]]
    return sep.join(chunks)


def _bind_mounts() -> list[Mount]:
    """Bind host runtime files into the app image. Empty env vars → omit that mount.

    The DAG still parses if paths are unset (it is created paused). A
    triggered run fails at Docker if a required file is missing.
    """
    mounts: list[Mount] = []
    project_dir = os.environ.get("HOST_PROJECT_DIR", "").strip()
    if project_dir:
        mounts.append(
            Mount(
                source=_join_host(project_dir, ".env"),
                target=DOTENV_IN_CONTAINER,
                type="bind",
                read_only=True,
            )
        )
        mounts.append(
            Mount(
                source=_join_host(project_dir, "data", "sources"),
                target=SOURCES_IN_CONTAINER,
                type="bind",
                read_only=True,
            )
        )
    # Profile is baked in the app image (DECISIONS #16). Do not mount ~/.dbt:
    # DBT_PROFILES_DIR=/app/dbt_profiles wins over HOME. env_var()
    # resolves GCP_PROJECT_ID from the mounted .env (DECISIONS #16).
    adc_path = os.environ.get("HOST_GCP_ADC", "").strip()
    if adc_path:
        mounts.append(
            Mount(
                source=adc_path,
                target=ADC_IN_CONTAINER,
                type="bind",
                read_only=True,
            )
        )
    return mounts


def _app_environment() -> dict[str, str]:
    """Env for the app container. GCP project/bucket stay in the mounted ``.env``."""
    if not os.environ.get("HOST_GCP_ADC", "").strip():
        return {}
    return {"GOOGLE_APPLICATION_CREDENTIALS": ADC_IN_CONTAINER}


def _log_task_failure(context: dict) -> None:
    """Local alert: one error line in Airflow logs. Paging is the Cloud Run alert."""
    ti = context["ti"]
    logger.error(
        "raw_to_marts failed dag_id=%s task_id=%s run_id=%s ds=%s",
        ti.dag_id,
        ti.task_id,
        ti.run_id,
        context.get("ds"),
    )


def _app_task(
    *,
    task_id: str,
    command: list[str],
    retries: int,
) -> DockerOperator:
    """One app container. ``command`` replaces the image CMD (``run-all``)."""
    return DockerOperator(
        task_id=task_id,
        image=APP_IMAGE,
        command=command,
        docker_url="unix://var/run/docker.sock",
        mount_tmp_dir=False,
        mounts=_bind_mounts(),
        environment=_app_environment(),
        auto_remove="force",
        force_pull=False,
        working_dir=APP_WORKDIR,
        network_mode="bridge",
        retries=retries,
    )


with DAG(
    dag_id="raw_to_marts",
    description="Raw load then dbt (seeds/snapshots/models) then dbt tests.",
    start_date=datetime(2026, 8, 25, tzinfo=UTC),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data",
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": _log_task_failure,
    },
    tags=["elt", "raw", "marts"],
    doc_md=(
        "Paused at creation (`DAGS_ARE_PAUSED_AT_CREATION`). Unpause or trigger "
        "only with explicit OK: tasks hit GCS and BigQuery. "
        "Build `saas-revenue-app` on the host first. "
        "`--run-date` is Airflow `ds`; `run_id` is still minted by the CLI."
    ),
) as dag:
    raw_load = _app_task(
        task_id="raw_load",
        command=[
            "python",
            "-m",
            "src",
            "run-raw-load",
            "--run-date",
            "{{ ds }}",
        ],
        retries=2,
    )
    dbt_transform = _app_task(
        task_id="dbt_transform",
        command=[
            "python",
            "-c",
            _DBT_WITH_DOTENV,
            "dbt",
            "build",
            "--project-dir",
            "dbt_project",
            "--exclude-resource-type",
            "test",
        ],
        retries=1,
    )
    dbt_test = _app_task(
        task_id="dbt_test",
        command=[
            "python",
            "-c",
            _DBT_WITH_DOTENV,
            "dbt",
            "test",
            "--project-dir",
            "dbt_project",
        ],
        retries=0,
    )

    raw_load >> dbt_transform >> dbt_test
