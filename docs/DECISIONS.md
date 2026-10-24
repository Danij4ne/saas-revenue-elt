# Technical decisions

This document records the choices that change pipeline behavior, published data, or the operating model. It is not a log of every small change.

How it is wired lives in [ARCHITECTURE.md](./ARCHITECTURE.md). Grain and compatibility live in [DATA_CONTRACT.md](./DATA_CONTRACT.md).

## How to read it

Each decision uses the same format:

- `Context`: what problem or constraint there is
- `Decision`: what the project does
- `Why`: why that choice
- `Consequences`: what it implies in practice

They follow pipeline order. A new decision takes the next free integer.

## Configuration

### Decision 1. Three config sources, one door, and one frozen object

- `Context`: environment, raw contract, and retries change at different rates. Several modules reading `.env` or YAML on their own diverge. The cached object was mutable.
- `Decision`: `.env` stores project, region, bucket, and dataset. `config/raw_contract.yaml` declares tables, columns, GCS layout, and load metadata. `config/runtime.yaml` stores retries and timeouts. The only door is `get_settings()` → `AppSettings`, validated with Pydantic. Paths come from `project_root`. The model is `frozen`; a resolved path is applied with `model_copy`.
- `Why`: each file has a single topic. Failing at startup avoids a badly written YAML in the middle of a load. A mutable singleton would change the config of the whole process.
- `Consequences`: outside `settings.py`, `.env` and YAML are not read by hand. `settings.x = ...` raises an error. Nested lists remain mutable.

## Extract

### Decision 2. In cloud the extract lives in `landing/`

- `Context`: the image does not copy `data/sources`. `raw/` in GCS is already the prepared Parquet (technical metadata). Running the Job against local disk died on file not found.
- `Decision`: the current dump, without metadata, is at `gs://<lake>/landing/<file>`. `RAW_SOURCE=local` (CLI and Airflow) reads `data/sources`. The Job injects `RAW_SOURCE=gcs` and the pipeline downloads `landing/` to a temp directory before validating. Seeding that prefix is `seed-landing`, outside `run-all`.
- `Why`: the image stays code. `landing/` (current dump) and `raw/` (immutable run) are not mixed. A local `run-all` does not overwrite the cloud source.
- `Consequences`: the Job needs `landing/` seeded. A new parquet in git does not reach the Job until the next `seed-landing`. Do not copy `data/` into the image or read the extract from `raw/`.

## Validation

### Decision 3. Raw validation blocks before the network

- `Context`: a parquet that is missing, unreadable, empty, or without the contract columns must not go up to GCS or BigQuery.
- `Decision`: `validate_raw_inputs` returns a report of all tables. `validate_raw_inputs_or_raise` fails before the load.
- `Why`: failing early avoids propagating garbage. Seeing all five tables at once saves one run per error.
- `Consequences`: the orchestrator validates before GCS and BigQuery. A validation failure stops the pipeline.

## Load

### Decision 4. The batch finishes before it fails

- `Context`: aborting on the first table hides the state of the rest.
- `Decision`: each stage (validation, GCS, BigQuery) accumulates a report and offers a `..._or_raise` that raises when the batch closes.
- `Why`: execution and failure policy stay separate, with the same shape in the three stages.
- `Consequences`: the orchestrator can inspect the report or stop the run with a single aggregated error.

### Decision 5. Each run has its own path in GCS

- `Context`: a fixed object path overwrites the previous run and does not distinguish two executions on the same day.
- `Decision`: the prepared object lives at `{prefix}/{table}/dt={run_date}/run_id={run_id}/{file}`. The layout is in `raw.gcs_layout`; the date and the id arrive in `PipelineRunContext`.
- `Why`: each run stays immutable and can be repeated on the same day. The name does not depend on who launches the process.
- `Consequences`: BigQuery loads the `gs://` that the GCS report returns. The path is not rebuilt by hand.

### Decision 6. Raw in BigQuery is append with technical metadata

