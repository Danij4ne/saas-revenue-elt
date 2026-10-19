with source as (
    select * from {{ source('raw', 'plans') }}
),

renamed as (
    select
        trim(cast(plan_id as string)) as plan_id,
        cast(initcap(trim(plan_name)) as string) as plan_name,
        cast(lower(trim(billing_period)) as string) as billing_period,
        cast(list_price as numeric) as list_price,
        cast(upper(trim(currency)) as string) as currency,
        cast(is_active as bool) as is_active,
        {{ timestamp_from_bq_int64_ns_autodetect('created_at') }} as created_at,
        _run_date,
        _run_id,
        _ingested_at
    from source
)

select *
from renamed
qualify row_number() over (
    partition by plan_id
    order by _run_date desc, _ingested_at desc, _run_id desc
) = 1
