{#
    Analysis cutoff date as a SQL DATE expression.

    Single source of truth for the hard cap of the monthly spine: it reads the
    `as_of_date` var (defined in dbt_project.yml) so the date and the cutoff
    logic are not repeated in each model. See DECISIONS #9.
#}
{% macro as_of_date() -%}
    cast('{{ var("as_of_date") }}' as date)
{%- endmacro %}
