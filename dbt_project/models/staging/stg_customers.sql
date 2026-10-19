with source as (
    select * from {{ source('raw', 'customers') }}
),

renamed as (
    select
        trim(cast(customer_id as string)) as customer_id,
        cast(initcap(trim(company_name)) as string) as company_name,
        cast(lower(trim(country)) as string) as country,
        cast(lower(trim(industry)) as string) as industry,
        cast(lower(trim(company_size)) as string) as company_size,
        {{ timestamp_from_bq_int64_ns_autodetect('created_at') }} as created_at,
        cast(is_deleted as bool) as is_deleted,
        _run_date,
        _run_id,
        _ingested_at
    from source
)

select *
from renamed
qualify row_number() over (
    partition by customer_id
    order by _run_date desc, _ingested_at desc, _run_id desc
) = 1
