-- SCD2 integrity: at most one open version per plan_id.
select
    plan_id
from {{ ref('snapshot_plans') }}
where dbt_valid_to is null
group by plan_id
having count(*) > 1
