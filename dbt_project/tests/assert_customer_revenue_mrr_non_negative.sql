-- A customer's MRR in a month can never be negative.
select
    customer_id,
    month,
    mrr
from {{ ref('int_customer_revenue_monthly') }}
where mrr < 0
