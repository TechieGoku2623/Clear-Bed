select
    id as payer_id,
    name as payer_name,
    ownership,
    city,
    state_headquartered,
    zip
from {{ source('raw', 'payers') }}
