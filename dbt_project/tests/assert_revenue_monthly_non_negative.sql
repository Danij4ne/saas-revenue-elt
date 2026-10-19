-- MRR, ARR, ARPU, active customers and subs_missing_qty are never negative.
select
    month,
    mrr,
    arr,
    arpu,
    active_customers,
    subs_missing_qty
from {{ ref('mart_revenue_monthly') }}
where mrr < 0
    or arr < 0
    or arpu < 0
    or active_customers < 0
    or subs_missing_qty < 0
