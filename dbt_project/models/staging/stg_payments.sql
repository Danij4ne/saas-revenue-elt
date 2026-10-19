with source as (
    select * from {{ source('raw', 'payments') }}
),

renamed as (
    select
        lower(trim(cast(payment_id as string))) as payment_id,
        lower(trim(cast(invoice_id as string))) as invoice_id,
        {{ timestamp_from_bq_int64_ns_autodetect('paid_at') }} as paid_at,
        cast(amount_paid as numeric) as amount_paid,
        cast(upper(trim(currency)) as string) as currency,
        cast(lower(trim(status)) as string) as status,
        cast(lower(trim(payment_method)) as string) as payment_method,
        _run_date,
        _run_id,
        _ingested_at
    from source
)

select *
from renamed
qualify row_number() over (
    partition by payment_id
    order by _run_date desc, _ingested_at desc, _run_id desc
) = 1
