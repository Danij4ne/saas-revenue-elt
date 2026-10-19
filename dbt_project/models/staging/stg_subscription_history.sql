with source as (
    select * from {{ source('raw', 'subscription_history') }}
),

renamed as (
    select
        trim(cast(subscription_version_id as string)) as subscription_version_id,
        lower(trim(cast(subscription_id as string))) as subscription_id,
        trim(cast(customer_id as string)) as customer_id,
        trim(cast(plan_id as string)) as plan_id,
        cast(lower(trim(status)) as string) as status,
        cast(quantity as int64) as quantity,
        {{ timestamp_from_bq_int64_ns_autodetect('valid_from') }} as valid_from,
        {{ timestamp_from_bq_int64_ns_autodetect('valid_to') }} as valid_to,
        {{ timestamp_from_bq_int64_ns_autodetect('started_at') }} as started_at,
        {{ timestamp_from_bq_int64_ns_autodetect('canceled_at') }} as canceled_at,
        {{ timestamp_from_bq_int64_ns_autodetect('updated_at') }} as updated_at,
        _run_date,
        _run_id,
        _ingested_at
    from source
)

select *
from renamed
qualify row_number() over (
    partition by subscription_version_id
    order by _run_date desc, _ingested_at desc, _run_id desc
) = 1
