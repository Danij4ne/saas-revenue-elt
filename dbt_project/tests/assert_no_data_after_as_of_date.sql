-- Sanity check of the declared cutoff (as_of_date, hard cap).
-- Fails if a business event falls after the cutoff: that signals "future"
-- data (bad load or mis-parsed date) that a hard cap would silently truncate.
-- Prefer a visible failure over a silent miss.
--
-- Only BUSINESS dates are checked (invoice_date, started_at). Operational /
-- derived dates (updated_at, due_date) may fall after the cutoff without
-- representing revenue activity. See DECISIONS #9.
with bounds as (
    select
        (select max(cast(invoice_date as date)) from {{ ref('stg_invoices') }})
            as max_invoice_date,
        (select max(cast(started_at as date)) from {{ ref('stg_subscription_history') }})
            as max_started_at
)

select *
from bounds
where max_invoice_date > {{ as_of_date() }}
    or max_started_at > {{ as_of_date() }}
