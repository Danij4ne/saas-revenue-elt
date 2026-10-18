# Aliases for commands that already exist (README). Not pipeline logic.
# Default is help so a bare `make` does not hit GCS/BigQuery.
# `load`, `seed-landing`, `dbt`, and `run` touch cloud. Lint/test/hooks do not.
# CI (`.github/workflows/ci.yml`) calls `lint` and `test` on the runner.
# GNU Make required (Git Bash or chocolatey on Windows). `uv` must be on PATH.

.PHONY: help lint test hooks load dbt run seed-landing
.DEFAULT_GOAL := help

help:
	@echo "lint          ruff check + format --check + sqlfluff + mypy (no GCP)"
	@echo "test          pytest + cov src/validation (no GCP)"
	@echo "hooks         pre-commit on all files (no GCP)"
	@echo "load          python -m src run-raw-load (GCS/BigQuery)"
	@echo "seed-landing  python -m src seed-landing (GCS landing/ only)"
	@echo "dbt           dbt build (BigQuery)"
	@echo "run           python -m src run-all (GCS/BigQuery)"
	@echo "Same commands without Make: see README."

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run sqlfluff lint dbt_project/models dbt_project/tests
	uv run mypy src

test:
	uv run pytest --cov=src/validation --cov-report=term-missing

hooks:
	uv run pre-commit run --all-files

load:
	uv run python -m src run-raw-load

seed-landing:
	uv run python -m src seed-landing

dbt:
	uv run --env-file .env dbt build --project-dir dbt_project

run:
	uv run python -m src run-all
