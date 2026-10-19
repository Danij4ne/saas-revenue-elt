-- Payments: non-negative amounts + status/amount consistency.
-- failed => 0; succeeded/refunded => > 0.
select
    payment_id,
    status,
    amount_paid
from {{ ref('stg_payments') }}
where amount_paid < 0
    or (status = 'failed' and amount_paid != 0)
    or (status in ('succeeded', 'refunded') and amount_paid <= 0)
