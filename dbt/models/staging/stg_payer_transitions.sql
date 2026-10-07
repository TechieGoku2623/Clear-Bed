select
    patient as patient_id,
    memberid as member_id,
    try_cast(nullif(start_date, '') as timestamp) as start_ts,
    try_cast(nullif(end_date, '') as timestamp) as end_ts,
    payer as payer_id,
    nullif(secondary_payer, '') as secondary_payer_id,
    plan_ownership,
    owner_name
from {{ source('raw', 'payer_transitions') }}
