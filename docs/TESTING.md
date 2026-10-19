# Testing guide

This guide answers a practical question: **which suite to run, when, and what
risk it covers**.

The project has two test families:

- `pytest` for the Python load layer
- `dbt` for data quality and rules in the warehouse

They do not replace each other.

## Quick commands

### Python: no real GCP

```bash
uv run pytest
uv run pytest tests/unit
uv run pytest tests/integration
```

### Static quality

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run sqlfluff lint dbt_project/models dbt_project/tests
```

Shortcuts:

```bash
make lint
make test
make hooks
```

### dbt: requires BigQuery

```bash
uv run --env-file .env dbt deps --project-dir dbt_project
uv run --env-file .env dbt compile --project-dir dbt_project
uv run --env-file .env dbt test --project-dir dbt_project
uv run --env-file .env dbt build --project-dir dbt_project
uv run --env-file .env dbt source freshness --project-dir dbt_project
```

## `pytest` vs `dbt`

| Suite | Answers | Runs against | When to use it |
|------|-------------|--------------|---------------|
| `pytest` | Do the load layer and the CLI behave correctly? | mocks, temp dirs, and test parquets | changes in `src/`, CLI, validation, prepare, GCS, or the BigQuery loader |
| `dbt` | Does the warehouse meet grains, joins, and metrics? | real BigQuery | changes in SQL, `.yml`, data tests, published metrics |

In one sentence:

- `pytest` protects the **Python orchestration**;
- `dbt` protects the **data contract**.

## What each suite covers

### `pytest`

Responsibility:

- validate Python code behavior without touching real GCP.

Protects:

- CLI and command parsing;
- raw validation before the network;
- enrichment of `_run_date`, `_run_id`, and `_ingested_at`;
- GCS object layout;
- BigQuery load job configuration;
- fail-fast across validate -> prepare -> GCS -> BigQuery;
- `RAW_SOURCE=local` vs `RAW_SOURCE=gcs` flow.

Does not protect:

- `staging` grains;
- `MRR`, churn, or `NRR` rules;
- relationships between dbt models.

### `dbt`

Responsibility:

- validate the warehouse contract and the published analytical behavior.

Protects:

- grains and uniqueness per model;
- enums and `accepted_values`;
- relationships between layers;
- subscription range consistency;
- monthly grid and the `as_of_date` cutoff;
- `MRR`, `ARR`, `ARPU`, churn, movement, and `NRR` rules;
- detection of partial raw loads through tests on `_run_id`.

Does not protect:

- CLI parsing;
- Python helpers;
- loader wiring outside the warehouse.

## What to run depending on the change

### You changed Python in the load layer

Run:

```bash
uv run pytest
```

If the change is small and local:

```bash
uv run pytest tests/unit
```

### You changed pipeline orchestration

Run:

```bash
uv run pytest tests/integration
```

### You changed SQL, `.yml`, or dbt tests

Start with:

```bash
uv run --env-file .env dbt compile --project-dir dbt_project
```

And if it touches the real warehouse:

```bash
uv run --env-file .env dbt build --project-dir dbt_project
```

### You changed the published contract or metrics

Run both layers:

```bash
uv run pytest
uv run --env-file .env dbt build --project-dir dbt_project
```

## Recommended flow

### Fast development loop

1. `uv run pytest tests/unit`
2. `uv run ruff check .`
3. `uv run mypy src`

### Large Python change

1. `uv run pytest`
2. `make lint`

### dbt change without touching cloud yet

1. `uv run --env-file .env dbt deps --project-dir dbt_project`
2. `uv run --env-file .env dbt compile --project-dir dbt_project`
3. `uv run sqlfluff lint dbt_project/models dbt_project/tests`

### dbt change with full validation

1. `uv run python -m src run-raw-load`
2. `uv run --env-file .env dbt seed --project-dir dbt_project`
3. `uv run --env-file .env dbt build --project-dir dbt_project`

The last flow touches real GCS and BigQuery; it is not used without explicit OK.

## Important notes

### `dbt build` vs `dbt run`

- `dbt run` materializes models, but does not run tests.
- `dbt test` runs tests, but assumes the objects already exist.
- `dbt build` does both in DAG order and is usually the most complete
  validation on the dbt side.

### Freshness

`dbt source freshness`:

- does not run inside `dbt run`, `dbt test`, or `dbt build`;
- uses `warn_after` on `_ingested_at`;
- today it is an operational signal, not a hard gate.

### Coverage

The current coverage gate applies to `src/validation`, not to all of `src`.

### Real GCP

`pytest` must not touch real GCP. Cloud clients are mocked.

## Relationship to other documents

- `README.md`: entry point and frequent commands
- `ARCHITECTURE.md`: responsibilities and system flow
- `DATA_CONTRACT.md`: which data rules are considered published
- `OPERATIONS.md`: how to run the flows that touch cloud
