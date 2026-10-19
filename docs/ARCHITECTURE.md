# Architecture

This document explains **how the system is organized**: which components
exist, what each one is responsible for, how data flows, and which
invariants must not be broken.

It is not a backlog or a status report. For that, see `history/ROADMAP.md` and
`AGENTS.md`. For the reasons, open `DECISIONS.md`.

## Overview

The project rests on four pieces:

1. **Configuration**: `get_settings()` builds a validated `AppSettings` from
   `.env`, `config/raw_contract.yaml`, and `config/runtime.yaml`.
2. **Python load layer**: validates raw, enriches technical metadata, uploads
   to GCS, and loads BigQuery `raw`.
3. **dbt transformation**: models `raw -> staging -> intermediate -> marts`
   and SCD2 snapshots.
4. **Infra and operations**: Terraform provisions the platform; the Cloud Run
   Job runs the pipeline; local Airflow serves as a lab.

## End-to-end flow

<p align="center">
  <img src="images/data_flow.png" alt="Data flow" width="560">
</p>

Quick reading of the flow:

- locally, the usual source is parquets in `data/sources/`;
- in cloud, the Job can read the current dump from `landing/`;
- the raw load is append-only with technical metadata;
- dbt cleans, normalizes, aggregates, and publishes the marts.

## Responsibilities by component

### 1. Configuration

Responsibility:

- centralize process configuration in one coherent object.

Input:

- `.env`
- `config/raw_contract.yaml`
- `config/runtime.yaml`

Output:

- `AppSettings`

Trade-off:

- an extra abstraction layer is paid for, but each module is kept from reading
  YAML or variables on its own.

Rule:

- outside `settings.py`, `.env` and YAML are not read by hand; the code
  consumes `get_settings()`.

### 2. Raw validation

Main module: `src/validation/raw_validation.py`

Responsibility:

- block the run before the network if files or columns are missing, or if the
  parquets are empty or unreadable.

Input:

- `AppSettings`
- raw files declared in `raw_contract.yaml`

Output:

- `RawValidationReport` or an exception in the strict variant

Trade-off:

- the pipeline fails earlier, but the failure is cheap and explicit.

### 3. Prepare

Main module: `src/load/prepare.py`

Responsibility:

- enrich each parquet with technical metadata before uploading it to cloud.

Input:

- validated parquets
- `PipelineRunContext`
- metadata policy declared in `raw_contract.yaml`

Output:

- new parquets enriched with `_run_date`, `_run_id`, and `_ingested_at`

Trade-off:

- metadata is written once in the file and then travels to BigQuery;
  in exchange, the load job does not need to invent columns that BigQuery
  cannot inject on its own.

### 4. GCS

Main module: `src/load/gcs.py`

Responsibility:

- upload the prepared parquets to versioned, immutable paths.

Input:

- enriched parquets
- `PipelineRunContext`
- layout declared in `raw.gcs_layout`

Output:

- `GcsBatchUploadReport` with `gs://...` URIs

Trade-off:

- the versioned layout uses more space, but it allows traceability and avoids
  silent overwrites.

### 5. BigQuery raw

Main module: `src/load/bigquery.py`

Responsibility:

- launch one load job per table into BigQuery `raw`.

Input:

- `gs://` URIs produced by GCS
- raw contract metadata
- retry and timeout configuration

Output:

- `BigQueryBatchLoadReport`

Design rules:

- `WRITE_APPEND`
- partition by `_run_date`
- deduplication does not happen here; it happens in dbt

### 6. dbt transformation

Responsibility:

- turn auditable raw into readable, reusable analytical layers.

Layers:

- `staging`: 1:1 cleanup, casts, normalization, and technical deduplication
- `intermediate`: joins and reusable logic
- `marts`: final consumption tables
- `snapshots`: SCD2 for mutable attributes

Current trade-off:

- snapshots exist, but published marts still read the current state in
  `stg_*`; that simplifies the current pipeline, but it means a catalog
  update can rewrite historical series.

### 7. Orchestration

Responsibility:

- run existing steps; not contain business logic.

Paths:

- **cloud**: Cloud Scheduler -> Cloud Run Job -> `python -m src run-all`
- **local lab**: Airflow in Docker Compose, using the same app image

Rule:

- the orchestrator automates; it does not redefine metrics or transform data
  outside dbt/Python.

## Configuration contracts

### `.env`

Declares:

- GCP project
- region
- bucket
- raw dataset
- raw source (`local` or `gcs`)

It must not be read directly from business modules.

### `config/raw_contract.yaml`

Declares:

- expected raw tables
- file names
- required columns
- GCS layout
- load metadata

It is the source of truth for the expected raw input.

### `config/runtime.yaml`

Declares:

- retries
- deadlines
- timeouts per cloud integration

It is the technical integration policy, not the business contract.

## Storage layers

### Local raw

- `data/sources/*.parquet`
- lab dump versioned in git

### GCS `landing/`

- current dump without technical metadata
- written by `seed-landing`
- read by the Job when `RAW_SOURCE=gcs`

### GCS `raw/`

- prepared parquet versioned by `dt` and `run_id`
- serves as the immediate source of the load job

### BigQuery `raw`

- append-only
- keeps load history
- does not model business SCD

### BigQuery `staging`, `intermediate`, `marts`, `snapshots`

- layers managed by dbt
- separate cleanup, reusable logic, the analytical product, and SCD2 history

## Environments

The project works with two isolated cloud environments:

- `prod`: project with data
- `dev`: separate sandbox

Separation is achieved with:

- `backend-prod.hcl` / `backend-dev.hcl`
- `envs/prod.tfvars` / `envs/dev.tfvars`
- `.env` pointing at the correct project and bucket for the runtime

Important:

- changing the Terraform backend does not change where Python or dbt point;
- changing `.env` does not change the state Terraform is looking at.

## Critical invariants

These points are expensive to break and should be read as architecture, not as
accidental detail:

1. `raw` is never the place for business history.
2. Technical metadata (`_run_date`, `_run_id`, `_ingested_at`) travels from
   `prepare.py` to BigQuery.
3. Business deduplication does not happen in the loader; it happens in dbt.
4. The orchestrator does not contain business logic.
5. Published marts come from `intermediate`, not directly from `raw`.
6. `dev` and `prod` are different GCP projects; they are not simulated with workspaces.

## Current non-goals

To keep the mental model from getting overloaded, it is worth stating what
this architecture does **not** do today:

- there is no incrementality in `intermediate` or `marts`;
- there is no operational semantic layer;
- there is no multi-currency or FX conversion in marts;
- snapshots do not yet feed the published marts;
- local Airflow is not the productive cloud path.

## Where to go deeper

- `README.md`: entry point and frequent commands
- `OPERATIONS.md`: operational guide for Terraform, deploy, Job, and Scheduler
- `DECISIONS.md`: reasons and trade-offs
- `DATA_CONTRACT.md`: published data contract
- `TESTING.md`: coverage and test commands
