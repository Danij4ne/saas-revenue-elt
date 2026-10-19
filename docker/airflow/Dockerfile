# Airflow image : orchestrator only. Not the app (see root Dockerfile).
# Build from the repo root:
#   docker build -t saas-revenue-airflow -f docker/airflow/Dockerfile docker/airflow
#
# Context is docker/airflow/ so src/, dbt, and secrets cannot be COPY'd by accident.
# DAGs are mounted at compose time, not baked in. No CMD: the official
# entrypoint already starts api-server/scheduler from compose `command:`.

FROM apache/airflow:3.3.0

# Re-pin the same core as the base image so pip cannot upgrade/downgrade Airflow
# while resolving the extra provider (official docker-compose extension pattern).
# docker = DockerOperator. Not google/dbt: those run inside the app image.
RUN pip install --no-cache-dir \
    "apache-airflow==${AIRFLOW_VERSION}" \
    "apache-airflow-providers-docker==4.5.7"
