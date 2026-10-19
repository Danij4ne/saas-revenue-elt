with movements as (
    select * from {{ ref('mart_mrr_movements') }}
),

monthly as (
    select
        month,
        countif(prev_mrr > 0) as active_customers_start,
        countif(movement_type = 'churn') as churned_customers,
        sum(case when movement_type = 'churn' then -mrr_delta else 0 end) as churned_mrr,
        sum(case when movement_type = 'expansion' then mrr_delta else 0 end) as expansion_mrr,
        sum(case when movement_type = 'contraction' then -mrr_delta else 0 end) as contraction_mrr
    from movements
    group by month
)

select
    month,
    active_customers_start,
    churned_customers,
    churned_mrr,
    expansion_mrr,
    contraction_mrr,
    safe_divide(churned_customers, active_customers_start) as customer_churn_rate
from monthly
