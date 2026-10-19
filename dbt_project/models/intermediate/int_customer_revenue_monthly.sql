with sub_month as (
    select * from {{ ref('int_subscription_monthly') }}
),

customers as (
    select * from {{ ref('int_customers_enriched') }}
),

-- MRR aggregated by customer and month, only for months with a version
-- in force. Active MRR set = {active, past_due}.
customer_month_activity as (
    select
        customer_id,
        month,
        sum(
            case
                when status_in_month in ('active', 'past_due')
                    then coalesce(mrr_base, 0)
                else 0
            end
        ) as mrr,
        countif(status_in_month in ('active', 'past_due')) as active_subscriptions,
        countif(status_in_month in ('active', 'past_due') and mrr_base is null)
            as subs_with_unknown_qty,
        -- Mutually exclusive causes of null mrr_base (DECISIONS #12).
        -- Qty-null wins over a missing plan. Orphan plan: list_price is
        -- null (subscription plan_id is still populated).
        countif(
            status_in_month in ('active', 'past_due')
            and quantity is null
        ) as subs_missing_qty,
        countif(
            status_in_month in ('active', 'past_due')
            and quantity is not null
            and list_price is null
        ) as subs_missing_plan,
        countif(
            status_in_month in ('active', 'past_due')
            and quantity is not null
            and list_price is not null
            and billing_period not in ('month', 'year')
        ) as subs_unknown_billing_period
    from sub_month
    group by customer_id, month
),

-- Global observed month range; the cap is as_of_date (hard cap), not the
-- wall clock. The dense grid runs through the declared cutoff month.
-- See DECISIONS #9.
month_bounds as (
    select
        min(month) as min_month,
        date_trunc({{ as_of_date() }}, month) as max_month
    from sub_month
),

all_months as (
    select month_start
    from unnest(
        generate_date_array(
            (select min_month from month_bounds),
            (select max_month from month_bounds),
            interval 1 month
        )
    ) as month_start
),

-- First month each customer appears with any subscription.
customer_start as (
    select
        customer_id,
        min(month) as first_month
    from customer_month_activity
    group by customer_id
),

-- Dense customer x month grid: from each customer's first month through
-- the global max. Density is what makes churn detectable (the month with
-- MRR 0 exists as a row instead of disappearing).
customer_months as (
    select
        cs.customer_id,
        m.month_start as month
    from customer_start cs
    cross join all_months m
    where m.month_start >= cs.first_month  
),

joined as (
    select
        cm.customer_id,
        cm.month,
        coalesce(a.mrr, 0) as mrr,
        coalesce(a.active_subscriptions, 0) as active_subscriptions,
        coalesce(a.subs_with_unknown_qty, 0) as subs_with_unknown_qty,
        coalesce(a.subs_missing_qty, 0) as subs_missing_qty,
        coalesce(a.subs_missing_plan, 0) as subs_missing_plan,
        coalesce(a.subs_unknown_billing_period, 0)
            as subs_unknown_billing_period,
        coalesce(a.active_subscriptions, 0) > 0 as has_active_subscription
    from customer_months cm
    left join customer_month_activity a
        on cm.customer_id = a.customer_id
        and cm.month = a.month
),

final as (
    select
        j.customer_id,
        j.month,
        c.country_code,
        c.size_segment,
        c.industry,
        j.mrr,
        j.active_subscriptions,
        j.subs_with_unknown_qty,
        j.subs_missing_qty,
        j.subs_missing_plan,
        j.subs_unknown_billing_period,
        j.has_active_subscription
    from joined j
    left join customers c
        on j.customer_id = c.customer_id
)

select * from final
