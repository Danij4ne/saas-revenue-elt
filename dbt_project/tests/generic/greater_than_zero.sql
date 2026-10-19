{% test greater_than_zero(model, column_name) %}
-- Fails if the value is not strictly positive (null does not fail; use not_null separately).
select *
from {{ model }}
where {{ column_name }} is not null
    and {{ column_name }} <= 0
{% endtest %}
