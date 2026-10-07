select
    patient as patient_id,
    encounter as encounter_id,
    try_cast(nullif(date, '') as timestamp) as observed_at,
    category,
    code,
    description,
    value,
    units,
    type
from {{ source('raw', 'observations') }}
