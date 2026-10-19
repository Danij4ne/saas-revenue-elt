# Data contract

This document describes **what data the pipeline publishes today**, what the
revenue marts guarantee, and which changes are considered compatible or breaking.

It does not try to be a line-by-line mirror of the code. The detailed
implementation is in `dbt_project/`, `config/raw_contract.yaml`, and the tests.
Here the contract a human needs to understand and defend is narrated.

<p align="center">
  <img src="images/data_layer.png" alt="Data layer" width="560">
</p>

## Executive summary

### What the project publishes today

The published layer is `marts` and today it delivers four models:

| Model | Grain | What it publishes |
|--------|-------|-------------|
| `mart_revenue_monthly` | `month` | `MRR`, `ARR`, `ARPU`, active customers, `subs_missing_qty` |
| `mart_mrr_movements` | `customer_id`, `month` | revenue movement per customer (`new`, `reactivation`, `expansion`, `contraction`, `churn`, `flat`) |
| `mart_customer_churn` | `month` | logo churn, monetary churn, expansion, and contraction |
| `mart_nrr` | `base_month` | 12-month `NRR` by cohort |

### What you should remember if you only read one page

- The published contract is **single-currency `EUR`**.
- The monthly spine cuts off at `as_of_date`; it does not depend on the machine clock.
- Published marts come from `intermediate`, not directly from `raw`.
- `snapshot_plans` and `snapshot_customers` exist, but today they do **not** feed
  the marts.
- MRR is catalog. Invoices and payments do not change it.
- `mart_revenue_monthly.subs_missing_qty` counts lines with null `quantity`.
  The `mrr` of that row already counts them as 0.
- `raw` is append-only with technical metadata; it is not a final analytical product.

## Sources of truth

If documentation and code conflict, the code comes first and then
the documentation is corrected.

Main sources:

| Guarantee | Main source |
|---------|------------------|
| expected raw tables, file names, and required columns | `config/raw_contract.yaml` |
| raw source definition and freshness | `dbt_project/models/sources.yml` |
| staging and intermediate | `dbt_project/models/staging/*.sql`, `dbt_project/models/intermediate/*.sql` |
| published marts | `dbt_project/models/marts/*.sql` |
| SCD2 snapshots | `dbt_project/snapshots/*.sql` |
| tests | model `.yml` files + `dbt_project/tests/*.sql` |
| behavior decisions | `docs/DECISIONS.md` |

## Scope of this contract

### Includes

- functional definition of the published marts;
- grain and semantics of the metrics;
- compatibility rules;
- owner, PII, and current SLA;
- summary of the internal models that support the published product.

### Does not include

- operational detail of Terraform, deploy, or Scheduler;
- exhaustive catalog of every internal staging column;
- credentials, project ids, or secrets;
- semantic layer, incrementality, or future multi-currency.

## Global conventions

- Logical IDs are treated as `string`.
- Money is modeled as `numeric`.
- Business timestamps live in `timestamp`.
- `raw` keeps technical load metadata: `_run_date`, `_run_id`,
  `_ingested_at`.
- `staging` cleans, casts, and deduplicates; it does not do business joins.
- `intermediate` concentrates reusable logic.
- `marts` publishes the final analytical product.

## Relevant internal layers and datasets

Published documentation does not need to describe every internal column, but it
is worth understanding which pieces support the final contract:

| Layer | Dataset / artifact | Grain | Role in the published product |
|------|----------------------|-------|--------------------------------|
| raw | `customers`, `plans`, `subscription_history`, `invoices`, `payments` | append per run | auditable technical landing |
| staging | `stg_customers`, `stg_plans`, `stg_subscription_history`, `stg_invoices`, `stg_payments` | 1:1 by business key | cleanup, casts, and deduplication |
| snapshots | `snapshot_plans`, `snapshot_customers` | SCD2 version by key | future history, today it does not enter marts |
| seeds | `country_mapping`, `company_size_mapping` | one row per raw key | customer enrichment |
| intermediate | `int_customers_enriched` | `customer_id` | customer enriched with canonical dimensions |
| intermediate | `int_subscription_monthly` | `subscription_id`, `month` | monthly normalization of subscriptions |
| intermediate | `int_customer_revenue_monthly` | `customer_id`, `month` | shared base of `MRR`, churn, movements, and `NRR` |

## Definition of the published product

### `mart_revenue_monthly`

Grain:

- one row per `month`

Published columns:

- `mrr`
- `arr`
- `active_customers`
- `arpu`
- `subs_missing_qty`

Rules:

- `ARR = MRR * 12`
- `ARPU = MRR / active_customers`
- if there are no active customers, `ARPU` is published as `0`
- `subs_missing_qty` is the sum, in the month, of `active` or `past_due` lines
  with null `quantity`. The unit is the subscription, not the customer. Those
  lines already enter `mrr` as 0: the column does not change `mrr`, `arr`, or
  `arpu`. Movements, churn, and `NRR` do not read it.

### `mart_mrr_movements`

Grain:

- one row per `customer_id` and `month`

Published columns:

- `mrr`
- `prev_mrr`
- `mrr_delta`
- `movement_type`

Possible values of `movement_type`:

- `new`
- `reactivation`
- `expansion`
- `contraction`
- `churn`
- `flat`

### `mart_customer_churn`

Grain:

- one row per `month`

Published columns:

- `active_customers_start`
- `churned_customers`
- `churned_mrr`
- `expansion_mrr`
- `contraction_mrr`
- `customer_churn_rate`

### `mart_nrr`

Grain:

- one row per `base_month`

Published columns:

- `base_mrr`
- `retained_mrr`
- `nrr_12m`

Only cohorts with a full 12-month window are published.

## Metric rules

### MRR

Base:

- comes from `int_customer_revenue_monthly`
- uses `status_in_month in ('active', 'past_due')` as the active set
- does not do intra-month proration

Important decisions:

- `past_due` counts as active MRR;
- `paused` and `canceled` compute `0`;
- null `quantity` is not imputed;
- the series cuts off at `as_of_date`, not at `current_date()`;
- MRR is catalog: `quantity` times the `list_price` of the `active` or
  `past_due` subscription at month end. Invoicing and collection do not change it.

### ARR

```text
ARR = MRR * 12
```

It is an accounting annualization of MRR, not a forecast.

### ARPU

```text
ARPU = monthly MRR / active customers in the month
```

The denominator is customers with `has_active_subscription = true`.

### MRR movements

Classification order:

1. `new`: the customer's first month with `mrr > 0`
2. `reactivation`: returns to `mrr > 0` after having fallen to `0`
3. `churn`: goes from `mrr > 0` to `mrr = 0`
4. `expansion`: `mrr > prev_mrr`
5. `contraction`: `mrr < prev_mrr` and still `> 0`
6. `flat`: the rest

### Customer churn

Definition:

- customer with positive MRR the previous month and zero MRR in the current one

Important:

- the churn month is the first month with `mrr = 0`, not `canceled_at`;
- monetary churn is aggregated from `mart_mrr_movements`.

### NRR

```text
NRR = retained_mrr / base_mrr
```

Rules:

- main window: 12 months
- cohort: customers with `MRR > 0` in `base_month`
- later new customers stay out
- churned customers contribute `0`

## Functional assumptions that affect the business

These points change how the data is read and that is why they are part of the contract:

1. Published marts are **single-currency `EUR`**.
2. There is no FX conversion.
3. There is no intra-month proration.
4. The price used today is the current price from `stg_plans`, not the historical
   snapshot price.
5. CRM `is_deleted` does not turn MRR off; MRR follows the subscription.
6. `stg_invoices` and `stg_payments` are loaded and tested. No mart reads them.
   An invoice or a payment does not modify `MRR`, `ARR`, `ARPU`, churn, or `NRR`.

## Quality and tests that reinforce the contract

This contract does not list every test one by one, but it does say what each
group protects:

- **pre-load**: existence, readability, non-empty, and required columns of the
  raw parquets;
- **raw sources**: non-null technical metadata and uniqueness by `(_run_id, grain)`;
- **staging**: 1:1 grains, enums, relationships, and date order;
- **intermediate**: coherent monthly grid, `MRR >= 0`, quality-flag
  consistency, and coverage through `as_of_date`;
- **marts**: identities such as `ARR = MRR * 12`, movement consistency,
  churn rate in range, and `NRR >= 0`.

For commands and suites, open `docs/TESTING.md`.

## Backward compatibility

### Breaking changes

These are considered breaking:

- removing a published column;
- renaming a published column;
- changing the grain of a published model;
- changing the formula of `MRR`, `ARR`, `ARPU`, churn, movements, or `NRR`;
- changing the set of active MRR statuses;
- stopping being single-currency `EUR` without introducing a new explicit contract;
- changing the `unknown` policy or the published quality flags.

### Generally safe changes

These are usually safe changes:

- adding a nullable column to an internal model;
- adding documentation or tests;
- extending mapping seeds without changing their semantics;
- adding extra internal flags that do not change published metrics;
- publishing on a mart the sum of a flag already computed in intermediate, without
  changing a metric formula (`subs_missing_qty` on
  `mart_revenue_monthly`).

### Changes that require an explicit decision

- connecting snapshots to marts;
- introducing FX or multi-currency;
- changing the analytical cadence of `as_of_date`;
- moving published logic out of the shared `MRR` base.

## Owner, PII, and SLA

### Owner

- product owner: Daniel Jane
- breaking changes require explicit agreement from the owner

### PII

There is no email, phone, or person name in the current extract.

Relevant sensitive data:

| Data | Where it lives | Does it appear in marts? |
|------|------------|-----------------|
| `customer_id` | several layers | yes, in `mart_mrr_movements` |
| `company_name` | staging, intermediate, snapshot | no |
| country / industry / size | staging and intermediate | not in the marts published today |

Policy:

- `company_name` is not promoted to marts;
- real access control is delegated to IAM, not to this document.

### SLA and freshness

Current state:

- the project works on a frozen dump;
- raw freshness is `warn_after 7d`, with no `error_after`;
- marts are fully rebuilt on every `dbt build`;
- there is no strong hourly or daily SLA until there is a recurring operation
  different from the current lab.

## Out of this version

These stay explicitly outside this contract:

- semantic layer;
- incrementality in `intermediate` or `marts`;
- multi-currency and FX;
- intra-month proration;
- marts built on SCD2 snapshots;
- reconciliation of contracted against invoiced or collected;
- a `rejected` or quarantine layer;
- a second exposure or dashboard with a real URL.

## Maintenance

Review this document if these change:

- `config/raw_contract.yaml`
- `dbt_project/models/sources.yml`
- `dbt_project/models/intermediate/*.sql`
- `dbt_project/models/marts/*.sql`
- `dbt_project/models/**/*.yml`
- `dbt_project/tests/*.sql`
- `docs/DECISIONS.md`

Short checklist:

- if a metric changes, review rules and compatibility;
- if a grain changes, review the published-models table;
- if PII, owner, or SLA change, update that section;
- if the snapshot enters marts, that requires an explicit contractual change.