- `Context`: a canonical table per entity is needed, and a Parquet load job does not inject constant columns. Business history (price, country) does not live here.
- `Decision`: `WRITE_APPEND`, partitioned by `_run_date`. `prepare.py` writes `_run_date`, `_run_id`, and `_ingested_at` before upload. Business SCD goes in dbt snapshots. API call retry is done by the SDK; the loader does not rerun a job that already finished.
- `Why`: append keeps load history. Retrying a closed `WRITE_APPEND` duplicates rows. "Latest row" deduplication is dbt work (`QUALIFY`).
- `Consequences`: the order is prepare → GCS → BigQuery. An orchestration retry uses a new `run_id`. The CLI `python -m src` only parses arguments and delegates; Airflow launches the image and does not import `src`.

## Transformation

### Decision 7. `timestamp[ns]` is converted in staging

- `Context`: Parquet brings `timestamp[ns]`. BigQuery, with autodetect, leaves it in `raw` as `INT64` (epoch in nanoseconds). `CAST(... AS TIMESTAMP)` fails.
- `Decision`: raw stays as it was loaded. The five `stg_*` convert with the `timestamp_from_bq_int64_ns_autodetect` macro (`timestamp_micros(div(col, 1000))`).
- `Why`: staging is the types layer. Recasting in `prepare.py` would break `INTEGER` tables already appended.
- `Consequences`: the macro assumes INT64 in nanoseconds. If a future load writes a real `TIMESTAMP`, it has to be removed. `_ingested_at` already arrives as `TIMESTAMP` and does not go through the macro.

### Decision 8. The original value is kept as `*_raw`

- `Context`: the country and size seeds produce a canonical code. If the original is overwritten, an `Espana` only shows up as `unknown`.
- `Decision`: `int_customers_enriched` does a left join and `coalesce(..., 'unknown')`, and stores the staging value in `country_raw` / `company_size_raw`.
- `Why`: the seed gap can be audited without reading staging again. A mapping failure does not delete customers.
- `Consequences`: later marts and intermediate read the canonical code. Removing `*_raw` is a contract change.

### Decision 9. The monthly spine cuts off at `as_of_date`

- `Context`: the dump closes at the end of 2025. A cap with `current_date()` lengthens the grid with empty months and makes churn and NRR depend on the day of the run.
- `Decision`: `vars.as_of_date` (default `2025-12-31`), read only by the `as_of_date()` macro. The cap is hard: neither the clock nor `greatest(max_data, as_of_date)`.
- `Why`: the same snapshot gives the same result in 2026 or in CI. A row after the cutoff fails in `assert_no_data_after_as_of_date` instead of stretching the grid.
- `Consequences`: models and tests use the macro. Operational dates (`due_date`, `updated_at`) can fall after the cutoff and the test does not look at them. A live pipeline would change the var per run.

### Decision 10. MRR uses the current catalog price

- `Context`: `int_subscription_monthly` joins `stg_plans`. The `list_price` of January 2024 is today's. `snapshot_plans` exists, but it only records plan versions from the day the snapshot starts running, so it cannot reconstruct prices for 2023–2025.
- `Decision`: every month through `as_of_date` uses `stg_plans`. Intermediate and marts do not read `snapshot_plans` or `snapshot_customers`.
- `Why`: joining the snapshot today would not make historical MRR correct, because the old months still have no guaranteed historical price to join to. Subscription history is already in `valid_from` / `valid_to`; price history is not.
- `Consequences`: if Pro goes from 20 to 30, the whole series is recalculated at 30. Once that price change has actually been captured in the snapshot, it becomes meaningful to plug the snapshot into the marts.

### Decision 11. Intermediate and marts are full refresh

- `Context`: the current source is a closed historical dump, not a real delta feed. `int_customer_revenue_monthly` builds a dense customer-month grid through `as_of_date`, and marts such as churn, movements, and NRR depend on comparing each month against the previous one. A badly closed incremental can therefore miss months, break `lag(mrr)`, and classify existing customers as `new`.
- `Decision`: `+materialized: table` on intermediate and marts. No `incremental`, no `partition_by`, and no `cluster_by`.
- `Why`: full refresh is the safest way to keep monthly metrics reproducible while the input is still a frozen dump. The expensive step is the intentional subscription × month spine, not an avoidable storage layout problem. Incremental logic would add correctness risk before it adds meaningful savings.
- `Consequences`: every `dbt build` rewrites intermediate and marts from the same frozen input, so the same dump yields the same MRR, churn, movements, and NRR. Incremental models wait until ingestion becomes a real delta feed and the close/rebuild rules can be defined explicitly.

