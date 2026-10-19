{#
    Converts an epoch in nanoseconds stored as INT64 to TIMESTAMP.

    Reason: the source parquet brings timestamp[ns]; the BigQuery load job
    (autodetect) does not support that unit and materializes the column as INT64.
    CAST(INT64 AS TIMESTAMP) is illegal in GoogleSQL: the unit must be declared.
    See DECISIONS #7.

    Input: column name as a Jinja string (quoted).
    Output: SQL TIMESTAMP expression. Nulls are preserved.
#}
{% macro timestamp_from_bq_int64_ns_autodetect(column) -%}
timestamp_micros(div({{ column }}, 1000))
{%- endmacro %}
