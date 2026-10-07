select
    patient as patient_id,
    encounter as encounter_id,
    try_cast(nullif(start, '') as timestamp) as start_ts,
    try_cast(nullif(stop, '') as timestamp) as stop_ts,
    code,
    description
from {{ source('raw', 'conditions') }}