### Decision 12. The unknown-MRR flag stays; the causes are added

- `Context`: `subs_with_unknown_qty` counts `mrr_base is null`, which also covers an orphan plan and a `billing_period` other than `month` / `year`. Renaming it is breaking.
- `Decision`: the total is kept. `subs_missing_qty`, `subs_missing_plan`, and `subs_unknown_billing_period` are added, mutually exclusive (if quantity is missing, that bucket wins). Of those three, only `subs_missing_qty` goes up to marts: `mart_revenue_monthly` publishes the month's sum. The other two stay in intermediate.
- `Why`: adding columns is a safe change. The sum of the three buckets equals the intermediate total. The case that understates MRR (null `quantity`) has to be visible in the published table; the MRR of that row is not recalculated.
- `Consequences`: intermediate has the three `int64`s. The monthly mart has `subs_missing_qty` (a count of lines, not of customers). Movements, churn, and NRR keep reading the MRR already imputed to 0. Staging tests do not change.

## Infrastructure

### Decision 13. Two GCP projects, not workspaces or dataset prefixes

- `Context`: a single state always pointed at the project with data. Renaming datasets to `dev_raw` would destroy tables. The `backend` block does not interpolate variables.
- `Decision`: the same root module, twice: `backend-prod.hcl` / `backend-dev.hcl` and `envs/*.tfvars`. Each environment is a GCP project. The ids stay `raw`, `staging`, `intermediate`, `marts`, `snapshots`. The state bucket is external to the module (it is not the data lake); the prefix lives in the `.hcl`, outside git. `environment` is required (`dev` or `prod`).
- `Why`: a workspace isolates state, not resources. Two projects separate IAM and quotas without touching dbt. The bucket name does not enter git.
- `Consequences`: `terraform init -reconfigure -backend-config=backend-<env>.hcl` and `plan -var-file=envs/<env>.tfvars`. Switching environments does not use `-migrate-state`. Python does not branch on `environment == "prod"`.

### Decision 14. The lake is not public and datasets are not destroyed

- `Context`: the bucket already had UBLA and `prevent_destroy`. The `for_each` datasets did not. The provider does not offer `deletion_protection` on `google_bigquery_dataset`.
- `Decision`: `public_access_prevention = "enforced"` on the data lake. `prevent_destroy = true` literal on the five datasets, in dev and in prod. No CMEK, no `delete_contents_on_destroy = true`.
- `Why`: `allUsers` on the lake is blocked by the API. A dataset ForceNew fails before the replace. Emptying `dev` requires a conscious `state rm`.
- `Consequences`: the CD apply applies this guard. Datasets come out of a `for_each`; dbt remains owner of the SCD2 tables inside `snapshots`. The lake lifecycle cools live `raw/` (Nearline, then Coldline) and deletes noncurrent versions after 7 days. New BigQuery `raw` partitions expire after 365 days. The state bucket does not inherit those rules.

## Delivery

### Decision 15. CI watches; CD applies dev and copies the digest to prod

- `Context`: a `plan` on every PR needs state and identity. Prod already has data. Two `docker build`s of the same commit are not bit for bit equal. The merge must not execute the ELT.
- `Decision`: `ci.yml` runs lint, pytest, `terraform validate`, and `dbt parse`. It does not run `plan`, `apply`, or load. `deploy.yml` builds the image, pushes it to dev with tag = SHA, and then applies Terraform in dev (the registry is created by that apply). Prod is an Environment with a reviewer: `image-prod` copies the dev digest and `terraform-prod` applies. The Job is defined; nobody calls `:run`. The app image runs with uid 10001 and base images are pinned by digest. Artifact Registry cleanup is in dry-run (keep 10, delete after 30 days).
- `Why`: CI and CD have different blast radius. Copying the digest leaves prod with the same bytes as dev, each in its own registry. Moving cleanup to enforce, or scanning the image in CI, needs a separate OK.
- `Consequences`: a push to `main` updates dev (Job, paused cron, alert) and does not run `run-all`. Prod waits for a reviewer. `terraform plan` in CI stays out until a read-only identity exists. Dependabot watches `uv`, Actions, and Docker; there is no Terraform ecosystem or automatic `dbt_utils` bump. No `GOOGLE_APPLICATION_CREDENTIALS` in GitHub.

