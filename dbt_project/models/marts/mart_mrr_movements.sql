with customer_revenue as (
    select * from {{ ref('int_customer_revenue_monthly') }}
),

-- Prior-month MRR per customer. Because the grid is dense, a customer who
-- drops to 0 has prev_mrr = 0 (not null); prev_mrr is null only in their first month.
with_prev as (
    select
        customer_id,
        month,
        mrr,
        lag(mrr) over (
            partition by customer_id
            order by month
        ) as prev_mrr
    from customer_revenue
),

classified as (
    select
        customer_id,
        month,
        mrr,
        prev_mrr,
        mrr - coalesce(prev_mrr, 0) as mrr_delta,
        case
            when prev_mrr is null and mrr > 0 then 'new'
            when prev_mrr = 0 and mrr > 0 then 'reactivation'
            when coalesce(prev_mrr, 0) > 0 and mrr = 0 then 'churn'
            when mrr > coalesce(prev_mrr, 0) then 'expansion'
            when mrr < prev_mrr and mrr > 0 then 'contraction'
            else 'flat'
        end as movement_type
    from with_prev
)

select * from classified
