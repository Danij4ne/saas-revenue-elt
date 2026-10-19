with subscriptions as (
    select * from {{ ref('stg_subscription_history') }}
),

-- Current catalogue photo (one row per plan_id). Not snapshot_plans:
-- SCD2 has no history before the first snapshot run, so list_price is
-- applied to every month through as_of_date. See DECISIONS #10.
plans as (
    select * from {{ ref('stg_plans') }}
),

customers as (
    select * from {{ ref('int_customers_enriched') }}
),

-- Monthly spine: from the earliest valid_from through as_of_date (hard cap).
-- The end does NOT depend on the wall clock (current_date): the data is a
-- historical snapshot and the cutoff is the declared date. See DECISIONS #9.
months as (
    select month_start
    from unnest(
        generate_date_array(
            date_trunc(
                (select min(cast(valid_from as date)) from subscriptions),
                month
            ),
            {{ as_of_date() }},
            interval 1 month
        )
    ) as month_start
),

-- (subscription, month) pairs where the subscription has some version
-- covering at least part of the month.
subscription_months as (
    select
        subscriptions.subscription_id,
        months.month_start
    from subscriptions
    cross join months
    where
        cast(subscriptions.valid_from as date)
            <= last_day(months.month_start)
        and (
            subscriptions.valid_to is null
            or cast(subscriptions.valid_to as date) > months.month_start
        )
    group by subscriptions.subscription_id, months.month_start
),

-- Of all versions of that subscription that cover the month, keep the
-- most recent one (the version in force at month end).
version_in_month as (
    select
        sm.subscription_id,
        sm.month_start,
        s.subscription_version_id,
        s.customer_id,
        s.plan_id,
        s.status,
        s.quantity,
        s.valid_from,
        s.valid_to,
        s.started_at,
        s.canceled_at
    from subscription_months sm
    inner join subscriptions s
        on s.subscription_id = sm.subscription_id
    where
        cast(s.valid_from as date) <= last_day(sm.month_start)
        and (s.valid_to is null or cast(s.valid_to as date) > sm.month_start)
    qualify row_number() over (
        partition by sm.subscription_id, sm.month_start
        order by s.valid_from desc
    ) = 1
),

enriched as (
    select
        v.subscription_id,
        v.month_start as month,
        v.subscription_version_id,
        v.customer_id,
        c.country_code,
        c.country_name,
        c.industry,
        c.size_segment,
        v.plan_id,
        p.plan_name,
        p.billing_period,
        p.currency,
        v.status as status_in_month,
        v.quantity,
        p.list_price,

        -- List price normalized to a monthly amount by billing period.
        case
            when p.billing_period = 'month' then p.list_price
            when p.billing_period = 'year' then p.list_price / 12
            else null
        end as price_monthly_equivalent,

        -- Potential line MRR: NULL if quantity is NULL (bad data; do not
        -- impute here — the mart decides).
        case
            when v.quantity is null then null
            when p.billing_period = 'month' then v.quantity * p.list_price
            when p.billing_period = 'year' then v.quantity * p.list_price / 12
            else null
        end as mrr_base,

        v.valid_from,
        v.valid_to,
        v.started_at,
        v.canceled_at
    from version_in_month v
    -- Current list_price for the whole spine; not snapshot_plans (#10).
    left join plans p
        on v.plan_id = p.plan_id
    left join customers c
        on v.customer_id = c.customer_id
)

select * from enriched
