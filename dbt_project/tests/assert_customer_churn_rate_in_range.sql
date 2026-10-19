-- Customer churn rate must be in [0, 1].
select
    month,
    customer_churn_rate
from {{ ref('mart_customer_churn') }}
where customer_churn_rate < 0
    or customer_churn_rate > 1
