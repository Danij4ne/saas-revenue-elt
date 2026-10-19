with customers as (
    select * from {{ ref('stg_customers') }}
),

country_map as (
    select * from {{ ref('country_mapping') }}
),

size_map as (
    select * from {{ ref('company_size_mapping') }}
),

enriched as (
    select
        customers.customer_id,
        customers.company_name,

        coalesce(country_map.country_code, 'unknown') as country_code,
        coalesce(country_map.country_name, 'Unknown') as country_name,
        customers.country as country_raw,

        customers.industry,

        coalesce(size_map.size_segment, 'unknown') as size_segment,
        customers.company_size as company_size_raw,

        customers.created_at,
        customers.is_deleted
    from customers
    left join country_map
        on customers.country = country_map.raw_country
    left join size_map
        on customers.company_size = size_map.raw_company_size
)

select * from enriched
