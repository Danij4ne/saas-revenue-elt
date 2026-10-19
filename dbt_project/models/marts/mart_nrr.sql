with customer_revenue as (
    select customer_id, month, mrr
    from {{ ref('int_customer_revenue_monthly') }}
),

max_month as (
    select max(month) as max_month from customer_revenue
),

-- Cohort: customers with MRR > 0 in the base month. Only base months with a
-- full 12-month window ahead (otherwise NRR would be misleading).
cohort as (
    select
        cr.customer_id,
        cr.month as base_month,
        cr.mrr as base_mrr
    from customer_revenue cr
    cross join max_month
    where cr.mrr > 0
        and date_add(cr.month, interval 12 month) <= max_month.max_month
),

-- MRR of those same customers 12 months later (0 if they no longer have any).
retained as (
    select
        c.base_month,
        c.customer_id,
        c.base_mrr,
        coalesce(fut.mrr, 0) as future_mrr
    from cohort c
    left join customer_revenue fut
        on fut.customer_id = c.customer_id
        and fut.month = date_add(c.base_month, interval 12 month)
)

select
    base_month,
    sum(base_mrr) as base_mrr,
    sum(future_mrr) as retained_mrr,
    safe_divide(sum(future_mrr), sum(base_mrr)) as nrr_12m
from retained
group by base_month
