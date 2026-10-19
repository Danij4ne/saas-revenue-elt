{% snapshot snapshot_plans %}

{{ config(
    unique_key='plan_id',
    strategy='check',
    check_cols=[
        'list_price',
        'billing_period',
        'currency',
        'is_active',
        'plan_name',
    ],
    hard_deletes='invalidate',
) }}

select
    plan_id,
    plan_name,
    billing_period,
    list_price,
    currency,
    is_active,
    created_at
from {{ ref('stg_plans') }}

{% endsnapshot %}
