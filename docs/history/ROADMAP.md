# Project roadmap (saas-revenue-elt)

Cloud path: **Cloud Scheduler -> Cloud Run Job -> `python -m src run-all`**. Local lab: **Airflow** (in Docker).

## Starting point (state before this roadmap)

This roadmap documents the plan **from the current state forward** (A->G),
not the prehistory. The project already had foundations before it was written.

**Already exists (does not need to be created):**

- Repo structure and dbt skeleton (`dbt_project/`, `sources.yml`, layers)
- Base Terraform: bucket + 4 datasets (`raw`, `staging`, `intermediate`, `marts`)
- Config subsystem: `settings.py`, `raw_contract.yaml`, `runtime.yaml`
- Raw validation: `src/validation/raw_validation.py`
- Load layer: `prepare.py` (technical metadata), `gcs.py`, `landing.py`,
`bigquery.py`, `raw_pipeline.py` (`run_raw_load_pipeline`; optional fetch
from `landing/` if `RAW_SOURCE=gcs`, DECISIONS #2)
- CLI: `src/cli.py` + `src/__main__.py` (`run-raw-load`, `run-all`,
`seed-landing`)
- A4 tests: `tests/` (unit + integration) + `docs/TESTING.md`
- A5 logging: `src/logging_config.py` + logs in pipeline/load (stdout)
- Documentation: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`,
`docs/TESTING.md`, `docs/DATA_CONTRACT.md` (closed in B14)

**Phase B closed** (B1-B14 **done**, including **B13** `dbt docs` + exposures and
**B14** final contract; **B15 outside this close** - semantic layer / incrementals). **C1-C4 done.** **D1-D2 done** (pre-commit + Makefile).
**E1-E5 done** (remote state, SA `elt-pipeline`, lake lifecycle +
365-day window on `raw`, dataset `for_each` + imported `snapshots`

- IAM; environments: var-files + backend prefix; **prod** = stack with data,
**dev** = second GCP project; the sandbox already had an explicit load).
**F1 done** (`.github/workflows/ci.yml`: lint, pytest, `terraform fmt` +
`validate`, `dbt parse`; **no** `plan` until a GCP identity exists). **F2 MVP
done** (`.github/workflows/deploy.yml`: `terraform apply` to the `dev` sandbox
via WIF; no image push, no apply to prod). **F3 done**
(`.github/dependabot.yml`: `uv`, Actions, Docker; no Terraform providers,
no `dbt_utils`). **G1 done** (`artifact_registry.tf` + `image` job in
`deploy.yml`; push to **dev**, tag = SHA). **G2 done** (`cloud_run.tf` +
jobs `image`->`terraform` / `image-prod` (copies the `dev` digest, DECISIONS #15)->`terraform-prod`; the merge does not
execute the ELT). **G4 done** (`scheduler.tf`: paused daily cron + SA
`elt-scheduler`; DECISIONS #18). **G5 done** (`monitoring.tf`: email alert
if the Job ends failed; DECISIONS #19). dbt profile in C1
(DECISIONS #16; there is no Secret Manager). Post-close G2: the Job injects
`RAW_SOURCE=gcs` and reads `gs://<lake>/landing/` (DECISIONS #2); `seed-landing`
is required before Run. **V2-2 code done** (DECISIONS #17:
`terraform/identity`; CD without `projectIamAdmin` / `storage.admin` /
`bigquery.admin`). Import/apply of `terraform/identity` and revoke of old roles
**not** without OK. **V2-3 done**: `docs/OPERATIONS.md` separates the operational guide
for Terraform, deploy, Job, Scheduler, and alerts from the `README` and from `AGENTS`.
**A-3 done** as a documented decision (DECISIONS #10):
MRR/ARR use current `stg_plans`; **no** join to `snapshot_plans`. **A-4 1.1 done**
(gate tests + cov >= 90% on `src/validation`). **A-4 1.2 done** (tests of
`raw_table` / `find_project_root` / `get_settings` cache; no fail_under on
`settings.py`). **A-5 done** in HCL (DECISIONS #14): `public_access_prevention`
on the lake + `prevent_destroy` on datasets; apply touches GCP - not without OK.
**A-7 done** (DECISIONS #16): the DAG does not mount `HOST_DBT_PROFILES_DIR`;
local Airflow uses the profile baked in C1. **A-8 done** (DECISIONS #15):
C1 non-root (uid 10001) + bases by digest; no Trivy in F1.
**AR cleanup done** in HCL (DECISIONS #15): KEEP 10 + DELETE 30d,
`cleanup_policy_dry_run = true`; apply touches GCP - not without OK; enforce
(`dry_run = false`) not without OK. **M-1 done** as a decision (DECISIONS #11):
int/marts stay `table` full refresh; no `incremental` or
`partition_by` until B15. **M-2 done** (DECISIONS #12): `subs_with_unknown_qty`
is kept and three cause buckets are added (not breaking).
**M-3 done**: `_print_pipeline_summary` removed; the pipeline only
logs per stage. **M-5 done** (DECISIONS #1): `AppSettings` and
nested models `frozen=True`; `logging.file` is resolved with `model_copy`,
not in-place. **M-6 done**: `ARCHITECTURE.md` in the present tense (pipeline,
retry, tree); the roadmap CI diagram is F1 (`validate`, not `plan`).
**M-11 done**: `ARCHITECTURE.md`
distinguishes prod (Scheduler -> Job -> `run-all`) from lab (Airflow);
both paused. **M-12 done**: single-currency `EUR` marts in the contract;
`accepted_values` also on `int_subscription_monthly`; no FX.
**M-14 timeouts done** (`timeout-minutes` in CI/CD; action SHA pin not done).
**m-5/m-6/m-7 done** (CODE_REVIEW): owner email stays;
dumps ~0.5 MB in git (README); no `analyses/` or starter gitkeep
in folders with artifacts.
**m-9 done**: `stg_plans.billing_period` contract = `month` / `year`
(aligned with the YAML and the annual branch of `int_subscription_monthly`).
**F4 stays outside this closed project** (optional `dbt build` in CI). Image apply / push touch GCP -
not without OK. The DAG is born paused; unpause/trigger touches GCS/BigQuery.

Technical detail of the current state: see `docs/ARCHITECTURE.md`.

## Original target (before Phase G)

This diagram is the plan written before Phase G. Two separate planes:
**infrastructure** (provisioned) and **data runtime** (executed on each run).
The orchestrator only coordinates; the logic lives in Python (`src/`) and in dbt.

```text
CI/CD (GitHub Actions)
  PR    -> lint + pytest + terraform fmt/validate + dbt parse
  merge -> terraform apply   (bucket, datasets, permissions)
        (infra ready, does NOT run on every data load)
                    |
                    v
ORCHESTRATOR (Airflow, in Docker)
  DAG "raw_to_marts"  (thin DAG, only coordinates)
    [t1] run_raw_load_pipeline()   -> calls Python
    [t2] dbt run
    [t3] dbt test
                    |
                    v
DATA LOGIC (plain Python, testable without Airflow)
  run_raw_load_pipeline()   (src/load/raw_pipeline.py)
    |- get_settings()                 settings.py
    |- build_local_run_context()      settings.py
    |- fetch landing (if RAW_SOURCE=gcs)  landing.py
    |- validate_raw_inputs_or_raise() raw_validation.py
    |- prepare_all_..._or_raise()     prepare.py
    |- upload_all_..._or_raise()      gcs.py
    \- load_all_..._or_raise()        bigquery.py

  dbt project (dbt_project/)
    raw -> staging -> intermediate -> marts
```

### What shipped

- A merge deploys the image and Terraform. It does not execute the ELT.
- The production trigger is Cloud Scheduler -> Cloud Run Job -> `python -m src run-all`.
- Airflow in Docker is the local lab. The DAG uses `DockerOperator` (C4).

### Three rules that hold the architecture up

1. **Airflow contains no logic.** The DAG only declares the order of the stages.
2. **Terraform lives in CI/CD**, not in the DAG. It is triggered by infra changes,
  not by data runs.
3. `raw_pipeline.py` **is the boundary.** Airflow calls it as a black box; it
  can be run by hand the same way.

> How Airflow calls the pipeline (decided in Phase C, closed in C4): the DAG
> runs the pipeline as a command in a container (`DockerOperator`), instead of
> `PythonOperator` importing `src` directly (avoids coupling the Airflow
> environment with the app's).



## Roadmap by phase

Golden rule: **sequential phases (A -> B -> C -> D -> E -> F -> G); do not advance
work from future phases.** The prior foundations already exist (see "Starting
point"); this rule forbids advancing Airflow/CI/Cloud, not redoing what is already done.
Do not move to the next phase until the previous one is closed. Airflow only automates something that
already works by hand.

Order by dependencies: tooling (D) and professional Terraform (E) come **before**
CI/CD (F), because CI/CD uses them (remote state backend, quality hooks). The
cloud (G) is the close, when everything works locally + Docker.

> **Sequence priority (avoid scope-creep).** The value of the project is the
> revenue (MRR/churn), not the infra. The full scope of F->G (Cloud Run Job +
> Scheduler + Monitoring + Workload Identity Federation +
> dependabot) is real production level and can consume weeks. Practical
> rule: **lock A->B until there is a raw->marts flow that produces a real metric
> (MRR calculated end-to-end locally)** before investing in C->G. A
> reviewer values "MRR end-to-end locally" much more than "half a cloud infra without
> data". This reinforces the golden rule: besides *not advancing* phases, prioritize
> the analytical core (B) over automation/cloud (C->G).



### Phase A - Close raw ingestion (Python)


| Step | File                                                                 | Goal                                                                                                                                                                                 |
| ---- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A1   | `src/load/bigquery.py`                                               | Load jobs from `gs_uri`, batch + `or_raise` (mirror of `gcs.py`). **Done.**                                                                                                          |
| A2   | `src/load/raw_pipeline.py` (+ `prepare.py`)                          | `run_raw_load_pipeline()`: validate -> prepare -> gcs -> bq + `RawPipelineRunReport`. Technical metadata in the parquet before upload. **Done.**                                     |
| A3   | `src/__main__.py` + `src/cli.py`                                     | CLI with subcommands: `run-raw-load` and `run-all` (load + `dbt build`; C1 image / Cloud Run). The Cloud Run entrypoint reuses this CLI, not a `dag.py`. **Done** (`run-all` in C1). |
| A4   | `tests/` (+ `docs/TESTING.md`)                                       | Load-layer unit tests + **integration test of** `raw_pipeline.py` (validate -> prepare -> gcs -> bq chained) with GCS/BQ client mocks (without touching GCP). **Done.**              |
| A5   | structured logging (`src/logging_config.py` + logs in pipeline/load) | Logs per stage: `run_id`, table, `gs_uri`, rows, duration, errors. **Done.**                                                                                                         |


Note: A5 is implemented in practice together with A2, not as a final step. The
**configuration** (`setup_logging()`) can live in `raw_pipeline.py`; if later
the CLI or Airflow need to configure it without dragging the pipeline along, it is
extracted to `src/logging_config.py`. The **use** (`logger = getLogger(__name__)`) goes
in each module. Output to **stdout** (in Cloud Run it goes to Cloud Logging on its own), not to
a folder of files. **Lineage does NOT go here**: it is dbt's responsibility
(see B13).

Note (backfill and idempotency): the load design is `WRITE_APPEND` + `run_id`
(see `DECISIONS.md` #6), so **reprocessing duplicates in raw and dbt deduplicates**
downstream with the technical columns. That policy must be **explicit**, not
implicit: **A3 (CLI)** exposes `run-raw-load` accepting an optional `--run-date`
(default, today) to reprocess a past date; re-running the same
`run_date` generates a **new** `run_id` (new immutable run in GCS and new
append partition in BigQuery), and deduplication/"latest row" is resolved in
dbt, not in the load. **C4 (DAG)** inherits this semantics via Airflow `catchup`/backfill,
reusing the same CLI.

> **AI tooling (Phase A):** there are two skills in `.cursor/skills/` for this
> phase: `add-raw-table` (end-to-end raw source onboarding) and `implement-load-step`
> (implement `bigquery.py`/`raw_pipeline.py` as a mirror of `gcs.py`). They guide the
> *how*; the rules `elt-capas`, `config-settings`, and `load-layer` fix the *what*.

Milestone A: complete raw ingestion, runnable with one command, with tests and logs.

### Phase B - Transformation (dbt)

> **The numbering reflects the recommended development order** (not the
> execution order: dbt resolves the DAG automatically via `ref()`/`source()`).


| Step | What to create                                        | Goal                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1   | `profiles.yml` / dbt profile                          | Connection to BigQuery (raw dataset as source). **Done** (real profile in `~/.dbt/profiles.yml`, outside the repo; versionable template in `dbt_project/profiles.yml.example`; verified with `dbt debug`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| B2   | `models/staging/`                                     | 1:1 cleanup of each raw table (types, names, casts). **Done** (5 `stg_*.sql`: cast/trim + dedup by grain/`_run_*`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| B3   | `seeds/` (reference data)                             | Plans/tiers, countries, exchange rates: data that enrich intermediate/marts. **Done** (`country_mapping.csv`, `company_size_mapping.csv`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| B4   | `models/intermediate/`                                | Joins and intermediate business logic. **Done** (`int_customers_enriched`, `int_subscription_monthly`, `int_customer_revenue_monthly`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| B5   | `docs/DATA_CONTRACT.md` - **draft**                   | Define **before** programming marts: what MRR is, what it includes (trials?), how a downgrade is treated, grain and periodicity of each mart. **Done** (draft; **closed in B14**)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| B6   | `models/marts/`                                       | Final revenue tables: **monthly MRR**, **MRR movements** (new/expansion/contraction/churn), **customer churn**, and the derived metrics **ARR** (MRR x 12), **ARPU** (MRR / active customers), and **NRR** (Net Revenue Retention by cohort; needs >12 months of history to be informative); built with the B5 contract already defined. **Done** (4 models: `mart_revenue_monthly`, `mart_mrr_movements`, `mart_customer_churn`, `mart_nrr`)                                                                                                                                                                     |
| B7   | dbt tests + `schema.yml`                              | `not_null`, `unique`, relationships, business tests, on marts and staging already built. **Done** (`.yml` on the 5 staging + intermediate + marts with `unique`/`not_null`/`accepted_values`/`relationships`; 5 singular business tests in `dbt_project/tests/`; 80 data tests in total)                                                                                                                                                                                                                                                                                                                                     |
| B8   | **dbt unit tests** (`unit_tests`, dbt >=1.8) on marts | **Done** (5 tests: `new`/`reactivation`/`churn`/first-month-0 on `mart_mrr_movements`; 12m window and churn-as-0 on `mart_nrr`). Version overlap in `int_subscription_monthly` is **not** unit-tested: the mock (3 `ref` + spine) does not pay for a one-line `QUALIFY`; it is added if that CTE is refactored. Complements -does not replace- the B7 data tests                                                                                                                                                                                                                                                                                                         |
| B9   | **snapshots (SCD2)** on plans/customers               | **Done** (`snapshot_plans`, `snapshot_customers`; `check` from staging; schema `snapshots`; marts do not consume them). Capture of **future** changes in mutable attributes. **Not a prerequisite of B6**: `subscription_history` already arrives versioned.                                                                                                                                                                                                                                                                                                                                                       |
| B10  | `freshness` in `sources.yml`                          | **Done** (`loaded_at_field: _ingested_at`, `warn_after` 7d, no `error_after`; the 5 `raw` tables inherit the block). Signal, not a gate: the frozen dump is not a daily feed.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| B11  | `packages.yml` (`dbt_utils`) + advanced tests         | **Done** (`dbt-labs/dbt_utils` 1.3.0). `mutually_exclusive_ranges` on `stg_subscription_history`; `sequential_values` + `expression_is_true` (statuses, grid through `as_of_date`, `subs_with_unknown_qty` warn, ARR/ARPU, churn amounts >= 0); `at_least_one` on `mart_revenue_monthly.month`. Natives from the same pass: `unique (subscription_id, valid_from)`, one open version, `not_null` warn on `quantity`, metadata/PK on sources, seeds, `relationships` warn to seeds. **No** `dbt_expectations`, no `date_spine`, no `unique_combination_of_columns` (the native composite `unique` already covers ties). |
| B12  | `docs/TESTING.md` - dbt section                       | **Done.** dbt tests from B7/B8/B11 and `assert_raw_run_id_consistency` (what is tested, where, `dbt test`/`dbt build`) and the relationship to A4 pytest. The rule catalog stays in `docs/DATA_CONTRACT.md` §9                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| B13  | `dbt docs` + `exposures`                              | **Done.** Catalog (`dbt docs generate` / `serve`; commands in the README) and one consumer: `revenue_dashboard` in `dbt_project/models/marts/exposures.yml` (the 4 marts; `maturity: low`, no `url`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| B14  | `docs/DATA_CONTRACT.md` - **final version**           | **Done.** Published contract: metrics/grain (sect. 7), consumer, ownership, PII, frozen-dump SLA, and versioning (sect. 11). Links YAML/tests; does not duplicate them. Proration/`error_after`/snapshots-in-marts stay out of this version (sect. 12), not as gaps in the close                                                                                                                                                                                                                                                                                                                                                                                         |
| B15  | Incremental models / metrics (semantic layer)         | **Outside this close**: incremental models and a semantic layer are not part of the finished project.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |


> **AI tooling (create when starting the phase):** add under `.cursor/` when the
> first real model exists as an example:
>
> - Skill `add-dbt-model` (create a model in the correct layer + `.yml` + tests). **Done.**
> - dbt conventions rule (glob `dbt_project/**`): naming, layers, required tests.
> It is the *what* (norm) that the skills execute as the *how*. **Done** (`dbt-conventions`).
> - Skill `add-dbt-snapshot` (SCD2 on plans/customers, B9). **Done.**
>
> Do not create the skills earlier: without a real model/snapshot, the `reference.md` would be
> generic.

Structure note: `dbt_project/` already brings the folders `staging/`,
`intermediate/`, `marts/`, `seeds/`, `snapshots/`, `tests/`, `macros/`, and
`sources.yml`. In dbt, each **model is a** `.sql` **file** that
you create inside its layer folder; dbt discovers them on its own. `profiles.yml` already
exists (B1): the real one lives in `~/.dbt/profiles.yml` and the template in
`dbt_project/profiles.yml.example`. `packages.yml` exists (B11): only `dbt_utils`;
install with `dbt deps --project-dir dbt_project` (`dbt_packages/` is in
`.gitignore`).

Development of each step:

- **B1 - profiles.yml:** connection to BigQuery (project, dataset, auth method).
Without this dbt does not know which warehouse to connect to. It usually lives in `~/.dbt/profiles.yml`
or in the project.
- **B2 - staging:** one `.sql` per raw table, 1:1 cleanup (rename, cast
types, standardize). Isolates the rest of the project from the "dirty" shape of raw.
- **B3 - seeds:** reference CSVs that dbt loads as tables (plans/tiers,
countries, exchange rates). They enrich with data that does not come from the source. It is a
**hard dependency**: any model that `ref()`s a seed needs it to
exist in order to compile, so it is created before intermediate/marts - but only
if some model is going to reference them (do not create seeds "just in case").
- **B4 - intermediate:** models that combine staging (joins, reusable business
logic). Builds intermediate pieces before the marts.
- **B5 - DATA_CONTRACT.md (draft):** define **before** programming the marts
the business definitions: what MRR is, which statuses count as "active",
whether it includes trials, how a mid-period downgrade is treated, grain and
periodicity of each mart. Draft closed in B14.
- **B6 - marts:** final business tables: monthly MRR, MRR movements
(new/expansion/contraction/churn), customer churn, and the derivatives
ARR (MRR x 12), ARPU (MRR / active customers), and NRR (net revenue
retention by cohort - the logic is built anyway; with ~1 year of
history it will return few points, with >12 months it is fully
informative). It is the product dashboards/analysts consume. They are
built with the B5 contract already defined.
- **B7 - tests + schema.yml:** declare tests (`not_null`, `unique`, relationships) and
document columns on marts and staging already built. Guarantees quality and
serves as documentation.
- **B8 - dbt unit tests:** the B7 data tests validate **the data** (are there
nulls?, is it unique?); the unit tests validate **the transformation** (given this
fixed set of subscriptions, March MRR must be X). They cover the
`movement_type` classification (`mart_mrr_movements`) and the NRR window /
churn-as-0 (`mart_nrr`). They do **not** cover version overlap of the spine
in `int_subscription_monthly`: the fixture cost (3 `ref` +
`generate_date_array` through `as_of_date`) does not justify protecting a
`QUALIFY ... order by valid_from desc`. If that CTE is refactored, then
yes. They complement -they do not replace- B7. They are written next to the marts (B6)
and the definitions are crossed with B5/B14 (`DATA_CONTRACT`).
- **B9 - snapshots (SCD2) on plans/customers:** **Done** (`snapshot_plans`,
`snapshot_customers` in SQL `{% snapshot %}` reading `stg_*`; business `check_cols`;
no load metadata; schema `snapshots` in `dbt_project.yml`).
They capture **future** changes in mutable attributes that do not keep history
at the source (a plan's price, a customer's country/industry). **Not a
prerequisite of B6**: `subscription_history` already arrives versioned from the source
(`valid_from`/`valid_to`), so subscription history for
MRR/churn/expansion comes from there, not from snapshots. A snapshot also only
accumulates history **from its first run** - it does not reconstruct the past.
Marts **keep** reading `stg_plans` / `int_customers_enriched` until
a contract change. E4 imported the `snapshots` dataset into Terraform.
- **B10 - freshness:** **Done.** Warnings if raw is stale, measured with
`_ingested_at` (ingestion clock, not business date). Only `warn_after`
7 days; no `error_after` so a quiet portfolio does not take the job down.
Command: `dbt source freshness` (`dbt run` does not include it).
- **B11 - packages + advanced tests:** **Done.** Only `dbt_utils`
(`packages.yml`). `dbt_expectations` is not added. Package tests: version
overlap (`mutually_exclusive_ranges`), dense grid (`sequential_values`
  - `expression_is_true` through `as_of_date`), drift of active statuses,
  `subs_with_unknown_qty` warn, `at_least_one` on `mart_revenue_monthly`,
  ARR/ARPU identities, churn amounts >= 0. Natives from the same pass where the
  package would duplicate (`unique` composite, seeds, raw metadata, `quantity`
  warn, `relationships` warn to seeds). Do not replace B7 singulars or the
  project's own spine with `date_spine`. Partial raw load: singular
  `assert_raw_run_id_consistency` (latest `_run_id` aligned across the 5 tables).
  Invoice<->payment stays out until the contract declares those rules.
- **B12 - TESTING.md (dbt section):** **Done.** Guide for how to run pytest vs
dbt (`run` / `test` / `build`), map by layer, warn vs error, B8 unit tests, and
singulars (including `assert_raw_run_id_consistency`). It does not duplicate the
rule inventory of `docs/DATA_CONTRACT.md` §9.
- **B13 - docs + exposures:** **Done.** `dbt docs generate` / `serve` (README);
one exposure `revenue_dashboard` on the 4 marts (`maturity: low`, no `url`).
`stg_invoices` / `stg_payments` stay out of that consumer on purpose.
- **B14 - DATA_CONTRACT.md (final):** **Done.** Published version: metrics and
grain (sect. 7); consumer, ownership, PII, dump SLA, and versioning
(sect. 11). YAML/tests remain the enforced contract. What does not enter
(proration, `error_after`, snapshots in marts, real BI) is in sect. 12, not
as a list of open homework.
- **B15 - incrementals/metrics (semantic layer):** future performance
and semantics improvement. Outside this close.



Order inside the phase (**development** order; **execution** is resolved
by dbt automatically via `ref()`/`source()`): the B1->B15 numbering already reflects the
recommended sequence. Nuances: B3 (seeds) is only done if some model is going to
reference them; B5 (contract draft) was written **before** the marts and
closed in B14; B8 (unit tests) is written next to the marts (B6), as soon as there is
revenue logic to test; B9 (snapshots) comes after the marts because it is not
their prerequisite - it captures future history of mutable attributes, not the past of
the subscriptions. B15 stays documented as a future improvement, not as work of
this phase.

Milestone B: `dbt build` runs from raw to marts, with snapshots and quality tests.

### Phase C - Orchestration (Airflow + Docker)


| Step | What to create                                   | Goal                                                                                                                                                                                                                                                                                                            |
| ---- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1   | `Dockerfile` (app) + `.dockerignore` + `run-all` | Packages `src/` + dbt + data deps. It is what executes the work. **Done.** (`Dockerfile` at the root; `python -m src run-all`; C2 lives in `docker/airflow/Dockerfile`, not `Dockerfile.airflow`)                                                                                                               |
| C2   | `docker/airflow/Dockerfile`                      | Extended Airflow image (providers). Orchestrator, separate from the app. **Done.** (`apache/airflow:3.3.0` + `apache-airflow-providers-docker==4.5.7`; no `src/`/`dbt`; no `requirements.txt`)                                                                                                                  |
| C3   | `docker-compose.yml`                             | Bring up Airflow (scheduler, webserver, metadata DB). **Done.** (C2 image, metadata Postgres, LocalExecutor, no Celery; `dag-processor` + api-server AF3; Fernet/JWT in `.env.airflow`, not the GCP `.env`)                                                                                                     |
| C4   | `dags/raw_to_marts.py`                           | Thin DAG: t1 `run-raw-load --run-date {{ ds }}` -> t2 `dbt build --exclude-resource-type test` -> t3 `dbt test`, **with** `schedule`, `retries`, alert (log callback), and `catchup=False`. **Done.** (`DockerOperator` on the C1 image; host paths in `.env.airflow`; does not fire GCP until unpause/trigger) |


Why **two Dockerfiles** (C1 and C2): they have different life cycles, they avoid
dependency conflicts (Airflow pins specific versions), and they fit the
`DockerOperator` pattern (the Airflow container launches your app image as
another container, consistent with "thin DAG that calls the app as a black box").
C1 is `Dockerfile` at the root (Cloud Run artifact). C2 is
`docker/airflow/Dockerfile` (local only).

DAG name `raw_to_marts`: describes the data flow end to end
(dataset `raw` -> `marts`), not the tool. It scales well with the
`source_to_destination` scheme if there are more flows in the future (e.g. backfill).

Backfill in C4: the DAG does not reinvent reprocess logic. `catchup` is
**off** by default (the frozen dump must not be re-appended for every historical
day). A one-off Airflow backfill invokes the same A3 CLI with
`--run-date` per logical date. The semantics of "re-run a `run_date`" are
those defined in the Phase A backfill note (new `run_id`, dedup in dbt).

> **Orchestrator: local vs production.** Airflow (Phase C) is the
> **local/learning** orchestrator: the DAG calls granular commands (`run-raw-load`,
> `dbt run`, `dbt test`) to have retries and observability per task. In
> production (Phase G) the trigger is **Cloud Scheduler -> Cloud Run Job**, which
> starts the image with the `run-all` entrypoint (chains the same steps). Both
> use the **same logic** (`raw_pipeline.py` + dbt): the trigger and the
> way of chaining change, not the work. `dags/` is only used by Airflow; in cloud it does not
> take part (if `dags/` is deleted, the cloud path still works).

> **Container entrypoint =** `run-all` **(Python subcommand), NOT a** `dag.py`
> **inside the image.** The app `Dockerfile` `CMD` is `python -m src run-all`.
> The three layers: **trigger** (Airflow/Scheduler) - **sequence** (task DAG
> locally / `run-all` in prod) - **logic** (`raw_pipeline.py` + dbt, identical).

Milestone C: the pipeline runs on its own, orchestrated. **Done** (DAG paused; running against GCP = explicit OK).

### Phase D - Code quality and tooling

It can start early, but it stays here in the sequence because CI/CD (F)
reuses these same checks.


| Step | What to create            | Goal                                                                                                                                                                                                                                    |
| ---- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1   | `.pre-commit-config.yaml` | Hooks before each commit: `ruff check` (lint), `ruff format` (format; **not black**), `sqlfluff lint` on `dbt_project/models` and `tests`. **Done.** (`uv run`; BigQuery dialect; SQL layout/style excluded so marts are not rewritten) |
| D2   | `Makefile`                | Unified commands: `make run`, `make test`, `make dbt`, `make lint`. **Done.** (also `help`, `hooks`, `load`; default `help`; no Docker/Terraform; `uv run` remains the source of truth)                                                 |


**Why pre-commit is not redundant with** `ci.yml`**:** they are the same check
at two moments. `pre-commit` runs on **your machine before the commit** (feedback
in seconds, avoids pushing trivial errors); `ci.yml` runs on **GitHub after the
push** (a barrier that cannot be skipped, guarantees nothing broken enters main).
pre-commit is local and optional (`--no-verify`); CI is mandatory. Both run
the same tools (ruff, sqlfluff), so you define the rules once.
Mental rule: pre-commit warns fast, CI is the lock.

Milestone D: automatic code hygiene and unified commands. **Done.**

### Phase E - Professional Terraform

It comes **before** CI/CD: the remote backend is a prerequisite for automating
Terraform in pipelines.

> **Validate before hardening:** the current Terraform (bucket + datasets) is already
> enough for the pipeline to work. First verify that the load
> (`gcs.py` + `bigquery.py`) and dbt load and clean well in BigQuery (Phases A and B);
> only then harden Terraform with this phase. These improvements are about robustness and
> collaboration, not functionality, so they do not block the data flow.

> **AI tooling (before E1-E5):** **Done.** HashiCorp Terraform MCP in
> `.cursor/mcp.json` (stdio via Docker; Registry docs, not TFE). Rules
> scoped to `terraform/**`: `terraform-docs.mdc` (auto-invoke of the MCP) and
> `terraform-conventions.mdc` (remote backend, least-privilege SA,
> `for_each`, no secrets). Principle: **the MCP gives the capability; the rule
> governs it** (same pattern as Context7 + `docs-context7`). There is no Terraform
> skill. **E1-E5 done** (prod with data; the `dev` sandbox was empty at that
> apply). F–G and the dev load were not done yet; they closed later.


| Step | What to create                                                                                      | Goal                                                                                                                                             | Priority                                                                                       |
| ---- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| E1   | Remote backend (`backend.tf`, state in a GCS bucket)                                                | Shared state with locking; requirement for CI/CD                                                                                                 | **High.** **Done** (code + dedicated bucket + `init -migrate-state`)                           |
| E2   | Service Account + IAM bindings (`iam.tf`)                                                           | Pipeline identity with least privilege (`storage.objectAdmin` on the lake, `bigquery.dataEditor` on datasets, `bigquery.jobUser` on the project) | **High.** **Done** (code + `apply`)                                                            |
| E3   | `lifecycle_rule` on the lake + `default_partition_expiration_ms` on dataset `raw` (edits `main.tf`) | Cool raw objects (Nearline/Coldline); 365-day window on `raw` partitions                                                                         | Medium. **Done** (code + `apply` + `ALTER` of the five tables)                                 |
| E4   | dataset `for_each` + `snapshots` (`main.tf`, `moved.tf`, IAM)                                       | One map instead of 4 blocks; `snapshots` dataset in Terraform + `dataEditor` for the SA                                                          | Medium. **Done** (`import` + `apply`; 0 destroys)                                              |
| E5   | Environment separation (dev/prod)                                                                   | Var-files + `backend-*.hcl` (not workspaces); two GCP projects; stack with data = prod                                                           | Medium. **Done** (prod with data; the `dev` sandbox was empty at the apply). The explicit dev load came later |


Development of each step:

- **E1 - Remote backend:** **Done.** State in a **dedicated GCS bucket**
(not the data lake), with locking and versioning. `backend.tf` + `backend-*.hcl`
per environment (gitignored; the prefix moved out of `backend.tf` in E5). DECISIONS #13.
- **E2 - Service Account + IAM:** **Done.** SA `elt-pipeline@saas-revenue-elt.iam.gserviceaccount.com`.
Roles: `storage.objectAdmin` on the **data lake** (not the tfstate),
`bigquery.dataEditor` on the 4 datasets, `bigquery.jobUser` on the project.
`*_iam_member`, no JSON key. Local stays ADC; G3 will use this SA. DECISIONS #17.
- **E3 - lake retention +** `raw` **window:** **Done** (DECISIONS #14).
`lifecycle_rule` only on `google_storage_bucket.data_lake` (never the
tfstate): live objects under `raw/` -> Nearline 30d -> Coldline 90d; live objects are not
deleted; noncurrent Delete 7d; incomplete multipart abort 1d. Dataset `raw`:
`default_partition_expiration_ms` = 365 days; the five existing tables
have the same `partition_expiration_days` (one-off ops, not in
DECISIONS). No Autoclass. No expiry in `src/load/bigquery.py`.
The bucket `lifecycle { prevent_destroy }` is not touched.
- **E4 -** `for_each` **on the datasets:** **Done** (DECISIONS #14).
One `google_bigquery_dataset.datasets` + `local.bq_datasets` (includes
`snapshots`). `moved.tf` rewrote the addresses of the four current datasets
(without recreating them). Only `raw` carries `default_partition_expiration_ms`.
`snapshots` was imported (dbt had already created it) and `elt-pipeline` has
`dataEditor` there.
- **E5 - Environment separation:** **Done** (DECISIONS #13): mechanism,
migrate-state to `saas-revenue-elt/prod`, labels `env=prod`, and a second
GCP sandbox project (`dev`) whose lake, datasets, and SA were **empty at the apply** (17 creates;
empty `plan` afterwards). Var-files and partial backend per environment, not
workspaces. Dataset ids are not prefixed. To switch environments locally:
`terraform init -reconfigure -backend-config=backend-prod.hcl` (or
`backend-dev.hcl`) - **never** `-migrate-state` when switching. At the close of E5 the app `.env`
pointed at **prod**. The explicit load in `dev` is the one recorded in the starting point.
dbt/Python do not change.

Milestone E: infrastructure that is collaborative, secure, and fit for CI/CD.

### Phase F - Automation (CI/CD)

Two separate workflows because they have different triggers and permissions:
**verify** (CI, on every PR, no write credentials) vs **deploy**
(CD, only on merge, with GCP credentials). Mental rule: `ci.yml` **watches,**
`deploy.yml` **touches,** `dependabot.yml` **proposes.**


| Step                           | What to create                 | Goal                                                                                                                                                                                                   |
| ------------------------------ | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| F1                             | `.github/workflows/ci.yml`     | On PR/push to `main`: lint + pytest + `terraform fmt`/`validate` + `dbt parse`. Only verifies. **Done** (DECISIONS #15; `plan` when a CI identity exists)                                              |
| F2                             | `.github/workflows/deploy.yml` | **MVP done** (DECISIONS #15): merge/`workflow_dispatch` -> apply **dev** via WIF (`github-deploy`). G1 added the push; G2 reordered `image`->`terraform` and added `terraform-prod`.                   |
| F3                             | `.github/dependabot.yml`       | **Done** (DECISIONS #15): PRs for `uv`, GitHub Actions, and Docker. `ci.yml` validates them. No Terraform providers or `packages.yml`.                                                                 |
| F4 *(optional, advanced/cost)* | `dbt build` job in `ci.yml`    | On PR: `dbt build` against an **ephemeral** BigQuery dataset (create/destroy per PR) instead of only `dbt parse`. Verifies that the models **run and pass tests** for real, not only that they compile |


- **F1 -** `ci.yml` **(verify):** **Done.** It fires on every PR and on push to
`main`. Parallel jobs: `make lint` (ruff, sqlfluff, mypy), `make test`
(pytest A4), `terraform fmt -check` + `init -backend=false` + `validate`
(without reading the GCS state), `dbt parse` (example profile + dummy `GCP_PROJECT_ID`).
No secrets, no `apply`, no load. `terraform plan` against the **dev** prefix
waits until a CI identity exists (DECISIONS #15). Goal:
nobody merges code that does not even compile.
- **F2 -** `deploy.yml` **(deploy):** **MVP done.** Only merge to `main` /
`workflow_dispatch` (from `main`; WIF rejects another ref). One job
`terraform` with Environment `dev`: WIF -> `github-deploy` -> writes
`backend-dev.hcl` + `envs/dev.tfvars` from Environment vars ->
`plan -out=tfplan` -> `apply` of that plan. G1 added the `image` job;
G2 reordered to `image`->`terraform` and added `image-prod`->`terraform-prod`
(Environment `prod` + reviewer). Identity in `terraform/identity/`
(not `elt-pipeline`; DECISIONS #17). First WIF apply: local, ADC, identity backend of the
environment, explicit OK. The merge does not execute the ELT.
- **F3 -** `dependabot.yml`**:** **Done.** It is not a workflow. `uv` (not `pip`),
GitHub Actions, and two `docker` (`/` and `/docker/airflow`). Weekly, groups
minor/patch, no automerge. No Terraform ecosystem (merge -> `apply` to
`dev`). `dbt_utils` in `packages.yml` is bumped by hand (there is no ecosystem).
- **F4 -** `dbt build` **in CI (optional, advanced/cost):** raises the F1 bar.
Instead of only `dbt parse` (which validates that dbt *compiles*), it runs `dbt build`
against an **ephemeral** BigQuery dataset created and destroyed on each PR, so
that models, snapshots, and tests actually run against the warehouse.
It is marked **optional** because it needs a Service
Account with write permissions on BigQuery and it adds **cost** and complexity
(isolate and *tear down* the dataset per PR). It stays outside this closed project. Until then, `dbt parse` in
F1 is the CI barrier.

Milestone F: automatic verification on PRs and controlled deploy on merge.

### Phase G - Take everything to Google Cloud (the "+")

Final close, when everything works locally + Docker. Note: the **data infra
already exists** (Terraform creates bucket and datasets on real GCP, even if launched from
local). What is missing is not the *destination*, but moving the *compute*: today the pipeline
runs on your laptop; this phase runs it in the cloud.

> **How Phase G is provisioned.** Resources are **added to the same Terraform**
> you hardened in E (Terraform grows by layers, there is no separate TF):
>
>
> | Element                                     | How it is created                                                          |
> | ------------------------------------------- | -------------------------------------------------------------------------- |
> | Artifact Registry, Cloud Run Job, Scheduler | **Terraform**                                                              |
> | Service Account + IAM                       | **Terraform**, defined in **E2**; G3 only references it                    |
> | Build + push of the **image**               | **CI/CD** (`image` job of `deploy.yml`, added in G1), not Terraform        |
> | dbt profile (`profiles.yml`)                | **C1 image** (public template; DECISIONS #16). There is no Secret Manager. |
>
>
> Rule: **Terraform creates resources and *references* the image; CI/CD *builds
> and uploads* it.** A real secret (if one appears) would go outside `tfstate`; the dbt
> profile is not that case.
>
> **Startup order (first deploy)**, because of the chained dependencies:
>
> 1. `terraform apply` -> creates Artifact Registry (and base/SA). The image does not exist yet.
> 2. CI `build + push` -> uploads the image to Artifact Registry.
> 3. `terraform apply` -> creates/updates the Cloud Run Job (references the image) + Scheduler.
>
> The Run Job cannot be created before the image exists, nor can a push happen before
> Artifact Registry exists.

> **Structure of the** `.tf` **files (maintainable as it grows).** Terraform joins all the `.tf`
> files in `terraform/` into one configuration: splitting into files is
> **organizational, not functional**. Rule: **one** `.tf` **per domain**, not one per step
> or everything in `main.tf`. In this phase:
>
> - `artifact_registry.tf` (G1)
> - `cloud_run.tf` (G2, the Job)
> - `scheduler.tf` (G4)
> - `monitoring.tf` (G5, the basic Job failure alert)
> - there is no `secrets.tf` (dbt profile in C1; DECISIONS #16)
> - the SA/IAM lives in E's `iam.tf` (G3 only references it)
>
> Creation order is resolved by Terraform from dependencies between resources,
> not by how you split the files.

> **Real execution order (literal):** `terraform apply` (G1 + E base/SA) ->
> CI `build + push` (`image` job of `deploy.yml`, added in G1) ->
> `terraform apply` (G2 + G4) -> G5 at any intermediate moment. The
> table below lists the **resources** to create; the deploy sequence
> is the one in this line (see also "Startup order" above).

> **Extend** `deploy.yml` **(F2 MVP).** Today the workflow only has the
> `terraform` -> `dev` job. Three deltas, also nailed in each row and
> G paragraph (that is the source per step):
>
> 1. **G1 applied** (registry live) -> add `image` job (C1 build + push,
>   tag = `github.sha`).
> 2. **After the first push** -> the second apply can create Job (G2) +
>   Scheduler (G4).
> 3. **WIF on the project with data + Environment** `prod` **+ reviewer** ->
>   add `terraform-prod` job (noted in G2). G3-G5 do **not**
>    add a job to `deploy.yml`. The merge does **not** fire the pipeline (Scheduler -> Job).


| Step | What to create                                             | Goal                                                                                                                                                                                                                                                                                                                           |
| ---- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| G1   | Artifact Registry (`artifact_registry.tf`)                 | **Done** (DECISIONS #15): Docker repo + `image` job (tag = SHA) to **dev**. No Cloud Run.                                                                                                                                                                                                                                      |
| G2   | Cloud Run Job (`cloud_run.tf`)                             | **Done** (DECISIONS #15, #2, #15): batch Job + `elt-pipeline` + AR reader + `RAW_SOURCE=gcs`. CD: `image`->`terraform` (dev) and `image-prod` **copies the digest**->`terraform-prod` (Environment `prod` + reviewer). **No** second `docker build`. **No** `gcloud run jobs update/execute`. The merge does not fire the ELT. |
| G3   | Runtime Service Account (reference E's `iam.tf`)           | **Covered in G2.** The Job already runs as `elt-pipeline` (E2). There is no second SA. `deploy.yml` **is not touched.**                                                                                                                                                                                                        |
| G4   | Cloud Scheduler (`scheduler.tf`) (or Cloud Composer)       | **Done** (DECISIONS #18): daily HTTP+OAuth cron to the G2 Job, `paused = true`, invoker SA `elt-scheduler` (not `elt-pipeline`). Same module in dev and prod. **No** new job in `deploy.yml`. The merge does not fire the ELT. Composer out of scope.                                                                          |
| G5   | Cloud Logging / Monitoring (`monitoring.tf` for the alert) | **Done** (DECISIONS #19): email channel + policy if the G2 Job ends `failed`. A5 (stdout) is not touched. **No** new job in `deploy.yml` (yes `GCP_ALERT_EMAIL` in the apply tfvars). Freshness/dbt out.                                                                                                                       |


Development of each step:

- **G1 - Artifact Registry:** **Done.** Docker repo (`artifact_registry.tf`,
location = `var.gcp_region`) + `image` job in `deploy.yml`. Tag =
`github.sha`. First destination = **dev** sandbox. The merge does not execute the
ELT.
- **G2 - Cloud Run Job:** **Done.** Runs a container **until it
finishes** (batch), not an always-on server. Uses the G1 image
and runs your CLI (`python -m src run-all`). The Job is created by the `apply`
(`terraform` in `dev` after `image`; `terraform-prod` after `image-prod`).
`image-prod` promotes the `dev` digest (DECISIONS #15), it does not rebuild.
There is **no** Actions job that only does `gcloud run jobs update`.
Environment `prod` + required reviewer. The merge does not fire the ELT.
Cloud source: **V2-1** (DECISIONS #2).
- **G3 - Runtime Service Account:** **Covered in G2.** "Robot"
identity with least privilege (lake + BigQuery + registry reader). The
Job already runs **as** `elt-pipeline` (E2). No other SA is created. Locally
you use your personal ADC. **This step does not change** `deploy.yml`**.**
- **G4 - Cloud Scheduler (or Cloud Composer):** **Done.** Scheduler is a managed
cron that fires the Cloud Run Job (simple and cheap). Composer is
Airflow managed by Google (consistent with Phase C, but expensive: out
of scope). Same as G2: Terraform + the same `apply`. It is born **paused**
(`var.scheduler_paused`, default true). Invoker SA `elt-scheduler`
(`run.invoker` only); the Job still runs as `elt-pipeline`. Daily cron
`0 9 * * *` `Etc/UTC`. **This step does not add a new job to**
`deploy.yml`**.** It does not authorize pressing Run or unpausing: `landing/`
must be seeded (DECISIONS #2) and an explicit OK is required.
- **G5 - Cloud Logging / Monitoring:** **Done.** A5 logs still
go to Cloud Logging on their own when the Job runs. The alert (`monitoring.tf`)
notifies by **email** (`var.alert_email`) when a Job execution
ends `failed` (Cloud Run Jobs metric, not `ERROR` logs). Channel +
policy in dev and prod; the GCP email has to be verified. There is **no**
new job in `deploy.yml`; CD writes `alert_email` from
`GCP_ALERT_EMAIL`. Slack / freshness / dbt tests stay out. It does not
authorize Run or unpause.

> **Your code does not become "invisible" in cloud.** The GCP client libraries
> (`google-cloud-*`) are the equivalent of boto3 on AWS: your code calling
> APIs. The same `src/` runs on your laptop (with ADC) or on Cloud Run (with a Service
> Account); the code does not change, only where it runs and how it authenticates. Cloud
> Run runs **your container**, so all your Python stays in the repo, visible
> and versioned. Thanks to Infrastructure as Code (Terraform), your repo **is** the
> organization of your cloud; only secrets and state stay outside.

Milestone G: pipeline running in the cloud on a schedule and observable.

## V2 - Post-close improvements (outside A->G)


| Step | What to create                                                        | Goal                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ---- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V2-1 | `src/load/landing.py` + CLI `seed-landing` + env `RAW_SOURCE`         | **Done** (DECISIONS #2). **Why:** the Cloud Run Job runs `run-all` but the image does not bring the parquets (`data/` does not enter the build). Locally that does not matter (they are on disk); on GCP, Run died in validate. **How:** the current dump lives in the lake, `gs://<lake>/landing/<file>`, without metadata. On the laptop `RAW_SOURCE` stays `local` (reads `data/sources`). The Job sets `gcs`, downloads those objects to a temp dir, and continues the pipeline (prepare -> `raw/` -> BigQuery -> dbt). To fill `landing/` you run `seed-landing` by hand; it does not go inside `run-all`. The merge does not fire the ELT or Run. |
| V2-2 | `terraform/identity/` + trimmed CD roles                              | **Code done** (DECISIONS #17). **Why:** `github-deploy` could read the lake and rewrite project IAM (`projectIamAdmin` + `storage.admin` + `bigquery.admin`). **How:** CD applies only the app root (`storage.admin` on the lake + `dataOwner` per dataset). WIF and project IAM live in `terraform/identity` (ADC). Import/apply and `gcloud` revoke: cloud OK, `dev` first.                                                                                                                                                                                                                                                                           |
| V2-3 | `docs/OPERATIONS.md` + editorial cleanup of operational documentation | **Done.** **Why:** `README.md` and `AGENTS.md` mixed onboarding with the cloud runbook, which made the first read harder and duplicated operational warnings. **How:** the operational guide is extracted to `docs/OPERATIONS.md`; `README.md` stays the entry point and `AGENTS.md` links the operation instead of duplicating it.                                                                                                                                                                                                                                                                                                                     |


Development of each step:

- **V2-1 - Cloud source** `landing/`**:** **Done.** Before, the Job had nowhere
to read from. We did not put the parquets in the image (that would couple data and
code). We also did not reuse the `raw/` prefix (that is where the
*prepared* files of each run already go). Solution: a `landing/` prefix
with the raw dump. `landing.py` does two things: **seed** (upload from
`data/sources` with `python -m src seed-landing`) and **fetch** (download
when `RAW_SOURCE=gcs`, which Terraform sets on the Job). Local and tests
do not change. The same bucket the Job uses has to be seeded **before**
Run or unpause. **This step does not add a new job to**
`deploy.yml`**.** It does not authorize Run or unpause.
- **V2-2 - CD privilege (C-2):** **Code done.** `github-deploy` no longer
has `projectIamAdmin` / `storage.admin` / `bigquery.admin` in the
HCL. Project IAM and WIF move to `terraform/identity` (local apply).
`deploy.yml` does not apply that root. Close the step in cloud: import +
apply `terraform/identity`, apply app (`removed` + lake `storage.admin` + `dataOwner`), revoke old roles
with `gcloud` - **only with OK**, `dev` then prod. No `-target`.
No custom role. No shared-tfstate condition.
- **V2-3 - Separate operational guide:** **Done.** Cloud operation already  
required enough detail not to live in the `README`. The change does not  
modify architecture or permissions; it improves readability and reduces duplication.  
The practical rule is: `README` explains the project, `docs/OPERATIONS.md`  
explains how to operate it.

