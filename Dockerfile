# App image: Python load + dbt. Not Airflow.
# Build from the repo root: docker build -t saas-revenue-app .
#
# The project is virtual (no [build-system] in pyproject.toml): uv installs
# dependencies only; python -m src works via PYTHONPATH=/app.
# Runtime secrets (.env, ADC) are mounted or injected at docker run / Cloud
# Run — never COPY'd here. Cloud Run sets RAW_SOURCE=gcs and fetches
# gs://<lake>/landing/ (DECISIONS #31); do not COPY data/sources. The public
# dbt template (profiles.yml.example) is COPY'd as /app/dbt_profiles/profiles.yml;
# env_var() resolves at run time (DECISIONS #28).
# Bases are pinned by index digest (DECISIONS #37). Dependabot ecosystem
# docker bumps them. USER app is last: earlier RUNs must write /app as root.

FROM python:3.13-slim-trixie@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0

COPY --from=ghcr.io/astral-sh/uv:0.11.14@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Lockfile first so a SQL change does not reinstall dbt-bigquery.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

COPY src/ src/
COPY config/ config/
COPY dbt_project/ dbt_project/
COPY dbt_project/profiles.yml.example /app/dbt_profiles/profiles.yml

# dbt_packages/ is gitignored; materialize dbt_utils in the image.
RUN uv run --no-dev dbt deps --project-dir dbt_project

ENV PATH="/app/.venv/bin:${PATH}" \
    DBT_PROFILES_DIR=/app/dbt_profiles

# After every COPY/RUN. Cloud Run / DockerOperator inherit this uid.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
 && chown -R app:app /app
USER app

# Default = Cloud Run / docker run. Airflow overrides the command per task.
CMD ["python", "-m", "src", "run-all"]
