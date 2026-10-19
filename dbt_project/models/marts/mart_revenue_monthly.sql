with customer_revenue as (
    select * from {{ ref('int_customer_revenue_monthly') }}
),

monthly as (
    select
        month,
        sum(mrr) as mrr,
        countif(has_active_subscription) as active_customers,
        -- Line count, not customers. Those lines are already 0 inside mrr.
        sum(subs_missing_qty) as subs_missing_qty
    from customer_revenue
    group by month
)

select
    month,
    mrr,
    mrr * 12 as arr,
    active_customers,
    case
        when active_customers > 0 then mrr / active_customers
        else 0
    end as arpu,
    subs_missing_qty
from monthly
