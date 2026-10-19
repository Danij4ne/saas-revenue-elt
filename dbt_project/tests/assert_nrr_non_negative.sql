-- NRR cannot be negative and the cohort base MRR must be positive.
select
    base_month,
    base_mrr,
    nrr_12m
from {{ ref('mart_nrr') }}
where nrr_12m < 0
    or base_mrr <= 0
