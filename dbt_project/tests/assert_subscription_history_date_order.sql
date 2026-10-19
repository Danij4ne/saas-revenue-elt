-- Date intervals must not be inverted.
-- null valid_to / canceled_at are valid (open version / not canceled).
-- valid_from < started_at is inconsistent: a version cannot be in force
-- before the subscription was created (version clock vs entity clock).
select
    subscription_version_id,
    valid_from,
    valid_to,
    started_at,
    canceled_at
from {{ ref('stg_subscription_history') }}
where (valid_to is not null and valid_from > valid_to)
    or (canceled_at is not null and started_at > canceled_at)
    or (valid_from < started_at)
