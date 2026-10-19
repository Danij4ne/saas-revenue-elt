-- Partial WRITE_APPEND load: or_raise fails the job after some tables
-- already landed. Staging QUALIFY is per-table, so mixed extracts yield
-- new customers with old subscriptions (unique/freshness stay green).
--
-- Latest _run_id per table uses the same sort as staging QUALIFY.
-- Never max(_run_id): UUIDs are not chronological.
-- Keep `raw_tables` in sync with config/raw_contract.yaml / sources.yml.

{% set raw_tables = [
    'customers',
    'plans',
    'subscription_history',
    'invoices',
    'payments',
] %}

with latest as (
    {% for table_name in raw_tables %}
    select
        '{{ table_name }}' as table_name,
        _run_id as latest_run_id
    from {{ source('raw', table_name) }}
    qualify row_number() over (
        order by _run_date desc, _ingested_at desc, _run_id desc
    ) = 1
    {% if not loop.last %}
    union all
    {% endif %}
    {% endfor %}
),

expected as (
    {% for table_name in raw_tables %}
    select '{{ table_name }}' as table_name
    {% if not loop.last %}
    union all
    {% endif %}
    {% endfor %}
),

joined as (
    select
        expected.table_name,
        latest.latest_run_id
    from expected
    left join latest
        on expected.table_name = latest.table_name
)

select
    table_name,
    latest_run_id
from joined
where latest_run_id is null
    or (
        select count(distinct latest_run_id)
        from joined
        where latest_run_id is not null
    ) != 1
