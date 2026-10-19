{% snapshot snapshot_customers %}

{{ config(
    unique_key='customer_id',
    strategy='check',
    check_cols=[
        'country',
        'industry',
        'company_size',
        'is_deleted',
        'company_name',
    ],
    hard_deletes='invalidate',
) }}

select
    customer_id,
    company_name,
    country,
    industry,
    company_size,
    created_at,
    is_deleted
from {{ ref('stg_customers') }}

{% endsnapshot %}
