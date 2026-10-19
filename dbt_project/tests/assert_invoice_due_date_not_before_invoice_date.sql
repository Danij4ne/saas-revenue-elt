-- due_date cannot be earlier than invoice_date.
select
    invoice_id,
    invoice_date,
    due_date
from {{ ref('stg_invoices') }}
where due_date < invoice_date