### Decision 16. The dbt profile goes in the image; there is no Secret Manager

- `Context`: `dbt build` needs a `profiles.yml`. The template only interpolates `GCP_PROJECT_ID` at runtime. It is not a secret. Cloud Run has no ConfigMap.
- `Decision`: the app image copies `profiles.yml.example` to `/app/dbt_profiles` and sets `DBT_PROFILES_DIR`. There is no Secret Manager resource or secret volume on the Job. The local CLI stays in `~/.dbt`. Local Airflow uses the same baked profile.
- `Why`: the YAML is not confidential. Secret Manager would add an empty envelope and a payload outside git, with no benefit. A real secret (token, key) would go there later: envelope in Terraform, value outside state.
- `Consequences`: changing threads or the template dataset requires a new tag. Do not add `secrets.tf` or a JSON key to the image. Do not mount `~/.dbt` in the DAG.

### Decision 17. CD is not granted project IAM

- `Context`: `github-deploy` had `projectIamAdmin`, `storage.admin`, and `bigquery.admin`. A workflow on `main` could make itself owner and delete data.
- `Decision`: two roots. `terraform/identity/` (local ADC only) owns WIF, `github-deploy`, and `elt-pipeline` (`jobUser` on the project, `objectAdmin` on the lake, `dataEditor` on the datasets, no JSON key). `deploy.yml` applies the app root and does not apply `identity`. CD does not have project-level IAM, Storage, or BigQuery admin. On the lake bucket it keeps `storage.admin` of that bucket; on the module datasets, `dataOwner`.
- `Why`: removing project admin cuts self-escalation. Moving WIF to another root stops CD from rewriting its own identity. IAM changes rarely and deserves human friction.
- `Consequences`: do not merge identity code to `main` until a local import/apply. Old project bindings are revoked with `gcloud` after that apply. Residual: CD can read and write objects of that single bucket.

## Orchestration

### Decision 18. The Scheduler is born paused and does not use the pipeline SA

- `Context`: a cron that can start the Job is needed. The dump is frozen (`as_of_date`): a daily tick would rewrite marts with the same facts and append another `run_id`. Local Airflow is already born paused.
- `Decision`: daily `google_cloud_scheduler_job` (`0 9 * * *` UTC), `paused = true` by default. The `elt-scheduler` SA has `run.invoker` on the Job. `retry_count = 0`. CD does not gain a new job in `deploy.yml`.
- `Why`: the clock and the data identity stay separate. A lost ACK must not launch a second `WRITE_APPEND`. The same resource exists in dev and in prod, off in both.
- `Consequences`: unpause is `scheduler_paused = false` plus apply, with explicit OK and `landing/` seeded. The Scheduler agent does not receive `actAs` on `elt-pipeline`.

### Decision 19. If the Job fails, an email notifies

- `Context`: a notice is needed when the execution ends failed. A Slack webhook would be a secret. An alert on `ERROR` logs also fires on recovered errors.
- `Decision`: email channel (`GCP_ALERT_EMAIL` in the Environment) and a policy on `run.googleapis.com/job/completed_execution_count` with `result = failed`. Active in dev and in prod. No Slack and no log alert.
- `Why`: email does not need Secret Manager. The Job metric says "the container died". With the cron paused, incidents are not opened for absence of data.
- `Consequences`: the email has to be confirmed in GCP or the notice does not arrive. The Job is not fired to test the alert.

## Change rules

- Update this document when the runtime, the semantics of published data, or the operating model changes.
- A refactor that does not change behavior does not belong here.
- If the decision changes grain, columns, or compatibility, also update `DATA_CONTRACT.md`. The additive vs breaking rule lives there.
- A new decision takes the next free integer.
