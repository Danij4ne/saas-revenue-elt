-- SCD2 integrity: at most one open version per customer_id.
select
    customer_id
from {{ ref('snapshot_customers') }}
where dbt_valid_to is null
group by customer_id
having count(*) > 1
