-- movement_type must match mrr / prev_mrr in both directions (CASE order
-- in mart_mrr_movements). Failing rows = inconsistent label vs numbers.
select
    customer_id,
    month,
    mrr,
    prev_mrr,
    movement_type
from {{ ref('mart_mrr_movements') }}
where
    -- Label => numbers
    (movement_type = 'new' and not (prev_mrr is null and mrr > 0))
    or (movement_type = 'reactivation' and not (prev_mrr = 0 and mrr > 0))
    or (movement_type = 'churn' and not (mrr = 0 and coalesce(prev_mrr, 0) > 0))
    or (movement_type = 'expansion' and not (mrr > coalesce(prev_mrr, 0)))
    or (movement_type = 'contraction' and not (mrr < prev_mrr and mrr > 0))
    or (movement_type = 'flat' and mrr != coalesce(prev_mrr, 0))
    -- Numbers => label (predicates follow CASE order so new/reactivation
    -- are not also flagged as expansion).
    or (prev_mrr is null and mrr > 0 and movement_type != 'new')
    or (prev_mrr = 0 and mrr > 0 and movement_type != 'reactivation')
    or (coalesce(prev_mrr, 0) > 0 and mrr = 0 and movement_type != 'churn')
    or (prev_mrr > 0 and mrr > prev_mrr and movement_type != 'expansion')
    or (mrr < prev_mrr and mrr > 0 and movement_type != 'contraction')
    or (mrr = coalesce(prev_mrr, 0) and movement_type != 'flat')
