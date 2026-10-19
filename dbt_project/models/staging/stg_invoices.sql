with source as (
    select * from {{ source('raw', 'invoices') }}
),

renamed as (
    select
        lower(trim(cast(invoice_id as string))) as invoice_id,
        lower(trim(cast(subscription_id as string))) as subscription_id,
        trim(cast(customer_id as string)) as customer_id,
        {{ timestamp_from_bq_int64_ns_autodetect('invoice_date') }} as invoice_date,
        cast(amount_due as numeric) as amount_due,
        cast(upper(trim(currency)) as string) as currency,
        cast(lower(trim(status)) as string) as status,
        {{ timestamp_from_bq_int64_ns_autodetect('due_date') }} as due_date,
        _run_date,
        _run_id,
        _ingested_at
    from source
)

select *
from renamed
qualify row_number() over (
    partition by invoice_id
    order by _run_date desc, _ingested_at desc, _run_id desc
) = 1
